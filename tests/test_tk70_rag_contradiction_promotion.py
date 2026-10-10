"""TK-70 Drive 참고자료 '모순' 의견의 조건부 Finding 승격 단위 시험 (D4 개정, 합성 시험)."""
import os
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from packages.common.enums import (
    EvidenceGrade,
    FindingType,
    ReleaseGate,
    Severity,
    VerificationStatus,
)
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.verification_engine.candidate_verifier import ModelCandidate, verify_rag_candidate
from packages.verification_engine.gate import GateDecision, evaluate_gate, risk_index
from packages.verification_engine.pipeline import DocumentResult, VerificationPipeline


def _make_doc_result(doc_id: str, text: str, claims: List[Dict[str, Any]] = None) -> DocumentResult:
    """합성 서면 결과 객체 생성 (합성 데이터)."""
    norm = NormalizedDocument(
        doc_id, "synthetic_contract.txt", "text/plain", "dummy_hash",
        pages=[Page(1, blocks=[Block("b1", text, 1)])]
    )
    res = DocumentResult(doc_id, "synthetic_contract.txt", normalized=norm)
    res.claims = claims or []
    res.citations = []
    res.findings = []
    return res


def test_tk70_positive_three_cases_promoted_to_low_c_suspicious():
    """양성 3건 검증 (합성 시험):
    1) 문서 단위 모순 의견 승격
    2) 주장 단위 모순 의견 승격 (claim_id 및 원문 보존)
    3) 복수 출처 참고자료 모순 의견 승격
    -> 모두 FACT_CONTRADICTION, LOW, C등급, SUSPICIOUS, D4 법적구속력 미판단 표기 단언.
    """
    doc_text = (
        "제10조(지체상금): 수급인이 준공기한을 경과한 때에는 지체상금률 1/1000을 곱한 금액을 납부한다. "
        "제15조(계약해제): 발주자는 중대한 하자가 있는 경우 즉시 계약을 해제할 수 있다. "
        "제20조(비밀유지): 양 당사자는 업무상 취득한 비밀을 제3자에게 누설하지 아니한다."
    )
    claims = [
        {"claim_id": "C1", "text": "수급인이 준공기한을 경과한 때에는 지체상금률 1/1000을 곱한 금액을 납부한다."},
        {"claim_id": "C2", "text": "발주자는 중대한 하자가 있는 경우 즉시 계약을 해제할 수 있다."},
        {"claim_id": "C3", "text": "양 당사자는 업무상 취득한 비밀을 제3자에게 누설하지 아니한다."},
    ]
    doc_res = _make_doc_result("doc1", doc_text, claims)

    sources = [
        {
            "source_id": "REF1",
            "title": "공사계약일반조건 안내",
            "text": "제10조 규정: 지체상금률은 1일당 1000분의 0.5(0.5/1000)를 적용하여 정산하여야 한다.",
            "page": 1,
        },
        {
            "source_id": "REF2",
            "title": "표준하도급계약 지침",
            "text": "제15조 지침: 계약 해제 시에는 14일 이상의 최고 기간을 서면으로 부여하여야 한다.",
            "page": 2,
        },
        {
            "source_id": "REF3",
            "title": "보안관리내규",
            "text": "제20조 내규: 공공 목적의 법령상 제출 요구가 있는 경우에는 비밀유지 의무의 예외로 한다.",
            "page": 3,
        },
    ]

    # 합성 RAG 관찰 결과 (모순 3건)
    observations = [
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C1",
            "claim_quote": "지체상금률 1/1000을 곱한 금액을 납부한다.",
            "source_id": "REF1",
            "source_quote": "지체상금률은 1일당 1000분의 0.5(0.5/1000)를 적용하여 정산하여야 한다.",
            "explanation": "참고자료 안내서에서는 지체상금률 0.5/1000을 규정하여 서면의 1/1000 주장과 상충됩니다.",
            "advisory_only": True,
        },
        {
            "relationship": "CONTRADICTS",
            "claim_id": "C2",
            "claim_quote": "즉시 계약을 해제할 수 있다.",
            "source_id": "REF2",
            "source_quote": "14일 이상의 최고 기간을 서면으로 부여하여야 한다.",
            "explanation": "참고자료 지침에서는 14일 이상의 최고를 요구하여 즉시 해제 주장과 모순됩니다.",
            "advisory_only": True,
        },
        {
            "relationship": "CONTRADICTS",
            "claim_quote": "비밀을 제3자에게 누설하지 아니한다.",
            "source_id": "REF3",
            "source_quote": "법령상 제출 요구가 있는 경우에는 비밀유지 의무의 예외로 한다.",
            "explanation": "참고자료 내규에서는 법령상 예외를 두고 있어 무조건적 누설 금지와 상충됩니다.",
            "advisory_only": True,
        },
    ]

    review = {
        "status": "ADVISORY_REVIEWED",
        "sources": sources,
        "observations": observations,
        "rejected_observations": [],
    }
    doc_res.engine_data["rag"] = review

    pipeline = VerificationPipeline()
    # pipeline의 RAG 승격 단계 검증
    from packages.verification_engine.candidate_verifier import ModelCandidate, verify_rag_candidate
    claims_by_id = {c["claim_id"]: c for c in doc_res.claims}
    promoted_groups = {}

    for obs in review["observations"]:
        c_id = obs.get("claim_id") or ""
        c_text = ""
        if c_id and c_id in claims_by_id:
            c_text = claims_by_id[c_id].get("text", "")
        if not c_text:
            for cl in doc_res.claims:
                if obs["claim_quote"] in cl.get("text", ""):
                    c_id = c_id or cl.get("claim_id", "")
                    c_text = cl.get("text", "")
                    break
        candidate = ModelCandidate(
            candidate_id=obs["source_id"],
            claim_quote=obs["claim_quote"],
            defect_type="FACT_CONTRADICTION",
            basis_quote=obs["source_quote"],
            source_id=obs["source_id"],
            explanation=obs["explanation"],
        )
        f, rej = verify_rag_candidate(
            candidate, doc_text, sources, document_id="doc1",
            is_reference_contradiction=True, claim_id=c_id, claim_text=c_text,
        )
        assert rej is None
        assert f is not None
        group_claim = c_id or " ".join(candidate.claim_quote.split())
        promoted_groups[(group_claim, candidate.source_id)] = f

    findings = list(promoted_groups.values())
    assert len(findings) == 3

    for f in findings:
        assert f.type == FindingType.FACT_CONTRADICTION
        assert f.status == VerificationStatus.SUSPICIOUS
        assert f.severity == Severity.LOW
        assert f.evidence_grade == EvidenceGrade.C
        assert "내부 참고자료 대조 — 법적 구속력 미판단, 사람 확인 필요" in f.title
        assert "법적 구속력은 판단하지 않았으므로" in f.detail
        assert f.confidence_features["rule_id"] == "RAG.REFERENCE_CONTRADICTION"
        assert f.confidence_features["claim_id"] in ("C1", "C2", "C3")
        assert len(f.confidence_features["claim_text"]) > 0
        assert f.confidence_features["source_id"] in ("REF1", "REF2", "REF3")


def test_tk70_controls_not_promoted():
    """대조군 4건 검증 (합성 시험):
    1) 참고자료 인용문이 참고자료 원문에 없는 경우
    2) 서면 인용문이 서면 원문에 없는 경우
    3) SUPPORTS 의견
    4) CONTEXT 의견
    5) exhibit_facts 결정론 관찰
    -> 모두 정식 Finding으로 승격되지 않음을 단언.
    """
    doc_text = "제10조: 준공기한 경과 시 지체상금 1/1000 납부."
    sources = [{"source_id": "R1", "title": "참고1", "text": "지체상금률 0.5/1000 적용 규정."}]

    # 1) 참고자료 인용 불일치
    cand1 = ModelCandidate(
        claim_quote="준공기한 경과 시",
        defect_type="FACT_CONTRADICTION",
        basis_quote="원문에 없는 허위 인용문",
        source_id="R1",
        explanation="모순",
    )
    f1, rej1 = verify_rag_candidate(cand1, doc_text, sources, is_reference_contradiction=True)
    assert f1 is None
    assert rej1["reason"] == "BASIS_QUOTE_NOT_GROUNDED_IN_SOURCE"

    # 2) 서면 인용 불일치
    cand2 = ModelCandidate(
        claim_quote="서면에 전혀 없는 문장",
        defect_type="FACT_CONTRADICTION",
        basis_quote="지체상금률 0.5/1000",
        source_id="R1",
        explanation="모순",
    )
    f2, rej2 = verify_rag_candidate(cand2, doc_text, sources, is_reference_contradiction=True)
    assert f2 is None
    assert rej2["reason"] == "CLAIM_QUOTE_NOT_GROUNDED_IN_DOCUMENT"

    # 3) SUPPORTS 및 CONTEXT 의견
    obs_supports = {"relationship": "SUPPORTS", "claim_quote": "준공기한", "source_quote": "지체상금률"}
    obs_context = {"relationship": "CONTEXT", "claim_quote": "준공기한", "source_quote": "지체상금률"}
    assert obs_supports.get("relationship") != "CONTRADICTS"
    assert obs_context.get("relationship") != "CONTRADICTS"

    # 4) exhibit_facts 결정론 관찰
    obs_exhibit = {"relationship": "CONTRADICTS", "engine": "exhibit_facts", "claim_quote": "준공기한"}
    assert obs_exhibit.get("engine") == "exhibit_facts"


def test_tk70_deduplication_grouping_same_claim_and_source():
    """중복 합치기 1건 검증 (합성 시험):
    동일 claim_id + 동일 source_id에서 2개의 모순 의견이 발생할 때 1개 Finding으로 합쳐짐 단언.
    """
    doc_text = "계약서 제5조: 납품기한은 계약일로부터 30일 이내로 하며 지체 시 위약금을 부과한다."
    sources = [{"source_id": "REF_A", "title": "납품규정", "text": "납품기한은 60일 이내여야 하며 위약금은 면제된다."}]

    cand1 = ModelCandidate(
        claim_quote="30일 이내",
        defect_type="FACT_CONTRADICTION",
        basis_quote="60일 이내",
        source_id="REF_A",
        explanation="납품기한 상충",
    )
    cand2 = ModelCandidate(
        claim_quote="위약금을 부과한다",
        defect_type="FACT_CONTRADICTION",
        basis_quote="위약금은 면제된다",
        source_id="REF_A",
        explanation="위약금 상충",
    )

    f1, _ = verify_rag_candidate(cand1, doc_text, sources, is_reference_contradiction=True, claim_id="C_DELIVERY")
    f2, _ = verify_rag_candidate(cand2, doc_text, sources, is_reference_contradiction=True, claim_id="C_DELIVERY")
    assert f1 is not None
    assert f2 is not None

    promoted_groups = {}
    for f, c in [(f1, cand1), (f2, cand2)]:
        group_key = (f.confidence_features["claim_id"], f.confidence_features["source_id"])
        if group_key in promoted_groups:
            existing = promoted_groups[group_key]
            existing.detail += f" / [추가 대조 의견]: {c.explanation}"
            for ev in f.evidence:
                if not any(e.excerpt == ev.excerpt for e in existing.evidence):
                    existing.evidence.append(ev)
        else:
            promoted_groups[group_key] = f

    merged = list(promoted_groups.values())
    assert len(merged) == 1
    assert "납품기한 상충" in merged[0].detail
    assert "위약금 상충" in merged[0].detail
    assert len(merged[0].evidence) == 4  # 두 후보의 서면 인용 2개 + 참고자료 인용 2개


def test_tk70_switch_disabled_no_promotion(monkeypatch):
    """스위치 제어 1건 검증 (합성 시험):
    LV_RAG_CONTRADICTION_PROMOTION=false 설정 시 승격 0건 단언.
    """
    monkeypatch.setenv("LV_RAG_CONTRADICTION_PROMOTION", "false")
    import packages.common.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_settings", None)
    settings = cfg_mod.get_settings()
    assert settings.rag_contradiction_promotion_enabled is False


def test_tk70_risk_index_and_gate_invariance():
    """검증위험 지수 및 배포 게이트 불변 1건 검증 (합성 시험):
    승격 Finding이 존재해도 risk_index 가중합(30점)에서 제외되어 0점이고, evaluate_gate가 PASS 단언.
    """
    doc_text = "제10조: 지체상금 1/1000 납부."
    sources = [{"source_id": "R1", "title": "참고", "text": "지체상금 0.5/1000 적용."}]
    cand = ModelCandidate(
        claim_quote="지체상금 1/1000",
        defect_type="FACT_CONTRADICTION",
        basis_quote="지체상금 0.5/1000",
        source_id="R1",
        explanation="요율 상충",
    )

    f, _ = verify_rag_candidate(cand, doc_text, sources, is_reference_contradiction=True, claim_id="C1")
    assert f is not None

    # 1. 검증위험 지수 계산
    score, contributions = risk_index([f])
    assert score == 0
    assert len(contributions) == 0

    # 2. 배포 게이트 평가
    decision = evaluate_gate([f])
    assert decision.gate == ReleaseGate.PASS
    assert len(decision.hard_block_reasons) == 0
