"""v4 P5: 법리 검토 확장 — 합성 주장 80건(결함 40·정상 40)으로 정밀도·재현율 0.75 이상을 확인한다.

범주(각 결함 10·정상 10)
1. 재량↔의무(DISCRETION_AS_MANDATE·MANDATE_AS_DISCRETION): 가상 조문 본문과 대조
2. 판결 취지 방향 반대(HOLDING_DIRECTION_REVERSED): 가상 판결요지와 대조
3. 절차 규칙(검사만 항소한 사건의 불이익변경금지, 형사소송법 제368조)
4. 양형 사유를 범죄 성립 요건으로 혼동(형법 제51조 범행 후의 정황)
조문·판결요지는 모두 합성이며 실존 법령·판례의 내용을 지어내지 않는다.
"""
from __future__ import annotations

import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import review_legal_rules
from packages.legal_engine.opinion_attribution import summary_direction_conflict
from packages.legal_engine.provision_content import compare_claim_to_provision

# (조문 본문, 결함 주장, 정상 주장) — 행정·민사·형사·가사·노동 분야의 가상 조문
MODALITY = [
    ("행정청은 처분 전에 당사자에게 통지할 수 있다.", "행정청은 처분 전에 반드시 당사자에게 통지하여야 한다.", "행정청은 처분 전에 당사자에게 통지할 수 있다."),
    ("법원은 직권으로 증거조사를 할 수 있다.", "법원은 직권으로 증거조사를 하여야 한다.", "법원은 필요하면 직권으로 증거조사를 할 수 있다."),
    ("가정법원은 양육자를 변경할 수 있다.", "가정법원은 청구가 있으면 양육자를 변경하여야 한다.", "가정법원은 사정 변경이 있으면 양육자를 변경할 수 있다."),
    ("검사는 공소를 취소할 수 있다.", "검사는 피해자가 원하면 공소를 취소하여야 한다.", "검사는 제1심판결 선고 전까지 공소를 취소할 수 있다."),
    ("사용자는 휴업수당을 감액할 수 있다.", "사용자는 휴업수당을 감액하여야 한다.", "사용자는 승인을 받아 휴업수당을 감액할 수 있다."),
    ("행정청은 청문을 실시하여야 한다.", "행정청은 청문을 실시할 수 있을 뿐이다.", "행정청은 처분 전에 청문을 실시하여야 한다."),
    ("사용자는 해고를 서면으로 통지하여야 한다.", "사용자는 해고를 서면으로 통지할 의무가 없다.", "사용자는 해고사유를 서면으로 통지하여야 한다."),
    ("법원은 판결 이유를 기재하여야 한다.", "법원은 판결 이유를 기재할 수 있다.", "법원은 판결서에 이유를 기재하여야 한다."),
    ("임대인은 수선의무를 이행하여야 한다.", "임대인은 수선의무를 이행할 수 있을 뿐이다.", "임대인은 목적물의 수선의무를 이행하여야 한다."),
    ("가정법원은 자녀의 의견을 청취하여야 한다.", "가정법원은 자녀의 의견을 청취할 수 있다.", "가정법원은 양육자를 정할 때 자녀의 의견을 청취하여야 한다."),
]

# (판결요지, 결함 요약, 정상 요약)
HOLDINGS = [
    ("사용자는 근로자의 생명과 신체를 보호할 보호의무를 부담한다.",
     "판결은 사용자가 근로자의 생명과 신체에 대한 보호의무를 부담하지 않는다고 보았다.",
     "판결은 사용자가 근로자의 생명과 신체에 대한 보호의무를 부담한다고 보았다."),
    ("임차인은 임대차 종료 시 목적물을 원상으로 회복하여야 한다.",
     "판결은 임차인이 임대차 종료 시 목적물을 원상으로 회복할 필요가 없다고 판시하였다.",
     "판결은 임차인이 임대차 종료 시 목적물을 원상으로 회복하여야 한다고 판시하였다."),
    ("행정청의 처분 사유 추가는 기본적 사실관계가 동일한 범위에서 허용된다.",
     "판결은 처분 사유 추가가 기본적 사실관계가 동일한 범위에서도 허용되지 않는다고 보았다.",
     "판결은 처분 사유 추가가 기본적 사실관계가 동일한 범위에서 허용된다고 보았다."),
    ("재산분할 대상에는 혼인 중 공동으로 형성한 퇴직급여채권이 포함된다.",
     "판결은 혼인 중 공동으로 형성한 퇴직급여채권이 재산분할 대상에 포함되지 않는다고 판시하였다.",
     "판결은 혼인 중 공동으로 형성한 퇴직급여채권이 재산분할 대상에 포함된다고 판시하였다."),
    ("피고인의 자백이 유일한 증거인 때에는 유죄로 인정할 수 없다.",
     "판결은 피고인의 자백이 유일한 증거인 때에도 유죄로 인정할 수 있다고 보았다.",
     "판결은 피고인의 자백이 유일한 증거인 때에는 유죄로 인정할 수 없다고 보았다."),
    ("운전자는 보행자의 안전을 확인할 주의의무가 있다.",
     "판결은 운전자에게 보행자의 안전을 확인할 주의의무가 없다고 보았다.",
     "판결은 운전자에게 보행자의 안전을 확인할 주의의무가 있다고 보았다."),
    ("공무원의 경과실로 인한 손해에 대하여 공무원 개인은 배상책임을 지지 않는다.",
     "판결은 공무원의 경과실로 인한 손해에 대하여도 공무원 개인이 배상책임을 진다고 판시하였다.",
     "판결은 공무원의 경과실로 인한 손해에 대하여 공무원 개인은 배상책임을 지지 않는다고 판시하였다."),
    ("제조업자는 설계상 결함으로 생긴 손해를 배상할 책임이 있다.",
     "판결은 제조업자가 설계상 결함으로 생긴 손해를 배상할 책임이 없다고 보았다.",
     "판결은 제조업자가 설계상 결함으로 생긴 손해를 배상할 책임이 있다고 보았다."),
    ("부모는 미성년 자녀를 보호하고 교양할 권리의무가 있다.",
     "판결은 부모에게 미성년 자녀를 보호하고 교양할 권리의무가 없다고 보았다.",
     "판결은 부모에게 미성년 자녀를 보호하고 교양할 권리의무가 있다고 보았다."),
    ("징계위원회는 징계혐의자에게 진술 기회를 주어야 한다.",
     "판결은 징계위원회가 징계혐의자에게 진술 기회를 주지 않아도 된다고 판시하였다.",
     "판결은 징계위원회가 징계혐의자에게 진술 기회를 주어야 한다고 판시하였다."),
]

PROCEDURAL_BAD = [
    "검사만 항소한 이 사건에서 항소심은 원심보다 무거운 형을 선고할 수 없다.",
    "검사만이 항소하였으므로 항소심은 원심판결의 형보다 중한 형을 선고하지 못한다.",
    "이 사건은 검사만 항소하였으므로 항소심이 피고인에게 불리한 형을 선고하는 것은 금지된다.",
    "검사만 양형부당을 이유로 항소한 경우에도 항소심은 중한 형을 선고할 수 없다.",
    "검사만 항소한 사건에서도 불이익변경금지 원칙상 무거운 형을 선고할 수 없다.",
    "피고인은 항소하지 않고 검사만 항소하였으나 항소심은 중한 형을 선고하지 못한다.",
    "검사만 사실오인을 이유로 항소한 이 사건에서 원심보다 중한 형은 선고할 수 없다.",
    "검사만 항소하였더라도 항소심은 원심보다 불리한 형을 선고할 수 없다.",
    "검사만 항소한 사건에서 원심의 형보다 무거운 형을 선고하는 것은 금지된다.",
    "검사만 적법하게 항소한 이 사건에서 항소심은 무거운 형을 선고하지 못한다.",
]
PROCEDURAL_OK = [
    "피고인만 항소한 이 사건에서 항소심은 원심보다 무거운 형을 선고할 수 없다.",
    "피고인이 항소한 사건에서는 원심판결의 형보다 중한 형을 선고하지 못한다.",
    "검사만 항소한 사건에서는 항소심이 원심보다 무거운 형을 선고할 수 있다.",
    "검사와 피고인이 모두 항소하였으므로 항소심은 형을 새로 정할 수 있다.",
    "피고인을 위하여 항소한 사건이므로 원심보다 중한 형을 선고할 수 없다.",
    "검사만 항소하였으므로 불이익변경금지 원칙은 적용되지 않는다.",
    "검사는 양형부당을 이유로 항소하였다.",
    "항소심은 검사의 항소이유를 받아들여 원심판결을 파기하였다.",
    "피고인은 원심의 형이 무겁다며 항소하였다.",
    "검사만 항소한 이 사건에서 피고인은 항소하지 않았다.",
]
SENTENCING_BAD = [
    "피고인은 피해액을 전액 변제하였으므로 업무상횡령죄는 성립하지 않는다.",
    "피고인이 편취금을 모두 반환하였으므로 사기죄는 성립하지 않는다.",
    "피고인은 피해자에게 손해를 배상하였으므로 배임죄가 성립할 수 없다.",
    "피고인이 피해 회복을 하였으므로 절도죄는 성립하지 않는다.",
    "피고인은 횡령금을 반환하였으므로 무죄이다.",
    "피고인이 피해금 전액을 공탁하였으므로 범죄는 성립하지 않는다.",
    "피고인은 편취한 돈을 되돌려 변제하였으므로 사기죄가 성립하지 않는다.",
    "피고인은 손해를 모두 배상하였기에 업무상배임죄는 성립하지 않는다.",
    "피고인이 피해자에게 물건을 반환하였으므로 절도죄는 성립되지 않는다.",
    "피고인은 차용금을 변제하였으므로 범행은 무죄이다.",
]
SENTENCING_OK = [
    "피고인은 피해액을 전액 변제하였으므로 이를 양형에 참작하여야 한다.",
    "피고인은 차용 당시 변제할 의사와 능력이 있었으므로 사기죄가 성립하지 않는다.",
    "피해자가 처벌을 원하지 않는다는 의사를 표시하였으므로 공소를 기각하여야 한다.",
    "피고인은 피해 회복을 위해 노력하였으므로 선처를 구한다.",
    "피고인은 피해액을 공탁하였으므로 형을 감경하여 주시기 바란다.",
    "피고인은 기망행위를 하지 않았으므로 사기죄가 성립하지 않는다.",
    "피고인은 편취의 범의가 없었으므로 무죄이다.",
    "피고인은 피해자와 합의하였으므로 집행유예를 선고하여 주시기 바란다.",
    "피고인은 범행 후 피해를 모두 변제하였다.",
    "고소 취소가 있었으므로 공소를 기각하여야 한다.",
]


def _doc(text):
    return NormalizedDocument(document_id="d", filename="d.pdf", mime_type="application/pdf", sha256="0",
                              pages=[Page(page_number=1, blocks=[Block(block_id="b0", text=text, page=1)])])


def modality_flag(body, claim):
    return compare_claim_to_provision(claim, body).get("basis") == "MODALITY"


def holding_flag(summary, claim):
    return summary_direction_conflict(claim, summary) is not None


def rule_flag(rule_id, text):
    return any(f.confidence_features.get("rule_id") == rule_id for f in review_legal_rules(_doc(text)))


def cases():
    bad = ([lambda b=b, c=c: modality_flag(b, c) for b, c, _ in MODALITY]
           + [lambda s=s, c=c: holding_flag(s, c) for s, c, _ in HOLDINGS]
           + [lambda t=t: rule_flag("CRIM.REFORMATIO_IN_PEIUS_SCOPE", t) for t in PROCEDURAL_BAD]
           + [lambda t=t: rule_flag("CRIM.RESTITUTION_AS_ELEMENT", t) for t in SENTENCING_BAD])
    good = ([lambda b=b, c=c: modality_flag(b, c) for b, _, c in MODALITY]
            + [lambda s=s, c=c: holding_flag(s, c) for s, _, c in HOLDINGS]
            + [lambda t=t: rule_flag("CRIM.REFORMATIO_IN_PEIUS_SCOPE", t) for t in PROCEDURAL_OK]
            + [lambda t=t: rule_flag("CRIM.RESTITUTION_AS_ELEMENT", t) for t in SENTENCING_OK])
    return bad, good


def test_set_sizes():
    bad, good = cases()
    assert len(bad) == 40 and len(good) == 40


def test_precision_and_recall_at_least_075():
    bad, good = cases()
    tp = sum(1 for check in bad if check())
    fp = sum(1 for check in good if check())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / len(bad)
    assert precision >= 0.75 and recall >= 0.75, (tp, fp, precision, recall)


@pytest.mark.parametrize("category, flawed, sound", [
    ("modality", [lambda b=b, c=c: modality_flag(b, c) for b, c, _ in MODALITY],
     [lambda b=b, c=c: modality_flag(b, c) for b, _, c in MODALITY]),
    ("holding", [lambda s=s, c=c: holding_flag(s, c) for s, c, _ in HOLDINGS],
     [lambda s=s, c=c: holding_flag(s, c) for s, _, c in HOLDINGS]),
])
def test_each_category_has_recall_and_no_false_positive_majority(category, flawed, sound):
    assert sum(f() for f in flawed) >= 7, category
    assert sum(f() for f in sound) <= 3, category
