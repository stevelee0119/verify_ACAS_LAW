"""서증 번호 및 목록 불일치(EVI-NUM) 구조 기반 검증 시험.

실제 진입점(VerificationPipeline.run), 다른 표현 양성 5건(축 1~4),
대조군 4건(완결 선언 없음, 기제출 원용, 가지번호 묶음, 통상 정상 서면) 포함.
사건 고유 리터럴 하드코딩 금지 규칙 준수.
"""
from __future__ import annotations

import pytest

from packages.common.config import reset_settings
from packages.common.enums import FindingType, EvidenceGrade
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.claim_engine.evidence_consistency import check_evidence_numbering_mismatches
from packages.verification_engine.pipeline import (
    DocumentInput,
    ProjectContext,
    VerificationPipeline,
)


def _make_doc(lines: list[str], doc_id: str = "test-doc") -> NormalizedDocument:
    """테스트용 NormalizedDocument 헬퍼 (한국어 주석)."""
    blocks = [Block(block_id=f"b{i}", text=line, page=1) for i, line in enumerate(lines)]
    return NormalizedDocument(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        pages=[Page(page_number=1, blocks=blocks)],
    )


# --- 1. 실제 진입점 파이프라인 시험 (VerificationPipeline.run) ---
def test_pipeline_entrypoint_evidence_numbering_mismatches(tmp_path, monkeypatch):
    """실제 파이프라인 진입점(VerificationPipeline.run)을 통한 EVI-NUM 검출 검증."""
    sample_text = (
        "원고는 피고의 납품 지연을 입증하기 위하여 갑 제6호증 발주서를 주요 증거로 인용합니다.\n"
        "입증방법: 갑 제1호증 계약서, 갑 제2호증 내역서 (이 서면의 제출 증거 전부)"
    )
    doc_path = tmp_path / "brief_num_mismatch.txt"
    doc_path.write_text(sample_text, encoding="utf-8")

    with monkeypatch.context() as patch:
        patch.setenv("LV_ALLOW_NETWORK", "0")
        patch.setenv("LV_DATA_DIR", str(tmp_path / "data"))
        reset_settings()
        try:
            pipeline = VerificationPipeline()
            result = pipeline.run(
                "pipeline-num-run",
                ProjectContext("pipeline-num-project"),
                [DocumentInput("brief-num-1", str(doc_path), doc_path.name)],
            )
        finally:
            reset_settings()

    assert not result.errors
    assert len(result.documents) == 1
    doc_result = result.documents[0]

    num_findings = [
        f for f in doc_result.findings
        if f.type == FindingType.EVIDENCE_LIST_MISMATCH
        and f.confidence_features.get("defect_code") == "EVIDENCE_REFERENCE_MISSING"
    ]
    assert len(num_findings) >= 1
    finding = num_findings[0]
    assert finding.evidence_grade == EvidenceGrade.B
    assert "갑 제6호증" in finding.title or "갑 제6호증" in finding.detail


# --- 2. 양성 시험 1 (축 1: 완결 목록에 없는 호증 번호 인용) ---
def test_positive_complete_list_missing_exhibit():
    """축 1: 완결을 선언한 증거목록에 없는 호증을 본문에서 인용."""
    doc = _make_doc([
        "원고는 갑 제12호증 배수 점검일지로 피고의 과실을 입증합니다.",
        "증거목록: 갑 제1호증 ~ 갑 제11호증, 이 서면의 제출 증거 전부",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) == 1
    f = findings[0]
    assert f.confidence_features.get("defect_code") == "EVIDENCE_REFERENCE_MISSING"
    assert "갑 제12호증" in f.title


# --- 3. 양성 시험 2 (축 2: 연속 범위 선언 후 중간 누락) ---
def test_positive_continuous_range_gap():
    """축 2: 을 제1호증부터 제4호증까지 연속 제출 선언 후 중간 번호 누락."""
    doc = _make_doc([
        "피고는 을 제1호증부터 을 제4호증까지 빠짐없이 연속 제출하며 본건 사실관계를 소명합니다.",
        "입증방법",
        "1. 을 제1호증 견적서",
        "2. 을 제2호증 세금계산서",
        "3. 을 제4호증 출고확인서",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) >= 1
    gap_findings = [f for f in findings if f.confidence_features.get("defect_code") == "CONTINUOUS_RANGE_GAP"]
    assert len(gap_findings) == 1
    assert "을 제3호증" in gap_findings[0].title


# --- 4. 양성 시험 3 (축 3: 본문·목록 동일 자료명의 호증 번호 불일치) ---
def test_positive_mismatched_exhibit_number_same_name():
    """축 3: 동일한 자료명(운반 사진)이 본문과 목록에서 서로 다른 호증 번호로 매핑됨."""
    doc = _make_doc([
        "본문에서는 갑 제22호증 운반 사진에 나타난 바와 같이 하자 상태가 심각합니다.",
        "입증방법",
        "1. 갑 제23호증 운반 사진",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) >= 1
    name_mismatches = [f for f in findings if f.confidence_features.get("defect_code") == "EXHIBIT_NUMBER_NAME_MISMATCH"]
    assert len(name_mismatches) == 1
    assert "운반 사진" in name_mismatches[0].title
    assert "갑 제22호증" in name_mismatches[0].detail and "갑 제23호증" in name_mismatches[0].detail


# --- 5. 양성 시험 4 (축 1: 수 호증 등 기타 당사자 부호의 완결 목록 누락 포섭) ---
def test_positive_su_exhibit_missing_in_complete_list():
    """축 1: '수' 부호 등 일반 한글 부호를 사용한 완결 목록 누락 정상 포섭."""
    doc = _make_doc([
        "피신청인은 수 제4호증 감정서를 통하여 신청인의 청구가 부당함을 입증합니다.",
        "입증방법: 수 제1호증 내지 수 제3호증 (제출 증거 일체)",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) >= 1
    f = [f for f in findings if f.confidence_features.get("defect_code") == "EVIDENCE_REFERENCE_MISSING"]
    assert len(f) >= 1
    assert "수 제4호증" in f[0].title


# --- 6. 양성 시험 5 (축 4: 선언 개수와 실제 목록 수 불일치) ---
def test_positive_count_mismatch():
    """축 4: 증거목록에서 총 4개 선언했으나 실제 목록은 3개."""
    doc = _make_doc([
        "입증방법: 총 4개 서증을 제출합니다.",
        "1. 갑 제1호증 계약서",
        "2. 갑 제2호증 영수증",
        "3. 갑 제3호증 통장사본",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) == 1
    f = findings[0]
    assert f.confidence_features.get("defect_code") == "EXHIBIT_COUNT_MISMATCH"
    assert f.confidence_features.get("declared_count") == 4
    assert f.confidence_features.get("actual_count") == 3


# --- 7. 대조군 시험 1 (완결 선언 없는 부분 목록 정상 보호) ---
def test_control_incomplete_list_not_flagged():
    """대조군 1: 완결 선언 없는 목록에서 본문이 다른 호증을 인용해도 결함 아님 (정상 서면)."""
    doc = _make_doc([
        "원고는 갑 제1호증 및 갑 제5호증을 참조하여 변론을 준비하였습니다.",
        "입증방법",
        "1. 갑 제1호증 품의서",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) == 0, f"완결 선언 없는 부분 목록은 결함으로 잡히지 않아야 함: {findings}"


# --- 8. 대조군 시험 2 (이전 제출 호증 재인용 정상 보호) ---
def test_control_prior_submission_reference():
    """대조군 2: 앞서 제출한 호증 재인용은 목록에 없더라도 규칙 레벨에서 정상 보호."""
    doc = _make_doc([
        "원고는 앞서 제출한 갑 제2호증 영수증에 기재된 금액을 다시 원용합니다.",
        "증거목록 (이 서면의 제출 증거 전부)",
        "1. 갑 제5호증 점검표",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) == 0, f"앞서 제출한 호증 재인용은 제외되어야 함: {findings}"


# --- 9. 대조군 시험 3 (상대방 증거 인용 정상 보호) ---
def test_control_opponent_exhibit_not_flagged():
    """대조군 3: 원고 서면이 상대방 증거(을 제3호증)를 인용하고 자기 목록은 갑 호증만 있어도 결함 아님."""
    doc = _make_doc([
        "원고는 피고가 제출한 을 제3호증 영수증의 진정성립을 부인합니다.",
        "입증방법: 갑 제1호증 계약서 (이 서면의 제출 증거 전부)",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) == 0, f"상대방 증거(을호증) 인용은 자기 완결목록 누락으로 잡히지 않아야 함: {findings}"


# --- 10. 대조군 시험 4 (상대방 제출 개수 서술 정상 보호) ---
def test_control_opponent_count_mention_not_flagged():
    """대조군 4: '피고는 3개의 증거를 제출하였으나...'와 같은 상대방 주어 개수 언급은 목록 개수 불일치 미검출."""
    doc = _make_doc([
        "피고는 3개의 증거를 제출하였으나 이는 본건과 무관한 자료에 불과합니다.",
        "입증방법",
        "1. 갑 제1호증 확인서",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    count_findings = [f for f in findings if f.confidence_features.get("defect_code") == "EXHIBIT_COUNT_MISMATCH"]
    assert len(count_findings) == 0, f"상대방 서술 개수는 목록 개수 불일치로 오탐되지 않아야 함: {count_findings}"


# --- 11. 대조군 시험 5 (동일 접두어를 가진 서로 다른 자료명 구분 정상 보호) ---
def test_control_distinct_names_with_common_prefix():
    """대조군 5: 목록에 '갑 제3호증 사진'과 '갑 제5호증 사진첩'이 공존할 때 상이한 번호로 오인하지 않음."""
    doc = _make_doc([
        "원고는 갑 제5호증 사진첩을 통하여 현장 전경을 설명합니다.",
        "입증방법",
        "1. 갑 제3호증 사진",
        "2. 갑 제5호증 사진첩",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    name_mismatches = [f for f in findings if f.confidence_features.get("defect_code") == "EXHIBIT_NUMBER_NAME_MISMATCH"]
    assert len(name_mismatches) == 0, f"'사진'과 '사진첩'은 서로 다른 자료명이므로 번호 불일치로 오탐되지 않아야 함: {name_mismatches}"


# --- 12. 대조군 시험 6 (정상적인 가지번호 묶음 제출 정상 보호) ---
def test_control_normal_sub_numbering():
    """대조군 6: 정상적인 가지번호(갑 제1호증의 1, 2) 묶음 제출은 결함 아님."""
    doc = _make_doc([
        "원고는 갑 제1호증의 1 및 갑 제1호증의 2를 제출합니다.",
        "입증방법",
        "1. 갑 제1호증의 1 사진",
        "2. 갑 제1호증의 2 사진",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) == 0


# --- 13. 대조군 시험 7 (통상 정상 소송서면) ---
def test_control_normal_pleading_no_defects():
    """대조군 7: 번호 불일치가 없는 통상 소송서면."""
    doc = _make_doc([
        "원고는 갑 제1호증 계약서에 따라 피고에게 이행을 촉구하였습니다.",
        "입증방법",
        "1. 갑 제1호증 계약서",
        "2. 갑 제2호증 내용증명",
    ])
    findings = check_evidence_numbering_mismatches(doc)
    assert len(findings) == 0

