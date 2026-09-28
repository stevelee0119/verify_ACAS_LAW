"""제8장 PII 파이프라인.

Original → Rule-based PII + NER Detection → Context Validation
→ Project-stable Pseudonym → Masked Evidence View → External LLM
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from packages.common.enums import ExternalAIPolicy
from packages.common.schemas import NormalizedDocument

from .detector import PIIMatch, detect
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
        for match in sorted(matches, key=lambda m: m.start):
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
        contextual = [m for m in detect("\n".join(b.text for b in blocks)) if m.confidence >= MIN_CONFIDENCE]
        offset = 0
        for block in blocks:
            matches = [m for m in detect(block.text, block_id=block.block_id, page=block.page)
                       if m.confidence >= MIN_CONFIDENCE]
            spans = {(m.start, m.end) for m in matches}
            for match in contextual:
                if offset <= match.start < match.end <= offset + len(block.text):
                    span = (match.start - offset, match.end - offset)
                    if span not in spans:
                        matches.append(replace(match, start=span[0], end=span[1], block_id=block.block_id, page=block.page))
                        spans.add(span)
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
