"""v3 D3: 다수의견·반대의견 귀속과 결론 방향.

재현: 테스트셋 v1 TC-02(전원합의체 판결의 반대의견 취지를 다수의견처럼 요약). 판결 문장은 모두 합성이다.
"""
from __future__ import annotations

from packages.legal_engine.opinion_attribution import (
    attribute_claim,
    direction_conflict,
    split_opinions,
)

FULL_TEXT = (
    "【이유】 상고이유를 판단한다. 1. 군인이 상관의 지시에 대하여 재판청구권을 행사하는 경우 먼저 군 내부의 "
    "건의 절차를 거쳐야 하는 것은 아니다. 지시를 따르면서 소를 제기하는 것은 그 자체로 복종의무 위반이 아니다. "
    "2. 그러므로 원심판결을 파기하고 사건을 원심법원에 환송하기로 하여 관여 법관의 일치된 의견으로 주문과 같이 "
    "판결한다. 이 판결에는 대법관 갑, 을, 병, 정의 반대의견이 있는 외에는 관여 법관의 의견이 일치하였으며, "
    "다수의견에 대한 대법관 무의 보충의견이 있다. "
    "3. 대법관 갑, 을, 병, 정의 반대의견은 다음과 같다. 군인은 상관의 지시에 이의가 있으면 먼저 군 내부의 건의 "
    "절차를 거쳐야 하고, 그 절차를 거치지 아니한 채 곧바로 소를 제기하는 것은 복종의무를 위반한 것이다. "
    "4. 다수의견에 대한 대법관 무의 보충의견은 다음과 같다. 재판청구권은 헌법이 보장하는 기본권이므로 내부 절차를 "
    "이유로 이를 제한할 수 없다는 다수의견의 논거를 보충한다."
)

SUMMARY = (
    "[1] [다수의견] 군인이 지시에 대하여 재판청구권을 행사하기 전에 군 내부의 건의 절차를 먼저 거쳐야 하는 것은 "
    "아니다. [대법관 갑, 을, 병, 정의 반대의견] 군인은 먼저 군 내부의 건의 절차를 거쳐야 하고 이를 거치지 아니한 "
    "소 제기는 복종의무 위반이다."
)

HOLDING = ("[1] 군인이 상관의 지시에 대하여 재판청구권을 행사하기 전에 군 내부의 건의 절차를 거쳐야 하는지 "
           "여부(소극) [2] 지시를 따르면서 소를 제기하는 것이 복종의무 위반인지 여부(원칙적 소극)")


def test_full_text_is_split_into_majority_dissent_and_supplementary():
    parts = split_opinions(FULL_TEXT)
    assert "건의 절차를 거쳐야 하는 것은 아니다" in parts["MAJORITY"]
    assert len(parts["DISSENT"]) == 1 and "복종의무를 위반한 것" in parts["DISSENT"][0]
    assert len(parts["SUPPLEMENTARY"]) == 1 and "보충한다" in parts["SUPPLEMENTARY"][0]
    assert "반대의견은 다음과 같다" not in parts["MAJORITY"]


def test_summary_bracket_markers_are_split_too():
    parts = split_opinions(SUMMARY)
    assert "거쳐야 하는 것은 아니다" in parts["MAJORITY"]
    assert "복종의무 위반이다" in parts["DISSENT"][0]


def test_reproduction_dissent_summarised_as_majority_is_misattributed():
    claim = "군인은 지시에 이의가 있으면 먼저 군 내부의 건의 절차를 거쳐야 하고 이를 거치지 않은 소 제기는 복종의무 위반이라고 판시하였다"
    result = attribute_claim(claim, FULL_TEXT, SUMMARY)
    assert result["verdict"] == "MISATTRIBUTED_OPINION"
    assert result["closest"] == "DISSENT" and result["scores"]["DISSENT"] > result["scores"]["MAJORITY"]


def test_synthetic_majority_summary_is_not_flagged():
    claim = "군인이 재판청구권을 행사하기 전에 건의 절차를 먼저 거쳐야 하는 것은 아니라고 판시하였다"
    assert attribute_claim(claim, FULL_TEXT, SUMMARY)["verdict"] is None


def test_synthetic_supplementary_opinion_supports_majority_and_is_not_misattribution():
    claim = "재판청구권은 헌법이 보장하는 기본권이므로 내부 절차를 이유로 제한할 수 없다고 하였다"
    result = attribute_claim(claim, FULL_TEXT, SUMMARY)
    assert result["verdict"] is None and result["closest"] == "SUPPLEMENTARY"


def test_synthetic_unanimous_judgment_has_no_attribution_issue():
    unanimous = "【이유】 원고의 청구는 이유 없다. 관여 법관의 일치된 의견으로 주문과 같이 판결한다."
    assert attribute_claim("원고의 청구는 이유 없다고 하였다", unanimous, "")["verdict"] is None


def test_direction_reversed_against_negative_holding():
    conflict = direction_conflict("군인은 재판청구권을 행사하기 전에 군 내부의 건의 절차를 거쳐야 한다고 판시하였다", HOLDING)
    assert conflict and conflict["holding_direction"] == "소극" and "건의 절차" in conflict["issue"]


def test_direction_consistent_claim_is_not_flagged():
    assert direction_conflict("재판청구권 행사 전에 건의 절차를 거쳐야 하는 것은 아니라고 판시하였다", HOLDING) is None


def test_synthetic_direction_against_positive_holding():
    holding = "[1] 징계처분 사유설명서를 교부하지 아니한 처분이 위법한지 여부(적극)"
    conflict = direction_conflict("사유설명서를 교부하지 아니한 징계처분도 위법하지 않다고 판시하였다", holding)
    assert conflict and conflict["holding_direction"] == "적극"
    assert direction_conflict("사유설명서를 교부하지 아니한 징계처분은 위법하다고 판시하였다", holding) is None


def test_unrelated_claim_is_not_compared_with_holding():
    assert direction_conflict("원고는 성실하게 근무하여 왔다", HOLDING) is None


def _case_citation(claim, quoted=None):
    from packages.common.enums import CitationType
    from packages.common.schemas import Citation
    citation = Citation.create(type=CitationType.CASE, raw_text="대법원 2018. 3. 22. 선고 2012두26401 전원합의체 판결",
                               document_id="d1", quoted_text=quoted)
    citation.attributes["case_claim"] = claim
    return citation


OFFICIAL = {"full_text": FULL_TEXT, "summary": SUMMARY, "holding": HOLDING}


def test_verifier_reports_misattributed_opinion_with_grade_and_sections():
    from packages.legal_engine.verifier import LegalVerifier
    claim = "군인은 지시에 이의가 있으면 먼저 군 내부의 건의 절차를 거쳐야 하고 이를 거치지 않은 소 제기는 복종의무 위반이라고 판시하였다"
    findings = LegalVerifier._opinion_findings(_case_citation(claim), OFFICIAL)
    labels = {f.confidence_features["verdict_label"] for f in findings}
    assert "MISATTRIBUTED_OPINION" in labels
    [mis] = [f for f in findings if f.confidence_features["verdict_label"] == "MISATTRIBUTED_OPINION"]
    assert str(mis.status) == "CONTRADICTED" and "반대의견" in mis.title


def test_verifier_flags_verbatim_quote_taken_from_dissent_as_grade_a():
    from packages.legal_engine.verifier import LegalVerifier
    quote = "군인은 상관의 지시에 이의가 있으면 먼저 군 내부의 건의 절차를 거쳐야 하고"
    findings = LegalVerifier._opinion_findings(_case_citation("라고 판시하였다", quoted=quote), OFFICIAL)
    [mis] = [f for f in findings if f.confidence_features["verdict_label"] == "MISATTRIBUTED_OPINION"]
    assert str(mis.evidence_grade) == "A"


def test_verifier_reports_reversed_direction():
    from packages.legal_engine.verifier import LegalVerifier
    findings = LegalVerifier._opinion_findings(
        _case_citation("군인은 재판청구권을 행사하기 전에 군 내부의 건의 절차를 거쳐야 한다고 판시하였다"), OFFICIAL)
    [rev] = [f for f in findings if f.confidence_features["verdict_label"] == "HOLDING_DIRECTION_REVERSED"]
    assert "소극" in rev.title


def test_verifier_leaves_majority_consistent_claim_alone():
    from packages.legal_engine.verifier import LegalVerifier
    claim = "군인이 재판청구권을 행사하기 전에 건의 절차를 먼저 거쳐야 하는 것은 아니라고 판시하였다"
    assert LegalVerifier._opinion_findings(_case_citation(claim), OFFICIAL) == []


# 공식 판시사항(대법원 2018. 3. 22. 선고 2012두26401 전원합의체 판결, 국가법령정보 공동활용 API 수집 2026-09-24)
REAL_HOLDING = (" [1] 군인이 상관의 지시와 명령에 대하여 헌법소원 등 재판청구권을 행사하는 것이 군인의 복종의무에 "
                "위반되는지 여부(원칙적 소극)  [2] 구 군인복무규율 제24조와 제25조를 군인에게 건의나 고충심사를 청구하여야 할 "
                "의무를 부과한 조항 내지 군인의 재판청구권 행사에 앞서 반드시 거쳐야 하는 군 내 사전절차로서의 의미를 갖는 것으로 "
                "볼 수 있는지 여부(소극)  [3] 구 군인복무규율 제13조 제1항에서 금지하는 ‘군무 외의 일을 위한 집단행위’의 의미 및 "
                "군인의 기본권 행사에 해당하는 행위가 이에 해당하는지 판단하는 방법 ")
# 테스트셋 v1 TC-02 2.가의 서면 문장
TC02_CLAIM = ("가. 대법원 전원합의체는 \"군인은 상관의 지시에 대하여 이의가 있는 경우 반드시 군 내부의 건의 절차를 먼저 "
              "거쳐야 하고, 이를 거치지 않은 채 외부 기관에 권리구제를 구하는 것은 복종의무 위반으로서 징계사유가 된다\"라고 "
              "판시하였습니다 .")


def test_reproduction_real_holding_direction_reversed_for_tc02():
    conflict = direction_conflict(TC02_CLAIM, REAL_HOLDING)
    assert conflict and conflict["holding_direction"] == "소극"


def test_subordinate_negation_does_not_flip_the_claim():
    holding = "[1] 공무원이 허가 없이 겸직한 것이 징계사유에 해당하는지 여부(적극)"
    assert direction_conflict("허가를 받지 않고 겸직한 것은 징계사유에 해당한다고 판시하였다", holding) is None
    assert direction_conflict("허가를 받지 않고 겸직하였더라도 징계사유에 해당하지 않는다고 판시하였다", holding)


def test_synthetic_civil_holding_direction():
    holding = "[1] 임대차계약 종료 후 임차인이 목적물을 계속 점유하는 경우 차임 상당 부당이득반환의무가 있는지 여부(소극)"
    assert direction_conflict("임대차 종료 후 임차인이 계속 점유하면 차임 상당 부당이득을 반환할 의무가 있다고 판시하였다", holding)
    assert direction_conflict("임대차 종료 후 임차인이 계속 점유하더라도 차임 상당 부당이득반환의무는 없다고 판시하였다",
                              holding) is None
