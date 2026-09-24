"""직접 인용문의 의미 있는 변형 탐지(v2 Phase 4, MODIFIED_QUOTE).

인용문이 원문과 거의 같아도(유사도 0.85 이상) 정도 부사("현저하게")를 빼거나 바꾸고, 부정·양태("할 수 있다"
↔ "하여야 한다")·수량을 바꾸면 판시의 의미가 달라진다. 유사도만 보면 '일부 일치'로 통과한다. 원문에서 인용문과
가장 비슷한 구간을 찾아 글자 단위로 비교하고, 빠지거나 더해진 부분에 이런 말이 있으면 의미 변형으로 본다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from packages.common.textutil import normalize_quote

MEANINGFUL_CHANGES = [
    ("DEGREE", "정도 부사", re.compile(r"현저|상당|명백|중대|매우|극히|다소|약간|전혀|반드시|항상|언제나|오로지|오직|특히")),
    ("NEGATION", "부정", re.compile(r"아니|않|못|없|불가|금지")),
    ("MODALITY", "양태(가능·의무)", re.compile(r"수있|하여야|해야|하도록|하여서는|할것|하지아니할")),
    ("QUANTITY", "수량", re.compile(r"\d")),
]
MIN_SIMILARITY = 0.85


def _compact(text: str) -> str:
    return re.sub(r"[\s\"'“”‘’.,·]", "", normalize_quote(text or ""))


def _best_window(haystack: str, needle: str) -> tuple:
    if not needle or not haystack:
        return "", 0.0
    if needle in haystack:
        return needle, 1.0
    size = len(needle)
    best, best_ratio = "", 0.0
    matcher = SequenceMatcher(None, "", needle, autojunk=False)
    step = max(1, size // 10)
    for width in {size, int(size * 1.1) + 1, int(size * 0.9)}:
        for start in range(0, max(1, len(haystack) - width + 1), step):
            window = haystack[start:start + width]
            matcher.set_seq1(window)
            if matcher.real_quick_ratio() <= best_ratio or matcher.quick_ratio() <= best_ratio:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best, best_ratio = window, ratio
    return best, best_ratio


def quote_changes(quote: str, official_text: str) -> Optional[Dict[str, Any]]:
    """의미 있는 변형이 있으면 {similarity, deleted, inserted, changes}를, 없으면 None."""
    needle, haystack = _compact(quote), _compact(official_text)
    window, ratio = _best_window(haystack, needle)
    if ratio >= 1.0 or ratio < MIN_SIMILARITY:
        return None
    deleted: List[str] = []
    inserted: List[str] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, window, needle, autojunk=False).get_opcodes():
        if op == "equal" or i1 == 0 or j1 == 0 or (i2 == len(window) and j2 == len(needle)):
            continue  # 구간 끝의 차이는 비교 창을 자른 자리일 수 있다(인용 범위 차이)
        if op in ("delete", "replace"):
            deleted.append(window[max(0, i1 - 2):i2 + 2] if i2 - i1 < 2 else window[i1:i2])
        if op in ("insert", "replace"):
            inserted.append(needle[max(0, j1 - 2):j2 + 2] if j2 - j1 < 2 else needle[j1:j2])
    changes = []
    for kind, label, pattern in MEANINGFUL_CHANGES:
        for side, pieces in (("원문에서 빠짐", deleted), ("인용문에 더해짐", inserted)):
            for piece in pieces:
                if pattern.search(piece):
                    changes.append({"kind": kind, "label": label, "side": side, "text": piece})
    if not changes:
        return None
    return {"similarity": round(ratio, 3), "deleted": deleted, "inserted": inserted, "changes": changes}
