"""TK-05 무리한 법률 주장(정당행위·사무관리 원용) 탐지 및 대조군 단위 테스트.

- 양성 3건 이상: 정당행위 및 사무관리 원용 무리한 주장(서면7 유형 및 변형)
- 대조군 3건 이상: 요건을 모두 갖춘 정당한 변론, 판례 인용 대조군
"""
import pytest
from packages.common.schemas import NormalizedDocument, Page, Block, new_id
from packages.legal_engine.legal_rules import review_legal_rules


def _make_doc(text: str) -> NormalizedDocument:
    doc = NormalizedDocument(document_id="DOC_TEST", filename="test.pdf", mime_type="application/pdf", sha256="test")
    doc.raw_layers["reading_order_text"] = text
    doc.raw_layers["rendered_text"] = text
    p = Page(page_number=1, blocks=[Block(block_id=new_id("B"), text=text, page=1, source_layer="visible_text")])
    doc.pages = [p]
    return doc


# ==============================================================================
# 1. 양성 테스트: 정당행위 및 사무관리 원용 탐지 (3건 이상)
# ==============================================================================
def test_justifiable_act_subsumption_positive():
    """서면7 문장 틀 및 변형에서 정당행위 요건 일부만으로 위법성 조각 단정 탐지 (양성 2건)."""
    # 양성 1: 서면7 문장 틀 (사회통념상 허용되는 정당행위이므로 위법성이 조각되어)
    text1 = (
        "청구원인\n"
        "피고인의 본 건 행위는 사회통념상 허용되는 정당행위이므로 위법성이 조각되어 형사처벌의 대상이 될 수 없습니다."
    )
    findings1 = review_legal_rules(_make_doc(text1))
    rule_ids1 = [f.confidence_features.get("rule_id") for f in findings1]
    assert "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS" in rule_ids1

    # 양성 2: 다른 문장 틀 (형법 제20조 정당행위로서 위법성이 조각)
    text2 = (
        "청구원인\n"
        "피고인의 조치는 형법 제20조의 정당행위로서 위법성이 조각된다 할 것이므로 무죄가 선고되어야 합니다."
    )
    findings2 = review_legal_rules(_make_doc(text2))
    rule_ids2 = [f.confidence_features.get("rule_id") for f in findings2]
    assert "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS" in rule_ids2


def test_management_of_affairs_defense_positive():
    """공무·예산 집행 또는 비위 사실에 민법 제734조 사무관리 원용 면책 주장 탐지 (양성 2건)."""
    # 양성 3: 민법 제734조 사무관리 법리 원용 위법성 조각
    text3 = (
        "청구원인\n"
        "원고의 예산 집행 행위는 민법 제734조의 사무관리 법리에 해당하여 위법성이 조각되고 징계 사유가 아닙니다."
    )
    findings3 = review_legal_rules(_make_doc(text3))
    rule_ids3 = [f.confidence_features.get("rule_id") for f in findings3]
    assert "CIVIL.MANAGEMENT_OF_AFFAIRS_DISCIPLINARY_DEFENSE" in rule_ids3

    # 양성 4: 사무관리 해당으로 면책·책임 없음 주장
    text4 = (
        "청구원인\n"
        "본 건 사용은 기관을 위한 사무관리에 해당하여 면책되므로 징계책임이 없습니다."
    )
    findings4 = review_legal_rules(_make_doc(text4))
    rule_ids4 = [f.confidence_features.get("rule_id") for f in findings4]
    assert "CIVIL.MANAGEMENT_OF_AFFAIRS_DISCIPLINARY_DEFENSE" in rule_ids4


# ==============================================================================
# 2. 대조군 테스트: 요건을 모두 구비하거나 정당한 인용 (대조군 3건 이상)
# ==============================================================================
def test_unreasonable_argument_negative_controls():
    """요건을 구비하여 주장하거나 부정/배척 문맥인 대조군은 탐지되지 않음 (대조군 3건)."""
    # 대조군 1: 정당행위의 5가지 요건(목적 정당성, 수단 상당성, 법익균형성, 긴급성, 보충성)을 모두 소명한 경우
    text1 = (
        "청구원인\n"
        "피고인의 행위는 목적의 정당성, 수단의 상당성, 법익 균형성, 긴급성 및 다른 수단이 없다는 보충성의 "
        "다섯 가지 요건을 모두 갖추어 형법 제20조의 정당행위에 해당하므로 위법성이 조각됩니다."
    )
    findings1 = review_legal_rules(_make_doc(text1))
    rule_ids1 = [f.confidence_features.get("rule_id") for f in findings1]
    assert "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS" not in rule_ids1

    # 대조군 2: 정당행위 주장을 배척하는 문맥
    text2 = (
        "청구원인\n"
        "피고인은 사회상규상 정당행위이므로 위법성이 조각된다고 주장하나, 피고인의 이러한 주장은 이유 없습니다."
    )
    findings2 = review_legal_rules(_make_doc(text2))
    rule_ids2 = [f.confidence_features.get("rule_id") for f in findings2]
    assert "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS" not in rule_ids2

    # 대조군 3: 민법상 정상적인 사무관리 비용상환청구 민사소송 서면
    text3 = (
        "청구취지\n"
        "피고는 원고에게 금 10,000,000원을 지급하라.\n"
        "청구원인\n"
        "원고는 법률상 의무 없이 본인의 의사에 적합하게 타인의 사무를 관리하였으므로 민법 제739조에 따라 필요비 상환을 구합니다."
    )
    findings3 = review_legal_rules(_make_doc(text3))
    rule_ids3 = [f.confidence_features.get("rule_id") for f in findings3]
    assert "CIVIL.MANAGEMENT_OF_AFFAIRS_DISCIPLINARY_DEFENSE" not in rule_ids3
