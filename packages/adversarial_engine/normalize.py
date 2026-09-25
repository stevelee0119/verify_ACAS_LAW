"""분류 전 정규화(v3 §3-4, v4 P7).

지시문을 키워드 검사에서 숨기는 흔한 방법을 되돌린 뒤 분류한다.
- 전각·호환 문자: NFKC로 바꾼다('ＡＩ' → 'AI').
- 폭 0 문자·서식 문자(Unicode Cf): 지운다('A\\u200bI' → 'AI').
- 한글 호환 자모로 풀어 쓴 글자: 음절로 다시 모은다('ㄱㅓㅁㅌㅗ' → '검토').
어떤 방법이 쓰였는지(kinds)를 함께 돌려주어 인젝션 경로로 표시한다. 정규화한 글자는 분류에만 쓰고 원문은 그대로 보존한다.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Tuple

CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ",
        "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
JAMO_RUN_RE = re.compile(r"[ㄱ-ㅣ]{2,}")

KIND_LABELS = {"FULLWIDTH": "전각·호환 문자(NFKC 정규화)", "ZERO_WIDTH": "폭 0 문자", "JAMO": "한글 자모 분리(재조합)"}


def compose_jamo(run: str) -> str:
    """호환 자모 나열을 음절로 모은다. 모음이 없는 자음만의 나열(ㅋㅋ 등)은 그대로 둔다."""
    out: List[str] = []
    i = 0
    while i < len(run):
        c = run[i]
        if c in CHO and i + 1 < len(run) and run[i + 1] in JUNG:
            cho, jung = CHO.index(c), JUNG.index(run[i + 1])
            i += 2
            jong = 0
            if i < len(run) and run[i] in JONG[1:] and not (i + 1 < len(run) and run[i + 1] in JUNG):
                jong = JONG.index(run[i])
                i += 1
            out.append(chr(0xAC00 + (cho * 21 + jung) * 28 + jong))
        else:
            out.append(c)
            i += 1
    return "".join(out)


def normalize_for_classification(text: str) -> Tuple[str, List[str]]:
    """(분류용 글자, 쓰인 은닉 방법 목록)."""
    kinds: List[str] = []
    stripped = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    if stripped != text:
        kinds.append("ZERO_WIDTH")
    if any("！" <= ch <= "～" for ch in stripped):
        kinds.append("FULLWIDTH")
    # 자모 재조합을 NFKC보다 먼저 한다. NFKC는 호환 자모(ㄱ)를 첫가끝 자모(ᄀ)로 바꿔 재조합을 막는다.
    composed = JAMO_RUN_RE.sub(lambda m: compose_jamo(m.group(0)), stripped)
    if composed != stripped:
        kinds.append("JAMO")
    # 남은 호환 자모(ㅋㅋ 등)는 NFKC에서 빼서 원래 글자대로 둔다.
    folded = "".join(ch if "ㄱ" <= ch <= "ㆎ" else unicodedata.normalize("NFKC", ch) for ch in composed)
    return folded, kinds
