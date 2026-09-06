"""제7.2장 Unicode 레이어 검사: zero-width, bidi override, homoglyph, tag 문자."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List

from packages.common.textutil import (
    BIDI_CONTROLS,
    HOMOGLYPHS,
    TAG_RANGE,
    ZERO_WIDTH,
    decode_tag_characters,
    defang_homoglyphs,
)


@dataclass
class UnicodeSignal:
    kind: str
    detail: str
    positions: List[int]
    sample: str
    recovered_text: str = ""


def scan_unicode(text: str) -> List[UnicodeSignal]:
    signals: List[UnicodeSignal] = []
    if not text:
        return signals

    zw_positions: Dict[str, List[int]] = {}
    bidi_positions: Dict[str, List[int]] = {}
    tag_positions: List[int] = []
    homoglyph_positions: List[int] = []

    for i, ch in enumerate(text):
        if ch in ZERO_WIDTH:
            zw_positions.setdefault(ch, []).append(i)
        elif ch in BIDI_CONTROLS:
            bidi_positions.setdefault(ch, []).append(i)
        elif TAG_RANGE[0] <= ord(ch) <= TAG_RANGE[1]:
            tag_positions.append(i)
        elif ch in HOMOGLYPHS:
            homoglyph_positions.append(i)

    for ch, positions in zw_positions.items():
        signals.append(
            UnicodeSignal(
                kind="ZERO_WIDTH",
                detail=f"{ZERO_WIDTH[ch]} (U+{ord(ch):04X}) {len(positions)}회",
                positions=positions[:50],
                sample=_context(text, positions[0]),
            )
        )

    for ch, positions in bidi_positions.items():
        signals.append(
            UnicodeSignal(
                kind="BIDI_CONTROL",
                detail=f"{BIDI_CONTROLS[ch]} (U+{ord(ch):04X}) {len(positions)}회",
                positions=positions[:50],
                sample=_context(text, positions[0]),
            )
        )

    if tag_positions:
        recovered = decode_tag_characters(text)
        signals.append(
            UnicodeSignal(
                kind="TAG_CHARACTERS",
                detail=f"Unicode Tag 영역 문자 {len(tag_positions)}자로 ASCII 문자열이 은닉되었다.",
                positions=tag_positions[:50],
                sample=_context(text, tag_positions[0]),
                recovered_text=recovered,
            )
        )

    # homoglyph는 다국어 문서에서 정상 출현할 수 있으므로 라틴 단어 내부 혼입만 신호로 본다
    mixed = _mixed_script_words(text)
    if mixed:
        signals.append(
            UnicodeSignal(
                kind="HOMOGLYPH",
                detail=f"스크립트 혼용 단어 {len(mixed)}건: {', '.join(mixed[:5])}",
                positions=homoglyph_positions[:50],
                sample=", ".join(mixed[:5]),
                recovered_text=defang_homoglyphs(" ".join(mixed[:20])),
            )
        )

    # 분리된 지시문(문자 사이 구분자 삽입) 탐지
    separated = _separated_instruction(text)
    if separated:
        signals.append(
            UnicodeSignal(
                kind="SEPARATED_INSTRUCTION",
                detail="문자 사이에 구분자를 넣어 패턴 탐지를 우회하려는 문자열이 있다.",
                positions=[],
                sample=separated[0][:120],
                recovered_text=separated[1],
            )
        )
    return signals


WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def _script_of(ch: str) -> str:
    name = unicodedata.name(ch, "")
    for script in ("HANGUL", "CYRILLIC", "GREEK", "LATIN", "CJK", "HIRAGANA", "KATAKANA"):
        if script in name:
            return script
    return "OTHER"


def _mixed_script_words(text: str) -> List[str]:
    out: List[str] = []
    for m in WORD_RE.finditer(text):
        word = m.group(0)
        scripts = {_script_of(c) for c in word if c.isalpha()}
        scripts.discard("OTHER")
        if len(scripts) > 1 and any(c in HOMOGLYPHS for c in word):
            out.append(word)
    return out


SEPARATOR_CLASS = r"[\s\.\-_\*\|/\\·:,~]"
SEPARATED_KEYWORDS = ["ignore", "instruction", "system", "prompt", "무시", "지시"]


def _separated_instruction(text: str):
    stripped = re.sub(SEPARATOR_CLASS, "", text.lower())
    for keyword in SEPARATED_KEYWORDS:
        if keyword in stripped and keyword not in text.lower():
            idx = stripped.find(keyword)
            return (text[max(0, idx - 40) : idx + 80], stripped[max(0, idx - 40) : idx + 80])
    return None


def _context(text: str, index: int, width: int = 60) -> str:
    start = max(0, index - width)
    return text[start : index + width].replace("\n", " ")
