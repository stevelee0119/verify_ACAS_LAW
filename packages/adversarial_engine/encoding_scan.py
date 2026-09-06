"""제7.2장 Encoding 레이어: Base64/Hex/URL/HTML entity/escape를 safe decode 후 재검사.

디코드는 표준 라이브러리만 사용하며 어떤 경우에도 실행·접속하지 않는다(부록 C 제9항).
"""
from __future__ import annotations

import base64
import binascii
import html
import re
import urllib.parse
from dataclasses import dataclass
from typing import List

B64_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2}[\s:]?){12,}")
URL_ENC_RE = re.compile(r"(?:%[0-9a-fA-F]{2}){6,}")
HTML_ENT_RE = re.compile(r"(?:&#x?[0-9a-fA-F]{2,6};){4,}|(?:&[a-z]{2,8};){4,}")
UNICODE_ESCAPE_RE = re.compile(r"(?:\\u[0-9a-fA-F]{4}){4,}|(?:\\x[0-9a-fA-F]{2}){6,}")

MAX_DECODE_BYTES = 200_000


@dataclass
class DecodedSegment:
    encoding: str
    original: str
    decoded: str
    start: int
    end: int


def _printable_ratio(s: str) -> float:
    if not s:
        return 0.0
    printable = sum(1 for c in s if c.isprintable() or c in "\n\t ")
    return printable / len(s)


def _accept(decoded: str) -> bool:
    return len(decoded.strip()) >= 8 and _printable_ratio(decoded) > 0.85


def decode_candidates(text: str) -> List[DecodedSegment]:
    """텍스트 안의 인코딩 후보를 안전하게 디코드한다."""
    out: List[DecodedSegment] = []
    if not text:
        return out
    sample = text[:MAX_DECODE_BYTES]

    for m in B64_RE.finditer(sample):
        raw = m.group(0)
        padded = raw + "=" * (-len(raw) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True).decode("utf-8", "strict")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if _accept(decoded):
            out.append(DecodedSegment("BASE64", raw, decoded, m.start(), m.end()))

    for m in HEX_RE.finditer(sample):
        raw = m.group(0)
        cleaned = re.sub(r"[\s:]", "", raw)
        if len(cleaned) % 2:
            cleaned = cleaned[:-1]
        try:
            decoded = bytes.fromhex(cleaned).decode("utf-8", "strict")
        except (ValueError, UnicodeDecodeError):
            continue
        if _accept(decoded):
            out.append(DecodedSegment("HEX", raw, decoded, m.start(), m.end()))

    for m in URL_ENC_RE.finditer(sample):
        raw = m.group(0)
        decoded = urllib.parse.unquote(raw, errors="strict") if "%" in raw else ""
        if decoded and decoded != raw and _accept(decoded):
            out.append(DecodedSegment("URL", raw, decoded, m.start(), m.end()))

    for m in HTML_ENT_RE.finditer(sample):
        raw = m.group(0)
        decoded = html.unescape(raw)
        if decoded != raw and _accept(decoded):
            out.append(DecodedSegment("HTML_ENTITY", raw, decoded, m.start(), m.end()))

    for m in UNICODE_ESCAPE_RE.finditer(sample):
        raw = m.group(0)
        try:
            decoded = raw.encode("ascii", "ignore").decode("unicode_escape")
        except Exception:
            continue
        if _accept(decoded):
            out.append(DecodedSegment("UNICODE_ESCAPE", raw, decoded, m.start(), m.end()))

    return out
