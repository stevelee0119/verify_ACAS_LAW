"""TK-12: 준비서면 시험용 미러(tests/fixtures/prepared_brief_mirror)의 무결성과 공식 연혁 대조(평가 에이전트).

원 시험(`tests/test_ground_truth_prepared_brief.py`)이 쓰는 자료를 국가법령정보센터 공식 원문으로 구성했다
(출처·한계는 같은 폴더의 SOURCES.md). 이 파일은 그 자료가 변조되거나 시험에 맞추어 고쳐지는 것을 막고,
공식 자료로 확인되는 범위의 행위시법 판단(제14조의2 제6항 3배→5배)을 고정한다.

- 사용자 결정(2026-10-03): 공식 데이터베이스에서 확인되지 않은 2018도15313을 확인된 판례(대법원 2020다268807 판결)로 바꾼다.
  확인되지 않은 사건번호는 미러에 넣지 않는다(아래 시험이 막는다).
- 공식 원문상 2020. 5. 12.에 카목(성과 도용)이 이미 있었으므로 원 시험의 "카목 부존재" 기대는 거두었다.
  신설된 카목(데이터 부정사용)을 2020년 행위에 인용하는 경우의 검출은 현재 엔진이 못 한다(조 단위 버전만 비교).
  이는 `test_new_data_ka_cited_for_2020_act_is_flagged`가 strict xfail로 고정한다(TK-34, 6차 이후 라운드).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from packages.common.enums import Severity, VerificationStatus
from packages.common.schemas import Citation, CitationType
from packages.legal_engine.temporal_review import paragraph_text, review_temporal_application
from packages.source_adapters.local_mirror import LocalLegalMirror

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "prepared_brief_mirror"
LAW = "부정경쟁방지 및 영업비밀보호에 관한 법률"
ACTION_DATE = "2020-05-12"
REQUIRED = ("law_name", "article", "text", "effective_from", "effective_to", "promulgation_date",
            "promulgation_number", "detail_link", "source_note")


def _rows():
    return json.loads((ROOT / "laws.json").read_text(encoding="utf-8"))


def _mirror():
    return LocalLegalMirror(root=ROOT)


def _day(value: str) -> date:
    return date.fromisoformat(value)


def _punitive_citation(claim: str) -> Citation:
    return Citation(
        citation_id="c4", document_id="doc1", block_id="b4", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제14조의2 제6항", type=CitationType.STATUTE, law_name="부정경쟁방지법",
        article="14조의2", paragraph="6", attributes={"claim_text": claim})


def test_every_entry_has_official_source_and_well_formed_dates():
    rows = _rows()
    assert rows, "laws.json이 비어 있다"
    for row in rows:
        missing = [key for key in REQUIRED if key not in row]
        assert not missing, f"{row.get('article')}: 필수 항목 누락 {missing}"
        assert row["detail_link"].startswith("https://www.law.go.kr/"), row["detail_link"]
        assert row["promulgation_number"].startswith("법률 제"), row["promulgation_number"]
        start = _day(row["effective_from"])
        _day(row["promulgation_date"])
        if row["effective_to"] is not None:
            assert _day(row["effective_to"]) >= start
        assert row["text"].strip(), "조문 본문이 비어 있다"


def test_article_14_2_versions_are_contiguous_without_overlap():
    versions = _mirror().all_versions(LAW, "14의2")
    assert len(versions) == 4
    for earlier, later in zip(versions, versions[1:]):
        assert earlier["effective_to"] is not None
        assert _day(later["effective_from"]) - _day(earlier["effective_to"]) == timedelta(days=1), \
            (earlier["effective_to"], later["effective_from"])
    assert versions[-1]["effective_to"] is None


def test_article_14_2_paragraph_6_multiplier_by_version():
    expected = {"2019-07-09": ("3배", "5배"), "2021-04-21": ("3배", "5배"),
                "2021-06-23": ("3배", "5배"), "2024-08-21": ("5배", "3배")}
    for version in _mirror().all_versions(LAW, "14의2"):
        present, absent = expected[version["effective_from"]]
        paragraph = paragraph_text(version["text"], "6")
        assert paragraph.startswith("⑥") and "⑦" not in paragraph
        assert present in paragraph and absent not in paragraph, version["effective_from"]


def test_cases_are_officially_linked_and_unverified_numbers_are_absent():
    mirror = _mirror()
    # 공식 데이터베이스에서 확인되지 않은 사건번호(2018도15313)와 가상 사건(2023다284109)은 들어 있으면 안 된다.
    assert mirror.find_case("2018도15313") is None, "공식 확인되지 않은 2018도15313이 미러에 들어 있다"
    assert mirror.find_case("2023다284109") is None, "가상 사건 2023다284109가 미러에 들어 있다"
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    assert [c["case_number"] for c in cases] == ["2020다268807"]
    for case in cases:
        assert case["detail_link"].startswith("https://www.law.go.kr/LSW/precInfoP.do?precSeq="), case["case_number"]
        assert case["court"] == "대법원" and case["decision_date"] == "2022-10-14" and case["case_kind"] == "판결"
        assert "(카)목" in case["holding"] and "제2조 제1호" in case["reference_provisions"]
    found = mirror.find_case("2020다268807")
    assert found is not None and "2020다268807" in found["case_number"]


def test_punitive_multiplier_retroactivity_with_official_versions():
    versions = _mirror().all_versions(LAW, "14의2")
    five = "손해액의 5배를 넘지 아니하는 범위에서 징벌적 배상책임이 인정된다"
    three = "손해액의 3배를 넘지 아니하는 범위에서 징벌적 배상책임이 인정된다"

    old_act = review_temporal_application(_punitive_citation(five), versions, {"date": ACTION_DATE, "basis": "FACT_DATE"})
    assert old_act is not None
    assert old_act.status == VerificationStatus.SUSPICIOUS and old_act.severity == Severity.HIGH
    assert "RETROACTIVE_APPLICATION_ERROR" in old_act.tags
    assert old_act.confidence_features["rule_id"] == "TEMPORAL.CURRENT_ONLY_MATCH"

    # 같은 날 행위에 행위시법(3배)을 적용한 서술은 오탐으로 보면 안 된다.
    correct = review_temporal_application(_punitive_citation(three), versions, {"date": ACTION_DATE, "basis": "FACT_DATE"})
    assert correct is not None
    assert correct.status == VerificationStatus.VERIFIED and correct.severity == Severity.INFO
    assert "RETROACTIVE_APPLICATION_ERROR" not in correct.tags

    # 5배가 시행된 뒤의 행위에는 5배가 맞다.
    new_act = review_temporal_application(_punitive_citation(five), versions, {"date": "2025-01-01", "basis": "FACT_DATE"})
    assert new_act is not None
    assert new_act.status == VerificationStatus.VERIFIED and "RETROACTIVE_APPLICATION_ERROR" not in new_act.tags


def _article2_ka_clause(text: str) -> str:
    start = text.index("\n카. ")
    nxt = text.find("\n타. ", start)
    end = nxt if nxt > 0 else text.index("\n2. ", start)
    return text[start:end]


def test_article2_ka_in_force_on_2020_05_12_is_performance_misappropriation():
    """공식 원문: 2020. 5. 12.에 시행 중인 제2조 제1호 카목은 성과 도용이고 데이터 부정사용이 아니다."""
    covering = [v for v in _mirror().all_versions(LAW, "2")
                if v["effective_from"] <= ACTION_DATE and (v["effective_to"] is None or ACTION_DATE <= v["effective_to"])]
    assert len(covering) == 1
    clause = _article2_ka_clause(covering[0]["text"])
    assert "타인의 상당한 투자나 노력으로 만들어진 성과" in clause
    assert "데이터" not in clause


def test_article2_current_ka_is_data_misuse_and_performance_misappropriation_moved_to_pa():
    """공식 원문(현행): 카목은 데이터 부정사용, 성과 도용은 파목(2021. 12. 7. 개정 법률 제18548호)."""
    current = [v for v in _mirror().all_versions(LAW, "2") if v["effective_to"] is None]
    assert len(current) == 1
    text = current[0]["text"]
    assert "데이터" in _article2_ka_clause(text)
    assert "\n파. 그 밖에 타인의 상당한 투자나 노력으로 만들어진 성과" in text


def test_performance_misappropriation_cited_as_ka_for_2020_act_is_not_flagged():
    """성과 도용 문언을 카목으로 인용한 서면을 2020. 5. 12. 행위에 적용하는 것은 행위시법에 맞다 — 오류로 표시하면 오탐."""
    claim = "타인의 상당한 투자나 노력으로 만들어진 성과를 무단으로 사용하여 이익을 침해"
    citation = Citation(
        citation_id="c3", document_id="doc1", block_id="b3", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제2조 제1호 카목", type=CitationType.STATUTE, law_name="부정경쟁방지법",
        article="2", item="1", attributes={"claim_text": claim})
    finding = review_temporal_application(
        citation, _mirror().all_versions(LAW, "2"), {"date": ACTION_DATE, "basis": "FACT_DATE"})
    assert finding is None or (finding.severity != Severity.HIGH and "RETROACTIVE_APPLICATION_ERROR" not in finding.tags)


@pytest.mark.xfail(strict=True, reason="TK-34: 목 단위 신설·이동 시점 검토 미구현 — 엔진은 조 단위 버전만 비교한다(6차 이후 라운드)")
def test_new_data_ka_cited_for_2020_act_is_flagged():
    """신설된 카목(데이터 부정사용, 2022. 4. 20. 시행)을 2020. 5. 12. 행위에 인용하면 소급 적용 오류다.

    claim_text는 평가 측이 공식 원문(현행 카목)을 요약해 지은 것이며 준비서면·정답지의 문구가 아니다.
    """
    claim = "전자적 방법으로 상당량 축적ㆍ관리되는 데이터를 접근권한 없이 부정하게 취득하여 사용하는 행위에 해당한다"
    citation = Citation(
        citation_id="c3", document_id="doc1", block_id="b3", page=1, span=(0, 30),
        raw_text="부정경쟁방지법 제2조 제1호 카목", type=CitationType.STATUTE, law_name="부정경쟁방지법",
        article="2", item="1", attributes={"claim_text": claim})
    finding = review_temporal_application(
        citation, _mirror().all_versions(LAW, "2"), {"date": ACTION_DATE, "basis": "FACT_DATE"})
    assert finding is not None
    assert finding.severity == Severity.HIGH and "RETROACTIVE_APPLICATION_ERROR" in finding.tags
