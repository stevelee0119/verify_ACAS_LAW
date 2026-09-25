"""v4 검토 2항: 실제 사건부호표(config/legal_rules/case_codes.yaml)로 대법원 + 항소·1심 부호 조합을 판정한다.

사건부호의 뜻은 「사건별 부호문자의 부여에 관한 예규」(재일 2003-1) 별표 원문에서 옮긴 것이다.
- 현행 재판예규 제1812호 별표 제공 파일에는 구합·누가 있다.
- 나·노·가합·고단은 제공 파일에 없다. 그래서 연혁본 재판예규 제1733호(2020. 4. 1. 시행) 별표에서 보충했다.
사건번호·날짜는 시험용으로 새로 지었다(실존 사건을 뜻하지 않는다).
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.legal_engine.citation_extractor import extract_from_text
from packages.legal_engine.citation_format import case_code_table, format_violations
from packages.legal_engine.verifier import LegalVerifier

TODAY = date(2026, 9, 25)


def court_code(text):
    [citation] = extract_from_text(text)
    return [v for v in format_violations(citation, today=TODAY) if v["kind"] == "COURT_CODE"]


def verified(text):
    class Law:  # 공식 DB 무응답: 형식 판정만 남는다
        def search_case(self, query, court=None):
            return SimpleNamespace(status="UNAVAILABLE", records=[], source_record=None, message="", found=False)

    [citation] = extract_from_text(text)
    return LegalVerifier(SimpleNamespace(law=Law())).verify_citations([citation], current_date="2026-09-25").findings


def test_real_table_holds_the_codes_under_review():
    codes = case_code_table()["codes"]
    expected = {"나": ("민사항소사건", "APPELLATE"), "노": ("형사항소사건", "APPELLATE"),
                "누": ("행정항소사건", "APPELLATE"), "가합": ("민사1심합의사건", "FIRST"),
                "고단": ("형사1심단독사건", "FIRST"), "구합": ("행정1심사건", "FIRST"),
                "다": ("민사상고사건", "SUPREME"), "도": ("형사상고사건", "SUPREME"), "두": ("행정상고사건", "SUPREME")}
    for code, (case_type, level) in expected.items():
        assert (codes[code]["case_type"], codes[code]["level"]) == (case_type, level), code


def test_supplemented_codes_carry_their_historical_source():
    table = case_code_table()
    source = table["supplement_source"]
    assert "제1733호" in source["version"] and "2020. 4. 1. 시행" in source["version"]
    assert all(f["sha256"] and "flSeq=" in f["url"] for f in source["files"])
    for code in ("나", "노", "가합", "고단"):
        assert table["codes"][code]["source"] == "SUPPLEMENT" and code in source["added_codes"]
    for code in ("구합", "누"):  # 현행 별표 제공 파일에 있는 부호는 보충 대상이 아니다
        assert "source" not in table["codes"][code]


@pytest.mark.parametrize("text,code,case_type,supplement", [
    ("대법원 2021. 4. 29. 선고 2020나123456 판결", "나", "민사항소사건", True),
    ("대법원 2022. 1. 27. 선고 2021노2345 판결", "노", "형사항소사건", True),
    ("대법원 2020. 11. 12. 선고 2019가합54321 판결", "가합", "민사1심합의사건", True),
    ("대법원 2023. 3. 9. 선고 2022고단1234 판결", "고단", "형사1심단독사건", True),
    ("대법원 2019. 10. 17. 선고 2018구합67890 판결", "구합", "행정1심사건", False),
])
def test_supreme_court_with_appellate_or_first_instance_code_is_mismatch(text, code, case_type, supplement):
    [v] = court_code(text)
    assert v["rule_id"] == "FMT.COURT_CODE_MISMATCH" and v["inferred_court"] == "하급법원"
    assert f"'{code}'" in v["reason"] and case_type in v["reason"]
    assert ("제1733호" in v["reason"]) is supplement


def test_supreme_court_nu_after_the_period_is_out_of_period():
    [v] = court_code("대법원 2006. 7. 13. 선고 2005누4321 판결")
    assert v["rule_id"] == "FMT.CODE_OUT_OF_PERIOD" and "행정항소사건" in v["reason"]


def test_supreme_court_nu_in_the_period_or_boundary_is_not_flagged():
    assert court_code("대법원 1995. 7. 11. 선고 94누4615 판결") == []
    assert court_code("대법원 2000. 3. 10. 선고 1999누1234 판결") == []  # 경계 연도는 판단하지 않는다


@pytest.mark.parametrize("text", [
    "대법원 2021. 4. 29. 선고 2020나123456 판결",
    "대법원 2022. 1. 27. 선고 2021노2345 판결",
    "대법원 2006. 7. 13. 선고 2005누4321 판결",
    "대법원 2020. 11. 12. 선고 2019가합54321 판결",
    "대법원 2023. 3. 9. 선고 2022고단1234 판결",
    "대법원 2019. 10. 17. 선고 2018구합67890 판결",
])
def test_every_combination_is_reported_as_court_code_mismatch(text):
    court = [f for f in verified(text) if (f.confidence_features or {}).get("defect_code") == "COURT_CODE_MISMATCH"]
    assert len(court) == 1 and "(COURT_CODE_MISMATCH)" in court[0].title and str(court[0].evidence_grade) == "A"


@pytest.mark.parametrize("text", [
    "대법원 2021. 4. 29. 선고 2020다123456 판결",        # 민사 상고
    "대법원 2022. 1. 27. 선고 2021도2345 판결",          # 형사 상고
    "대법원 2019. 10. 17. 선고 2018두67890 판결",        # 행정 상고
    "서울고등법원 2020. 6. 11. 선고 2019나2012345 판결",  # 민사 항소
    "서울중앙지방법원 2022. 5. 4. 선고 2021고단5678 판결",  # 형사 1심 단독
    "서울행정법원 2018. 9. 7. 선고 2017구합61234 판결",  # 행정 1심
])
def test_consistent_court_and_code_is_not_flagged(text):
    assert court_code(text) == []


def test_lower_court_with_supreme_code_is_mismatch_in_every_field():
    for text, code in (("서울고등법원 2021. 2. 4. 선고 2020다12345 판결", "다"),
                       ("수원지방법원 2021. 2. 4. 선고 2020도12345 판결", "도"),
                       ("대전고등법원 2021. 2. 4. 선고 2020두12345 판결", "두")):
        [v] = court_code(text)
        assert v["rule_id"] == "FMT.COURT_CODE_MISMATCH" and v["inferred_court"] == "대법원" and f"'{code}'" in v["reason"]


# --- 생성기 보충 규칙(합성 표) ------------------------------------------------------------------
spec = importlib.util.spec_from_file_location(
    "build_case_codes", Path(__file__).resolve().parents[1] / "scripts" / "build_case_codes.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def _history(**versions):
    return {issued: {"pairs": pairs, "files": [{"url": f"https://www.law.go.kr/LSW/flDownload.do?flSeq={issued}",
                                                 "sha256": "0" * 64}]} for issued, pairs in versions.items()}


def test_supplement_adds_only_missing_codes_and_keeps_current_entries():
    table = {"codes": {"르": {"case_type": "가사항소사건", "level": "APPELLATE"}}}
    history = _history(**{"20190101": {"르": "옛 이름", "나": "민사항소사건", "노": "형사항소사건"},
                          "20200101": {"르": "옛 이름", "나": "민사항소사건", "노": "형사항소사건"}})
    rows = {"20200101": {"발령번호": "9999", "시행일자": "20200301", "행정규칙일련번호": "1"}}
    out = builder.supplement(table, history, rows, "20200101")
    assert out["codes"]["르"] == {"case_type": "가사항소사건", "level": "APPELLATE"}  # 현행 표는 덮어쓰지 않는다
    assert out["codes"]["나"]["level"] == "APPELLATE" and out["codes"]["나"]["source"] == "SUPPLEMENT"
    assert out["codes"]["노"]["versions_agreeing"] == 2 and "제9999호" in out["supplement_source"]["version"]


def test_supplement_skips_codes_whose_name_differs_between_versions():
    history = _history(**{"20150101": {"고단": "형사1심단독사건", "하기": "기타 파산 관련 신청사건"},
                          "20160101": {"고단": "형사1심단독사건", "하기": "기타 파산·면책 관련 신청사건"}})
    out = builder.supplement({"codes": {}}, history, {}, "20160101")
    assert "고단" in out["codes"] and "하기" not in out["codes"]
    assert out["supplement_source"]["excluded_conflicting_codes"] == ["하기"]


def test_supplement_refuses_a_version_that_was_not_fetched():
    with pytest.raises(SystemExit):
        builder.supplement({"codes": {}}, _history(**{"20200101": {"가합": "민사1심합의사건"}}), {}, "20210101")
