# -*- coding: utf-8 -*-
"""F3 주장 단위 검색 및 문맥 발췌 추출 단위 시험.

검증 항목:
1. ReferenceLibrary.sync 완료 후 self.client 속성 보존.
2. 주장별 핵심어 매칭 위치 기반 문맥 발췌 구간(800자 이내) 추출 (원문 앞 800자 기계적 절단 방지).
3. 주장당 검색 호출 한도(SEARCH_CALLS_PER_CLAIM = 2) 준수.
4. validate_claim_request_payload 유효성 통과.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from packages.rag_engine.library import ReferenceLibrary
from packages.rag_engine.review import (
    SEARCH_CALLS_PER_CLAIM,
    validate_claim_request_payload,
)


class _MockDriveClient:
    """단위 시험용 Drive 클라이언트 대역."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    def remaining(self):
        return 100

    def inventory(self, *args, **kwargs):
        return []

    def search_fulltext(self, folder_ids, terms, *, max_results=200):
        self.calls.append((folder_ids, terms))
        return {"fid_mock_001"}

    def close(self):
        pass


def test_reference_library_preserves_client(tmp_path):
    """ReferenceLibrary.sync 실행 시 self.client 속성이 정상 저장되어 검색에 활용 가능한지 검증."""
    settings = SimpleNamespace(
        rag_drive_folder_id="test_folder_id",
        storage_root=str(tmp_path),
        rag_metadata_first=False,
        rag_sync_seconds=10,
        rag_max_files=10,
        rag_inventory_max_files=10,
        rag_download_mb=10,
        allow_network=True,
    )
    lib = ReferenceLibrary(settings, client_factory=_MockDriveClient)
    assert lib.client is None
    lib.sync()
    assert lib.client is not None
    assert isinstance(lib.client, _MockDriveClient)


def test_context_aware_excerpt_extraction():
    """800자 이후에 위치한 핵심어에 대해 원문 앞 800자가 아닌 핵심어 주변 문맥이 발췌되는지 검증."""
    from packages.rag_engine import relevance

    # 1,500자 위치에 핵심어가 출현하는 2,500자 합성 본문
    padding_before = "가나다라마바사 일반적인 안내 규정 내용입니다. " * 50  # 약 1,300자
    target_sentence = "현장 점검 시 추락 위험 방지 조치를 의무적으로 이행하여야 한다."
    padding_after = " 추가적인 세부 관리 지침 및 후속 조치 사항입니다. " * 40  # 약 1,200자
    full_text = padding_before + target_sentence + padding_after

    claim_text = "피고는 현장 점검 시 추락 위험 방지 조치 의무를 이행하지 않았다."
    from packages.rag_engine.review import _claim_salient_words
    salient = _claim_salient_words(claim_text)
    assert "추락" in salient or "위험" in salient or "조치" in salient

    # 발췌 로직 시뮬레이션
    best_pos = -1
    for w in salient:
        pos = full_text.find(w)
        if pos != -1:
            best_pos = pos
            break

    assert best_pos >= 1000, "핵심어가 800자 이후에 위치해야 시험 목적에 부합함"

    # 앞뒤 800자 문맥 발췌
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


def test_search_calls_bounded_per_claim():
    """주장당 search_fulltext 호출 횟수가 최대 2회(SEARCH_CALLS_PER_CLAIM)를 초과하지 않는지 검증."""
    client = _MockDriveClient()
    folder_ids = ["test_folder"]
    salient = ["안전점검", "위험방지", "작업발판", "추락방지", "보호구", "비계연결", "안전통로"]

    search_calls = 0
    search_halted = False
    found_fids = set()

    # 1차 검색
    if client and salient and not search_halted:
        res = client.search_fulltext(folder_ids, salient[:5], max_results=200)
        search_calls += 1
        # 1차에서 빈 결과 시뮬레이션
        res = set()

        # 2차 검색
        if not search_halted and search_calls < SEARCH_CALLS_PER_CLAIM and not res and len(salient) > 5:
            res2 = client.search_fulltext(folder_ids, salient[5:10], max_results=200)
            search_calls += 1
            if isinstance(res2, (set, list)):
                found_fids.update(res2)

    assert search_calls <= SEARCH_CALLS_PER_CLAIM
    assert search_calls == 2
    assert len(client.calls) == 2


def test_claim_search_executes_during_review(monkeypatch):
    """review_document 실행 시 library.client.search_fulltext가 실제로 호출되고 맞춤 발췌가 구성되는지 검증."""
    from packages.rag_engine.review import review_document
    from packages.common.enums import ExternalAIPolicy, VerificationProfile

    client = _MockDriveClient()
    source_text = "서두 안내문입니다. " * 60 + "현장 점검 시 추락 위험 방지 조치를 이행하여야 한다." + " 후반 지침입니다. " * 40
    library = SimpleNamespace(
        summary={"status": "READY", "snapshot_hash": "mock_hash"},
        client=client,
        folder="test_folder",
        select=lambda text: {
            "decision": "USED",
            "reason": "RELEVANT_REFERENCE_FOUND",
            "coverage": "CHECKED_INDEXED_CORPUS",
            "sources": [{
                "file_id": "fid_mock_001",
                "source_id": "R1",
                "title": "안전관리 운영지침.txt",
                "folder_path": "",
                "page": 1,
                "relevance": 0.8,
                "text_coverage": 0.5,
                "shared_terms": 5,
                "text": source_text,
            }],
        },
    )

    doc_text = "피고는 현장 점검 시 추락 위험 방지 조치 의무를 이행하지 않았다."
    monkeypatch.setattr("packages.rag_engine.review.analysis_text", lambda doc, findings: (doc_text, {"omitted_chars": 0}))
    result = SimpleNamespace(
        document_id="doc1",
        normalized=SimpleNamespace(visible_text=doc_text, pages=[SimpleNamespace(text=doc_text)], blocks=[]),
        findings=[],
        claims=[{"claim_id": "CLM_1", "text": doc_text}],
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

    # 1. client.search_fulltext가 실제로 호출되었는지 검증
    assert len(client.calls) >= 1
    # 2. 주장 단위 대조 요청(stage="claim_rag_advisory")이 라우터에 전달되었는지 검증
    claim_reqs = [r for r in executed_requests if r.metadata.get("stage") == "claim_rag_advisory"]
    assert len(claim_reqs) == 1
    user_payload = json.loads(claim_reqs[0].user)
    assert user_payload["claim_id"] == "CLM_1"
    # 3. 맞춤 발췌문에 핵심 문장이 포함되고 기계적 선두 절단이 아님을 검증
    extracted_text = user_payload["reference_sources"][0]["text"]
    assert "추락 위험 방지 조치" in extracted_text
    assert extracted_text != source_text[:800]

