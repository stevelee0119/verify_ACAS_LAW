"""문자열 정규화·유사도 유틸리티."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# 제어문자 / Unicode 은닉문자 (제7.2 Unicode 레이어)
# ---------------------------------------------------------------------------
ZERO_WIDTH = {
    "​": "ZERO WIDTH SPACE",
    "‌": "ZERO WIDTH NON-JOINER",
    "‍": "ZERO WIDTH JOINER",
    "⁠": "WORD JOINER",
    "﻿": "ZERO WIDTH NO-BREAK SPACE (BOM)",
    "­": "SOFT HYPHEN",
    "᠎": "MONGOLIAN VOWEL SEPARATOR",
}

BIDI_CONTROLS = {
    "‪": "LEFT-TO-RIGHT EMBEDDING",
    "‫": "RIGHT-TO-LEFT EMBEDDING",
    "‬": "POP DIRECTIONAL FORMATTING",
    "‭": "LEFT-TO-RIGHT OVERRIDE",
    "‮": "RIGHT-TO-LEFT OVERRIDE",
    "⁦": "LEFT-TO-RIGHT ISOLATE",
    "⁧": "RIGHT-TO-LEFT ISOLATE",
    "⁨": "FIRST STRONG ISOLATE",
    "⁩": "POP DIRECTIONAL ISOLATE",
}

# U+E0000..U+E007F : Unicode Tag characters (ASCII smuggling)
TAG_RANGE = (0xE0000, 0xE007F)

# 대표적 라틴/키릴 homoglyph 쌍
HOMOGLYPHS: Dict[str, str] = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "х": "x", "у": "y", "А": "A", "В": "B", "Е": "E",
    "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "Х": "X", "Α": "A", "Β": "B",
    "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
    "Χ": "X", "‐": "-", "‑": "-", "ａ": "a", "ｏ": "o",
}


# 문자 단위 파이썬 반복 대신 str.translate로 한 번에 처리한다. 같은 결과를
# C 수준에서 얻는다. 비교 단위마다 문서 전체를 정규화하므로 이 비용이 쌓인다.
_INVISIBLE_TABLE = {ord(ch): None for ch in (*ZERO_WIDTH, *BIDI_CONTROLS)}
_INVISIBLE_TABLE.update({cp: None for cp in range(TAG_RANGE[0], TAG_RANGE[1] + 1)})
_HOMOGLYPH_TABLE = {ord(source): target for source, target in HOMOGLYPHS.items()}


def strip_invisible(text: str) -> str:
    """은닉 제어문자를 제거한 표시용 문자열."""
    return text.translate(_INVISIBLE_TABLE)


def decode_tag_characters(text: str) -> str:
    """Unicode Tag 영역에 숨겨진 ASCII 문자열을 복원한다."""
    out = []
    for ch in text:
        cp = ord(ch)
        if TAG_RANGE[0] <= cp <= TAG_RANGE[1]:
            out.append(chr(cp - 0xE0000))
    return "".join(out)


def defang_homoglyphs(text: str) -> str:
    """homoglyph를 대응 라틴 문자로 바꿔 우회 탐지를 가능하게 한다."""
    return text.translate(_HOMOGLYPH_TABLE)


def normalize_for_match(text: str) -> str:
    """공백·제어문자·homoglyph를 정규화한 비교용 문자열."""
    t = unicodedata.normalize("NFKC", strip_invisible(text))
    t = defang_homoglyphs(t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def normalize_quote(text: str) -> str:
    """인용문 비교용: 따옴표·공백·문장부호 정규화."""
    t = normalize_for_match(text)
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = re.sub(r"[\s·、,]+", " ", t)
    return t.strip()


def similarity(a: str, b: str) -> float:
    """0.0~1.0 문자열 유사도(fuzzy quote match용)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, normalize_quote(a), normalize_quote(b)).ratio()


def contains_fuzzy(haystack: str, needle: str, threshold: float = 0.9) -> Tuple[bool, float]:
    """needle이 haystack 안에 (근사) 포함되는지 판정한다."""
    return contains_fuzzy_normalized(normalize_quote(haystack), normalize_quote(needle),
                                     threshold=threshold)


def contains_fuzzy_normalized(h: str, n: str, *, threshold: float = 0.9) -> Tuple[bool, float]:
    """정규화가 끝난 문자열끼리 비교한다.

    같은 문서를 haystack으로 두고 여러 단위를 검사할 때, 문서 전체를 비교
    단위마다 다시 정규화하는 것은 순수한 낭비다. 호출부가 한 번만 정규화하고
    이 함수를 부르면 그 반복이 사라진다.
    """
    if not n:
        return False, 0.0
    if n in h:
        return True, 1.0
    if len(n) > len(h):
        return False, SequenceMatcher(None, h, n).ratio() if h else 0.0
    best = 0.0
    step = max(1, len(n) // 4)
    # b를 고정한 matcher를 재사용한다. difflib은 b에 대한 색인을 캐시하므로
    # 창마다 matcher를 새로 만들면 같은 색인을 매번 다시 만든다.
    matcher = SequenceMatcher(None, "", n)
    for i in range(0, len(h) - len(n) + 1, step):
        matcher.set_seq1(h[i : i + len(n)])
        # real_quick_ratio와 quick_ratio는 ratio의 상한이다. 상한이 지금까지의
        # 최고값을 넘지 못하면 그 창은 최고값도 기준도 바꿀 수 없으므로
        # 건너뛴다. 반환되는 비율 자체는 달라지지 않는다.
        #
        # 기준(threshold)으로 걸러서는 안 된다. verifier._compare_quote는
        # 기준에 못 미치는 비율을 TRUNCATED(절단 인용)와 CONTRADICTED(왜곡)를
        # 가르는 데 쓴다. 상한을 최고값에만 견주어야 그 판단이 보존된다.
        if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
            continue
        r = matcher.ratio()
        if r > best:
            best = r
        if best >= threshold:
            return True, best
    return best >= threshold, best


# 문장 종결부호 앞이 숫자이면 "2024. 1. 15."와 같은 날짜이므로 분할하지 않는다.
SENTENCE_SPLIT_RE = re.compile(r'(?<=[가-힣A-Za-z)\]"”\'’】」])\s*[.!?。]\s+|\n+')


def sentences(text: str) -> List[str]:
    """한국어 법률문서에 맞춘 문장 분할. 날짜 표기(2024. 1. 15.)를 문장 경계로 보지 않는다."""
    parts = SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def parse_number(token: str) -> float:
    return float(token.replace(",", ""))

