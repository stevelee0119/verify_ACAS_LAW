"""직접 인용문의 변형 탐지(v2 Phase 4, v3 D1: 어절 단위 diff, MODIFIED_QUOTE).

인용문이 원문과 거의 같아도(유사도 0.85 이상 1.0 미만) 정도 부사("현저하게")를 빼거나, 부정·양태("할 수
있다" ↔ "하여야 한다")·조문 한정어(단서·본문·제N항)·수량을 바꾸면 판시의 의미가 달라진다. 유사도만 보면 '일부
일치'로 통과한다.

1. 원문에서 인용문과 가장 비슷한 구간을 공백·문장부호를 뺀 글자열로 찾는다(띄어쓰기 차이는 변형이 아니다).
2. 그 구간을 어절 경계까지 넓혀 원문 어절열을 얻고, 인용문 어절열과 비교해 삭제·추가·치환 어절을 낸다.
   구간 양 끝의 차이는 인용 범위를 자른 자리일 수 있으므로 변형으로 보지 않는다.
3. 말줄임표(…, ..., (중략))로 생략을 표시한 인용은 표시된 구간마다 따로 대조한다(생략 자체는 변형이 아니다).
4. 바뀐 어절에 정도 부사·부정·양태·조문 한정어·수량이 들어 있고 양쪽이 다르면 의미 변형(meaningful)이다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from packages.common.textutil import normalize_quote

MEANINGFUL_CHANGES = [
    ("DEGREE", "정도 부사", re.compile(r"현저|상당|명백|중대|매우|극히|다소|약간|전혀|반드시|항상|언제나|오로지|오직|특히")),
    ("NEGATION", "부정", re.compile(r"아니|않|못|없|불가|금지")),
    ("MODALITY", "양태(가능·의무)", re.compile(r"수있|하여야|해야|하도록|하여서는|할것|하지아니할")),
    ("PROVISION_QUALIFIER", "조문 한정어", re.compile(r"단서|본문|전단|후단|제\d+항|제\d+호|각호")),
    ("QUANTITY", "수량", re.compile(r"\d+")),
]
MIN_SIMILARITY = 0.85
MIN_SEGMENT = 8  # 생략 표시로 나눈 구간 중 이보다 짧은 조각은 대조하지 않는다
ELLIPSIS_RE = re.compile(r"…+|\.{3,}|\(\s*중\s*략\s*\)|\[\s*중\s*략\s*\]")
DROP_RE = re.compile(r"[\s\"'“”‘’.,·「」『』()\[\]<>《》]")
OP_LABELS = {"delete": "삭제", "insert": "추가", "replace": "치환"}


def _compact(text: str) -> str:
    return DROP_RE.sub("", normalize_quote(text or ""))


def _compact_with_map(text: str) -> Tuple[str, List[int]]:
    kept, index = [], []
    for position, char in enumerate(text):
        if not DROP_RE.match(char):
            kept.append(char)
            index.append(position)
    return "".join(kept), index


def _best_window(haystack: str, needle: str) -> Tuple[int, int, float]:
    """haystack에서 needle과 가장 비슷한 구간 (시작, 끝, 유사도)."""
    if not needle or not haystack:
        return 0, 0, 0.0
    exact = haystack.find(needle)
    if exact >= 0:
        return exact, exact + len(needle), 1.0
    size = len(needle)
    best = (0, 0, 0.0)
    matcher = SequenceMatcher(None, "", needle, autojunk=False)
    step = max(1, size // 10)
    for width in {size, int(size * 1.1) + 1, int(size * 0.9)}:
        for start in range(0, max(1, len(haystack) - width + 1), step):
            window = haystack[start:start + width]
            matcher.set_seq1(window)
            if matcher.real_quick_ratio() <= best[2] or matcher.quick_ratio() <= best[2]:
                continue
            ratio = matcher.ratio()
            if ratio > best[2]:
                best = (start, start + len(window), ratio)
    return best


def _word_span(text: str, start: int, end: int) -> str:
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[start:end]


def _minor(original: str, quoted: str) -> bool:
    a, b = _compact(original), _compact(quoted)
    common = 0
    while common < min(len(a), len(b)) and a[common] == b[common]:
        common += 1
    return bool(a and b) and common >= 2 and max(len(a), len(b)) - common <= 2


def _classify(original: str, quoted: str) -> List[Tuple[str, str]]:
    a, b = _compact(original), _compact(quoted)
    return [(kind, label) for kind, label, pattern in MEANINGFUL_CHANGES
            if set(pattern.findall(a)) != set(pattern.findall(b))]


def _segment_ops(quote: str, official: str) -> Optional[Tuple[float, List[Dict[str, Any]]]]:
    norm_off = normalize_quote(official)
    compact_off, index = _compact_with_map(norm_off)
    needle = _compact(quote)
    start, end, ratio = _best_window(compact_off, needle)
    if ratio < MIN_SIMILARITY:
        return None
    if ratio >= 1.0:
        return ratio, []
    segment = _word_span(norm_off, index[start], index[end - 1] + 1)
    original, quoted = segment.split(), normalize_quote(quote).split()
    keys_o, keys_q = [_compact(w) for w in original], [_compact(w) for w in quoted]
    ops: List[Dict[str, Any]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, keys_o, keys_q, autojunk=False).get_opcodes():
        if op == "equal" or (i1 == 0 and j1 == 0) or (i2 == len(original) and j2 == len(quoted)):
            continue  # 구간 끝의 차이는 인용 범위를 자른 자리일 수 있다
        before, after = " ".join(original[i1 - 1:i1]), " ".join(original[i2:i2 + 1])
        o_text, q_text = " ".join(original[i1:i2]), " ".join(quoted[j1:j2])
        if _compact(o_text) == _compact(q_text):
            continue  # 띄어쓰기만 다름
        kinds = _classify(o_text, q_text)
        if not kinds and _minor(o_text, q_text):
            continue  # 어미·조사 1~2자 차이("것이라고"→"것이라")는 의미를 바꾸지 않는다
        ops.append({"op": op, "label": OP_LABELS[op], "original": o_text, "quoted": q_text,
                    "before": before, "after": after, "kinds": [k for k, _ in kinds],
                    "kind_labels": [label for _, label in kinds]})
    return ratio, ops


def quote_changes(quote: str, official_text: str) -> Optional[Dict[str, Any]]:
    """원문과 다른 어절이 있으면 {similarity, ops, changes, meaningful, deleted, inserted}, 없으면 None.

    유사도 0.85 미만(다른 문장)이나 완전 일치는 None이다. 불일치 판정은 호출하는 쪽의 유사도 검사가 맡는다.
    """
    segments = [s for s in ELLIPSIS_RE.split(quote or "") if len(_compact(s)) >= MIN_SEGMENT]
    if not segments:
        return None
    ratios, ops = [], []
    for segment in segments:
        found = _segment_ops(segment, official_text)
        if found is None:
            return None
        ratios.append(found[0])
        ops.extend(found[1])
    if not ops:
        return None
    changes = []
    for op in ops:
        for kind, label in zip(op["kinds"], op["kind_labels"]):
            side = {"delete": "원문에서 빠짐", "insert": "인용문에 더해짐"}.get(op["op"], "치환")
            text = op["original"] if op["op"] == "delete" else op["quoted"] if op["op"] == "insert" \
                else f"{op['original']} → {op['quoted']}"
            changes.append({"kind": kind, "label": label, "side": side, "text": text, "op": op["op"]})
    return {"similarity": round(min(ratios), 3), "ops": ops, "changes": changes, "meaningful": bool(changes),
            "deleted": [o["original"] for o in ops if o["op"] in ("delete", "replace")],
            "inserted": [o["quoted"] for o in ops if o["op"] in ("insert", "replace")]}


def render_quote_diff(result: Dict[str, Any], limit: int = 4) -> str:
    """바뀐 어절을 원문과 나란히: 삭제 — 원문 「사회통념상 [현저하게] 타당성을」 → 인용 「사회통념상 타당성을」."""
    parts = []
    for op in (result.get("ops") or [])[:limit]:
        before = f"{op['before']} " if op["before"] else ""
        after = f" {op['after']}" if op["after"] else ""
        original = f"{before}[{op['original']}]{after}" if op["original"] else f"{before}{after}".strip()
        quoted = f"{before}[{op['quoted']}]{after}" if op["quoted"] else f"{before}{after}".strip()
        kinds = f"({', '.join(op['kind_labels'])})" if op["kind_labels"] else ""
        parts.append(f"{op['label']}{kinds} — 원문 「{original.strip()}」 → 인용 「{quoted.strip()}」")
    extra = len(result.get("ops") or []) - limit
    return "; ".join(parts) + (f"; 외 {extra}곳" if extra > 0 else "")


def quote_diff_summary(result: Dict[str, Any]) -> str:
    """짧은 결함 요약: 인용문 변형: 원문 '현저하게' 삭제."""
    pieces = []
    for op in (result.get("ops") or [])[:3]:
        if op["op"] == "delete":
            pieces.append(f"원문 '{op['original']}' 삭제")
        elif op["op"] == "insert":
            pieces.append(f"'{op['quoted']}' 추가")
        else:
            pieces.append(f"'{op['original']}'→'{op['quoted']}'")
    return "인용문 변형: " + ", ".join(pieces)
