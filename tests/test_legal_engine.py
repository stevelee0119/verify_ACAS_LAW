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


# --- 실제 보고서(verification_rpt_251392c6e1a044f7)에서 드러난 허위 일치 회귀 ---
class _StubLawAdapter:
    """국가법령정보 키워드 검색의 실제 동작(무관한 결과 반환)을 재현한다."""

    def __init__(self, case_records=None, law_records=None, articles=None):
        self.case_records = case_records or []
        self.law_records = law_records or []
        self.articles = articles
        self.queries = []

    def search_case(self, query, *, court=None):
        from packages.common.enums import AdapterStatus
        from packages.source_adapters.base import AdapterResponse

        self.queries.append(query)
        return AdapterResponse(AdapterStatus.READY, list(self.case_records), None, "")

    def search_law(self, law_name, *, article=None, as_of=None):
        from packages.common.enums import AdapterStatus
        from packages.source_adapters.base import AdapterResponse

        self.queries.append(law_name)
        return AdapterResponse(AdapterStatus.READY, list(self.law_records), None, "")

    def fetch_articles(self, law):
        return self.articles


def _registry_with(adapter):
    from packages.source_adapters import SourceRegistry

    registry = SourceRegistry()
    registry.legal[0] = adapter  # law는 legal[0]을 가리키는 property이다
    return registry


def _citation(**kwargs):
    from packages.common.enums import CitationType
    from packages.common.schemas import Citation

    base = dict(
        citation_id="CIT_test",
        type=CitationType.STATUTE if kwargs.get("law_name") else CitationType.CASE,
        document_id="D", block_id="B", page=1, span=(0, 10), raw_text="x",
    )
    base.update(kwargs)
    return Citation(**base)


def test_unrelated_case_result_is_not_bound_as_official():
    """가공 사건번호가 전혀 다른 실재 판례에 결부되어서는 안 된다.

    실제 보고서에서 '2023다284910'이 접두 재검색('2023다284')으로 '2024도12341'에
    매칭되어 level1=VERIFIED, 선고일 불일치(CONTRADICTED)로 보고되었다.
    존재하지 않는 판례가 '존재는 확인됨'으로 둔갑한 것이다.
    """
    from packages.common.enums import VerificationStatus
    from packages.legal_engine.verifier import LegalVerifier

    adapter = _StubLawAdapter(case_records=[{
        "case_number": "2024도12341", "court": "대법원", "decision_date": "2026-04-16",
    }])
    verdict = LegalVerifier(registry=_registry_with(adapter)).verify_case(
        _citation(canonical_case_number="2023다284910", case_number="2023다284910",
                  court="대법원", decision_date="2023-11-16",
                  raw_text="대법원 2023. 11. 16. 선고 2023다284910 판결")
    )
    assert verdict.status == VerificationStatus.NOT_FOUND
    assert verdict.official_record is None
    assert verdict.levels.get("level1") == "NOT_FOUND"
    assert all("2023다284" != q for q in adapter.queries), "사건번호를 잘라 검색하지 않는다"


def test_substring_law_match_is_rejected():
    """'민법' 조회가 '난민법'에 매칭되어 VERIFIED가 되어서는 안 된다."""
    from packages.common.enums import VerificationStatus
    from packages.legal_engine.verifier import LegalVerifier
    from packages.source_adapters.law_go_kr import _same_law_name

    assert _same_law_name("민법", "난민법") is False

    adapter = _StubLawAdapter(law_records=[])  # 이름 완전일치 필터를 통과한 결과가 없다
    verdict = LegalVerifier(registry=_registry_with(adapter)).verify_statute(
        _citation(law_name="민법", article="390의2", raw_text="민법 제390조의2")
    )
    assert verdict.status == VerificationStatus.NOT_FOUND


def test_nonexistent_article_is_not_verified():
    """법령명이 맞아도 실재하지 않는 조문은 VERIFIED가 될 수 없다."""
    from packages.common.enums import VerificationStatus
    from packages.legal_engine.verifier import LegalVerifier

    adapter = _StubLawAdapter(
        law_records=[{"law_name": "민법", "effective_from": "1958-02-22", "raw": {"법령일련번호": "1"}}],
        articles=["389", "390", "391"],
    )
    verdict = LegalVerifier(registry=_registry_with(adapter)).verify_statute(
        _citation(law_name="민법", article="390의2", raw_text="민법 제390조의2")
    )
    assert verdict.status == VerificationStatus.NOT_FOUND
    assert verdict.levels.get("article") == "NOT_FOUND"
    assert any("실재하지 않는 조문" in f.title for f in verdict.findings)


def test_article_lookup_failure_does_not_claim_verified():
    """조문 목록을 조회하지 못하면 VERIFIED가 아니라 UNVERIFIED다."""
    from packages.common.enums import VerificationStatus
    from packages.legal_engine.verifier import LegalVerifier

    adapter = _StubLawAdapter(
        law_records=[{"law_name": "민법", "effective_from": "1958-02-22", "raw": {"법령일련번호": "1"}}],
        articles=None,
    )
    verdict = LegalVerifier(registry=_registry_with(adapter)).verify_statute(
        _citation(law_name="민법", article="390의2", raw_text="민법 제390조의2")
    )
    assert verdict.status == VerificationStatus.UNVERIFIED


def test_existing_article_still_verifies():
    """정상 인용은 그대로 VERIFIED여야 한다(과잉 차단 방지)."""
    from packages.common.enums import VerificationStatus
    from packages.legal_engine.verifier import LegalVerifier

    adapter = _StubLawAdapter(
        law_records=[{"law_name": "민법", "effective_from": "1958-02-22", "raw": {"법령일련번호": "1"}}],
        articles=["389", "390", "391"],
    )
    verdict = LegalVerifier(registry=_registry_with(adapter)).verify_statute(
        _citation(law_name="민법", article="390", raw_text="민법 제390조")
    )
    assert verdict.status == VerificationStatus.VERIFIED
    assert verdict.levels.get("article") == "VERIFIED"


def test_matching_case_number_still_verifies():
    """사건번호가 일치하면 종전대로 확인된다."""
    from packages.common.enums import VerificationStatus
    from packages.legal_engine.verifier import LegalVerifier

    adapter = _StubLawAdapter(case_records=[{
        "case_number": "2023다284910", "court": "대법원", "decision_date": "2023-11-16",
    }])
    verdict = LegalVerifier(registry=_registry_with(adapter)).verify_case(
        _citation(canonical_case_number="2023다284910", case_number="2023다284910",
                  court="대법원", decision_date="2023-11-16")
    )
    assert verdict.status != VerificationStatus.NOT_FOUND
    assert verdict.official_record is not None


@pytest.mark.parametrize("text,expected_title", [
    ("(홍길동, 『현대 계약법과 알고리즘 책임론』, 법문사, 2024, 312면)", "현대 계약법과 알고리즘 책임론"),
    ("김철수, 「도급계약상 하자담보책임」, 법조 제70권 제3호, 2021, 55면", "도급계약상 하자담보책임"),
])
def test_book_and_article_citations_are_extracted(text, expected_title):
    """단행본 표기 『』가 누락되어 문헌 인용이 전혀 추출되지 않던 문제."""
    from packages.legal_engine.citation_extractor import ACADEMIC_RE

    matches = list(ACADEMIC_RE.finditer(text))
    assert matches, "문헌 인용이 추출되어야 한다"
    assert matches[0].group("title") == expected_title


@pytest.mark.parametrize("text", [
    "원고와 피고는 2025. 4. 15. 총 계약금액 12억 원 규모의 『차세대 관제』 계약을 체결하였다.",
    "피고는 원고에게 금원을 지급하라.",
])
def test_non_citation_brackets_are_not_extracted(text):
    """계약명 등 일반 『』 표기를 문헌 인용으로 오인하지 않는다."""
    from packages.legal_engine.citation_extractor import ACADEMIC_RE

    assert not list(ACADEMIC_RE.finditer(text))
