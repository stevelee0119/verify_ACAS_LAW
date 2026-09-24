"""v3 D4: 정확한 인용을 '확인 완료'로 표시한다(VERIFIED_CITATION·VERIFIED_PROVISION, 사건 적용성은 별도).

재현: 테스트셋 v1 TC-01(대조군)의 정확한 판례·조문 인용이 미검증 목록에 남던 문제. 합성: 다른 분야 인용.
"""
from __future__ import annotations

from types import SimpleNamespace

from packages.common.enums import AdapterStatus, CitationType, VerificationStatus
from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.components import component_summary
from packages.legal_engine.verification_labels import citation_label, provision_label


def test_provision_without_reference_date_is_verified_against_current_version_with_advisory():
    status, label, advisory = provision_label({"existence": "VERIFIED", "article": "VERIFIED",
                                               "content": "VERIFIED", "temporal": "UNVERIFIED"},
                                              VerificationStatus.PARTIALLY_VERIFIED, as_of=None)
    assert status == VerificationStatus.VERIFIED and label == "VERIFIED_PROVISION"
    assert "현행 버전 기준 일치" in advisory and "기준일" in advisory


def test_provision_with_reference_date_needs_the_dated_version():
    status, label, _ = provision_label({"existence": "VERIFIED", "article": "VERIFIED", "content": "VERIFIED",
                                        "temporal": "UNVERIFIED"}, VerificationStatus.PARTIALLY_VERIFIED,
                                       as_of="2020-01-01")
    assert status == VerificationStatus.PARTIALLY_VERIFIED and label is None
    status, label, _ = provision_label({"existence": "VERIFIED", "article": "VERIFIED", "content": "NOT_ASSERTED",
                                        "temporal": "VERIFIED"}, VerificationStatus.PARTIALLY_VERIFIED,
                                       as_of="2020-01-01")
    assert status == VerificationStatus.VERIFIED and label == "VERIFIED_PROVISION"


def test_contradicted_or_unchecked_content_is_never_verified():
    for content in ("CONTRADICTED", "UNVERIFIED", "AVAILABLE"):
        status, label, _ = provision_label({"existence": "VERIFIED", "article": "VERIFIED", "content": content},
                                           VerificationStatus.PARTIALLY_VERIFIED, as_of=None)
        assert label is None and status != VerificationStatus.VERIFIED


def test_case_label_requires_existence_bibliography_and_quote():
    ok = {"level1": "VERIFIED", "level2": "VERIFIED", "level3": "VERIFIED"}
    assert citation_label(ok, VerificationStatus.VERIFIED, has_quote=True) == (VerificationStatus.VERIFIED,
                                                                              "VERIFIED_CITATION")
    no_quote = {"level1": "VERIFIED", "level2": "VERIFIED"}
    assert citation_label(no_quote, VerificationStatus.VERIFIED, has_quote=False)[1] == "VERIFIED_CITATION"
    for bad in ({**ok, "level3": "MODIFIED"}, {**ok, "level2": "CONTRADICTED"}, {**ok, "opinion": "SUSPICIOUS"},
                {"level1": "VERIFIED", "level2": "VERIFIED"}):
        assert citation_label(bad, VerificationStatus.PARTIALLY_VERIFIED, has_quote=True)[1] is None


def _law(record):
    class Law:
        def search_case(self, query, court=None):
            return SimpleNamespace(status=AdapterStatus.READY, records=[record], source_record=None, message="",
                                   found=True)
    return Law()


def test_reproduction_exact_case_citation_is_verified_citation_in_verdict_and_summary():
    from packages.legal_engine.verifier import LegalVerifier
    record = {"court": "대법원", "decision_date": "2006-12-21", "case_number": "2006두16274", "case_name": "해임처분취소",
              "case_kind": "판결", "holding": "", "summary": "징계처분이 사회통념상 현저하게 타당성을 잃어 재량권을 남용한 것이라고 "
              "인정되는 경우에 한한다", "full_text": "징계처분이 사회통념상 현저하게 타당성을 잃어 재량권을 남용한 것이라고 인정되는 "
              "경우에 한한다"}
    [c] = [c for c in extract_from_text('대법원은 "징계처분이 사회통념상 현저하게 타당성을 잃어 재량권을 남용한 것이라고 '
                                        '인정되는 경우에 한한다"라고 판시하였다(대법원 2006. 12. 21. 선고 2006두16274 판결).')
           if c.type == CitationType.CASE]
    result = LegalVerifier(SimpleNamespace(law=_law(record))).verify_citations([c], current_date="2026-09-24")
    [verdict] = result.data["verdicts"]
    assert verdict["status"] == "VERIFIED"
    assert verdict["verification_label"] == "VERIFIED_CITATION"
    assert verdict["applicability"] == "APPLICABILITY_UNREVIEWED"
    assert result.data["component_summary"]["verified"] == 1
    assert not result.findings


def test_synthetic_civil_case_with_wrong_date_is_not_verified():
    from packages.legal_engine.verifier import LegalVerifier
    record = {"court": "대법원", "decision_date": "2019-05-30", "case_number": "2018다12345", "case_name": "손해배상(기)",
              "case_kind": "판결", "holding": "", "summary": "", "full_text": ""}
    [c] = [c for c in extract_from_text("대법원 2019. 6. 13. 선고 2018다12345 판결") if c.type == CitationType.CASE]
    result = LegalVerifier(SimpleNamespace(law=_law(record))).verify_citations([c], current_date="2026-09-24")
    [verdict] = result.data["verdicts"]
    assert verdict["verification_label"] is None and verdict["status"] == "CONTRADICTED"


def test_summary_counts_verified_labels():
    entries = [{"verification_label": "VERIFIED_CITATION", "status": "VERIFIED", "components": []},
               {"verification_label": "VERIFIED_PROVISION", "status": "VERIFIED", "components": []},
               {"verification_label": None, "status": "NOT_FOUND", "components": []}]
    summary = component_summary(entries)
    assert summary["verified"] == 2 and summary["verified_citation"] == 1 and summary["verified_provision"] == 1
