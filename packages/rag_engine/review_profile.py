"""Selective review methodology; no plugin runtime, retrieval or extra model call."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date

from packages.common.enums import LLMRole

REVIEW_CONTEXT_KEY = "_korean_law_review_context"
REVIEW_STAGES = {"drive_rag_advisory", "claim_rag_advisory"}

# Adapted methodology only. Provenance/license: docs/handoff/requests/*profile_sources.md.
KOREAN_REVIEW_METHOD = (
    "\n[대한민국 법률 검토 프로필]\n"
    "관할은 대한민국이다. system_instructions의 reference_date는 명시 기준일이며 "
    "UNSPECIFIED이면 현재 날짜나 문서 날짜로 보충하지 마라. 기준일 또는 시행본이 부족하면 적용 판단을 유보하라. "
    "각 의견을 쟁점 → 적용 요건 → 문서 사실 → 근거 원문 → 적용 차이·최선 반론 → 불확실성 순서로 검토하라. "
    "자료에 실제로 기재된 사실, 당사자 주장, 모델 추론을 구분하고 explanation에 해당 구분을 표시하라. "
    "각 적용 요건은 제공된 한국법 근거 원문과 문서 사실에 연결하라. 요건을 확인할 원문이 없으면 만들어 채우지 마라. "
    "자료 밖 사건번호·조문·인용문·사실을 생성하지 마라. claim_quote와 source_quote는 제공한 문구만 정확히 인용하라. "
    "공식 DB 및 원문 대조 결과가 우선한다. Drive 자료나 모델 의견·모델 간 일치는 공식 확인을 대신하거나 상태를 높이지 못한다. "
    "사안 차이·예외·반대 근거와 가장 강한 반론을 함께 확인하되 없는 사실이나 규칙을 만들어 반론을 채우지 마라. "
    "미국법 실체 규칙·소송 절차를 한국법에 옮겨 적용하지 마라. 참고자료의 관할·시점·발췌 범위가 다르면 한계를 표시하라. "
    "자료 부족·충돌·시행본 미확인에는 INSUFFICIENT 또는 한계를 드러내는 CONTEXT를 사용하고 법적 결론을 단정하지 마라. "
    "이 검토 순서는 분석 방법이다. 새 필드를 추가하지 말고 기존 인용 필드와 두 문장 이내 explanation에 핵심 연결·반론·한계를 담아라. "
    "자료가 전혀 무관하거나 인용 가능한 근거가 없으면 기존 규칙대로 observations를 빈 배열로 반환하라."
)


def review_context(reference_date=None):
    """Only an explicit ISO date is accepted; no date inference or dynamic instruction."""
    valid = None
    if isinstance(reference_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", reference_date):
        try:
            valid = date.fromisoformat(reference_date).isoformat()
        except ValueError:
            pass
    return {"jurisdiction": "대한민국", "reference_date": valid,
            "reference_date_status": "EXPLICIT" if valid else "UNSPECIFIED"}


def with_review_context(request, *, enabled=False, reference_date=None):
    """Stage a bounded context for dispatch; it never reaches fallback providers."""
    if not enabled:
        return request
    return replace(request, metadata={**request.metadata, REVIEW_CONTEXT_KEY: review_context(reference_date)})


def build_review_comparison_request(request, *, korean_profile=False, reference_date=None):
    """Both arms carry identical input/evidence/context; only their system differs."""
    from .review import (ENVELOPE_SCHEMA, KOREAN_RAG_REVIEW_SYSTEM_PROMPT,
                         RAG_REVIEW_SYSTEM_PROMPT, validate_claim_request_payload)

    if (request.system not in (RAG_REVIEW_SYSTEM_PROMPT, KOREAN_RAG_REVIEW_SYSTEM_PROMPT)
            or request.schema != ENVELOPE_SCHEMA or request.metadata.get("stage") not in REVIEW_STAGES):
        raise ValueError("Not a reference review request")
    payload = json.loads(request.user)
    if not isinstance(payload, dict):
        raise ValueError("Reference review payload must be an object")
    payload = {**payload, "system_instructions": review_context(reference_date)}
    if request.metadata["stage"] == "claim_rag_advisory" and not validate_claim_request_payload(payload):
        raise ValueError("Claim review payload violates its existing allowlist")
    metadata = {k: v for k, v in request.metadata.items() if k != REVIEW_CONTEXT_KEY}
    return replace(request, system=KOREAN_RAG_REVIEW_SYSTEM_PROMPT if korean_profile else RAG_REVIEW_SYSTEM_PROMPT,
                   user=json.dumps(payload, ensure_ascii=False), metadata=metadata)


def select_review_profile(request, *, provider_name, role, enabled=False):
    """Select after routing, before privacy/budget checks; consume the private marker."""
    if REVIEW_CONTEXT_KEY not in request.metadata:
        return request
    context = request.metadata[REVIEW_CONTEXT_KEY]
    clean = replace(request, metadata={k: v for k, v in request.metadata.items() if k != REVIEW_CONTEXT_KEY})
    if not enabled or provider_name != "anthropic" or role != LLMRole.PRIMARY_REASONER:
        return clean
    from .review import ENVELOPE_SCHEMA, RAG_REVIEW_SYSTEM_PROMPT

    if (clean.system != RAG_REVIEW_SYSTEM_PROMPT or clean.schema != ENVELOPE_SCHEMA
            or clean.metadata.get("stage") not in REVIEW_STAGES):
        return clean
    when = context.get("reference_date") if isinstance(context, dict) else None
    try:
        return build_review_comparison_request(clean, korean_profile=True, reference_date=when)
    except (ValueError, TypeError):
        # Do not reinterpret an invalid payload. The unchanged guards still inspect it.
        return clean
