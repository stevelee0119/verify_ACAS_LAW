"""TK-70 Drive 참고자료 '모순' 의견의 조건부 Finding 승격 단위 시험 (D4 개정, 파이프라인 경로 합성 시험)."""
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from packages.common.config import get_settings
from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ReleaseGate,
    Severity,
    VerificationProfile,
    VerificationStatus,
)
from packages.common.storage import sha256_file
from packages.rag_engine.library import ReferenceLibrary
from packages.verification_engine.candidate_verifier import ModelCandidate, verify_rag_candidate
from packages.verification_engine.gate import evaluate_gate, risk_index
from packages.verification_engine.pipeline import (
    DocumentInput,
    ProjectContext,
    VerificationPipeline,
)


def _setup_pipeline_test(tmp_path: Path, monkeypatch, observations: List[Dict[str, Any]], sources: List[Dict[str, Any]]):
    """VerificationPipeline.run을 거치는 모의 RAG 환경 구성 (한국어 주석)."""
    # 1. 테스트 서면 파일 생성 (.txt 텍스트 파일)
    doc_text = (
        "제10조(지체상금): 수급인이 공사를 지체한 때에는 지체상금률 1/1000을 납부한다. "
        "제15조(계약해제): 발주자는 중대한 하자가 있는 경우 즉시 계약을 해제할 수 있다. "
        "제20조(비밀유지): 양 당사자는 업무상 취득한 비밀을 제3자에게 누설하지 아니한다."
    )
    doc_path = tmp_path / "synthetic_contract.txt"
    doc_path.write_text(doc_text, encoding="utf-8")

    # 2. ReferenceLibrary 동기화 성공 상태 모킹
    def fake_sync(self, query=None):
        self.summary.update(
            status="READY",
            files_seen=len(sources),
            files_indexed=len(sources),
            checked_at="2026-10-10T00:00:00Z",
            issues=[],
        )

    monkeypatch.setattr(ReferenceLibrary, "sync", fake_sync)

    # 3. review_document 함수 모킹: 주입된 observations 및 sources 반환
    def fake_review_document(document_result, references, router, context, pii):
        # 파이프라인 주장 목록 등록
        document_result.claims = [
            {"claim_id": "C1", "type": "FACT", "text": "수급인이 공사를 지체한 때에는 지체상금률 1/1000을 납부한다."},
            {"claim_id": "C2", "type": "FACT", "text": "발주자는 중대한 하자가 있는 경우 즉시 계약을 해제할 수 있다."},
            {"claim_id": "C3", "type": "FACT", "text": "양 당사자는 업무상 취득한 비밀을 제3자에게 누설하지 아니한다."},
        ]
        review = {
            "status": "ADVISORY_REVIEWED",
            "sources": sources,
            "observations": observations,
            "rejected_observations": [],
            "model_executed": True,
            "review_completed": True,
        }
        document_result.engine_data["rag"] = review
        return review

    monkeypatch.setattr("packages.rag_engine.review.review_document", fake_review_document)

    pipeline = VerificationPipeline()
    pipeline.settings = replace(
        get_settings(),
        rag_drive_folder_id="synthetic_folder",
        allow_network=False,
    )
    doc_input = DocumentInput(
        "doc1",
        str(doc_path),
        doc_path.name,
        sha256=sha256_file(doc_path),
        mime_type="text/plain",
    )
    context = ProjectContext("test-project", profile=VerificationProfile.QUICK)
    return pipeline, context, [doc_input]


def test_tk70_pipeline_run_contradiction_promotion_five_cases(tmp_path, monkeypatch):
    """평가 측 요구 5건 관찰의 파이프라인 실제 경로 검증 (VerificationPipeline.run):
    1) 주장 단위 모순 1건 (claim_id C1 있음, 원문 일치)
    2) 동일 주장·동일 참고자료 문서 단위 모순 1건 (claim_id 없음, 같은 인용문, 같은 source_id)
    3) 참고자료 인용 불일치 1건 (source_quote 불일치 -> 거부 rej)
    4) SUPPORTS 의견 1건 (모순 아님 -> 승격 제외)
    5) 결정론 관찰 1건 (exhibit_facts -> 승격 제외)
    
    결과 단언:
    - 정확히 1건의 Finding으로 승격 및 중복 합치기(주장 단위와 문서 단위가 하나로 합쳐짐)
    - 설명 병합 및 근거 2건 모두 보존
    - LOW, C등급, SUSPICIOUS, FACT_CONTRADICTION
    - D4 법적 구속력 미판단 표기 및 메타데이터 단언
    - 거부 의견 1건이 rejected_observations에 기록됨
    - 게이트 PASS 및 위험지수 0(격리) 단언
    """
    sources = [
        {
            "source_id": "REF1",
            "title": "공사계약일반조건 안내",
            "text": "제10조 지체상금 규정: 지체상금률은 1일당 0.5/1000을 적용하여 정산한다.",
            "page": 1,
        }
    ]
    observations = [
        # 1) 주장 단위 모순 1건
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 1일당 0.5/1000을 적용하여 정산한다.",
            "explanation": "참고자료 0.5/1000과 서면의 1/1000 주장이 상충됩니다.",
            "advisory_only": True,
        },
        # 2) 같은 주장·같은 참고자료의 문서 단위 모순 1건 (claim_id 없음, 동일 claim_quote)
        {
            "relationship": "CONTRADICTS",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 1일당 0.5/1000을 적용하여 정산한다.",
            "explanation": "문서 단위 대조에서도 지체상금률 상충이 확인되었습니다.",
            "advisory_only": True,
        },
        # 3) 참고자료 인용 불일치 1건 (source_quote 원문 부존재 -> 거부 대상)
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C2",
            "claim_quote": "즉시 계약을 해제할 수 있다.",
            "source_id": "REF1",
            "source_quote": "참고자료에 전혀 존재하지 않는 조작된 허위 문장.",
            "explanation": "참고자료 인용 불일치 의견.",
            "advisory_only": True,
        },
        # 4) SUPPORTS 의견 1건 (제외 대상)
        {
            "relationship": "SUPPORTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 1일당 0.5/1000을 적용하여 정산한다.",
            "explanation": "지지 의견이므로 승격 제외.",
            "advisory_only": True,
        },
        # 5) 결정론 관찰 1건 (제외 대상)
        {
            "relationship": "CONTRADICTS",
            "engine": "exhibit_facts",
            "source_type": "deterministic",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 1일당 0.5/1000을 적용하여 정산한다.",
            "explanation": "결정론적 관찰이므로 AI 모델 승격 대상 아님.",
            "advisory_only": True,
        },
    ]

    pipeline, context, doc_inputs = _setup_pipeline_test(tmp_path, monkeypatch, observations, sources)
    result = pipeline.run("test-run-1", context, doc_inputs)

    assert len(result.documents) == 1
    doc_res = result.documents[0]

    # 승격된 Finding 단언 (정확히 1건으로 중복 병합됨)
    promoted = [
        f for f in doc_res.findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted) == 1
    finding = promoted[0]

    # 속성 단언: LOW, C등급, SUSPICIOUS, FACT_CONTRADICTION
    assert finding.type == FindingType.FACT_CONTRADICTION
    assert finding.status == VerificationStatus.SUSPICIOUS
    assert finding.severity == Severity.LOW
    assert finding.evidence_grade == EvidenceGrade.C
    assert "내부 참고자료 대조 — 법적 구속력 미판단, 사람 확인 필요" in finding.title
    assert "법적 구속력은 판단하지 않았으므로" in finding.detail

    # 설명 병합 및 근거 2건 보존 단언
    assert "참고자료 0.5/1000과 서면의 1/1000 주장이 상충됩니다." in finding.detail
    assert "문서 단위 대조에서도 지체상금률 상충이 확인되었습니다." in finding.detail
    assert len(finding.evidence) == 2

    # 신뢰도 메타데이터 단언
    features = finding.confidence_features
    assert features["rule_id"] == "RAG.REFERENCE_CONTRADICTION"
    assert features["claim_id"] == "C1"
    assert "지체상금률 1/1000을 납부한다" in features["claim_text"]
    assert features["source_id"] == "REF1"
    assert features["source_title"] == "공사계약일반조건 안내"
    assert features["human_review"] is True

    # 거부 의견 단언 (인용 불일치 1건이 rejected_observations에 등록됨)
    rag_data = doc_res.engine_data.get("rag") or {}
    rejected = rag_data.get("rejected_observations") or []
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "BASIS_QUOTE_NOT_GROUNDED_IN_SOURCE"

    # 게이트 불변 및 위험지수 격리 단언 (승격을 뺀 경우와 완전히 동일)
    findings_without_promo = [
        f for f in result.all_findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") != "RAG.REFERENCE_CONTRADICTION"
    ]
    gate_decision = evaluate_gate(result.all_findings)
    assert gate_decision.gate == ReleaseGate.PASS
    assert gate_decision.gate == evaluate_gate(findings_without_promo).gate

    score, _ = risk_index(result.all_findings)
    assert score == 0
    assert score == risk_index(findings_without_promo)[0]


def test_tk70_pipeline_run_switch_toggle(tmp_path, monkeypatch):
    """스위치 제어 검증 (VerificationPipeline.run):
    같은 입력에서 켬(True) -> 승격 1건, 끔(False) -> 승격 0건을 파이프라인 결과로 단언 (한국어 주석).
    """
    sources = [{"source_id": "REF1", "title": "공사조건", "text": "지체상금률은 0.5/1000을 적용한다."}]
    observations = [
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 0.5/1000을 적용한다.",
            "explanation": "지체상금률 상충.",
            "advisory_only": True,
        }
    ]

    # 1) 기본 켬 (True) 상태에서 실행
    pipeline_on, context, doc_inputs = _setup_pipeline_test(tmp_path, monkeypatch, observations, sources)
    result_on = pipeline_on.run("test-switch-on", context, doc_inputs)
    promoted_on = [
        f for f in result_on.documents[0].findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted_on) == 1

    # 2) 끔 (False) 상태에서 실행 (monkeypatch로 설정 해제)
    import packages.common.config as cfg_mod
    monkeypatch.setenv("LV_RAG_CONTRADICTION_PROMOTION", "false")
    cfg_mod._settings = None

    pipeline_off = VerificationPipeline()
    pipeline_off.settings = replace(
        get_settings(),
        rag_drive_folder_id="synthetic_folder",
        allow_network=False,
    )
    result_off = pipeline_off.run("test-switch-off", context, doc_inputs)
    promoted_off = [
        f for f in result_off.documents[0].findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted_off) == 0

    # 설정 원복
    monkeypatch.setenv("LV_RAG_CONTRADICTION_PROMOTION", "true")
    cfg_mod._settings = None


def test_tk70_pipeline_run_multiple_sources_promoted(tmp_path, monkeypatch):
    """복수 참고자료/주장 양성 3건 검증 (VerificationPipeline.run):
    서로 다른 3개의 참고자료에 대한 모순 의견이 각각 정식 Finding으로 승격됨 단언 (한국어 주석).
    """
    sources = [
        {"source_id": "REF1", "title": "참고자료1", "text": "지체상금률 규정: 0.5/1000을 적용한다."},
        {"source_id": "REF2", "title": "참고자료2", "text": "계약 해제 규정: 14일 이상의 최고 기간을 서면으로 부여한다."},
        {"source_id": "REF3", "title": "참고자료3", "text": "비밀유지 규정: 법령상 제출 요구가 있는 경우에는 예외로 한다."},
    ]
    observations = [
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "0.5/1000을 적용한다.",
            "explanation": "지체상금률 불일치.",
            "advisory_only": True,
        },
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C2",
            "claim_quote": "즉시 계약을 해제할 수 있다.",
            "source_id": "REF2",
            "source_quote": "14일 이상의 최고 기간을 서면으로 부여한다.",
            "explanation": "해제 절차 불일치.",
            "advisory_only": True,
        },
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C3",
            "claim_quote": "비밀을 제3자에게 누설하지 아니한다.",
            "source_id": "REF3",
            "source_quote": "법령상 제출 요구가 있는 경우에는 예외로 한다.",
            "explanation": "비밀유지 범위 불일치.",
            "advisory_only": True,
        },
    ]

    pipeline, context, doc_inputs = _setup_pipeline_test(tmp_path, monkeypatch, observations, sources)
    result = pipeline.run("test-multi-source", context, doc_inputs)

    promoted = [
        f for f in result.documents[0].findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted) == 3
    for f in promoted:
        assert f.type == FindingType.FACT_CONTRADICTION
        assert f.status == VerificationStatus.SUSPICIOUS
        assert f.severity == Severity.LOW
        assert f.evidence_grade == EvidenceGrade.C
        assert "내부 참고자료 대조 — 법적 구속력 미판단, 사람 확인 필요" in f.title
        assert f.confidence_features["claim_id"] in ("C1", "C2", "C3")
        assert f.confidence_features["source_id"] in ("REF1", "REF2", "REF3")


def test_tk70_candidate_verifier_rejection_reasons():
    """verify_rag_candidate 단위 수준 거부 사유 검증 (한국어 주석):
    1) 참고자료 인용문 부존재 -> BASIS_QUOTE_NOT_GROUNDED_IN_SOURCE
    2) 서면 인용문 부존재 -> CLAIM_QUOTE_NOT_GROUNDED_IN_DOCUMENT
    """
    doc_text = "제10조: 지체상금률 1/1000을 납부한다."
    sources = [{"source_id": "REF1", "title": "참고자료", "text": "지체상금률 0.5/1000 규정."}]

    # 1) 참고자료 인용문 부존재
    cand1 = ModelCandidate(
        claim_quote="지체상금률 1/1000을 납부한다.",
        defect_type="FACT_CONTRADICTION",
        basis_quote="원문에 없는 가짜 인용문",
        source_id="REF1",
    )
    f1, rej1 = verify_rag_candidate(cand1, doc_text, sources, is_reference_contradiction=True)
    assert f1 is None
    assert rej1["reason"] == "BASIS_QUOTE_NOT_GROUNDED_IN_SOURCE"

    # 2) 서면 인용문 부존재
    cand2 = ModelCandidate(
        claim_quote="서면에 없는 가짜 주장",
        defect_type="FACT_CONTRADICTION",
        basis_quote="지체상금률 0.5/1000 규정.",
        source_id="REF1",
    )
    f2, rej2 = verify_rag_candidate(cand2, doc_text, sources, is_reference_contradiction=True)
    assert f2 is None
    assert rej2["reason"] == "CLAIM_QUOTE_NOT_GROUNDED_IN_DOCUMENT"
