"""v5 3-6: 법리 규칙의 표현 변형(능동·수동, 어순, 조사, 번호 머리말, 줄바꿈) 10종씩.

전칭 일반화, 검사 단독 항소의 불이익변경금지 오인, 사후 변제를 범죄 불성립 사유로 주장하는 규칙을 각 10가지 표현으로
시험한다. 두 형사 규칙은 블라인드 v3 결함 유형에서 유래했으므로 블라인드 문장을 쓰지 않고 새로 지은 다른 분야
(사기·횡령·배임·상해·교통) 문장으로 검증한다.
"""
from __future__ import annotations

import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.claim_review import review_claims
from packages.legal_engine.legal_rules import review_legal_rules


def _rule_ids(paragraphs):
    blocks = [Block(block_id=f"b{i}", text=t, page=1, block_type="paragraph") for i, t in enumerate(paragraphs)]
    doc = NormalizedDocument(document_id="d", filename="d.pdf", mime_type="application/pdf", sha256="0",
                             pages=[Page(page_number=1, blocks=blocks)])
    return {f.confidence_features.get("rule_id") for f in review_legal_rules(doc) + review_claims(doc)}


GENERALIZATION = [
    ["어떠한 경우에도 임대인의 소멸시효 주장은 권리남용에 해당합니다."],
    ["임차인이 보증금을 돌려받지 못한 이상, 임대인의 시효 항변은 어떠한 경우라도 허용될 수 없습니다."],
    ["1. 보증금 반환 의무", "보증금 반환 의무는 예외 없이 인정되어야 한다."],
    ["가. 손해배상 책임", "사용자는 언제나 근로자의 손해를 배상할 책임을 진다."],
    ["운송인은 화물이 멸실되면 무조건 전액을 배상하여야 한다."],
    ["모든 경우에 계약 해제는 무효로 보아야 합니다."],
    ["건축주의 하자보수 청구는 어떤 경우에도 거절될 수 없습니다."],
    ["공사대금 지급의무는 예외 없이 소멸하지 않는다."],
    ["보험자는 고지의무 위반이 있더라도 항상 보험금을 지급할 의무가 있습니다."],
    ["3. 위약금의 성격 위약금은 어떠한 경우에도 감액될 수 없습니다."],
]

REFORMATIO = [
    ["피고인에 대한 사기 공소사실의 항소심입니다.", "검사만 항소한 이 사건에서 항소심은 원심보다 무거운 형을 선고할 수 없습니다."],
    ["피고인에 대한 횡령 공소사실의 항소심입니다.", "이 사건은 검사만 항소하였으므로 원심보다 중한 형을 선고하는 것은 금지됩니다."],
    ["피고인에 대한 배임 공소사실의 항소심입니다.", "검사만이 양형부당을 이유로 항소하였으므로 불이익한 형의 선고는 허용되지 않습니다."],
    ["피고인에 대한 상해 공소사실의 항소심입니다.", "항소는 검사만 제기하였으므로 항소심은 피고인에게 더 무거운 형을 선고할 수 없다."],
    ["피고인에 대한 교통사고 공소사실의 항소심입니다.", "검사 측만 항소한 사건이므로 원심 형량보다 무거운 형은 선고될 수 없습니다."],
    ["피고인에 대한 사기 공소사실입니다.", "2. 형의 범위", "검사만 항소한 경우 항소심은 원심판결의 형보다 중한 형을 선고하지 못한다."],
    ["피고인에 대한 횡령 공소사실입니다.", "검사만 항소한 이 사건에는 불이익변경금지 원칙이 적용되어 원심보다 무거운 형을 선고할 수 없습니다."],
    ["피고인에 대한 폭행 공소사실입니다.", "피고인은 항소하지 않았고 검사만 항소하였으므로 형을 무겁게 변경할 수 없습니다."],
    ["피고인에 대한 배임 공소사실입니다.", "검사가 단독으로 항소하였으므로 항소심은 피고인에게 불리하게 형을 변경할 수 없다."],
    ["피고인에 대한 사기 공소사실입니다.", "이 사건 항소는 검사만의 항소이므로 원심보다 무거운 형의 선고는 금지된다."],
]

RESTITUTION = [
    ["피고인은 거래처를 속여 대금을 받은 사기 공소사실로 기소되었습니다.", "피고인은 피해액을 모두 변제하였으므로 사기죄는 성립하지 않습니다."],
    ["피고인은 회사 자금 횡령으로 기소되었습니다.", "피고인이 횡령금 전액을 반환한 이상 횡령죄가 성립할 수 없습니다."],
    ["피고인은 업무상 배임으로 기소되었습니다.", "손해를 모두 배상하였으므로 피고인에게 배임죄가 성립한다고 볼 수 없습니다."],
    ["피고인은 사기 혐의로 기소되었습니다.", "피해 회복이 이루어졌으므로 피고인은 무죄입니다."],
    ["피고인은 절도 공소사실로 기소되었습니다.", "피고인은 훔친 물건을 돌려주었으므로 절도죄가 되지 않습니다."],
    ["피고인은 사기 공소사실로 기소되었습니다.", "3. 범죄의 성립 여부", "피고인이 편취금을 공탁한 이상 사기죄는 성립되지 않는다."],
    ["피고인은 횡령 공소사실로 기소되었습니다.", "피고인은 문제된 금원을 전부 갚았기에 횡령죄는 성립하지 아니합니다."],
    ["피고인은 배임 공소사실로 기소되었습니다.", "피해자에게 손해액을 변제한 이상 배임죄의 구성요건을 충족하지 않습니다."],
    ["피고인은 사기 공소사실로 기소되었습니다.", "변제를 마쳤으므로 피고인의 행위는 범죄가 되지 않습니다."],
    ["피고인은 횡령 공소사실로 기소되었습니다.", "횡령한 돈을 반환하였으니 피고인에게는 죄가 없습니다."],
]


@pytest.mark.parametrize("paragraphs", GENERALIZATION, ids=[f"gen{i}" for i in range(10)])
def test_generalization_variants(paragraphs):
    found = _rule_ids(paragraphs)
    assert {"CLAIM.UNSUPPORTED_GENERALIZATION", "GEN.UNSUPPORTED_GENERALIZATION", "ADMIN.NULLITY_ALWAYS"} & found, paragraphs


@pytest.mark.parametrize("paragraphs", REFORMATIO, ids=[f"reformatio{i}" for i in range(10)])
def test_reformatio_in_peius_variants(paragraphs):
    assert "CRIM.REFORMATIO_IN_PEIUS_SCOPE" in _rule_ids(paragraphs), paragraphs


@pytest.mark.parametrize("paragraphs", RESTITUTION, ids=[f"restitution{i}" for i in range(10)])
def test_restitution_variants(paragraphs):
    assert "CRIM.RESTITUTION_AS_ELEMENT" in _rule_ids(paragraphs), paragraphs


@pytest.mark.parametrize("paragraphs", [
    ["피고인에 대한 사기 공소사실의 항소심입니다.", "피고인만 항소한 이 사건에서 항소심은 원심보다 무거운 형을 선고할 수 없습니다."],
    ["피고인은 사기 공소사실로 기소되었습니다.", "피고인은 피해액을 모두 변제하였으므로 선처를 구합니다."],
    ["피고인은 횡령 공소사실로 기소되었습니다.", "피해자가 처벌을 원하지 않아 공소를 기각하여야 한다는 주장은 반의사불벌죄에 관한 것입니다."],
    ["임대인의 시효 항변은 특별한 사정이 없는 한 허용된다고 보는 것이 일반적입니다."],
])
def test_correct_statements_are_not_flagged(paragraphs):
    found = _rule_ids(paragraphs)
    assert not ({"CRIM.REFORMATIO_IN_PEIUS_SCOPE", "CRIM.RESTITUTION_AS_ELEMENT",
                 "CLAIM.UNSUPPORTED_GENERALIZATION"} & found), (paragraphs, found)
