"""제7.3장 Cross-Layer Comparison.

Rendered View, Raw Text, Embedded OCR Layer, 독립 OCR, XML, Metadata를 상호 비교한다.
사용자 화면에 보이지 않는 문자열이 내부 Text Object나 OCR Layer에만 존재하면
HIDDEN_TEXT_MISMATCH 또는 OCR_LAYER_INJECTION 후보로 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List

from packages.common.textutil import normalize_for_match


@dataclass
class LayerDelta:
    left_layer: str
    right_layer: str
    left_chars: int
    right_chars: int
    difference: int
    only_in_right: List[str]
    similarity: float


MIN_SEGMENT_CHARS = 12


def _segments_only_in(right: str, left: str) -> List[str]:
    """right에만 존재하는 연속 구간을 뽑는다."""
    a, b = normalize_for_match(left), normalize_for_match(right)
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    out: List[str] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            segment = b[j1:j2].strip()
            if len(segment) >= MIN_SEGMENT_CHARS:
                out.append(segment)
    return out


def compare_layers(layers: Dict[str, str]) -> List[LayerDelta]:
    """의미 있는 레이어 쌍을 비교한다."""
    pairs = [
        ("rendered_text", "raw_text"),
        ("rendered_text", "ocr_layer"),
        ("rendered_text", "embedded_stream_text"),
        ("rendered_text", "annotation_text"),
        ("ocr_layer", "independent_ocr"),
    ]
    deltas: List[LayerDelta] = []
    for left_name, right_name in pairs:
        left = layers.get(left_name)
        right = layers.get(right_name)
        if left is None or right is None:
            continue
        if not right.strip():
            continue
        only_right = _segments_only_in(right, left)
        if not only_right and len(right) <= len(left):
            continue
        deltas.append(
            LayerDelta(
                left_layer=left_name,
                right_layer=right_name,
                left_chars=len(normalize_for_match(left)),
                right_chars=len(normalize_for_match(right)),
                difference=len(normalize_for_match(right)) - len(normalize_for_match(left)),
                only_in_right=only_right[:20],
                similarity=round(SequenceMatcher(None, normalize_for_match(left), normalize_for_match(right)).ratio(), 4),
            )
        )
    return deltas
