"""v0.9.0 법리 내용 검증 및 교차 대조 고도화 단위 테스트.

과제 1: 법령 조문 상한 검증 및 부존재 조문 차단 (LAW-NX)
과제 2: 판례 판시 요지 왜곡 (CIT-MIS) 및 조문 인용 변형 (QUOTE-MOD)
과제 3: 서면 간 엔티티 교차 일치성 검증 (XDOC)
과제 4: 대조군 무결점 검증
"""
from __future__ import annotations

import pytest
from packages.common.enums import FindingType, Severity, VerificationStatus
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.statute_ranges import check_statute_article_range
from packages.legal_engine.precedent_verifier import verify_precedent_distortions, verify_statute_quotes
from packages.claim_engine.cross_document_entities import verify_cross_document_entities


def _make_dummy_doc(doc_id: str, filename: str, text: str) -> NormalizedDocument:
    """단위 테스트용 더미 정규화 문서를 생성한다."""
    block = Block(
        block_id=f"{doc_id}_b1",
        text=text,
        page=1,
    )
    page = Page(page_number=1, blocks=[block])
    return NormalizedDocument(
        document_id=doc_id,
        filename=filename,
        mime_type="application/pdf",
        sha256="dummy_sha256",
        pages=[page],
        raw_layers={"rendered_text": text, "raw_text": text},
    )


def test_statute_article_range_check():
    """과제 1 (LAW-NX): 대한민국 주요 법령의 조문 상한 초과 여부를 정확히 검증하는지 테스트."""
    # 근로기준법은 최대 116조이므로 제250조는 부존재(상한 초과)
    res_lsa = check_statute_article_range("근로기준법", 250)
    assert res_lsa is not None
    assert res_lsa["defect_code"] == "LAW-NX"
    assert res_lsa["max_article"] == 116
    assert res_lsa["cited_article"] == 250
    assert "근로기준법" in res_lsa["law_name"]

    # 근로기준법 제27조는 정상 범위 내이므로 None
    res_lsa_valid = check_statute_article_range("근로기준법", 27)
    assert res_lsa_valid is None

    # 행정소송법은 최대 46조이므로 제100조는 부존재
    res_admin = check_statute_article_range("행정소송법", 100)
    assert res_admin is not None
    assert res_admin["defect_code"] == "LAW-NX"
    assert res_admin["max_article"] == 46

    # 민사소송법은 최대 502조
    res_civ = check_statute_article_range("민사소송법", 600)
    assert res_civ is not None
    assert res_civ["defect_code"] == "LAW-NX"
    assert res_civ["max_article"] == 502


def test_precedent_distortion_detection():
    """과제 2 (CIT-MIS): 리딩 판례의 판시 방향과 정반대 주장을 검출하는지 테스트."""
    # 대법원 2019두52386 판결 취지 왜곡 서면
    distorted_text = (
        "대법원 2019두52386 판결에 따르면 근로자가 정년 도달 후에는 "
        "구제명령을 받을 수 없어 구제이익이 소멸한다고 판시하였습니다."
    )
    doc = _make_dummy_doc("doc_cit_mis", "distorted_brief.pdf", distorted_text)

    findings = verify_precedent_distortions(doc)
    assert len(findings) >= 1
    f = findings[0]
    assert f.type == FindingType.CASE_HOLDING_DISTORTION
    assert f.severity == Severity.MEDIUM
    assert f.status == VerificationStatus.UNVERIFIED and f.advisory_only
    assert "2019두52386" in f.title or "2019두52386" in f.detail
    assert "구제이익" in f.detail


def test_statute_quote_modification_detection():
    """과제 2 (QUOTE-MOD): 법조문 큰따옴표 인용구에 존재하지 않는 요건이 삽입·변형된 경우를 검출하는지 테스트."""
    # 근로기준법 제27조 따옴표 인용구 변형 서면
    mod_text = (
        '근로기준법 제27조 제2항은 "해고사유와 해고시기를 서면(이메일이나 카카오톡 메시지를 포함한다)으로 '
        '통지하여야 효력이 있다."라고 규정하고 있습니다.'
    )
    doc = _make_dummy_doc("doc_quote_mod", "distorted_statute_brief.pdf", mod_text)

    findings = verify_statute_quotes(doc)
    assert len(findings) >= 1
    f = findings[0]
    assert f.type == FindingType.STATUTE_TEXT_MISMATCH
    assert f.severity == Severity.MEDIUM
    assert f.status == VerificationStatus.UNVERIFIED and f.advisory_only
    assert "근로기준법 제27조" in f.title or "근로기준법 제27조" in f.detail
    assert "카카오톡" in f.detail or "이메일" in f.detail


def test_cross_document_entities_contradiction():
    """과제 3 (XDOC): 서면 간 입사일/판정일/근무시간 불일치를 정밀 탐지하는지 테스트."""
    doc1 = _make_dummy_doc(
        "doc_1",
        "D-01_complaint.pdf",
        "원고는 2021. 3. 4. 피고 회사에 입사하여 근무하였으며, 노동위원회 판정일은 2024. 8. 12.입니다. 총 연장근로시간 86시간입니다."
    )
    doc2 = _make_dummy_doc(
        "doc_2",
        "D-04_evidence.pdf",
        "근로계약서 상 근로계약 체결일(입사일): 2021. 4. 3. / 중앙노동위원회 재결 판정일: 2024. 8. 21. / 근무기록 연장근로 30 + 28 + 30 = 88시간"
    )

    findings = verify_cross_document_entities([doc1, doc2])
    assert len(findings) >= 2  # 입사일, 판정일, 연장근로시간 중 불일치 탐지
    entity_types = [f.confidence_features.get("entity_type") for f in findings]
    assert "입사일" in entity_types
    assert "판정일" in entity_types


def test_clean_document_no_false_positives():
    """과제 4 (대조군 무결점): 정상적인 대조군 문서에서 허위 결함이 발생하지 않는지 검증."""
    clean_text = (
        "원고는 근로기준법 제27조에 따라 서면으로 통지받지 못하였습니다. "
        "대법원 2019두52386 판결 취지에 따르면 정년에 도달하였더라도 구제명령을 받을 이익이 있습니다. "
        "2021. 3. 4. 입사하여 성실히 근무하였습니다."
    )
    doc = _make_dummy_doc("doc_clean", "clean_brief.pdf", clean_text)

    p_findings = verify_precedent_distortions(doc)
    assert len(p_findings) == 0

    q_findings = verify_statute_quotes(doc)
    assert len(q_findings) == 0

    x_findings = verify_cross_document_entities([doc])
    assert len(x_findings) == 0
