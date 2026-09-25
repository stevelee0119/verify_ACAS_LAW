"""제7.3장 Cross-Layer Comparison.

Rendered View, Raw Text, Embedded OCR Layer, 독립 OCR, XML, Metadata를 상호 비교한다.
사용자 화면에 보이지 않는 문자열이 내부 Text Object나 OCR Layer에만 존재하면
HIDDEN_TEXT_MISMATCH 또는 OCR_LAYER_INJECTION 후보로 만든다.

비교는 문자 단위 diff가 아니라 라인·문장 단위 포함 여부로 수행한다.
한국어는 조사·어미가 반복되어 문자 단위 diff가 잘게 조각나므로,
"이 문장이 저쪽 레이어에 존재하는가"를 묻는 편이 정확하다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List

from packages.common.textutil import (contains_fuzzy_normalized, normalize_for_match,
                                      normalize_quote, sentences)

MIN_SEGMENT_CHARS = 12
MAX_UNITS = 300
LONG_LINE_CHARS = 200

# 레이어 쌍별 포함 판정 임계값. OCR은 인식 오차가 있으므로 느슨하게 본다.
OCR_LAYERS = {"ocr_layer", "independent_ocr"}
OCR_THRESHOLD = 0.55
EXACT_THRESHOLD = 0.85

# CID 폰트 PDF의 content stream은 글리프 ID라서 유니코드로 복원되지 않고
# "\\325<\\254\\340" 같은 8진 이스케이프 문자열로 남는다.
# 숫자는 이런 노이즈에도 많으므로 '문자'의 비율과 역슬래시 밀도로 판독 가능 여부를 본다.
LETTER_RE = re.compile(r"[A-Za-z가-힣]")
MIN_LETTER_RATIO = 0.15
MAX_BACKSLASH_RATIO = 0.05


@dataclass
class LayerDelta:
    left_layer: str
    right_layer: str
    left_chars: int
    right_chars: int
    difference: int
    only_in_right: List[str]
    similarity: float


def is_readable(text: str) -> bool:
    """유니코드로 복원된 텍스트인지 판정한다.

    판독 불가능하면 비교를 건너뛴다. 건너뛰는 방향이 오탐보다 안전하다.
    """
    if not text:
        return False
    sample = text[:20000]
    if sample.count("\\") / len(sample) > MAX_BACKSLASH_RATIO:
        return False
    return len(LETTER_RE.findall(sample)) / len(sample) >= MIN_LETTER_RATIO


def _units(text: str) -> List[str]:
    """비교 단위(라인, 긴 라인은 문장)를 만든다."""
    units: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) > LONG_LINE_CHARS:
            units.extend(sentences(line))
        else:
            units.append(line)
    return units


class _Layer:
    """레이어 한 개의 정규화 결과를 한 번만 만들어 둔다.

    한 레이어는 여러 쌍에 거듭 등장하고(rendered_text는 네 쌍),
    비교 단위마다 문서 전체를 다시 정규화하면 그만큼 낭비가 쌓인다.
    """

    __slots__ = ("text", "_norm", "_quoted", "_units")

    def __init__(self, text: str) -> None:
        self.text = text
        self._norm = self._quoted = None
        self._units = None

    @property
    def norm(self) -> str:
        if self._norm is None:
            self._norm = normalize_for_match(self.text)
        return self._norm

    @property
    def quoted(self) -> str:
        """contains_fuzzy가 haystack에 적용하는 것과 같은 정규화."""
        if self._quoted is None:
            self._quoted = normalize_quote(self.norm)
        return self._quoted

    @property
    def units(self):
        """(원문 단위, 비교용 정규화 문자열) 목록."""
        if self._units is None:
            pairs = []
            for unit in _units(self.text)[:MAX_UNITS]:
                normalized = normalize_for_match(unit)
                if len(normalized) < MIN_SEGMENT_CHARS:
                    continue
                pairs.append((unit.strip(), normalize_quote(normalized)))
            self._units = pairs
        return self._units


def _segments_only_in(right: "_Layer", left: "_Layer", *, threshold: float) -> List[str]:
    """right에만 존재하는(=left에서 확인되지 않는) 문장을 뽑는다."""
    haystack = left.quoted
    return [unit for unit, needle in right.units
            if not contains_fuzzy_normalized(haystack, needle, threshold=threshold)[0]]


def compare_layers(layers: Dict[str, str]) -> List[LayerDelta]:
    """의미 있는 레이어 쌍을 비교한다."""
    pairs = [
        ("rendered_text", "raw_text"),
        ("rendered_text", "ocr_layer"),
        ("rendered_text", "embedded_stream_text"),
        ("rendered_text", "annotation_text"),
        ("ocr_layer", "independent_ocr"),
        # 역방향: 화면(독립 OCR)에는 없는데 내장 텍스트 레이어에만 있는 문자열.
        # 제7.2장 "화면과 OCR text 불일치"에 해당하는 핵심 공격 형태이다.
        ("independent_ocr", "rendered_text"),
        ("independent_ocr", "raw_text"),
    ]
    deltas: List[LayerDelta] = []
    prepared: Dict[str, _Layer] = {}

    def layer(name: str, text: str) -> _Layer:
        if name not in prepared:
            prepared[name] = _Layer(text)
        return prepared[name]

    for left_name, right_name in pairs:
        left = layers.get(left_name)
        right = layers.get(right_name)
        if left is None or right is None or not right.strip():
            continue
        if not is_readable(right) or (left.strip() and not is_readable(left)):
            continue

        is_ocr_pair = bool({left_name, right_name} & OCR_LAYERS)
        threshold = OCR_THRESHOLD if is_ocr_pair else EXACT_THRESHOLD
        left_layer, right_layer = layer(left_name, left), layer(right_name, right)
        only_right = _segments_only_in(right_layer, left_layer, threshold=threshold)
        left_norm, right_norm = left_layer.norm, right_layer.norm
        if not only_right and len(right_norm) <= len(left_norm):
            continue
        deltas.append(
            LayerDelta(
                left_layer=left_name,
                right_layer=right_name,
                left_chars=len(left_norm),
                right_chars=len(right_norm),
                difference=len(right_norm) - len(left_norm),
                only_in_right=only_right[:20],
                similarity=round(SequenceMatcher(None, left_norm, right_norm).ratio(), 4),
            )
        )
    return deltas
