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


def strip_invisible(text: str) -> str:
    """은닉 제어문자를 제거한 표시용 문자열."""
    out = []
    for ch in text:
        cp = ord(ch)
        if ch in ZERO_WIDTH or ch in BIDI_CONTROLS:
            continue
        if TAG_RANGE[0] <= cp <= TAG_RANGE[1]:
            continue
        out.append(ch)
    return "".join(out)


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
    return "".join(HOMOGLYPHS.get(ch, ch) for ch in text)


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
    h, n = normalize_quote(haystack), normalize_quote(needle)
    if not n:
        return False, 0.0
    if n in h:
        return True, 1.0
    if len(n) > len(h):
        return False, similarity(h, n)
    best = 0.0
    step = max(1, len(n) // 4)
    for i in range(0, len(h) - len(n) + 1, step):
        window = h[i : i + len(n)]
        r = SequenceMatcher(None, window, n).ratio()
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


def char_windows(text: str, size: int = 400, overlap: int = 80) -> List[Tuple[int, str]]:
    out = []
    i = 0
    while i < len(text):
        out.append((i, text[i : i + size]))
        i += max(1, size - overlap)
    return out


NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def parse_number(token: str) -> float:
    return float(token.replace(",", ""))


def find_numbers(text: str) -> List[Tuple[int, int, float, str]]:
    """(start, end, value, raw) 목록."""
    out = []
    for m in NUMBER_RE.finditer(text):
        try:
            out.append((m.start(), m.end(), parse_number(m.group()), m.group()))
        except ValueError:  # pragma: no cover
            continue
    return out
