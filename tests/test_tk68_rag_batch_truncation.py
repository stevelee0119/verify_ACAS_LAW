"""TK-68 문서 단위 Drive 대조 묶음 크기 축소 및 출력 한도 잘림 방지 단위 시험."""
import asyncio
import hashlib
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from packages.common.enums import ExternalAIPolicy
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.llm_router.router import ModelExecution, RouterResult
from packages.rag_engine.review import grounded_observations, review_document
from packages.verification_engine.pipeline import DocumentResult, ProjectContext


def _make_dummy_library(sources: List[Dict[str, Any]]):
    """테스트용 가짜 참고자료 라이브러리 생성."""
    class FakeLibrary:
        summary = {"status": "READY", "snapshot_hash": "dummy_snapshot_hash"}

        def select(self, query: str):
            return {
                "decision": "PROCEED",
                "reason": "OK",
                "coverage": "FULL",
                "sources": list(sources),
            }

        def has_case_tables(self):
            return False

    return FakeLibrary()


def _make_doc_result(text: str) -> DocumentResult:
    """테스트용 문서 결과 객체 생성."""
    doc = NormalizedDocument(
        "doc1", "test.txt", "text/plain", hashlib.sha256(text.encode()).hexdigest(),
        pages=[Page(1, blocks=[Block("b1", text, 1)])]
    )
    res = DocumentResult("doc1", "test.txt", normalized=doc)
    res.claims = []
    res.citations = []
    return res


def test_tk68_batch_size_reduction_and_metadata_stage():
    """6개 참고자료 제공 시 3개씩 분할되어 drive_rag_advisory stage로 요청되는지 검증."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: 계약 손해배상 요건.", "page": 1}
        for i in range(1, 7)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    sent_requests = []

    class MockRouter:
        def has_available_provider(self, **kwargs):
            return True

        async def run(self, role, request, **kwargs):
            sent_requests.append(request)
            data = json.loads(request.user)
            refs = data.get("untrusted_references", [])
            # 각 참고자료에 대해 관찰 결과 생성
            obs = [
                {
                    "claim_quote": doc_text[:10],
                    "source_id": r["source_id"],
                    "source_quote": r["text"][:10],
                    "relationship": "CONTEXT",
                    "explanation": f"참고자료 {r['source_id']} 대조 확인.",
                }
                for r in refs
            ]
            exec_record = ModelExecution(
                role="primary_reasoner", provider="anthropic", model="fake", ok=True
            )
            return RouterResult(used=True, parsed={"observations": obs}, executions=[exec_record])

    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, MockRouter(), context, mock_pii)

    # 6개 소스가 기본 크기 3개로 분할되어 정확히 2회 요청되었는지 검증
    assert len(sent_requests) == 2
    for idx, req in enumerate(sent_requests, start=1):
        assert req.metadata.get("stage") == "drive_rag_advisory"
        assert req.metadata.get("batch") == idx
        req_data = json.loads(req.user)
        assert len(req_data["untrusted_references"]) == 3

    assert review["status"] == "ADVISORY_REVIEWED"
    assert review["batches_evaluated"] == 2
    assert len(review["observations"]) == 6


def test_tk68_batch_text_char_limit_split():
    """참고자료 개수가 2개라도 본문 글자 수가 12,000자를 초과하면 분할 요청되는지 검증."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    # 각 참고자료의 본문 길이가 8,000자 (합계 16,000자로 12,000자 초과)
    long_text = "손해배상 " * 1600
    sources = [
        {"source_id": "R1", "title": "대형 규정 1", "text": long_text, "page": 1},
        {"source_id": "R2", "title": "대형 규정 2", "text": long_text, "page": 1},
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    sent_requests = []

    class MockRouter:
        def has_available_provider(self, **kwargs):
            return True

        async def run(self, role, request, **kwargs):
            sent_requests.append(request)
            data = json.loads(request.user)
            refs = data.get("untrusted_references", [])
            obs = [
                {
                    "claim_quote": doc_text[:10],
                    "source_id": r["source_id"],
                    "source_quote": r["text"][:10],
                    "relationship": "CONTEXT",
                    "explanation": "대형 자료 대조.",
                }
                for r in refs
            ]
            exec_record = ModelExecution(
                role="primary_reasoner", provider="anthropic", model="fake", ok=True
            )
            return RouterResult(used=True, parsed={"observations": obs}, executions=[exec_record])

    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, MockRouter(), context, mock_pii)

    # 12,000자 초과로 1개씩 2회로 분할 요청되었는지 단언
    assert len(sent_requests) == 2
    assert len(json.loads(sent_requests[0].user)["untrusted_references"]) == 1
    assert len(json.loads(sent_requests[1].user)["untrusted_references"]) == 1
    assert review["batches_evaluated"] == 2


def test_tk68_adaptive_halving_on_output_truncated():
    """OUTPUT_TRUNCATED 발생 시 적응형 이분할(Adaptive Halving)로 재시도하여 의견이 온전히 회수되는지 검증."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    # 3개 참고자료
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: 손해배상 요건.", "page": 1}
        for i in range(1, 4)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    call_count = 0
    requested_batch_sizes = []

    class MockRouter:
        def has_available_provider(self, **kwargs):
            return True

        async def run(self, role, request, **kwargs):
            nonlocal call_count
            call_count += 1
            data = json.loads(request.user)
            refs = data.get("untrusted_references", [])
            requested_batch_sizes.append(len(refs))

            # 첫 번째 호출(3개 묶음)에서 OUTPUT_TRUNCATED 발생 모의
            if call_count == 1:
                exec_record = ModelExecution(
                    role="primary_reasoner", provider="anthropic", model="fake", ok=False,
                    error="OUTPUT_TRUNCATED: 응답이 출력 한도(4000 토큰)에서 잘림"
                )
                return RouterResult(used=False, executions=[exec_record])

            # 분할된 호출(1개 또는 2개)에서는 정상 성공
            obs = [
                {
                    "claim_quote": doc_text[:10],
                    "source_id": r["source_id"],
                    "source_quote": r["text"][:10],
                    "relationship": "CONTEXT",
                    "explanation": f"참고자료 {r['source_id']} 분할 성공 대조.",
                }
                for r in refs
            ]
            exec_record = ModelExecution(
                role="primary_reasoner", provider="anthropic", model="fake", ok=True
            )
            return RouterResult(used=True, parsed={"observations": obs}, executions=[exec_record])

    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, MockRouter(), context, mock_pii)

    # 호출 흐름 검증:
    # 1. 3개 묶음 호출 -> OUTPUT_TRUNCATED 발생
    # 2. 적응형 이분할로 1개와 2개로 분할됨 (mid = 3 // 2 = 1 -> [:1], [1:])
    # 3. 1개 묶음 호출 -> 성공
    # 4. 2개 묶음 호출 -> 성공
    assert requested_batch_sizes == [3, 1, 2]
    assert review["status"] == "ADVISORY_REVIEWED"
    # 모든 3개 참고자료의 관찰 결과가 온전히 회수되었는지 단언
    collected_sources = {obs["source_id"] for obs in review["observations"]}
    assert collected_sources == {"R1", "R2", "R3"}
    assert review["batches_evaluated"] == 2


def test_tk68_single_source_truncated_falls_back_to_retry():
    """참고자료가 1개인 상태에서 OUTPUT_TRUNCATED 발생 시 추가 분할 없이 타 공급자 재시도로 이어지는지 검증."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    sources = [
        {"source_id": "R1", "title": "단일 규정", "text": "단일 참고자료 본문 내용입니다.", "page": 1}
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    calls = []

    class MockRouter:
        def has_available_provider(self, **kwargs):
            return True

        async def run(self, role, request, exclude=None, **kwargs):
            calls.append({"exclude": exclude})
            if not exclude:
                # 1차 시도 anthropic에서 OUTPUT_TRUNCATED 발생
                exec_record = ModelExecution(
                    role="primary_reasoner", provider="anthropic", model="fake", ok=False,
                    error="OUTPUT_TRUNCATED: 응답이 출력 한도(4000 토큰)에서 잘림"
                )
                return RouterResult(used=False, executions=[exec_record])
            else:
                # 2차 시도 openai(재시도)에서 성공
                obs = [
                    {
                        "claim_quote": doc_text[:10],
                        "source_id": "R1",
                        "source_quote": "단일 참고자료 본문",
                        "relationship": "CONTEXT",
                        "explanation": "재시도 공급자 대조 성공.",
                    }
                ]
                exec_record = ModelExecution(
                    role="primary_reasoner", provider="openai", model="fake", ok=True
                )
                return RouterResult(used=True, parsed={"observations": obs}, executions=[exec_record])

    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, MockRouter(), context, mock_pii)

    # 1차 호출(anthropic) 실패 후 2차 재시도 호출(exclude=["anthropic"])로 이어졌는지 확인
    assert len(calls) == 2
    assert calls[0]["exclude"] is None
    assert calls[1]["exclude"] == ["anthropic"]
    assert review["retried_after"] == ["anthropic"]
    assert review["status"] == "ADVISORY_REVIEWED"
    assert len(review["observations"]) == 1
