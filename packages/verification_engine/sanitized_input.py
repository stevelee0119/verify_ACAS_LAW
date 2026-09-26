"""격리 문서의 정제 입력(v6 P3): 문서 속 지시문(프롬프트 인젝션) 구간을 뺀 본문.

격리(QUARANTINED)는 문서를 색인하지 않고 지시문을 실행하지 않는다는 뜻이지, 나머지 본문의 검토를 포기한다는
뜻이 아니다. 탐지된 지시문 블록과 그 문자열을 뺀 본문만 모델 검토·Drive 검색에 쓴다. 지시문은 자료로만 다루며,
제외 사실과 제외한 블록 수를 결과에 남긴다.
"""
from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from packages.common.enums import ADVERSARIAL_FINDING_TYPES
from packages.document_engine.reading_text import build_reading_text

PLACEHOLDER = "[문서 속 지시문 제외]"


def injection_parts(findings: Iterable) -> Tuple[Set[str], List[str]]:
    """탐지된 지시문의 블록 ID와 관찰 문자열(긴 것부터)."""
    blocks: Set[str] = set()
    texts: List[str] = []
    for finding in findings:
        if finding.type not in ADVERSARIAL_FINDING_TYPES or finding.advisory_only:
            continue
        features = finding.confidence_features or {}
        blocks.update(features.get("block_ids") or ([finding.block_id] if finding.block_id else []))
        observed = str(features.get("observed_text") or "").strip()
        if observed:
            texts.append(observed)
    return blocks, sorted(set(texts), key=len, reverse=True)


def strip_injections(text: str, texts: Iterable[str]) -> str:
    for observed in texts:
        if observed and observed in text:
            text = text.replace(observed, PLACEHOLDER)
    return text


def sanitized_reading_text(doc, findings) -> Tuple[str, dict]:
    """지시문 블록을 빼고 이어 읽은 본문과, 무엇을 뺐는지에 대한 기록."""
    blocks, texts = injection_parts(findings)
    kept = [b for b in doc.body_blocks() if b.block_id not in blocks]
    text = strip_injections(build_reading_text(doc, blocks=kept).text, texts)
    return text, {"mode": "SANITIZED_EXCLUDING_INSTRUCTIONS", "excluded_blocks": sorted(blocks),
                  "excluded_texts": len(texts), "remaining_chars": len(text)}
