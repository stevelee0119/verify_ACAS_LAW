"""제8장 PII 파이프라인.

Original → Rule-based PII + NER Detection → Context Validation
→ Project-stable Pseudonym → Masked Evidence View → External LLM
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from packages.common.enums import ExternalAIPolicy
from packages.common.schemas import NormalizedDocument

from .detector import PIIMatch, detect, is_lawyer_court_address_context
from .pseudonym import PseudonymStore

MIN_CONFIDENCE = 0.6


@dataclass
class MaskResult:
    masked_text: str
    matches: List[PIIMatch] = field(default_factory=list)
    replacements: Dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.matches)


@dataclass
class MaskedDocument:
    document_id: str
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    match_count: int = 0
    kinds: Dict[str, int] = field(default_factory=dict)
    replacements: Dict[str, str] = field(default_factory=dict)
    policy: str = ExternalAIPolicy.MASKED.value

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.blocks)


class PIIEngine:
    def __init__(self, store: PseudonymStore) -> None:
        self.store = store

    def mask_text(self, text: str, *, block_id: Optional[str] = None, page: Optional[int] = None) -> MaskResult:
        matches = [m for m in detect(text, block_id=block_id, page=page) if m.confidence >= MIN_CONFIDENCE]
        return self._mask_matches(text, matches)

    def _mask_matches(self, text, matches):
        if not matches:
            return MaskResult(text, [], {})
        replacements: Dict[str, str] = {}
        out = []
        cursor = 0
        # 같은 위치에서 시작하면 긴 탐지를 먼저 쓴다(블록 경계를 넘는 문맥 탐지가 부분 탐지를 덮는다).
        for match in sorted(matches, key=lambda m: (m.start, -(m.end - m.start))):
            if match.start < cursor:
                continue
            token = self.store.pseudonym_for(match.kind, match.text)
            replacements[token] = match.kind
            out.append(text[cursor : match.start])
            out.append(f"[{token}]")
            cursor = match.end
        out.append(text[cursor:])
        return MaskResult("".join(out), matches, replacements)

    def mask_document(self, doc: NormalizedDocument, *, policy: ExternalAIPolicy = ExternalAIPolicy.MASKED) -> MaskedDocument:
        """외부 LLM에 보낼 Masked Evidence View를 만든다."""
        masked = MaskedDocument(document_id=doc.document_id, policy=policy.value)
        if policy == ExternalAIPolicy.ORIGINAL:
            masked.blocks = [
                {"block_id": b.block_id, "page": b.page, "text": b.text, "layer": b.source_layer}
                for b in doc.body_blocks()
            ]
            return masked

        blocks = doc.body_blocks()
        # Labels and their values may be different table cells. Detect across the
        # assembled text, then map contained matches back to unchanged block spans.
        assembled_text = "\n".join(b.text for b in blocks)
        contextual = [m for m in detect(assembled_text) if m.confidence >= MIN_CONFIDENCE]
        offset = 0
        for block in blocks:
            raw_matches = [m for m in detect(block.text, block_id=block.block_id, page=block.page)
                           if m.confidence >= MIN_CONFIDENCE]
            # 블록 경계를 넘는 문맥 확인: 블록 단위로 탐지된 주소가 전체 문서 문맥상 소송대리인/법원 주소인 경우 보존
            matches = []
            for m in raw_matches:
                if m.kind == "ADDRESS" and is_lawyer_court_address_context(assembled_text, offset + m.start, offset + m.end):
                    continue
                matches.append(m)
            spans = {(m.start, m.end) for m in matches}
            end_of_block = offset + len(block.text)
            for match in contextual:
                if match.end <= offset or match.start >= end_of_block:
                    continue
                # 줄바꿈으로 여러 블록에 걸친 값("생년월일: 1985. 11." / "24.")은 블록마다 해당 조각을 가린다.
                # 한 블록 안에 든 값만 옮기면 나머지 조각이 그대로 외부 모델로 나간다.
                span = (max(match.start, offset) - offset, min(match.end, end_of_block) - offset)
                if not block.text[span[0]:span[1]].strip():
                    continue
                piece = replace(match, start=span[0], end=span[1], block_id=block.block_id, page=block.page)
                if span not in spans:
                    matches.append(piece)
                    spans.add(span)
                elif match.start < offset or match.end > end_of_block:
                    # 블록 안의 부분 탐지(지역명 없는 면허번호 등)보다 경계를 넘는 전체 값의 가명을 쓴다.
                    matches = [piece if (m.start, m.end) == span else m for m in matches]
            offset += len(block.text) + 1
            result = self._mask_matches(block.text, matches)
            masked.blocks.append(
                {"block_id": block.block_id, "page": block.page, "text": result.masked_text,
                 "layer": block.source_layer}
            )
            masked.match_count += result.count
            for match in result.matches:
                masked.kinds[match.kind] = masked.kinds.get(match.kind, 0) + 1
            masked.replacements.update(result.replacements)
        self.store.save()
        return masked
