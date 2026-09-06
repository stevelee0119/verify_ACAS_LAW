"""제9장 Citation Extraction 및 검증, 제10장 Source Adapter."""
from __future__ import annotations

import pytest

from packages.common.enums import AdapterStatus, CitationType, EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.legal_engine import (
    LegalVerifier,
    canonical_case_number,
    canonical_date,
    canonical_law_name,
    extract_from_text,
)


# --- 제9.3장 정규화 ----------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    ["2023도12345", "2023 도 12345", "2023도 12345", "2023 도12345"],
)
def test_case_number_normalization(raw):
    assert canonical_case_number(raw) == "2023도12345"


def test_case_number_serial_leading_zero():
    assert canonical_case_number("2023가합00123") == "2023가합123"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024. 1. 15.", "2024-01-15"),
        ("2024년 1월 15일", "2024-01-15"),
        ("2024-01-15", "2024-01-15"),
    ],
)
def test_date_normalization(raw, expected):
    assert canonical_date(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("「형사소송법」", "형사소송법"),
        ("또한 형법", "형법"),
        ("적용법조는 테스트가상법", "테스트가상법"),
        ("현행 도로교통법", "도로교통법"),
        ("형소법", "형사소송법"),
    ],
)
def test_law_name_normalization(raw, expected):
    assert canonical_law_name(raw) == expected


# --- 제9.1장 추출 -----------------------------------------------------------
def test_extract_full_case_citation():
    citations = extract_from_text("대법원 2024. 1. 15. 선고 2023도12345 판결을 원용한다.")
    case = next(c for c in citations if c.type == CitationType.CASE)
    assert case.court == "대법원"
    assert case.decision_date == "2024-01-15"
    assert case.canonical_case_number == "2023도12345"


def test_extract_statute_with_paragraph_and_item():
    citations = extract_from_text("개인정보 보호법 제15조 제1항 제1호에 따라")
    statute = next(c for c in citations if c.type == CitationType.STATUTE)
    assert statute.law_name == "개인정보보호법"
    assert (statute.article, statute.paragraph, statute.item) == ("15", "1", "1")


def test_extract_constitutional_citation():
    citations = extract_from_text("헌법재판소 2020. 3. 26. 2018헌바123 결정 참조")
    constitutional = next(c for c in citations if c.type == CitationType.CONSTITUTIONAL)
    assert constitutional.canonical_case_number == "2018헌바123"


def test_extract_captures_direct_quote():
    text = '대법원 2024. 1. 15. 선고 2023도12345 판결은 "정당방위에 해당하지 아니한다"고 판시하였다.'
    case = next(c for c in extract_from_text(text) if c.type == CitationType.CASE)
    assert case.quoted_text and "정당방위" in case.quoted_text


def test_extract_article_with_sub_number():
    statute = next(c for c in extract_from_text("형사소송법 제308조의2") if c.type == CitationType.STATUTE)
    assert statute.article == "308의2"


# --- 제9.2장 검증 5단계 ------------------------------------------------------
def _verify(registry, text, **kwargs):
    citations = extract_from_text(text, document_id="D1", block_id="B1", page=1)
    return registry, LegalVerifier(registry).verify_citations(citations, **kwargs)


def test_level1_2_verified_when_matching(registry):
    _, result = _verify(registry, "대법원 2099. 1. 15. 선고 2099도99999 판결")
    assert result.data["verified_count"] == 1
    assert not [f for f in result.findings if f.severity.rank >= Severity.MEDIUM.rank]


def test_level2_metadata_mismatch_is_grade_a(registry):
    _, result = _verify(registry, "대법원 2098. 5. 5. 선고 2099도99999 판결")
    mismatch = next(f for f in result.findings if f.type == FindingType.CASE_METADATA_MISMATCH)
    assert mismatch.status == VerificationStatus.CONTRADICTED
    assert mismatch.evidence_grade == EvidenceGrade.A


def test_level3_quote_mismatch_detected(registry):
    text = '대법원 2099. 1. 15. 선고 2099도99999 판결은 "피고인은 무죄이며 어떠한 책임도 지지 아니한다"고 판시하였다.'
    _, result = _verify(registry, text)
    assert any(f.type == FindingType.CASE_QUOTE_MISMATCH for f in result.findings)


def test_level3_quote_match_passes(registry):
    text = '대법원 2099. 1. 15. 선고 2099도99999 판결은 "테스트를 위한 가상의 판시사항이다"라고 판시하였다.'
    _, result = _verify(registry, text)
    assert not any(f.type == FindingType.CASE_QUOTE_MISMATCH for f in result.findings)


def test_unknown_case_is_unverified_not_declared_absent(registry):
    """공식 Source를 쓸 수 없으면 '존재하지 않는 판례'라고 단정하지 않는다(제9.3장)."""
    _, result = _verify(registry, "대법원 2099. 3. 3. 선고 2099도88888 판결")
    findings = [f for f in result.findings if f.document_id == "D1"]
    assert findings
    assert all(f.status == VerificationStatus.UNVERIFIED for f in findings)
    assert all(f.evidence_grade == EvidenceGrade.U for f in findings)


# --- 제9.4장 기준시점 --------------------------------------------------------
@pytest.mark.parametrize("as_of,expect_mismatch", [("1995-01-01", True), ("2015-06-01", False), ("2022-06-01", False)])
def test_temporal_law_verification(registry, as_of, expect_mismatch):
    _, result = _verify(registry, "테스트가상법 제10조", case_date=as_of)
    has_mismatch = any(f.type == FindingType.TEMPORAL_LAW_MISMATCH for f in result.findings)
    assert has_mismatch is expect_mismatch


# --- 제10장 Adapter 상태 -----------------------------------------------------
def test_missing_key_does_not_fail_job(registry):
    """API Key가 없다는 이유로 전체 Verification Job을 실패시키지 않는다(부록 C 제4항)."""
    states = {s.name: s.status for s in registry.states()}
    assert states["kci"] == AdapterStatus.MISSING_KEY
    _, result = _verify(registry, "김철수, 「정당방위의 한계」, 법학연구 제25권 제2호, 2021.")
    assert result.unverified_items or result.findings
    assert all(f.status != VerificationStatus.ERROR for f in result.findings)


def test_unavailable_sources_are_reported(registry):
    names = {s["name"] for s in registry.unavailable()}
    assert "kci" in names


def test_source_record_created_for_every_query(registry):
    _, result = _verify(registry, "대법원 2099. 1. 15. 선고 2099도99999 판결")
    assert result.source_records
    for record in result.source_records:
        assert record.query and record.retrieved_at
        if record.status == AdapterStatus.READY:
            assert record.response_hash
