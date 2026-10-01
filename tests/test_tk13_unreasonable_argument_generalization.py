"""TK-13 무리한 주장(위법성조각·비용상환·헌법상 기본권 원용) 구조 일반화 단위 테스트.

양성 예시 5건 이상, 대조군 3건 이상으로 다양한 문장 구조와 조문 원용에서의 탐지 및 오탐 방지를 검증한다.
사건 고유 리터럴(사건번호, 특정 당사자명, 구체적 일자)을 포함하지 않는다.
"""

import pytest
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import review_legal_rules


def _make_doc(body_text: str) -> NormalizedDocument:
    """테스트용 가상 정규화 문서를 생성한다."""
    # 3. 본안에 관한 주장 섹션으로 인식되도록 헤딩 포함
    full_text = f"3. 본안에 관한 주장\n\n{body_text}"
    block = Block(
        block_id="b1",
        text=full_text,
        page=1,
        source_layer="visible_text",
        visible=True,
    )
    page = Page(page_number=1, width=595.0, height=842.0, blocks=[block])
    return NormalizedDocument(
        document_id="doc_test_unreasonable_arg",
        filename="virtual_test_brief.txt",
        mime_type="text/plain",
        sha256="test_sha256",
        pages=[page],
    )


# ---------------------------------------------------------
# 양성 예시 (5건 이상)
# ---------------------------------------------------------
# 1. 정당행위 어미 변형 (형법 제20조 원용 및 징계 불가 단정)
# 2. 사회상규 원용 (위법성 조각되어 징계 대상 아님 단정)
# 3. 긴급피난 원용 (형법 제22조 원용 및 위법성 조각 단정)
# 4. 정당방위 원용 (형법 제21조 원용 및 어떤 책임도 질 수 없음 단정)
# 5. 민법 제203조 비용상환 법리 원용 (공금 비위에 대해 위법성 조각 주장)
# 6. 헌법상 기본권·신의칙 원용 (계약상 지체상금 청구의 전면 무효 주장)
POSITIVE_CASES = [
    (
        "정당행위_어미_변형",
        "이는 형법 제20조가 정한 정당행위로서 위법성이 없으므로 징계할 수 없다.",
        "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS",
    ),
    (
        "사회상규_원용_징계배제",
        "당해 행위는 사회상규에 위배되지 않는 행위이므로 위법성이 조각되어 징계 대상이 아니다.",
        "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS",
    ),
    (
        "긴급피난_원용_위법성조각",
        "당사자는 급박한 상황에서 불가피하게 조치한 것이므로 형법 제22조의 긴급피난에 해당하여 위법성이 조각된다.",
        "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS",
    ),
    (
        "정당방위_원용_책임부인",
        "이는 형법 제21조의 정당방위에 해당하여 위법성이 조각되므로 어떤 책임도 질 수 없다.",
        "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS",
    ),
    (
        "비용상환_법리_징계면책",
        "부서 복지비 지출은 민법 제203조에 따른 비용상환 법리가 적용되어 위법성이 조각되므로 징계책임이 없다.",
        "CIVIL.EXPENSE_REIMBURSEMENT_DISCIPLINARY_DEFENSE",
    ),
    (
        "헌법상_기본권_지체상금_무효",
        "중소 협력업체에 거액의 지체상금을 부과하는 것은 헌법 제119조의 경제민주화 및 헌법 제34조에 규정된 근로자들의 생존권을 침해하는 것으로서 무효이다.",
        "CONST.ECONOMIC_DEMOCRACY_CONTRACT_NULLIFICATION",
    ),
]


# ---------------------------------------------------------
# 대조군 (3건 이상: 정상 변론 및 요건 구비 소명)
# ---------------------------------------------------------
# 1. 정당행위 5대 요건(동기, 수단, 법익균형, 긴급성, 보충성)을 모두 갖추어 소명하는 정상 변론
# 2. 판례 인용 후 해당 요건을 충족하지 못함을 자인/다투지 않는 문장
# 3. 민법상 손해배상액 예정에 대한 구체적 감액 청구 변론 (unless에 걸려 무리한 주장 아님)
CONTROL_CASES = [
    (
        "정당행위_5대요건_모두_소명",
        "행위가 정당행위로 인정되려면 동기의 정당성, 수단의 상당성, 법익균형성, 긴급성, 보충성의 요건을 모두 갖추어야 한다. 피청구인은 위 요건을 다음과 같이 소명한다.",
    ),
    (
        "판례요건_설명_및_불해당_자인",
        "정당행위가 성립하려면 위 다섯 가지 요건을 모두 갖추어야 한다(대법원 판례 참조). 본 사건의 행위는 이에 해당하지 않으므로 징계사유 자체는 다투지 않는다.",
    ),
    (
        "지체상금_구체적_감액_소명",
        "지체상금이 부당하게 과다한 경우 민법 제398조 제2항에 따라 법원은 적당히 감액할 수 있으므로, 당사자의 귀책 정도와 실제 손해액에 비추어 감액되어야 한다.",
    ),
]


@pytest.mark.parametrize("case_id, body_text, expected_rule_id", POSITIVE_CASES)
def test_unreasonable_argument_positive_detection(case_id: str, body_text: str, expected_rule_id: str):
    """양성 예시에서 해당 무리한 주장 규칙이 정상적으로 탐지되는지 검증한다."""
    doc = _make_doc(body_text)
    findings = review_legal_rules(doc)
    matched_rules = {
        f.confidence_features.get("rule_id")
        for f in findings
        if f.confidence_features and "rule_id" in f.confidence_features
    }
    assert expected_rule_id in matched_rules, (
        f"[{case_id}] 규칙 '{expected_rule_id}'이(가) 탐지되지 않았습니다. (탐지된 규칙들: {matched_rules})"
    )


@pytest.mark.parametrize("case_id, body_text", CONTROL_CASES)
def test_unreasonable_argument_control_no_false_positive(case_id: str, body_text: str):
    """대조군(요건 소명, 판례 인용 불해당 자인, 합법적 감액 변론)에서 오탐이 발생하지 않는지 검증한다."""
    doc = _make_doc(body_text)
    findings = review_legal_rules(doc)
    target_rule_ids = {
        "CRIM.JUSTIFIABLE_ACT_PARTIAL_REQUIREMENTS",
        "CIVIL.EXPENSE_REIMBURSEMENT_DISCIPLINARY_DEFENSE",
        "CONST.ECONOMIC_DEMOCRACY_CONTRACT_NULLIFICATION",
    }
    matched_targets = [
        f.confidence_features.get("rule_id")
        for f in findings
        if f.confidence_features and f.confidence_features.get("rule_id") in target_rule_ids
    ]
    assert not matched_targets, (
        f"[{case_id}] 대조군에서 오탐이 발생했습니다: {matched_targets}"
    )
