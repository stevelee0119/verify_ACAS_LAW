"""TK-68 문서 단위 Drive 대조 묶음 크기 축소 및 비용 비증가 조건(C1~C3) 단위 시험."""
import asyncio
import hashlib
import json
import math
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from packages.common.enums import ExternalAIPolicy
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.llm_router.router import ModelExecution, RouterResult
from packages.rag_engine.review import report_lines, review_document
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


def _simulate_before_stats(
    doc_text: str, sources: List[Dict[str, Any]], threshold: int,
    is_doc9_scenario: bool = False, always_fail: bool = False
) -> Dict[str, Any]:
    """변경 전(Steve 3c89a4e) 경로의 실행 기록 시뮬레이션:
    - 6개씩 고정 묶음
    - is_doc9_scenario=True: 서면9 실제 양상 모델링
      (첫 묶음 6개만 Anthropic에서 잘린 뒤 대체 공급자 재시도 성공, 둘째 묶음 5개는 첫 시도 성공)
    - always_fail=True: 모든 묶음에서 1차·2차 시도 모두 실패
    """
    batches = [sources[i:i + 6] for i in range(0, len(sources), 6)] or [sources]
    calls = 0
    input_tokens = 0
    output_tokens = 0
    latency_ms = 0
    cost_usd = 0.0

    for b_idx, s_batch in enumerate(batches):
        req_user = json.dumps({"document": doc_text, "untrusted_references": s_batch}, ensure_ascii=False)
        in_tok = len(req_user) // 4
        calls += 1
        input_tokens += in_tok

        if always_fail:
            # 1차 실패
            output_tokens += 4000
            latency_ms += 30000
            cost_usd += round(in_tok * 0.000003 + 4000 * 0.000015, 6)
            # 2차 실패
            calls += 1
            input_tokens += in_tok
            output_tokens += 4000
            latency_ms += 30000
            cost_usd += round(in_tok * 0.000003 + 4000 * 0.000015, 6)
        elif is_doc9_scenario:
            if b_idx == 0:
                # 서면9 첫 묶음(6개): 1차 Anthropic 실패(잘림) + 2차 대체 공급자 성공
                output_tokens += 4000
                latency_ms += 30000
                cost_usd += round(in_tok * 0.000003 + 4000 * 0.000015, 6)

                calls += 1
                input_tokens += in_tok
                out_tok = len(s_batch) * 200
                output_tokens += out_tok
                latency_ms += len(s_batch) * 1000
                cost_usd += round(in_tok * 0.000003 + out_tok * 0.000015, 6)
            else:
                # 서면9 둘째 묶음(5개): 1차 시도 성공
                out_tok = len(s_batch) * 200
                output_tokens += out_tok
                latency_ms += len(s_batch) * 1000
                cost_usd += round(in_tok * 0.000003 + out_tok * 0.000015, 6)
        else:
            if len(s_batch) > threshold:
                # 1차 실패 후 2차 재시도 성공
                output_tokens += 4000
                latency_ms += 30000
                cost_usd += round(in_tok * 0.000003 + 4000 * 0.000015, 6)

                calls += 1
                input_tokens += in_tok
                out_tok = len(s_batch) * 200
                output_tokens += out_tok
                latency_ms += len(s_batch) * 1000
                cost_usd += round(in_tok * 0.000003 + out_tok * 0.000015, 6)
            else:
                out_tok = len(s_batch) * 200
                output_tokens += out_tok
                latency_ms += len(s_batch) * 1000
                cost_usd += round(in_tok * 0.000003 + out_tok * 0.000015, 6)

    return {
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": round(cost_usd, 6),
    }


class SimulatedRouter:
    """C5 요구사항 가짜 공급자 라우터:
    - 실행 기록에 input_tokens, cost_usd(입력 글자 수 비례), output_tokens, latency_ms(참고자료 수 비례) 기록
    - threshold 초과 묶음은 OUTPUT_TRUNCATED 반환
    """

    def __init__(self, doc_text: str, threshold: int = 5, always_fail: bool = False):
        self.doc_text = doc_text
        self.threshold = threshold
        self.always_fail = always_fail
        self.executions: List[ModelExecution] = []
        self.sent_requests = []

    def has_available_provider(self, **kwargs):
        return True

    async def run(self, role, request, exclude=None, **kwargs):
        self.sent_requests.append(request)
        data = json.loads(request.user)
        refs = data.get("untrusted_references", [])
        in_tok = len(request.user) // 4

        # exclude가 지정된 대체 공급자 호출이거나 정상 크기인 경우 성공
        is_truncated = self.always_fail or (not exclude and len(refs) > self.threshold)
        if is_truncated:
            out_tok = 4000
            lat_ms = 30000
            cost = round(in_tok * 0.000003 + out_tok * 0.000015, 6)
            exec_rec = ModelExecution(
                role="primary_reasoner", provider="anthropic", model="fake", ok=False,
                input_tokens=in_tok, output_tokens=out_tok, latency_ms=lat_ms, cost_usd=cost,
                error="OUTPUT_TRUNCATED: 응답이 출력 한도(4000 토큰)에서 잘림"
            )
            self.executions.append(exec_rec)
            return RouterResult(used=False, executions=[exec_rec])

        # 정상 성공
        out_tok = len(refs) * 200
        lat_ms = len(refs) * 1000
        cost = round(in_tok * 0.000003 + out_tok * 0.000015, 6)
        provider_name = "openai" if exclude else "anthropic"
        obs = [
            {
                "claim_quote": self.doc_text[:10],
                "source_id": r["source_id"],
                "source_quote": r["text"][:10],
                "relationship": "CONTEXT",
                "explanation": f"참고자료 {r['source_id']} 대조 확인.",
            }
            for r in refs
        ]
        exec_rec = ModelExecution(
            role="primary_reasoner", provider=provider_name, model="fake", ok=True,
            input_tokens=in_tok, output_tokens=out_tok, latency_ms=lat_ms, cost_usd=cost,
        )
        self.executions.append(exec_rec)
        return RouterResult(used=True, parsed={"observations": obs}, executions=[exec_rec])


def test_tk68_c1_no_truncation_general_inputs():
    """C1 검증: 잘림 없는 일반 입력(N=6, 작은 참고자료 조각당 800자 이하)에서 호출 수·입력 토큰·비용이 변경 전 이하임을 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    # 실제 발췌 크기: 조각당 800자 (1,200자 이하 준수)
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: " + ("손해배상 " * 80), "page": 1}
        for i in range(1, 7)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    router = SimulatedRouter(doc_text, threshold=6)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    before_stats = _simulate_before_stats(doc_text, sources, threshold=6)

    after_calls = len(router.sent_requests)
    after_in_tok = sum(e.input_tokens for e in router.executions)
    after_cost = sum(e.cost_usd for e in router.executions)

    # C1 단언: 호출 수 1회 이하, 입력 토큰 변경 전 이하, 비용 변경 전 이하
    assert after_calls == 1
    assert after_calls <= before_stats["calls"]
    assert after_in_tok <= before_stats["input_tokens"]
    assert round(after_cost, 6) <= round(before_stats["cost_usd"], 6)

    assert review["status"] == "ADVISORY_REVIEWED"
    assert len(review["observations"]) == 6
    assert review["batches_evaluated"] == 1


def test_tk68_c2_document9_truncation_inputs():
    """C2 검증: 서면9 실제 양상(N=11, 본문 7,000자, 조각당 1,000자)에서 호출 수 변경 전 이하, 비용 변경 전 미만 단언."""
    # 서면9처럼 긴 서면 본문 (7,000자)
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다.\n" + ("소송 서면 본문 상세 내용입니다. " * 300)
    # 실제 Drive 발췌 크기: 조각당 1,000자 (1,200자 이하 준수)
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: " + ("규정조항 " * 100), "page": 1}
        for i in range(1, 12)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    # threshold = 5: 6개는 잘리고 5개 이하는 성공 (서면9 실제 양상)
    router = SimulatedRouter(doc_text, threshold=5)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    # 변경 전 서면9 실제 양상 시뮬레이션 (첫 묶음 6개 실패+재시도=2회, 둘째 묶음 5개 성공=1회 -> 총 3회)
    before_stats = _simulate_before_stats(doc_text, sources, threshold=5, is_doc9_scenario=True)

    after_calls = len(router.sent_requests)
    after_in_tok = sum(e.input_tokens for e in router.executions)
    after_out_tok = sum(e.output_tokens for e in router.executions)
    after_lat_ms = sum(e.latency_ms for e in router.executions)
    after_cost = sum(e.cost_usd for e in router.executions)

    # C2 단언:
    # 1. 호출 수: 변경 전(3회) 이하 (본문 길이 연동으로 5개, 5개, 1개 사전 분할되어 3회 호출)
    assert after_calls == 3
    assert after_calls <= before_stats["calls"]
    # 2. 입력 토큰 합계: 변경 전 이하
    assert after_in_tok <= before_stats["input_tokens"]
    # 3. 출력 토큰 합계: 변경 전 이하 (실패 4,000토큰 낭비 제거)
    assert after_out_tok < before_stats["output_tokens"]
    # 4. 지연 시간 합계: 변경 전 이하 (실패 30초 대기 제거)
    assert after_lat_ms < before_stats["latency_ms"]
    # 5. 비용 합계: 변경 전보다 작음 (실패 낭비 비용 절감)
    assert round(after_cost, 6) < round(before_stats["cost_usd"], 6)

    # 11개 모든 참고자료 검토 의견 정상 수집 단언
    assert review["status"] == "ADVISORY_REVIEWED"
    collected_ids = {obs["source_id"] for obs in review["observations"]}
    assert len(collected_ids) == 11


def test_tk68_c3_worst_case_continuous_truncation():
    """C3 검증: 최악의 계속 잘림 상황에서 호출 수가 2*ceil(N/6) 이하로 강제 차단되고 report_lines에 노출됨을 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: 조항 내용입니다.", "page": 1,
         "modified_time": "2026-10-09T00:00:00Z", "sha256": "dummy_sha", "url": "https://drive.google.com/test"}
        for i in range(1, 12)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    # always_fail=True: 모든 호출에서 OUTPUT_TRUNCATED 발생
    router = SimulatedRouter(doc_text, threshold=0, always_fail=True)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    before_worst_stats = _simulate_before_stats(doc_text, sources, threshold=0, always_fail=True)

    after_calls = len(router.sent_requests)
    after_in_tok = sum(e.input_tokens for e in router.executions)

    # C3 단언: 호출 수 <= 2 * ceil(N/6) = 2 * ceil(11/6) = 4
    max_allowed_calls = 2 * math.ceil(len(sources) / 6)
    assert after_calls <= max_allowed_calls
    assert after_calls <= before_worst_stats["calls"]
    assert after_in_tok <= before_worst_stats["input_tokens"]

    # 상한 도달로 대조되지 못한 참고자료가 'unreviewed_drive_sources'에 기록됨을 단언
    assert "unreviewed_drive_sources" in review
    assert len(review["unreviewed_drive_sources"]) > 0

    # report_lines 보고서에 미대조 참고자료 라인이 노출됨을 단언
    doc_result.engine_data["rag"] = review
    run_result = SimpleNamespace(
        run_manifest={"reference_library": {"status": "READY"}},
        documents=[doc_result]
    )
    lines = report_lines(run_result)
    assert any("미대조 참고자료" in l for l in lines)


def test_tk68_c6_coverage_preservation_fallback():
    """보완 3 검증: N=6 작은 문서에서 1차 시도 잘림 발생 시 남은 예산(1회)으로 대체 공급자 재시도를 수행하여 6개 전체 대조 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: 내용 대조입니다.", "page": 1}
        for i in range(1, 7)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    # threshold = 3: 1차(6개)는 실패하지만, 남은 호출이 1회뿐이므로 반 나누기 대신 대체 공급자 재시도로 전환
    router = SimulatedRouter(doc_text, threshold=3)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    # 1차 시도(6개 실패) + 2차 대체 공급자 재시도(6개 성공) = 총 2회 호출 (상한 2회 충족)
    assert len(router.sent_requests) == 2
    assert review["status"] == "ADVISORY_REVIEWED"
    # 대조 누락 없이 6개 전원 대조 완료 단언
    collected_ids = {obs["source_id"] for obs in review["observations"]}
    assert len(collected_ids) == 6
    assert "unreviewed_drive_sources" not in review


def test_tk68_invariants_and_metadata_preserved():
    """C4 불변 요건 검증: stage 'drive_rag_advisory', ENVELOPE_SCHEMA, advisory_only 등 보존 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    sources = [
        {"source_id": "R1", "title": "규정", "text": "참고자료 본문 내용입니다. 손해배상 요건.", "page": 1}
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    router = SimulatedRouter(doc_text, threshold=4)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    # stage 값 및 max_tokens 단언
    assert len(router.sent_requests) >= 1
    req = router.sent_requests[0]
    assert req.metadata.get("stage") == "drive_rag_advisory"
    assert req.max_tokens == 4000
    assert req.schema.get("required") == ["observations"]

    # advisory_only 속성 보존 단언
    assert review["advisory_only"] is True
    assert review["status"] == "ADVISORY_REVIEWED"
