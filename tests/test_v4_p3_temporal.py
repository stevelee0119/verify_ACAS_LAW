"""v4 P3: 법령 적용 시점(행위시법) 검토. 개정된 가상 조문 5개(형사·민사·행정·가사·조세)로 시험한다.

조문은 모두 합성(가상 법령)이다. 실존 법령의 개정 연혁을 지어내지 않는다.
"""
from __future__ import annotations

import pytest

from packages.common.enums import CitationType, VerificationStatus
from packages.common.schemas import Citation
from packages.legal_engine.temporal_review import (act_date, paragraph_text, reference_for,
                                                   review_temporal_application)


def version(text, start, end=None):
    return {"text": text, "effective_from": start, "effective_to": end, "_synthetic": True}


# (분야, 법령, 조, 항, 개정 전, 개정 후, 개정일)
AMENDED = [
    ("형사", "가상형사법", "5", None, "제5조 업무상 횡령은 5년 이하의 징역에 처한다.", "제5조 업무상 횡령은 7년 이하의 징역에 처한다.", "2022-01-01"),
    ("민사", "가상손해배상법", "10", "1", "제10조 ① 손해를 안 날부터 3년간 행사하지 아니하면 소멸한다. ② 10년이 지나면 같다.",
     "제10조 ① 손해를 안 날부터 5년간 행사하지 아니하면 소멸한다. ② 10년이 지나면 같다.", "2020-07-01"),
    ("행정", "가상행정소송법", "20", "1", "제20조 ① 처분이 있음을 안 날부터 60일 이내에 제기하여야 한다.",
     "제20조 ① 처분이 있음을 안 날부터 90일 이내에 제기하여야 한다.", "2019-01-01"),
    ("가사", "가상가사법", "8", None, "제8조 재산분할청구권은 이혼한 날부터 1년이 지나면 소멸한다.",
     "제8조 재산분할청구권은 이혼한 날부터 2년이 지나면 소멸한다.", "2021-03-01"),
    ("조세", "가상국세법", "26", None, "제26조 부과제척기간은 5년간으로 한다.", "제26조 부과제척기간은 7년간으로 한다.", "2023-01-01"),
]


def versions_of(row):
    _, _, _, _, old, new, changed = row
    day_before = {"2022-01-01": "2021-12-31", "2020-07-01": "2020-06-30", "2019-01-01": "2018-12-31",
                  "2021-03-01": "2021-02-28", "2023-01-01": "2022-12-31"}[changed]
    return [version(old, "2010-01-01", day_before), version(new, changed)]


def citation(row, claim):
    field, law, article, paragraph, *_ = row
    return Citation.create(type=CitationType.STATUTE, raw_text=f"{law} 제{article}조", document_id="d", law_name=law,
                           article=article, paragraph=paragraph, attributes={"claim_text": claim})


OLD_CLAIMS = ["는 업무상 횡령을 5년 이하의 징역에 처한다", "은 3년간 행사하지 아니하면 소멸한다고 정한다",
              "에 따르면 처분이 있음을 안 날부터 60일 이내에 제기하여야 한다", "는 1년이 지나면 소멸한다고 정한다",
              "은 부과제척기간을 5년간으로 정한다"]
NEW_CLAIMS = ["는 업무상 횡령을 7년 이하의 징역에 처한다", "은 5년간 행사하지 아니하면 소멸한다고 정한다",
              "에 따르면 처분이 있음을 안 날부터 90일 이내에 제기하여야 한다", "는 2년이 지나면 소멸한다고 정한다",
              "은 부과제척기간을 7년간으로 정한다"]
WRONG_CLAIMS = ["는 업무상 횡령을 10년 이하의 징역에 처한다", "은 1년간 행사하지 아니하면 소멸한다고 정한다",
                "에 따르면 처분이 있음을 안 날부터 30일 이내에 제기하여야 한다", "는 3년이 지나면 소멸한다고 정한다",
                "은 부과제척기간을 10년간으로 정한다"]
OLD_DATE = {"형사": "2021-06-01", "민사": "2019-05-01", "행정": "2018-03-01", "가사": "2020-10-01", "조세": "2022-06-30"}


def rule(finding):
    return finding.confidence_features["rule_id"]


@pytest.mark.parametrize("index", range(5))
def test_claim_matching_the_reference_version_is_verified_with_current_difference(index):
    row = AMENDED[index]
    f = review_temporal_application(citation(row, OLD_CLAIMS[index]), versions_of(row),
                                    {"date": OLD_DATE[row[0]], "basis": "EXPLICIT_REVIEW_DATE"}, criminal=row[0] == "형사")
    assert rule(f) == "TEMPORAL.REFERENCE_VERSION_MATCH" and f.status == VerificationStatus.VERIFIED
    assert "현행과 다름" in f.title and f.advisory_only


@pytest.mark.parametrize("index", range(5))
def test_claim_matching_only_the_current_version_is_a_warning(index):
    row = AMENDED[index]
    f = review_temporal_application(citation(row, NEW_CLAIMS[index]), versions_of(row),
                                    {"date": OLD_DATE[row[0]], "basis": "EXPLICIT_REVIEW_DATE"})
    assert rule(f) == "TEMPORAL.CURRENT_ONLY_MATCH" and f.status == VerificationStatus.SUSPICIOUS


@pytest.mark.parametrize("index", range(5))
def test_claim_matching_no_version_is_contradicted_with_every_value(index):
    row = AMENDED[index]
    f = review_temporal_application(citation(row, WRONG_CLAIMS[index]), versions_of(row), {"date": None, "basis": "MISSING"})
    assert rule(f) == "TEMPORAL.NO_VERSION_MATCH" and f.status == VerificationStatus.CONTRADICTED
    assert len(f.confidence_features["versions"]) == 2


@pytest.mark.parametrize("index", range(5))
def test_without_reference_date_a_version_dependent_claim_is_never_contradicted(index):
    row = AMENDED[index]
    f = review_temporal_application(citation(row, OLD_CLAIMS[index]), versions_of(row), {"date": None, "basis": "MISSING"})
    assert rule(f) == "TEMPORAL.REVIEW_NEEDED" and f.status != VerificationStatus.CONTRADICTED


def test_criminal_review_cites_criminal_act_article_1():
    row = AMENDED[0]
    f = review_temporal_application(citation(row, OLD_CLAIMS[0]), versions_of(row),
                                    {"date": "2021-06-01", "basis": "EXPLICIT_REVIEW_DATE"}, criminal=True)
    assert "형법 제1조 제1항" in f.detail and "제2항" in f.detail


def test_single_version_is_left_to_content_comparison():
    row = AMENDED[4]
    assert review_temporal_application(citation(row, WRONG_CLAIMS[4]), versions_of(row)[:1], {"date": None}) is None


def test_document_asserted_act_date_is_used_only_with_a_time_qualifier():
    text = ("피고인은 2021. 6. 1. 회사 자금을 횡령하였다는 공소사실로 기소되었다. 피고인은 2022. 8. 3. 범행 당시 현장에 없었다고 "
            "주장한다.")
    row = AMENDED[0]
    c = citation(row, OLD_CLAIMS[0])
    assert reference_for(c, "행위 당시 가상형사법 제5조는 …", text, None)["date"] == "2021-06-01"   # 공소사실 행위일 우선
    assert reference_for(c, "가상형사법 제5조의 법정형은 …", text, None)["date"] is None           # 시점 표시 없음
    assert reference_for(c, "행위 당시 …", text, "2020-01-01")["basis"] == "EXPLICIT_REVIEW_DATE"   # 입력 기준일 우선
    assert act_date("처분청은 2024. 2. 1. 영업정지 처분을 하였다.", "처분") == "2024-02-01"


def test_paragraph_text_selects_the_cited_paragraph():
    text = "제10조 ① 3년간 행사하지 아니하면 소멸한다. ② 5년이 지난 때에도 같다."
    assert paragraph_text(text, "2").startswith("② 5년") and paragraph_text(text, None) == text
