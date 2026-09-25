"""v5 3-2: 법리 판정의 극성(단정·부정·전달·가정). 같은 명제의 긍정·부정·전달 변형 3종 × 규칙 12개.

재현(일반화): "헌법 조항 자체는 위헌심사의 대상이 아니라고 보았습니다"(정확한 서술)를 '헌법 조항 자체를 위헌이라고
주장'으로 판정(CONTRADICTED B)한 오탐. 문장은 모두 시험용으로 새로 지었다(블라인드 문장을 쓰지 않는다).
"""
from __future__ import annotations

import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.claim_review import review_claims
from packages.legal_engine.legal_rules import review_legal_rules
from packages.legal_engine.polarity import ASSERTED, CONDITIONAL, NEGATED, REPORTED, polarity


def _doc(*paragraphs):
    blocks = [Block(block_id=f"b{i}", text=t, page=1, block_type="paragraph") for i, t in enumerate(paragraphs)]
    return NormalizedDocument(document_id="d", filename="d.pdf", mime_type="application/pdf", sha256="0",
                              pages=[Page(page_number=1, blocks=blocks)])


def rule_ids(*paragraphs):
    doc = _doc("청 구 원 인", *paragraphs)
    return {f.confidence_features.get("rule_id") for f in review_legal_rules(doc) + review_claims(doc)}


# (규칙, 맥락 문단, 긍정, 부정, 전달)
CASES = [
    ("CLAIM.UNCONSTITUTIONALITY", "",
     "헌법 제37조 제2항 자체가 위헌입니다.",
     "헌법 제37조 제2항 자체는 위헌심사의 대상이 아니라고 보는 것이 타당합니다.",
     "헌법 제37조 제2항 자체가 위헌이라는 청구인의 주장은 이유 없습니다."),
    ("CLAIM.UNSUPPORTED_GENERALIZATION", "",
     "임대인은 어떠한 경우에도 보증금 반환책임을 진다.",
     "임대인이 어떠한 경우에도 보증금 반환책임을 진다고 볼 수는 없다.",
     "피고는 임대인이 어떠한 경우에도 보증금 반환책임을 진다고 주장하나, 이는 사실과 다르다."),
    ("CLAIM.NO_BASIS_REMEDY", "",
     "피고는 원고에게 손해액의 3배를 배상하여야 합니다.",
     "이 사건에서 피고가 손해액의 3배를 배상하여야 하는 것은 아닙니다.",
     "원고는 피고가 손해액의 3배를 배상하여야 한다고 주장하나, 근거 조항이 없습니다."),
    ("CLAIM.LITIGATION_REQUIREMENT_EXCLUSION", "",
     "이 사건 청구에는 소멸시효가 적용되지 않습니다.",
     "이 사건 청구에 소멸시효가 적용되지 않는다고 볼 수는 없습니다.",
     "피고는 이 사건 청구에 소멸시효가 적용되지 않는다고 주장하나, 받아들일 수 없습니다."),
    ("TORT.OFFICIAL_LIGHT_NEGLIGENCE", "",
     "담당 공무원은 경과실만 있어도 개인적으로 배상할 책임이 있습니다.",
     "담당 공무원이 경과실만으로 개인적으로 배상할 책임이 있는 것은 아닙니다.",
     "원고는 담당 공무원이 경과실만 있어도 배상할 책임이 있다고 주장하나, 이는 국가배상 법리에 반합니다."),
    ("MIL.PRE_TRIAL_REVIEW_REQUIRED", "원고는 육군 부사관으로서 감봉 징계처분을 받았습니다.",
     "징계처분을 받은 부사관은 항고 절차를 거치지 않아도 곧바로 소송을 제기할 수 있습니다.",
     "징계처분을 받은 부사관이 항고 절차를 거치지 않아도 된다고 볼 수 없습니다.",
     "원고는 부사관이 항고 절차를 거치지 않아도 된다고 주장하나, 군인사법은 전심절차를 요구합니다."),
    ("ADMIN.DEADLINE_EXCEPTION", "",
     "영업정지처분이 위법한 이상 제소기간은 적용되지 않습니다.",
     "영업정지처분이 위법하다고 하여 제소기간이 적용되지 않는다고 할 수 없습니다.",
     "원고는 제소기간이 적용되지 않는다고 주장하나, 행정소송법은 그런 예외를 두지 않습니다."),
    ("ADMIN.NULLITY_ALWAYS", "",
     "절차상 하자는 언제나 당연무효 사유가 됩니다.",
     "절차상 하자가 언제나 당연무효 사유가 되는 것은 아닙니다.",
     "원고는 절차상 하자가 언제나 당연무효라고 주장하나, 하자는 중대하고 명백하여야 합니다."),
    ("DISC.CRIMINAL_PENDING_BAR", "",
     "수사 중인 교사에 대하여는 징계할 수 없습니다.",
     "수사 중인 교사에 대하여 징계할 수 없는 것은 아닙니다.",
     "원고는 수사 중에는 징계할 수 없다고 주장하나, 법은 징계절차를 진행하지 아니할 수 있다고 정할 뿐입니다."),
    ("CRIM.RESTITUTION_AS_ELEMENT", "피고인은 거래처를 속여 대금을 받은 사기 공소사실로 기소되었습니다.",
     "피고인은 피해액을 모두 변제하였으므로 사기죄가 성립하지 않습니다.",
     "피고인이 피해액을 모두 변제하였으므로 사기죄가 성립하지 않는다고 할 수는 없습니다.",
     "변호인은 피고인이 피해액을 변제하였으므로 사기죄가 성립하지 않는다고 주장하나, 변제는 양형 사유일 뿐입니다."),
    ("CRIM.REFORMATIO_IN_PEIUS_SCOPE", "피고인에 대한 상해 공소사실의 항소심입니다.",
     "검사만 항소한 이 사건에서 항소심은 원심보다 무거운 형을 선고할 수 없습니다.",
     "검사만 항소한 사건에서 항소심이 원심보다 무거운 형을 선고할 수 없는 것은 아닙니다.",
     "피고인은 검사만 항소한 이 사건에서 무거운 형을 선고할 수 없다고 주장하나, 그 원칙은 피고인이 항소한 사건에 적용됩니다."),
    ("GEN.UNSUPPORTED_GENERALIZATION", "",
     "법원은 하도급대금 분쟁에서 예외 없이 수급사업자의 청구를 인용해 왔다.",
     "법원이 하도급대금 분쟁에서 예외 없이 수급사업자의 청구를 인용해 왔다고 할 수는 없다.",
     "피고는 법원이 하도급대금 분쟁에서 예외 없이 수급사업자의 청구를 인용해 왔다고 주장하나, 근거 판례가 없다."),
]


@pytest.mark.parametrize("rule, context, affirmative, negative, reported", CASES, ids=[c[0] for c in CASES])
def test_affirmative_claim_is_flagged(rule, context, affirmative, negative, reported):
    assert rule in rule_ids(*(p for p in (context, affirmative) if p))


@pytest.mark.parametrize("rule, context, affirmative, negative, reported", CASES, ids=[c[0] for c in CASES])
def test_negated_claim_is_not_flagged(rule, context, affirmative, negative, reported):
    assert rule not in rule_ids(*(p for p in (context, negative) if p))


@pytest.mark.parametrize("rule, context, affirmative, negative, reported", CASES, ids=[c[0] for c in CASES])
def test_reported_opponent_claim_is_not_flagged(rule, context, affirmative, negative, reported):
    assert rule not in rule_ids(*(p for p in (context, reported) if p))


# --- 판례 전달·가정 ---------------------------------------------------------------------------
def test_accurate_report_of_constitutional_court_holding_is_not_a_claim():
    """헌법재판소가 '헌법 조항은 위헌심사 대상이 아니다'라고 본 것을 옮긴 정확한 서술."""
    sentence = "헌법재판소는 헌법 조항 자체는 위헌심사의 대상이 아니라고 보았습니다(헌법재판소 1995. 12. 28. 95헌바3 결정)."
    assert "CLAIM.UNCONSTITUTIONALITY" not in rule_ids(sentence)


def test_court_report_needs_a_specific_case_to_count_as_reported():
    cited = "대법원은 절차상 하자가 언제나 당연무효라고 판시하였습니다(대법원 2011. 3. 10. 선고 2010두99999 판결)."
    uncited = "대법원은 절차상 하자가 언제나 당연무효라고 판시하였습니다."
    span = (cited.index("언제나"), cited.index("당연무효") + 4)
    assert polarity(cited, span) == REPORTED
    assert polarity(uncited, (uncited.index("언제나"), uncited.index("당연무효") + 4)) == ASSERTED
    assert "ADMIN.NULLITY_ALWAYS" in rule_ids(uncited)  # 판례를 특정하지 않은 전달은 작성자의 주장


def test_conditional_and_double_negative():
    conditional = "설령 제소기간이 적용되지 않는다 하더라도 청구는 기각되어야 합니다."
    start = conditional.index("제소기간")
    assert polarity(conditional, (start, conditional.index("않는다") + 2)) == CONDITIONAL
    double = "제소기간이 적용되지 않는다고 볼 수 없는 것은 아니다."
    assert polarity(double, (0, double.index("않는다") + 2)) == ASSERTED
    negated = "제소기간이 적용되지 않는다고 볼 수 없다."
    assert polarity(negated, (0, negated.index("않는다") + 2)) == NEGATED


def test_unsourced_standard_is_flagged_whatever_the_content_polarity():
    assert "CLAIM.UNSOURCED_STANDARD" in rule_ids("업계 기준표에 따르면 이 사건 수리비는 과다하지 않습니다.")
    assert "CLAIM.UNSOURCED_STANDARD" not in rule_ids(
        "피고는 업계 기준표에 따라 수리비가 과다하다고 주장하나, 그 기준표의 출처가 없습니다.")
