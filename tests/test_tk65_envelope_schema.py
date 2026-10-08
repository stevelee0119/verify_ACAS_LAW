"""TK-65: F3 주장 단위 대조 응답 최상위 형식 프롬프트 명시, 공급자 빈 예외 형식 기록, 비용 기록(spent_usd/uncertain_usd) 분리 시험.

문서·문장·주장 및 테스트 데이터는 모두 시험용 합성이다 (서면9 문장, 규정명, 특정 조항 번호 일체 미포함).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import pytest

from packages.common.enums import ExternalAIPolicy, VerificationProfile
from packages.llm_router.privacy import (
    is_registered_schema,
    is_registered_system_prompt,
)
from packages.llm_router.providers import (
    AnthropicProvider,
    GeminiProvider,
    LLMRequest,
    LocalLLMProvider,
    OpenAIProvider,
)
from packages.rag_engine.review import (
    ENVELOPE_SCHEMA,
    RAG_REVIEW_SYSTEM_PROMPT,
    SCHEMA,
    review_document,
)


# ======================================================================================
# 1. 프롬프트 최상위 형식 문장 및 등록 스키마/프롬프트 검사
# ======================================================================================

def test_rag_review_system_prompt_envelope_format_and_registration():
    """[합성 1] RAG_REVIEW_SYSTEM_PROMPT에 최상위 형식 문장과 전체 SCHEMA가 포함되고 등록 프롬프트 검사를 통과한다."""
    # 1) 최상위 형식 안내 문구 확인
    assert "observations" in RAG_REVIEW_SYSTEM_PROMPT
    assert "최상위" in RAG_REVIEW_SYSTEM_PROMPT or "배열" in RAG_REVIEW_SYSTEM_PROMPT
    assert "객체" in RAG_REVIEW_SYSTEM_PROMPT

    # 2) 전체 SCHEMA가 직렬화되어 프롬프트 끝에 포함되어 있는지 확인
    schema_dump = json.dumps(SCHEMA, ensure_ascii=False)
    assert schema_dump in RAG_REVIEW_SYSTEM_PROMPT

    # 3) 등록 고정 시스템 프롬프트 및 스키마 검증 통과
    assert is_registered_system_prompt(RAG_REVIEW_SYSTEM_PROMPT) is True
    assert is_registered_schema(SCHEMA) is True
    assert is_registered_schema(ENVELOPE_SCHEMA) is True


# ======================================================================================
# 2. 공급자 어댑터별 빈 예외 메시지 오류 형식 보존 검사
# ======================================================================================

class EmptyMessageTimeout(Exception):
    """메시지가 빈 합성 예외."""
    def __str__(self):
        return ""


def test_openai_adapter_records_exception_type_on_empty_message(monkeypatch):
    """[합성 2-1] OpenAIProvider에서 빈 메시지 예외 발생 시 예외 형식 이름이 error에 기록된다."""
    import httpx

    monkeypatch.setattr(OpenAIProvider, "available", property(lambda self: True))
    provider = OpenAIProvider(SimpleNamespace(api_key="mock_key", model="mock-model", base_url="http://mock", enabled=True, has_key=True))

    async def mock_post(*args, **kwargs):
        raise EmptyMessageTimeout()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    req = LLMRequest(system="sys", user="usr")
    resp = asyncio.run(provider.generate(req))
    assert resp.ok is False
    assert "EmptyMessageTimeout" in resp.error
    assert resp.error.startswith("PROVIDER_EXCEPTION:")


def test_anthropic_adapter_records_exception_type_on_empty_message(monkeypatch):
    """[합성 2-2] AnthropicProvider에서 빈 메시지 예외 발생 시 예외 형식 이름이 error에 기록된다."""
    import httpx

    monkeypatch.setattr(AnthropicProvider, "available", property(lambda self: True))
    provider = AnthropicProvider(SimpleNamespace(api_key="mock_key", model="mock-model", base_url="http://mock", enabled=True, has_key=True))

    async def mock_post(*args, **kwargs):
        raise EmptyMessageTimeout()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    req = LLMRequest(system="sys", user="usr")
    resp = asyncio.run(provider.generate(req))
    assert resp.ok is False
    assert "EmptyMessageTimeout" in resp.error
    assert resp.error.startswith("PROVIDER_EXCEPTION:")


def test_gemini_adapter_records_exception_type_on_empty_message(monkeypatch):
    """[합성 2-3] GeminiProvider에서 빈 메시지 예외 발생 시 예외 형식 이름이 error에 기록된다."""
    import httpx

    monkeypatch.setattr(GeminiProvider, "available", property(lambda self: True))
    provider = GeminiProvider(SimpleNamespace(api_key="mock_key", model="mock-model", base_url="http://mock", enabled=True, has_key=True))

    async def mock_post(*args, **kwargs):
        raise EmptyMessageTimeout()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    req = LLMRequest(system="sys", user="usr")
    resp = asyncio.run(provider.generate(req))
    assert resp.ok is False
    assert "EmptyMessageTimeout" in resp.error
    assert resp.error.startswith("PROVIDER_EXCEPTION:")


def test_local_adapter_records_exception_type_on_empty_message(monkeypatch):
    """[합성 2-4] LocalLLMProvider에서 빈 메시지 예외 발생 시 예외 형식 이름이 error에 기록된다."""
    import httpx

    monkeypatch.setattr(LocalLLMProvider, "available", property(lambda self: True))
    provider = LocalLLMProvider(SimpleNamespace(api_key="", model="mock-model", base_url="http://mock", enabled=True, has_key=True))

    async def mock_post(*args, **kwargs):
        raise EmptyMessageTimeout()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    req = LLMRequest(system="sys", user="usr")
    resp = asyncio.run(provider.generate(req))
    assert resp.ok is False
    assert "EmptyMessageTimeout" in resp.error
    assert resp.error.startswith("PROVIDER_EXCEPTION:")


# ======================================================================================
# 3. 비용 기록 (spent_usd 및 uncertain_usd) 분리 검증
# ======================================================================================

def test_claim_coverage_budget_records_spent_and_uncertain_usd(monkeypatch):
    """[합성 3] 확정 비용과 RESERVED_UNCERTAIN 예약액이 섞인 실행에서 spent_usd와 uncertain_usd가 정확히 분리 기록된다."""
    claim_text = "원고는 피고에게 계약상 대금을 지급할 의무가 존재한다."
    sources_list = [{
        "file_id": "fid_contract_01",
        "source_id": "R1",
        "title": "물품공급계약서.txt",
        "folder_path": "",
        "page": 1,
        "text": "제5조 대금의 지급: 매수인은 물품 수령 후 대금을 전액 지급하여야 한다.",
    }]

    library = SimpleNamespace(
        summary={"status": "READY", "snapshot_hash": "mock_hash"},
        folder="test_folder",
        select=lambda text: {
            "decision": "USED",
            "reason": "RELEVANT_REFERENCE_FOUND",
            "coverage": "CHECKED_INDEXED_CORPUS",
            "sources": sources_list,
        },
    )

    result = SimpleNamespace(
        document_id="doc_tk65_test",
        normalized=SimpleNamespace(visible_text=claim_text, pages=[SimpleNamespace(text=claim_text)], blocks=[]),
        findings=[],
        claims=[
            {"claim_id": "CLM_PAID_01", "text": claim_text},
            {"claim_id": "CLM_PAID_02", "text": "피고는 원고의 추가 요청을 승인하였다."},
        ],
        citations=[],
        engine_data={},
    )
    context = SimpleNamespace(
        requested_issues=[],
        profile=VerificationProfile.STANDARD,
        external_ai_policy=ExternalAIPolicy.ORIGINAL,
    )
    pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (claim_text, {"omitted_chars": 0}))

    # 2건의 주장 실행 시:
    # 1번째 주장: 확정 비용 $0.05, cost_status="SETTLED"
    # 2번째 주장: 예약 비용 $0.15, cost_status="RESERVED_UNCERTAIN"
    claim_call_count = 0

    class MockCostRouter:
        def has_available_provider(self, **kwargs):
            return True

        async def run(self, role, request, **kwargs):
            nonlocal claim_call_count
            if request.metadata.get("stage") != "claim_rag_advisory":
                return SimpleNamespace(used=True, quarantined=False, executions=[], parsed={"observations": []})

            claim_call_count += 1
            if claim_call_count == 1:
                exec_item = SimpleNamespace(cost_usd=0.05, cost_status="SETTLED", to_dict=lambda: {"cost_usd": 0.05, "cost_status": "SETTLED"})
            else:
                exec_item = SimpleNamespace(cost_usd=0.15, cost_status="RESERVED_UNCERTAIN", to_dict=lambda: {"cost_usd": 0.15, "cost_status": "RESERVED_UNCERTAIN"})

            return SimpleNamespace(
                used=True,
                quarantined=False,
                executions=[exec_item],
                parsed={"observations": [{
                    "claim_quote": "대금을 지급할 의무가 존재한다",
                    "source_id": "R1",
                    "source_quote": "대금을 전액 지급하여야 한다",
                    "relationship": "SUPPORTS",
                    "explanation": "계약서 규정과 주장이 부합합니다.",
                }]}
            )

    review = review_document(result, library, MockCostRouter(), context, pii)
    cov = review.get("claim_coverage", {})
    budget = cov.get("budget", {})

    assert "spent_usd" in budget, "budget에 spent_usd 키가 존재해야 함"
    assert "uncertain_usd" in budget, "budget에 uncertain_usd 키가 존재해야 함"
    assert budget["spent_usd"] == 0.20, f"spent_usd는 0.05 + 0.15 = 0.20이어야 함 (실제: {budget['spent_usd']})"
    assert budget["uncertain_usd"] == 0.15, f"uncertain_usd는 0.15여야 함 (실제: {budget['uncertain_usd']})"
    assert budget["halt_reason"] is None
