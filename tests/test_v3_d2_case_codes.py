"""v3 D2: 법원–사건부호 호환성(공식 재판예규 별표 기준)과 부호가 가리키는 법원으로 재조회.

재현: 테스트셋 v1 TC-02 "대법원 … 2019구합51234", TC-06 "헌법재판소 … 2012두26401 결정".
합성: 다른 법원·부호·연도 조합.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.common.enums import CitationType
from packages.legal_engine import citation_format
from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.citation_format import code_court_family, format_violations

TABLE = {
    "source": {"title": "사건별 부호문자의 부여에 관한 예규(재일 2003-1)", "url": "https://www.law.go.kr/"},
    "codes": {
        "구합": {"case_type": "행정1심사건", "level": "FIRST"},
        "누": {"case_type": "행정항소사건", "level": "APPELLATE", "supreme_court_until_year": 1998,
              "supreme_court_unknown_until_year": 1999},
        "두": {"case_type": "행정상고사건", "level": "SUPREME"},
        "므": {"case_type": "가사상고사건", "level": "SUPREME"},
        "드합": {"case_type": "가사1심합의사건", "level": "FIRST"},
        "아": {"case_type": "행정신청사건", "level": "ANY"},
    },
    "constitutional_codes": {"헌마": "헌법소원심판사건(§68①)", "헌바": "헌법소원심판사건(§68②)"},
}


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(citation_format, "case_code_table", lambda: TABLE)


def cite(text):
    [c] = [c for c in extract_from_text(text) if c.type in (CitationType.CASE, CitationType.CONSTITUTIONAL)]
    return c


def rules(text):
    return {v["rule_id"]: v for v in format_violations(cite(text), today=__import__("datetime").date(2026, 9, 24))}


def test_reproduction_supreme_court_with_first_instance_code():
    found = rules("대법원 2020. 3. 12. 선고 2019구합51234 판결")
    v = found["FMT.COURT_CODE_MISMATCH"]
    assert v["inferred_court"] == "하급법원" and "행정1심사건" in v["reason"]


def test_reproduction_constitutional_court_with_supreme_code_points_to_supreme_court():
    found = rules("헌법재판소는 2018. 3. 22. 2012두26401 결정에서")
    v = found["FMT.COURT_CODE_MISMATCH"]
    assert v["inferred_court"] == "대법원"


def test_synthetic_high_court_with_supreme_family_code():
    assert "FMT.COURT_CODE_MISMATCH" in rules("서울고등법원 2021. 5. 13. 선고 2020므12345 판결")


def test_synthetic_supreme_court_with_constitutional_code():
    assert rules("대법원 2020. 5. 28. 선고 2019헌마123 판결")["FMT.COURT_CODE_MISMATCH"]["inferred_court"] == "헌법재판소"


def test_synthetic_consistent_combinations_are_not_flagged():
    assert rules("서울행정법원 2020. 5. 28. 선고 2019구합51234 판결") == {}
    assert rules("대법원 2020. 5. 28. 선고 2019두51234 판결") == {}
    assert rules("서울고등법원 2020. 5. 28. 선고 2019누51234 판결") == {}
    assert rules("헌법재판소 2020. 5. 28. 2019헌바123 결정") == {}


def test_year_condition_for_supreme_court_nu():
    assert rules("대법원 1995. 7. 11. 선고 94누4615 판결") == {}
    assert rules("대법원 2000. 7. 11. 선고 1999누4615 판결") == {}  # 경계 연도는 판단하지 않는다(unknown)
    assert "FMT.CODE_OUT_OF_PERIOD" in rules("대법원 2006. 7. 11. 선고 2005누4615 판결")


def test_codes_absent_from_table_or_any_level_are_unknown():
    assert rules("대법원 2020. 5. 28. 선고 2019카확123 결정") == {}
    assert rules("대법원 2020. 5. 28. 선고 2019아123 결정") == {}


def test_family_inference():
    assert code_court_family("두") == "대법원"
    assert code_court_family("구합") == "하급법원"
    assert code_court_family("헌마") == "헌법재판소"
    assert code_court_family("카확") is None


def test_particle_after_court_is_not_part_of_the_citation():
    c = cite("헌법재판소는 2018. 3. 22. 2012두26401 결정에서")
    assert c.raw_text.startswith("헌법재판소 ") and "헌법재판소는" not in c.raw_text


def test_verifier_requeries_the_court_the_code_points_to(monkeypatch):
    from packages.common.enums import AdapterStatus
    from packages.legal_engine.verifier import LegalVerifier

    calls = []
    record = {"court": "대법원", "decision_date": "2018-03-22", "case_number": "2012두26401",
              "case_name": "전역처분등취소", "case_kind": "판결", "holding": "", "summary": "", "full_text": ""}

    class Law:
        def search_case(self, query, court=None):
            calls.append(court)
            found = court == "대법원"
            return SimpleNamespace(status=AdapterStatus.READY, records=[record] if found else [],
                                   source_record=None, message="", found=found)

    citation = cite("헌법재판소는 2018. 3. 22. 2012두26401 결정에서")
    result = LegalVerifier(SimpleNamespace(law=Law())).verify_citations([citation], current_date="2026-09-24")
    assert "대법원" in calls
    titles = " ".join(f.title + " " + (f.detail or "") for f in result.findings)
    assert "법원 표시 오류(실제: 대법원 판결)" in titles
    [finding] = [f for f in result.findings if f.confidence_features.get("rule_id") == "FMT.COURT_CODE_MISMATCH"]
    assert str(finding.evidence_grade) == "A"
    assert "법원–부호 불일치" in finding.title
