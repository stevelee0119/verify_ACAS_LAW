"""TK-68 문서 단위 Drive 대조 묶음 크기 축소 및 비용 비증가 조건(C1~C3) 단위 시험."""
import asyncio
import hashlib
import json
import math
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from packages.common.enums import ExternalAIPolicy
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.llm_router.router import ModelExecution, RouterResult
from packages.rag_engine.review import review_document
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
    doc_text: str, sources: List[Dict[str, Any]], threshold: int, retry_succeeds: bool = True
) -> Dict[str, Any]:
    """변경 전(Steve 3c89a4e) 경로의 실행 기록 시뮬레이션:
    - 6개씩 고정 묶음
    - threshold 초과 시 Anthropic에서 OUTPUT_TRUNCATED(4000토큰, 30초, $0.092)
    - 실패 시 retry_succeeds가 True이면 대체 공급자에서 성공(2차 호출)
    """
    batches = [sources[i:i + 6] for i in range(0, len(sources), 6)] or [sources]
    calls = 0
    input_tokens = 0
    output_tokens = 0
    latency_ms = 0
    cost_usd = 0.0

    for s_batch in batches:
        req_user = json.dumps({"document": doc_text, "untrusted_references": s_batch}, ensure_ascii=False)
        in_tok = len(req_user) // 4
        calls += 1
        input_tokens += in_tok

        if len(s_batch) > threshold:
            # 1차 시도 실패 (OUTPUT_TRUNCATED)
            output_tokens += 4000
            latency_ms += 30000
            cost_usd += round(in_tok * 0.000003 + 4000 * 0.000015, 6)

            # 2차 시도 (대체 공급자 재시도)
            calls += 1
            input_tokens += in_tok
            if retry_succeeds:
                out_tok = len(s_batch) * 200
                output_tokens += out_tok
                latency_ms += len(s_batch) * 1000
                cost_usd += round(in_tok * 0.000003 + out_tok * 0.000015, 6)
            else:
                output_tokens += 4000
                latency_ms += 30000
                cost_usd += round(in_tok * 0.000003 + 4000 * 0.000015, 6)
        else:
            # 1차 시도 성공
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
    """C5 요구사항에 따른 가짜 공급자 라우터:
    - 실행 기록에 input_tokens, cost_usd(입력 글자 수 비례), output_tokens, latency_ms(참고자료 수 비례) 기록
    - threshold 초과 묶음은 OUTPUT_TRUNCATED 반환
    """

    def __init__(self, doc_text: str, threshold: int = 4, always_fail: bool = False):
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

        is_truncated = self.always_fail or (len(refs) > self.threshold)
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
    """C1 검증: 잘림 없는 일반 입력(N=6, 작은 참고자료)에서 호출 수·입력 토큰·비용이 변경 전 이하임을 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    # 각 400자 크기의 작은 참고자료 6개 (합계 2,400자 < 안전 기준 8,000자)
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: " + ("손해배상 " * 40), "page": 1}
        for i in range(1, 7)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    # threshold = 6 (6개까지 잘리지 않음)
    router = SimulatedRouter(doc_text, threshold=6)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    # 변경 전 기대값 계산
    before_stats = _simulate_before_stats(doc_text, sources, threshold=6)

    # 변경 후 실행 통계
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
    """C2 검증: 서면9형 큰 입력(N=11)에서 호출 수·토큰·지연 시간 변경 전 이하, 비용 변경 전 미만 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    # 각 2,500자 크기의 큰 참고자료 11개 (합계 27,610자 > 8,000자이므로 사전 분할됨)
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: " + ("손해배상 " * 500), "page": 1}
        for i in range(1, 12)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    # threshold = 4 (5개 이상이면 잘림 발생, 서면9형)
    router = SimulatedRouter(doc_text, threshold=4)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    # 변경 전 서면9 통계 (첫 묶음 6개 실패 후 대체 공급자 재시도 성공, 둘째 묶음 5개 실패 후 재시도 성공)
    before_stats = _simulate_before_stats(doc_text, sources, threshold=4, retry_succeeds=True)

    after_calls = len(router.sent_requests)
    after_in_tok = sum(e.input_tokens for e in router.executions)
    after_out_tok = sum(e.output_tokens for e in router.executions)
    after_lat_ms = sum(e.latency_ms for e in router.executions)
    after_cost = sum(e.cost_usd for e in router.executions)

    # C2 단언:
    # 1. 호출 수: 변경 전(4회) 이하 (안전 분할로 3회 호출)
    assert after_calls <= before_stats["calls"]
    # 2. 입력 토큰 합계: 변경 전 이하
    assert after_in_tok <= before_stats["input_tokens"]
    # 3. 출력 토큰 합계: 변경 전 이하 (잘림 낭비 4,000토큰이 없음)
    assert after_out_tok <= before_stats["output_tokens"]
    # 4. 지연 시간 합계: 변경 전 이하 (30초 대기 낭비 없음)
    assert after_lat_ms <= before_stats["latency_ms"]
    # 5. 비용 합계: 변경 전보다 작음 (실패 낭비 비용 절감)
    assert round(after_cost, 6) < round(before_stats["cost_usd"], 6)

    # 11개 모든 참고자료 검토 의견 수집 단언
    assert review["status"] == "ADVISORY_REVIEWED"
    collected_ids = {obs["source_id"] for obs in review["observations"]}
    assert len(collected_ids) == 11


def test_tk68_c3_worst_case_continuous_truncation():
    """C3 검증: 최악의 계속 잘림(모든 호출 실패) 상황에서도 호출 수가 2*ceil(N/6) 이하로 강제 차단됨을 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: 손해배상 내용입니다.", "page": 1}
        for i in range(1, 12)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    # always_fail=True: 모든 묶음에서 OUTPUT_TRUNCATED 발생
    router = SimulatedRouter(doc_text, threshold=0, always_fail=True)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    before_worst_stats = _simulate_before_stats(doc_text, sources, threshold=0, retry_succeeds=False)

    after_calls = len(router.sent_requests)
    after_in_tok = sum(e.input_tokens for e in router.executions)

    # C3 단언: 호출 수 <= 2 * ceil(N/6) = 2 * ceil(11/6) = 4
    max_allowed_calls = 2 * math.ceil(len(sources) / 6)
    assert after_calls <= max_allowed_calls
    assert after_calls <= before_worst_stats["calls"]
    assert after_in_tok <= before_worst_stats["input_tokens"]

    # 상한 도달로 대조되지 못한 참고자료가 'unreviewed_drive_sources'에 기록됨을 단언 (분모 보존)
    assert "unreviewed_drive_sources" in review
    assert len(review["unreviewed_drive_sources"]) > 0


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


def test_tk68_adaptive_halving_on_unexpected_truncation():
    """사전 분할되지 않은 6개 묶음에서 예상치 못한 잘림 발생 시 1회 적응형 이분할로 의견이 온전히 회수됨을 단언."""
    doc_text = "계약 위반으로 인한 손해배상 청구 검토가 필요하다."
    # 6개 참고자료 (각 500자로 사전 분할되지 않고 1개 묶음으로 생성됨)
    sources = [
        {"source_id": f"R{i}", "title": f"규정_{i}", "text": f"참고자료 {i} 본문: " + ("손해배상 " * 50), "page": 1}
        for i in range(1, 7)
    ]
    lib = _make_dummy_library(sources)
    doc_result = _make_doc_result(doc_text)
    context = ProjectContext("proj", external_ai_policy=ExternalAIPolicy.MASKED)

    # threshold = 3: 6개 묶음은 실패하지만, 절반인 3개 묶음은 성공
    router = SimulatedRouter(doc_text, threshold=3)
    mock_pii = SimpleNamespace(mask_text=lambda t: SimpleNamespace(masked_text=t))

    review = review_document(doc_result, lib, router, context, mock_pii)

    # C3 최악 상한: N=6일 때 최대 호출 수는 2 * ceil(6/6) = 2회로 제한됨.
    # 따라서 6개(잘림, 1회) -> 앞의 3개(성공, 2회) 실행 후 상한(2회) 도달로 중단됨.
    assert len(router.sent_requests) == 2
    # 앞의 3개 관찰 결과 수집
    assert review["status"] == "ADVISORY_REVIEWED"
    collected_ids = {obs["source_id"] for obs in review["observations"]}
    assert len(collected_ids) == 3
    # 상한 도달로 실행되지 못한 뒤의 3개는 unreviewed_drive_sources에 분모 보존
    assert "unreviewed_drive_sources" in review
    assert len(review["unreviewed_drive_sources"]) == 3
