"""청구 구조 확장: 민사 청구취지의 행정·징계 처분 요구, 요건을 생략한 책임 단정, 행정 결정의 민사 기속 주장.

모든 문장은 시험용으로 새로 지었다(특정 평가 문서의 당사자·금액·문구를 쓰지 않는다).
"""
import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import review_legal_rules


def pleading(relief, body):
    texts = ["소 장", "청 구 취 지", *relief, "청 구 원 인", *body]
    return NormalizedDocument("d", "d.pdf", "application/pdf", "0",
                              pages=[Page(1, blocks=[Block(f"b{i}", t, 1) for i, t in enumerate(texts)])])


def rules(relief, body=("원고는 다음과 같이 주장합니다.",)):
    return [f.confidence_features["rule_id"] for f in review_legal_rules(pleading(relief, body))]


MONEY = "1. 피고는 원고에게 금 5,000,000원을 지급하라."


# --- 민사 청구취지의 행정·징계 처분 요구 -------------------------------------------------------------------
@pytest.mark.parametrize("item", [
    "2. 피고 학교법인은 피고 2를 즉시 퇴학시키고 원고에게 사과하라.",
    "2. 피고 회사는 피고 3을 해임하라.",
    "2. 피고 교육청은 위원회의 조치 내용을 원고가 요구하는 대로 변경하라.",
    "2. 피고 협회는 원고에 대한 제명 결정을 철회하라.",
])
def test_civil_relief_demanding_dispositions_is_flagged(item):
    assert "CIV.RELIEF_ADMIN_DISPOSITION" in rules([MONEY, item])


@pytest.mark.parametrize("relief", [
    [MONEY, "2. 소송비용은 피고가 부담한다."],
    ["1. 피고가 원고에게 한 해임은 무효임을 확인한다.", "2. 피고는 원고에게 임금 3,000,000원을 지급하라."],
    ["1. 피고는 원고에게 위자료 10,000,000원을 지급하라.", "2. 제1항은 가집행할 수 있다."],
])
def test_ordinary_civil_relief_is_not_flagged(relief):
    assert "CIV.RELIEF_ADMIN_DISPOSITION" not in rules(relief)


def test_administrative_suit_is_left_to_admin_rules():
    relief = ["1. 피고가 2026. 1. 5. 원고에게 한 정직처분을 취소한다.", "2. 소송비용은 피고가 부담한다."]
    assert "CIV.RELIEF_ADMIN_DISPOSITION" not in rules(relief)


# --- 요건·단서를 생략한 무조건적 책임 단정 --------------------------------------------------------------
@pytest.mark.parametrize("sentence", [
    "피고 2는 감독자로서 아무런 과실이 없어도 언제나 손해 전액을 배상할 책임이 있습니다.",
    "피고 회사는 과실 여부와 무관하게 사용자로서 모든 손해를 배상하여야 한다.",
    "보호자는 자녀의 행위에 대하여 예외 없이 책임을 부담한다.",
    "피고는 별도의 요건이나 입증 없이 위자료 전액을 지급할 책임이 있다.",
])
def test_liability_without_requirements_is_flagged(sentence):
    assert "GEN.LIABILITY_REQUIREMENTS_OMITTED" in rules([MONEY], [sentence])


@pytest.mark.parametrize("sentence", [
    "피고는 과실 여부와 무관하게 책임이 있다고 주장하나, 이는 받아들일 수 없습니다.",
    "피고 2는 감독의무를 게을리하지 아니한 때에는 책임을 면합니다.",
    "제조업자의 무과실책임을 규정한 법률에 따라 피고는 결함으로 인한 손해를 배상하여야 한다.",
    "책임의 범위는 과실, 손해, 인과관계가 모두 증명되어야 정해집니다.",
])
def test_conditional_or_rejected_liability_is_not_flagged(sentence):
    assert "GEN.LIABILITY_REQUIREMENTS_OMITTED" not in rules([MONEY], [sentence])


# --- 행정·심의 결정이 민사 책임을 확정한다는 주장 ---------------------------------------------------------
@pytest.mark.parametrize("sentence", [
    "위 심의위원회의 결정은 민사법원을 전부 구속하므로 피고의 책임은 이미 정해졌습니다.",
    "교육청의 조치 결과에 따라 배상액은 별도 입증 없이 자동으로 인정되어야 한다.",
    "징계위원회의 의결은 법원을 기속하여 손해배상 책임을 확정한다.",
])
def test_admin_decision_binding_civil_court_is_flagged(sentence):
    assert "GEN.ADMIN_DECISION_BINDS_CIVIL" in rules([MONEY], [sentence])


@pytest.mark.parametrize("sentence", [
    "다만 위 행정상 조치의 존재만으로 민사상 배상 책임의 범위가 모두 확정되는 것은 아닙니다.",
    "심의위원회의 결정은 참고 자료일 뿐 법원을 구속하지 않습니다.",
    "피고는 위원회 결정이 법원을 구속한다고 주장하지만 이유 없습니다.",
])
def test_denied_or_limited_binding_is_not_flagged(sentence):
    assert "GEN.ADMIN_DECISION_BINDS_CIVIL" not in rules([MONEY], [sentence])
