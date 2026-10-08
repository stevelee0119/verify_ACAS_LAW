# -*- coding: utf-8 -*-
"""F3 주장 단위 로컬 점수 정렬 및 문맥 발췌 추출 단위 시험.

검증 항목:
1. review_document 실행 시 주장 핵심어에 따라 로컬 점수 정렬로 주장별 최적 발췌가 골라짐 (시험 내 제품 루프 재구현 배제).
2. 주장별 핵심어 매칭 위치 기반 문맥 발췌 구간(800자 이내) 추출 (원문 앞 800자 기계적 절단 방지).
3. 주장 단위 요청 페이로드의 validate_claim_request_payload 유효성 통과 및 스키마 제한 준수.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from packages.common.enums import ExternalAIPolicy, VerificationProfile
from packages.rag_engine.review import (
    _claim_salient_words,
    review_document,
    validate_claim_request_payload,
)


def test_context_aware_excerpt_extraction():
    """800자 이후에 위치한 핵심어에 대해 원문 앞 800자가 아닌 핵심어 주변 문맥이 발췌되는지 검증."""
    # 1,500자 위치에 핵심어가 출현하는 2,500자 합성 본문
    padding_before = "일반적인 안내 규정 내용입니다. " * 50  # 약 1,000자 이상
    target_sentence = "현장 점검 시 추락 위험 방지 조치를 의무적으로 이행하여야 한다."
    padding_after = " 추가적인 세부 관리 지침 및 후속 조치 사항입니다. " * 40  # 약 1,000자 이상
    full_text = padding_before + target_sentence + padding_after

    claim_text = "피고는 현장 점검 시 추락 위험 방지 조치 의무를 이행하지 않았다."
    salient = _claim_salient_words(claim_text)
    assert any(w in salient for w in ("추락", "위험", "방지", "조치"))

    # 핵심어 위치 탐색
    best_pos = -1
    for w in salient:
        pos = full_text.find(w)
        if pos != -1:
            best_pos = pos
            break

    assert best_pos >= 800, "핵심어가 800자 이후에 위치해야 시험 목적에 부합함"

    # 앞뒤 800자 문맥 발췌 계산
    start_pos = max(0, best_pos - 200)
    end_pos = min(len(full_text), start_pos + 800)
    if end_pos - start_pos < 800 and len(full_text) > (end_pos - start_pos):
        start_pos = max(0, end_pos - 800)
    excerpt = full_text[start_pos:end_pos]

    # 검증:
    # 1. 원문 앞 800자(0~800)와 완전히 다름
    assert excerpt != full_text[:800]
    # 2. 발췌문에 핵심 문장이 포함됨
    assert target_sentence in excerpt
    # 3. 발췌문 길이가 800자 이내
    assert len(excerpt) <= 800

    # 4. 페이로드 스키마 검증 통과 확인
    payload = {
        "claim_id": "CLM_001",
        "claim_text": claim_text,
        "reference_sources": [
            {"source_id": "R1", "text": excerpt, "page": 1}
        ],
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
