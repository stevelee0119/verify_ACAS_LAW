# -*- coding: utf-8 -*-
"""F3 주장 단위 선별 규칙 및 예산형 상한(TK-63) 단위 시험.

검증 항목:
1. 선별(TK-63 3.4.1): 대상 주장 12개 이상이고 인용 연결 주장이 문서 순서 11번째 이후일 때,
   상한 10 하에서도 인용 연결 주장이 우선 대조되고 T7 불변식이 유지됨 (합성 입력).
2. 형식 문장(TK-63 3.4.2): 공백 제외 15자 미만의 형식 문장('다 음' 등)이 5순위로 밀려
   상한 밖의 예산 초과(REASON_BUDGET_EXCEEDED)로 남음 (합성 입력).
3. 시간 예산(TK-63 3.4.3): 가짜 시계로 시간 예산을 초과하면 다음 주장을 보내지 않고 중단되며,
   budget.halt_reason이 'TIME'으로 기록됨 (합성 입력).
4. 비용 예산(TK-63 3.4.4): 가짜 실행 비용으로 비용 예산 초과 시 중단되고 원인이 'COST'이며,
   budget_usd가 0이면 비용 예산이 비활성화됨 (합성 입력).
5. 설정값(TK-63 3.4.5): 환경변수(LV_RAG_CLAIM_MAX_PER_DOCUMENT 등)로 설정값이 정상 적용됨.
6. 문맥 발췌 및 review_document 대조 (기존 회귀 방지).
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import packages.common.config as config_module
from packages.common.config import get_settings
from packages.common.enums import ExternalAIPolicy, VerificationProfile
from packages.rag_engine.review import (
    _claim_salient_words,
    review_document,
    select_claims_for_review,
    validate_claim_request_payload,
)


def _make_mock_library(sources=None):
    """합성 테스트용 ReferenceLibrary 대역."""
    if sources is None:
        sources = [{
            "file_id": "fid_test_001",
            "source_id": "R1",
            "title": "합성_운영규정.txt",
            "folder_path": "",
            "page": 1,
            "relevance": 0.9,
            "text_coverage": 0.6,
            "shared_terms": 5,
            "text": "제1조 관련하여 추락방지 및 안전관리 의무 기준을 규정한다. " * 30,
        }]
    return SimpleNamespace(
        summary={"status": "READY", "snapshot_hash": "mock_hash_123"},
        folder="test_folder",
        select=lambda text: {
            "decision": "USED",
            "reason": "RELEVANT_REFERENCE_FOUND",
            "coverage": "CHECKED_INDEXED_CORPUS",
            "sources": sources,
        },
    )


class _MockRouter:
    """합성 테스트용 LLMRouter 대역."""

    def __init__(self, cost_per_call=0.0, claim_observations=None):
        self.executed_requests = []
        self.cost_per_call = cost_per_call
        self.claim_observations = claim_observations or {}

    def has_available_provider(self, **kwargs):
        return True

    async def run(self, role, request, **kwargs):
        self.executed_requests.append(request)
        execution = SimpleNamespace(
            role="PRIMARY_REASONER",
            provider="anthropic",
            model="fake",
            ok=True,
            cost_usd=self.cost_per_call,
            to_dict=lambda: {"cost_usd": self.cost_per_call, "ok": True},
        )
        cid = (request.metadata or {}).get("claim_id")
        obs = self.claim_observations.get(cid, [])
        return SimpleNamespace(
            used=True,
            quarantined=False,
            executions=[execution],
            parsed={"observations": obs},
        )


def _make_document_result(claims, doc_text="합성 서면 본문"):
    return SimpleNamespace(
        document_id="doc_tk63_test",
        normalized=SimpleNamespace(
            visible_text=doc_text,
            pages=[SimpleNamespace(text=doc_text)],
            blocks=[],
        ),
        findings=[],
        claims=claims,
        citations=[],
        engine_data={},
    )


# ---------------------------------------------------------------------------
# 1. 선별 규칙 단위 시험 (TK-63 3.4.1)
# ---------------------------------------------------------------------------
def test_claim_selection_prioritizes_citations_over_document_order(monkeypatch):
    """(합성 입력) 대상 주장 12개 중 11번째의 인용 연결 주장이 상한 10 하에서 우선 대조됨."""
    monkeypatch.setenv("LV_RAG_CLAIM_MAX_PER_DOCUMENT", "10")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_SECONDS", "600")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_USD", "0")
    monkeypatch.setattr(config_module, "_settings", None)

    # 1~10번째: 인용 없는 사실/의견 주장 (20자 이상)
    claims = [
        {"claim_id": f"CLM_{i:02d}", "type": "FACT", "text": f"피고 회사의 일반적인 {i}번째 사실관계 주장 내용입니다."}
        for i in range(1, 11)
    ]
    # 11번째: 인용 연결 주장 (1순위)
    claims.append({
        "claim_id": "CLM_CITATION_11",
        "type": "FACT",
        "citation_ids": ["CIT_999"],
        "text": "피고의 안전관리 운영규정 제7조에 근거한 구체적인 인용 주장입니다.",
    })
    # 12번째: 일반 사실 주장
    claims.append({
        "claim_id": "CLM_12",
        "type": "FACT",
        "text": "피고 회사의 일반적인 12번째 사실관계 주장 내용입니다.",
    })

    doc_text = "\n".join(c["text"] for c in claims)
    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (doc_text, {"omitted_chars": 0}))

    result = _make_document_result(claims, doc_text)
    context = SimpleNamespace(requested_issues=[], profile=VerificationProfile.STANDARD, external_ai_policy=ExternalAIPolicy.ORIGINAL)
    pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))
    router = _MockRouter(claim_observations={
        "CLM_CITATION_11": [{
            "claim_quote": "피고의 안전관리 운영규정 제7조에 근거한 구체적인 인용 주장입니다.",
            "source_id": "R1",
            "source_quote": "제1조 관련하여 추락방지 및 안전관리 의무 기준을 규정한다.",
            "relationship": "SUPPORTS",
            "explanation": "인용 주장 대조 완료",
        }]
    })

    review = review_document(result, _make_mock_library(), router, context, pii)

    # 대조 요청으로 나간 주장 id 수집
    sent_claim_ids = [r.metadata.get("claim_id") for r in router.executed_requests if r.metadata.get("stage") == "claim_rag_advisory"]
    assert len(sent_claim_ids) == 10
    # 원래 11번째였던 인용 연결 주장이 상한 10 안에 포함되어 대조되었는지 검증
    assert "CLM_CITATION_11" in sent_claim_ids
    # 1순위로 승격되어 대조 첫 번째로 처리되었는지 확인
    assert sent_claim_ids[0] == "CLM_CITATION_11"

    # coverage 및 T7 불변식 검증
    coverage = review["claim_coverage"]
    assert coverage["eligible_claims"] == 12
    assert coverage["linked_claims"] == 1
    assert coverage["selection_rule"] == "TK63_CITATION_LEGAL_FACT_LENGTH_V1"
    assert coverage["budget"]["max_per_document"] == 10
    assert coverage["budget"]["halt_reason"] == "COUNT"

    unreviewed_map = {u["claim_id"]: u["reason"] for u in coverage["unreviewed"]}
    assert "CLM_CITATION_11" not in unreviewed_map
    assert len(coverage["unreviewed"]) == 11
    # 상한 밖으로 밀린 2개 주장은 REASON_BUDGET_EXCEEDED
    budget_exceeded = [cid for cid, reason in unreviewed_map.items() if reason == "REASON_BUDGET_EXCEEDED"]
    assert len(budget_exceeded) == 2
    assert coverage["linked_claims"] + len(coverage["unreviewed"]) == coverage["eligible_claims"]


# ---------------------------------------------------------------------------
# 2. 형식 문장 강등 단위 시험 (TK-63 3.4.2)
# ---------------------------------------------------------------------------
def test_claim_selection_deprioritizes_short_boilerplate_sentences(monkeypatch):
    """(합성 입력) 공백 제외 15자 미만의 형식 문장이 5순위로 밀려 상한 밖에 남음."""
    monkeypatch.setenv("LV_RAG_CLAIM_MAX_PER_DOCUMENT", "5")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_SECONDS", "600")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_USD", "0")
    monkeypatch.setattr(config_module, "_settings", None)

    # 앞쪽에 위치한 15자 미만 형식 문장 2개 (공백 제외 15자 미만)
    short_claim_1 = {"claim_id": "CLM_SHORT_1", "type": "FACT", "text": "다 음."}
    short_claim_2 = {"claim_id": "CLM_SHORT_2", "type": "OPINION", "text": "종합하건대 그러하다."}
    # 실질적인 15자 이상 문장 5개
    long_claims = [
        {"claim_id": f"CLM_LONG_{i}", "type": "FACT", "text": f"피고는 원고에 대하여 구체적인 안전배려의무 {i}호를 이행하지 않았다."}
        for i in range(1, 6)
    ]

    claims = [short_claim_1, short_claim_2] + long_claims
    doc_text = "\n".join(c["text"] for c in claims)
    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (doc_text, {"omitted_chars": 0}))

    result = _make_document_result(claims, doc_text)
    context = SimpleNamespace(requested_issues=[], profile=VerificationProfile.STANDARD, external_ai_policy=ExternalAIPolicy.ORIGINAL)
    pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))
    router = _MockRouter()

    review = review_document(result, _make_mock_library(), router, context, pii)

    sent_claim_ids = [r.metadata.get("claim_id") for r in router.executed_requests if r.metadata.get("stage") == "claim_rag_advisory"]
    assert len(sent_claim_ids) == 5
    # 상한 5개 안에는 15자 이상의 실질 문장 5개가 모두 들어가고, 형식 문장은 배제됨
    assert set(sent_claim_ids) == {f"CLM_LONG_{i}" for i in range(1, 6)}

    # 형식 문장 2개는 unreviewed에 REASON_BUDGET_EXCEEDED로 남음
    coverage = review["claim_coverage"]
    unreviewed_map = {u["claim_id"]: u["reason"] for u in coverage["unreviewed"]}
    assert "CLM_SHORT_1" in unreviewed_map
    assert "CLM_SHORT_2" in unreviewed_map
    assert unreviewed_map["CLM_SHORT_1"] == "REASON_BUDGET_EXCEEDED"
    assert unreviewed_map["CLM_SHORT_2"] == "REASON_BUDGET_EXCEEDED"


# ---------------------------------------------------------------------------
# 3. 시간 예산 초과 단위 시험 (TK-63 3.4.3)
# ---------------------------------------------------------------------------
def test_claim_budget_time_limit_halts_with_time_reason(monkeypatch):
    """(합성 입력) 가짜 시계로 시간 예산 초과 시 다음 주장을 보내지 않고 중단되며 halt_reason이 'TIME'임."""
    monkeypatch.setenv("LV_RAG_CLAIM_MAX_PER_DOCUMENT", "30")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_SECONDS", "10")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_USD", "0")
    monkeypatch.setattr(config_module, "_settings", None)

    claims = [
        {"claim_id": f"CLM_T_{i}", "type": "FACT", "text": f"피고의 구체적인 {i}번째 의무 위반 사실관계 주장입니다."}
        for i in range(1, 6)
    ]
    doc_text = "\n".join(c["text"] for c in claims)
    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (doc_text, {"omitted_chars": 0}))

    # 가짜 시계: 1번째 주장 처리 후 시간이 15초(예산 10초 초과) 경과하도록 조작
    clock = [0.0]

    def fake_monotonic():
        val = clock[0]
        clock[0] += 6.0  # 호출될 때마다 6초씩 증가 -> 2번째 루프 진입 전 12초 도달
        return val

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    result = _make_document_result(claims, doc_text)
    context = SimpleNamespace(requested_issues=[], profile=VerificationProfile.STANDARD, external_ai_policy=ExternalAIPolicy.ORIGINAL)
    pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))
    router = _MockRouter()

    review = review_document(result, _make_mock_library(), router, context, pii)

    sent_claim_ids = [r.metadata.get("claim_id") for r in router.executed_requests if r.metadata.get("stage") == "claim_rag_advisory"]
    # 1번째 주장만 전송되고 2번째 주장을 보내기 전에 시간 초과로 중단됨
    assert len(sent_claim_ids) == 1
    assert sent_claim_ids[0] == "CLM_T_1"

    coverage = review["claim_coverage"]
    assert coverage["budget"]["halt_reason"] == "TIME"
    assert coverage["budget"]["budget_seconds"] == 10.0


# ---------------------------------------------------------------------------
# 4. 비용 예산 초과 단위 시험 (TK-63 3.4.4)
# ---------------------------------------------------------------------------
def test_claim_budget_cost_limit_halts_with_cost_reason_and_can_be_disabled(monkeypatch):
    """(합성 입력) 가짜 실행 비용 초과 시 중단(halt_reason='COST') 및 0 설정 시 비활성화 검증."""
    # 1) 비용 예산 활성화 케이스 (예산 1.00 USD, 1회당 0.60 USD -> 2회차 전송 후 누적 1.20 USD로 3회차 전 중단)
    monkeypatch.setenv("LV_RAG_CLAIM_MAX_PER_DOCUMENT", "30")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_SECONDS", "600")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_USD", "1.00")
    monkeypatch.setattr(config_module, "_settings", None)

    claims = [
        {"claim_id": f"CLM_C_{i}", "type": "FACT", "text": f"피고의 구체적인 비용 시험 {i}번째 주장입니다."}
        for i in range(1, 6)
    ]
    doc_text = "\n".join(c["text"] for c in claims)
    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (doc_text, {"omitted_chars": 0}))

    result = _make_document_result(claims, doc_text)
    context = SimpleNamespace(requested_issues=[], profile=VerificationProfile.STANDARD, external_ai_policy=ExternalAIPolicy.ORIGINAL)
    pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    router = _MockRouter(cost_per_call=0.60)
    review = review_document(result, _make_mock_library(), router, context, pii)

    sent_claim_ids = [r.metadata.get("claim_id") for r in router.executed_requests if r.metadata.get("stage") == "claim_rag_advisory"]
    # 2개 대조 후 누적 비용 1.20 USD >= 1.00 USD 이므로 3번째 전송 전 중단
    assert len(sent_claim_ids) == 2
    assert review["claim_coverage"]["budget"]["halt_reason"] == "COST"

    # 2) 비용 예산 0 (비활성화) 케이스: 예산 한도 없이 모두 전송됨
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_USD", "0")
    monkeypatch.setattr(config_module, "_settings", None)

    router_disabled = _MockRouter(cost_per_call=0.60)
    result_disabled = _make_document_result(claims, doc_text)
    review_disabled = review_document(result_disabled, _make_mock_library(), router_disabled, context, pii)

    sent_disabled = [r.metadata.get("claim_id") for r in router_disabled.executed_requests if r.metadata.get("stage") == "claim_rag_advisory"]
    assert len(sent_disabled) == 5
    assert review_disabled["claim_coverage"]["budget"]["halt_reason"] is None


# ---------------------------------------------------------------------------
# 5. 설정값 적용 단위 시험 (TK-63 3.4.5)
# ---------------------------------------------------------------------------
def test_claim_settings_applied_from_environment_variables(monkeypatch):
    """(합성 입력) 환경변수로 설정값 변경 시 Settings 및 claim_coverage에 반영됨을 검증."""
    monkeypatch.setenv("LV_RAG_CLAIM_MAX_PER_DOCUMENT", "15")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_SECONDS", "180")
    monkeypatch.setenv("LV_RAG_CLAIM_BUDGET_USD", "2.50")
    monkeypatch.setattr(config_module, "_settings", None)

    settings = get_settings()
    assert settings.rag_claim_max_per_document == 15
    assert settings.rag_claim_budget_seconds == 180.0
    assert settings.rag_claim_budget_usd == 2.50

    claims = [{"claim_id": "CLM_1", "type": "FACT", "text": "피고의 안전관리 의무 위반 관련 단일 주장입니다."}]
    doc_text = claims[0]["text"]
    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (doc_text, {"omitted_chars": 0}))

    result = _make_document_result(claims, doc_text)
    context = SimpleNamespace(requested_issues=[], profile=VerificationProfile.STANDARD, external_ai_policy=ExternalAIPolicy.ORIGINAL)
    pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(result, _make_mock_library(), _MockRouter(), context, pii)
    budget_record = review["claim_coverage"]["budget"]
    assert budget_record["max_per_document"] == 15
    assert budget_record["budget_seconds"] == 180.0
    assert budget_record["budget_usd"] == 2.50


# ---------------------------------------------------------------------------
# 6. 문맥 발췌 및 선별 함수 단위 시험 (기존 회귀 방지)
# ---------------------------------------------------------------------------
def test_context_aware_excerpt_extraction():
    """800자 이후에 위치한 핵심어에 대해 원문 앞 800자가 아닌 핵심어 주변 문맥이 발췌되는지 검증."""
    padding_before = "일반적인 안내 규정 내용입니다. " * 50
    target_sentence = "현장 점검 시 추락 위험 방지 조치를 의무적으로 이행하여야 한다."
    padding_after = " 추가적인 세부 관리 지침 및 후속 조치 사항입니다. " * 40
    full_text = padding_before + target_sentence + padding_after

    claim_text = "피고는 현장 점검 시 추락 위험 방지 조치 의무를 이행하지 않았다."
    salient = _claim_salient_words(claim_text)
    assert any(w in salient for w in ("추락", "위험", "방지", "조치"))

    best_pos = -1
    for w in salient:
        pos = full_text.find(w)
        if pos != -1:
            best_pos = pos
            break

    assert best_pos >= 800

    start_pos = max(0, best_pos - 200)
    end_pos = min(len(full_text), start_pos + 800)
    if end_pos - start_pos < 800 and len(full_text) > (end_pos - start_pos):
        start_pos = max(0, end_pos - 800)
    excerpt = full_text[start_pos:end_pos]

    assert excerpt != full_text[:800]
    assert target_sentence in excerpt
    assert len(excerpt) <= 800

    payload = {
        "claim_id": "CLM_001",
        "claim_text": claim_text,
        "reference_sources": [{"source_id": "R1", "text": excerpt, "page": 1}],
    }
    assert validate_claim_request_payload(payload) is True


def test_claim_level_excerpt_selection_via_review_document(monkeypatch):
    """review_document 실행 시 이미 읽은 sources 안에서 주장별 핵심어에 따라 서로 다른 관련 발췌가 선정됨을 검증."""
    # 2가지 서로 다른 참고자료 준비:
    # R1: 안전 및 추락 방지 규정 (앞부분 패딩 후 1,000자 부근에 핵심 내용 배치)
    pad1 = "산업현장 일반 시설관리 기본 원칙입니다. " * 40
    safety_body = pad1 + "작업발판 및 추락방지 난간 설치 의무 기준을 반드시 준수하여야 한다." + pad1
    # R2: 임금 및 퇴직금 정산 규정 (앞부분 패딩 후 1,000자 부근에 핵심 내용 배치)
    pad2 = "경영지원 일반 행정처리 기본 절차입니다. " * 40
    wage_body = pad2 + "퇴직금 지급 기일은 퇴직일로부터 14일 이내로 정산 지급하여야 한다." + pad2

    sources_list = [
        {
            "file_id": "fid_safety_001",
            "source_id": "R1",
            "title": "안전관리 운영지침.txt",
            "folder_path": "",
            "page": 1,
            "relevance": 0.8,
            "text_coverage": 0.5,
            "shared_terms": 5,
            "text": safety_body,
        },
        {
            "file_id": "fid_wage_002",
            "source_id": "R2",
            "title": "급여및퇴직금 관리규정.txt",
            "folder_path": "",
            "page": 1,
            "relevance": 0.8,
            "text_coverage": 0.5,
            "shared_terms": 5,
            "text": wage_body,
        },
    ]

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

    # 2가지 서로 다른 주장:
    claim1_text = "피고는 작업발판 및 추락방지 난간을 설치하지 않아 사고를 유발하였다."
    claim2_text = "피고는 원고의 퇴직일로부터 14일 이내에 퇴직금을 지급하지 않았다."

    combined_doc_text = f"{claim1_text}\n{claim2_text}"
    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (combined_doc_text, {"omitted_chars": 0}))

    result = SimpleNamespace(
        document_id="doc_test_1",
        normalized=SimpleNamespace(visible_text=combined_doc_text, pages=[SimpleNamespace(text=combined_doc_text)], blocks=[]),
        findings=[],
        claims=[
            {"claim_id": "CLM_SAFETY", "text": claim1_text},
            {"claim_id": "CLM_WAGE", "text": claim2_text},
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

    executed_requests = []

    class MockRouter:
        def has_available_provider(self, **kwargs):
            return True

        async def run(self, role, request, **kwargs):
            executed_requests.append(request)
            return SimpleNamespace(used=True, quarantined=False, executions=[], parsed={"observations": []})

    review_document(result, library, MockRouter(), context, pii)

    # 주장 단위 대조 요청(stage="claim_rag_advisory") 필터링
    claim_reqs = [r for r in executed_requests if r.metadata.get("stage") == "claim_rag_advisory"]
    assert len(claim_reqs) == 2, f"주장 2건에 대해 각각 대조 요청이 생성되어야 함 (실제: {len(claim_reqs)})"

    # 주장 1 검증: 안전 관련 주장 -> R1(안전지침)이 최우선 발췌로 선택됨
    req1_payload = json.loads(claim_reqs[0].user)
    assert req1_payload["claim_id"] == "CLM_SAFETY"
    assert validate_claim_request_payload(req1_payload) is True
    assert req1_payload["reference_sources"][0]["source_id"] == "R1"
    assert "추락방지 난간 설치 의무" in req1_payload["reference_sources"][0]["text"]
    assert req1_payload["reference_sources"][0]["text"] != safety_body[:800]

    # 주장 2 검증: 퇴직금 관련 주장 -> R2(퇴직금규정)가 최우선 발췌로 선택됨
    req2_payload = json.loads(claim_reqs[1].user)
    assert req2_payload["claim_id"] == "CLM_WAGE"
    assert validate_claim_request_payload(req2_payload) is True
    assert req2_payload["reference_sources"][0]["source_id"] == "R2"
    assert "퇴직금 지급 기일" in req2_payload["reference_sources"][0]["text"]
    assert req2_payload["reference_sources"][0]["text"] != wage_body[:800]
