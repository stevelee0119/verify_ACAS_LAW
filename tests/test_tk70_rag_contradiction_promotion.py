"""TK-70 Drive 참고자료 '모순' 의견의 조건부 Finding 승격 단위 시험 (D4 개정, 파이프라인 경로 합성 시험)."""
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from packages.common.config import get_settings
import packages.common.config as cfg_mod
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
    doc_text = (
        "제10조(지체상금): 수급인이 공사를 지체한 때에는 지체상금률 1/1000을 납부한다. "
        "제15조(계약해제): 발주자는 중대한 하자가 있는 경우 즉시 계약을 해제할 수 있다. "
        "제20조(비밀유지): 양 당사자는 업무상 취득한 비밀을 제3자에게 누설하지 아니한다."
    )
    doc_path = tmp_path / "synthetic_contract.txt"
    doc_path.write_text(doc_text, encoding="utf-8")

    def fake_sync(self, query=None):
        self.summary.update(
            status="READY",
            files_seen=len(sources),
            files_indexed=len(sources),
            checked_at="2026-10-10T00:00:00Z",
            issues=[],
        )

    monkeypatch.setattr(ReferenceLibrary, "sync", fake_sync)

    def fake_review_document(document_result, references, router, context, pii):
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


def test_tk70_positive_three_cases_promoted_to_low_c_suspicious(tmp_path, monkeypatch):
    """복수 참고자료/주장 양성 3건 검증 (VerificationPipeline.run 경로):
    서로 다른 3개의 참고자료에 대한 모순 의견이 각각 정식 Finding으로 승격됨 단언 (한국어 주석).
    - LOW, C등급, SUSPICIOUS, FACT_CONTRADICTION
    - D4 내부 참고자료 대조 사람 확인 필요 안내문 및 신뢰도 속성 단언
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
        assert "법적 구속력은 판단하지 않았으므로" in f.detail
        assert f.confidence_features["claim_id"] in ("C1", "C2", "C3")
        assert f.confidence_features["source_id"] in ("REF1", "REF2", "REF3")


def test_tk70_controls_not_promoted(tmp_path, monkeypatch):
    """대조군 검증 (VerificationPipeline.run 경로):
    1) 참고자료 인용 불일치 (거부 사유 기록)
    2) 서면 인용 불일치 (거부 사유 기록)
    3) SUPPORTS 의견 (승격 제외)
    4) exhibit_facts 결정론 관찰 (승격 제외)
    -> 정식 Finding으로 승격되지 않음을 파이프라인 결과로 단언 (한국어 주석).
    """
    sources = [{"source_id": "REF1", "title": "참고자료", "text": "지체상금률 0.5/1000 규정."}]
    observations = [
        # 1) 참고자료 인용 불일치
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "원문에 존재하지 않는 가짜 인용문",
            "explanation": "인용 불일치",
            "advisory_only": True,
        },
        # 2) 서면 인용 불일치
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C1",
            "claim_quote": "서면에 존재하지 않는 가짜 주장문",
            "source_id": "REF1",
            "source_quote": "지체상금률 0.5/1000 규정.",
            "explanation": "서면 불일치",
            "advisory_only": True,
        },
        # 3) SUPPORTS
        {
            "relationship": "SUPPORTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률 0.5/1000 규정.",
            "explanation": "지지",
            "advisory_only": True,
        },
        # 4) 결정론 관찰
        {
            "relationship": "CONTRADICTS",
            "engine": "exhibit_facts",
            "source_type": "deterministic",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률 0.5/1000 규정.",
            "explanation": "결정론",
            "advisory_only": True,
        },
    ]

    pipeline, context, doc_inputs = _setup_pipeline_test(tmp_path, monkeypatch, observations, sources)
    result = pipeline.run("test-controls", context, doc_inputs)

    promoted = [
        f for f in result.documents[0].findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted) == 0

    # 거부 사유 2건이 rejected_observations에 등록됨을 단언
    rag_data = result.documents[0].engine_data.get("rag") or {}
    rejected = rag_data.get("rejected_observations") or []
    assert len(rejected) == 2
    rej_reasons = {r["reason"] for r in rejected}
    assert "BASIS_QUOTE_NOT_GROUNDED_IN_SOURCE" in rej_reasons
    assert "CLAIM_QUOTE_NOT_GROUNDED_IN_DOCUMENT" in rej_reasons


def test_tk70_deduplication_grouping_same_claim_and_source(tmp_path, monkeypatch):
    """중복 합치기 검증 (VerificationPipeline.run 경로):
    동일 주장(claim_id C1 있음)과 문서 단위(claim_id 없음, 같은 인용문)가 동일 참고자료에서
    발생 시 1개의 Finding으로 합쳐지고 설명 및 근거가 병합됨을 단언 (한국어 주석).
    """
    sources = [{"source_id": "REF1", "title": "참고자료", "text": "지체상금률은 0.5/1000을 적용한다."}]
    observations = [
        # 1) 주장 단위 모순 (claim_id C1)
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 0.5/1000을 적용한다.",
            "explanation": "주장 단위 지체상금률 상충.",
            "advisory_only": True,
        },
        # 2) 문서 단위 모순 (claim_id 없음, 동일 인용문, 동일 source_id)
        {
            "relationship": "CONTRADICTS",
            "claim_quote": "지체상금률 1/1000을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 0.5/1000을 적용한다.",
            "explanation": "문서 단위 대조 지체상금률 상충.",
            "advisory_only": True,
        },
    ]

    pipeline, context, doc_inputs = _setup_pipeline_test(tmp_path, monkeypatch, observations, sources)
    result = pipeline.run("test-dedup", context, doc_inputs)

    promoted = [
        f for f in result.documents[0].findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted) == 1
    finding = promoted[0]
    assert "주장 단위 지체상금률 상충." in finding.detail
    assert "문서 단위 대조 지체상금률 상충." in finding.detail
    assert len(finding.evidence) == 2
    assert finding.confidence_features["claim_id"] == "C1"
    assert finding.confidence_features["source_id"] == "REF1"


def test_tk70_switch_disabled_no_promotion(tmp_path, monkeypatch):
    """운영 스위치 검증 (VerificationPipeline.run 경로):
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

    # 1) 기본 켬 (True)
    pipeline_on, context, doc_inputs = _setup_pipeline_test(tmp_path, monkeypatch, observations, sources)
    result_on = pipeline_on.run("test-switch-on", context, doc_inputs)
    promoted_on = [
        f for f in result_on.documents[0].findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted_on) == 1

    # 2) 끔 (False)
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

    monkeypatch.setenv("LV_RAG_CONTRADICTION_PROMOTION", "true")
    cfg_mod._settings = None


def test_tk70_risk_index_and_gate_invariance(tmp_path, monkeypatch):
    """게이트 및 위험지수 불변 격리 검증 (VerificationPipeline.run 경로):
    모순 Finding이 승격되더라도 게이트 판정 PASS 및 risk_index 0(승격을 뺀 경우와 동일)을 단언 (한국어 주석).
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

    pipeline, context, doc_inputs = _setup_pipeline_test(tmp_path, monkeypatch, observations, sources)
    result = pipeline.run("test-gate-invariance", context, doc_inputs)

    promoted = [
        f for f in result.documents[0].findings
        if (getattr(f, "confidence_features", None) or {}).get("rule_id") == "RAG.REFERENCE_CONTRADICTION"
    ]
    assert len(promoted) == 1

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
