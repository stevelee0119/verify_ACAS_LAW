"""F2 통합 검토 항목(ReviewItem) 및 단일 판정 단위 시험.

- T1 단일 판정: 1인용 1행, 순수 파생 심각도, item_id 고유성
- T2 손실 없음: 모든 검토 대상 Finding이 검토 행에 도달
- T4 AI 탭 배타성: AI·보안 Finding은 검토 행에 일체 미포함
- 근거 사다리 2축 분리: official_status / reference_status 독립성
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.finding_category_map import ScreenTab, get_finding_tab
from packages.common.schemas import (
    Finding,
    OfficialConfirmationStatus,
    ReferenceSupportStatus,
    ReviewItem,
    ReviewItemKind,
)
from packages.verification_engine.review_items import (
    build_document_review_items,
    derive_item_severity,
)


@dataclass
class DummyDocResult:
    """단위 시험용 Mock DocumentResult."""
    document_id: str = "doc_test_1"
    findings: List[Finding] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    ai_hallucination_table: List[Dict[str, Any]] = field(default_factory=list)
    engine_data: Dict[str, Any] = field(default_factory=dict)


def _make_finding(
    fid: str,
    ftype: FindingType,
    sev: Severity,
    citation_id: Optional[str] = None,
) -> Finding:
    features = {}
    if citation_id:
        features["citation_id"] = citation_id
    f = Finding.create(
        type=ftype,
        status=VerificationStatus.CONTRADICTED,
        severity=sev,
        evidence_grade=EvidenceGrade.A,
        title=f"테스트 지적 {fid}",
        detail=f"상세 내용 {fid}",
        confidence=0.9,
        confidence_features=features,
        document_id="doc_test_1",
    )
    f.finding_id = fid
    return f




def test_derive_item_severity_logic():
    """심각도 순수 파생 규칙 단위 시험 (T1)."""
    # 1. Finding 없을 때 INFO
    assert derive_item_severity([]) == Severity.INFO

    # 2. 단일 Finding
    f_low = _make_finding("f1", FindingType.CASE_NOT_FOUND, Severity.LOW)
    assert derive_item_severity([f_low]) == Severity.LOW

    # 3. 복수 Finding 혼합 시 최고 순위 파생
    f_high = _make_finding("f2", FindingType.CASE_HOLDING_DISTORTION, Severity.HIGH)
    f_med = _make_finding("f3", FindingType.CASE_CITATION_ERROR, Severity.MEDIUM)
    assert derive_item_severity([f_low, f_med, f_high]) == Severity.HIGH

    f_crit = _make_finding("f4", FindingType.FACT_CONTRADICTION, Severity.CRITICAL)
    assert derive_item_severity([f_low, f_med, f_high, f_crit]) == Severity.CRITICAL


def test_build_review_items_single_verdict_and_no_loss():
    """인용 1행 원칙(T1) 및 Finding 누락 0(T2), AI 배타성(T4) 통합 검증."""
    # 2개 인용 준비
    citations = [
        {"citation_id": "cit_1", "raw_text": "대법원 판결 A"},
        {"citation_id": "cit_2", "raw_text": "민법 제1조"},
    ]

    # Findings 준비
    # cit_1에 연결된 법률 Finding 2개
    f1 = _make_finding("f1", FindingType.CASE_NOT_FOUND, Severity.MEDIUM, citation_id="cit_1")
    f2 = _make_finding("f2", FindingType.CASE_HOLDING_DISTORTION, Severity.CRITICAL, citation_id="cit_1")

    # cit_2에는 연결 Finding 없음 (순수 인용)

    # 인용에 연결되지 않은 사실관계 및 품질 Finding 2개 (T2 대상)
    f3 = _make_finding("f3", FindingType.MODEL_FACT_REMARK, Severity.LOW)
    f4 = _make_finding("f4", FindingType.OCR_LOW_QUALITY, Severity.MEDIUM)

    # AI·보안 Finding 1개 (T4 대상: ReviewItem에 절대 들어가면 안 됨)
    f_ai = _make_finding("f_ai", FindingType.PROMPT_INJECTION_SUSPECTED, Severity.HIGH, citation_id="cit_1")

    doc = DummyDocResult(
        document_id="doc_test_1",
        findings=[f1, f2, f3, f4, f_ai],
        citations=citations,
        engine_data={
            "legal_verdicts": [
                {"citation_id": "cit_1", "status": "NOT_FOUND"},
                {"citation_id": "cit_2", "status": "CONFIRMED"},
            ]
        },
    )

    items = build_document_review_items(doc)

    # T1: 인용당 1행, 중복 없음
    cit_items = [i for i in items if i.citation_id]
    assert len(cit_items) == 2
    assert {i.citation_id for i in cit_items} == {"cit_1", "cit_2"}

    # T1: cit_1의 심각도는 f1(MEDIUM), f2(CRITICAL) 중 최고값인 CRITICAL이어야 함
    cit_1_item = next(i for i in items if i.citation_id == "cit_1")
    assert cit_1_item.severity == Severity.CRITICAL
    assert set(cit_1_item.finding_ids) == {"f1", "f2"}
    assert cit_1_item.official_status == OfficialConfirmationStatus.OFFICIAL_NOT_FOUND

    # cit_2의 심각도는 연결 Finding이 없으므로 INFO이어야 함
    cit_2_item = next(i for i in items if i.citation_id == "cit_2")
    assert cit_2_item.severity == Severity.INFO
    assert cit_2_item.finding_ids == []
    assert cit_2_item.official_status == OfficialConfirmationStatus.OFFICIAL_CONFIRMED

    # T4: f_ai(AI·보안 Finding)는 어떤 ReviewItem의 finding_ids에도 없어야 함
    all_linked_fids = {fid for i in items for fid in i.finding_ids}
    assert "f_ai" not in all_linked_fids

    # T2: 검토 대상 Finding (f1, f2, f3, f4)은 100% 매핑되어야 함
    assert {"f1", "f2", "f3", "f4"} <= all_linked_fids

    # f3(FACT), f4(PROCESSING_QUALITY)는 개별 검토 행으로 존재해야 함
    f3_item = next(i for i in items if "f3" in i.finding_ids)
    assert f3_item.kind == ReviewItemKind.FACT
    assert f3_item.severity == Severity.LOW
    assert f3_item.citation_id is None

    f4_item = next(i for i in items if "f4" in i.finding_ids)
    assert f4_item.kind == ReviewItemKind.PROCESSING_QUALITY
    assert f4_item.severity == Severity.MEDIUM
    assert f4_item.citation_id is None


def test_review_item_to_dict_structure():
    """ReviewItem.to_dict() 직렬화 명세 검증."""
    item = ReviewItem(
        item_id="doc1_CITATION_cit1",
        kind=ReviewItemKind.CITATION,
        document_id="doc1",
        claim_text="주장 문구",
        official_status=OfficialConfirmationStatus.OFFICIAL_CONFIRMED,
        reference_status=ReferenceSupportStatus.NOT_CHECKED,
        verdict_label="공식 원문 일치",
        severity=Severity.INFO,
        citation_id="cit1",
    )
    d = item.to_dict()
    assert d["item_id"] == "doc1_CITATION_cit1"
    assert d["kind"] == "CITATION"
    assert d["official_status"] == "OFFICIAL_CONFIRMED"
    assert d["reference_status"] == "NOT_CHECKED"
    assert d["severity"] == "INFO"
    assert d["citation_id"] == "cit1"
