"""ACASia_LAW 0.9.11 신규 법리 규칙 3종 단위 테스트.

규칙 대상:
1. CIV.RELIEF_CRIMINAL_SANCTION: 민사 청구취지에서 형사 제재(벌금, 형벌, 가집행)를 구하는 주장
2. CIV.CONTRACT_BREACH_MENTAL_DISTRESS: 계약위반(채무불이행)만으로 위자료가 당연히 발생·인정된다는 주장
3. CIV.UNSUPPORTED_BURDEN_OF_PROOF_SHIFT: 법률상 근거 없는 입증책임 전환·전가 주장

각 규칙별 합성 테스트 3건 + 반례 테스트 3건(총 18건)을 검증한다.
모든 시험 문장은 평가 문서와 무관하게 새로 지은 문장이다.
"""
from __future__ import annotations

import pytest

from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import review_legal_rules


def _make_doc(relief, body):
    """청구취지와 청구원인을 포함하는 정규화 문서 생성 헬퍼 함수."""
    texts = ["소 장", "청 구 취 지", *relief, "청 구 원 인", *body]
    return NormalizedDocument(
        document_id="doc_v0911_test",
        filename="doc_v0911_test.pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        pages=[Page(page_number=1, blocks=[Block(f"b_{i}", t, 1) for i, t in enumerate(texts)])]
    )


def _rule_ids(relief, body=("원고는 다음과 같이 청구원인을 진술합니다.",)):
    """문서 검토 결과에서 검출된 rule_id 목록 반환."""
    return [f.confidence_features["rule_id"] for f in review_legal_rules(_make_doc(relief, body))]


MONEY_CLAIM = "1. 피고는 원고에게 금 10,000,000원을 지급하라."


# ==============================================================================
# 1. CIV.RELIEF_CRIMINAL_SANCTION (민사 청구에서 형사 제재/가집행을 구함)
# ==============================================================================

@pytest.mark.parametrize("item", [
    # 합성 1: 청구취지에서 징역형 선고를 구함
    "2. 피고를 징역 1년에 처한다.",
    # 합성 2: 청구취지에서 벌금형 부과를 구함
    "2. 피고에게 벌금 5,000,000원을 부과하라.",
    # 합성 3: 벌금형에 대한 가집행 선고를 구함
    "2. 제1항의 벌금에 대하여는 가집행할 수 있다.",
])
def test_civil_relief_criminal_sanction_flagged(item):
    """민사 청구취지에서 벌금·징역 등 형사 제재나 그 가집행을 구하면 탐지되어야 한다."""
    flagged = _rule_ids([MONEY_CLAIM, item])
    assert "CIV.RELIEF_CRIMINAL_SANCTION" in flagged


@pytest.mark.parametrize("relief", [
    # 반례 1: 통상적인 금전 채권 판결에 대한 가집행선고
    [MONEY_CLAIM, "2. 제1항은 가집행할 수 있다."],
    # 반례 2: 소송비용 부담 청구
    [MONEY_CLAIM, "2. 소송비용은 피고가 부담한다."],
    # 반례 3: 배상명령 사건 청구
    ["1. 피고는 배상명령에 따라 원고에게 금 10,000,000원을 지급하라.", "2. 소송비용은 피고의 부담으로 한다."],
])
def test_civil_relief_criminal_sanction_benign(relief):
    """정상적인 민사 청구취지나 적법한 가집행 신청은 오탐되지 않아야 한다."""
    flagged = _rule_ids(relief)
    assert "CIV.RELIEF_CRIMINAL_SANCTION" not in flagged


# ==============================================================================
# 2. CIV.CONTRACT_BREACH_MENTAL_DISTRESS (채무불이행만으로 위자료 당연 발생 주장)
# ==============================================================================

@pytest.mark.parametrize("sentence", [
    # 합성 1: 계약 위반 사실만으로 당연히 위자료 청구권 발생 주장
    "피고의 계약 위반 사실만으로도 원고에게 당연히 위자료 청구권이 발생합니다.",
    # 합성 2: 납기 지연으로 별도 입증 없이 정신적 고통 위자료 인정 주장
    "납기 지연이 발생하였으므로 별도의 입증 없이 정신적 고통에 대한 위자료가 인정되어야 합니다.",
    # 합성 3: 채무불이행 자체로 별도 사정 없이 정신적 손해배상 청구 주장
    "채무불이행 자체로도 별도의 사정 없이 정신적 손해배상이 지급되어야 합니다.",
])
def test_contract_breach_mental_distress_flagged(sentence):
    """계약위반(채무불이행)만으로 위자료가 당연 인정된다는 주장은 탐지되어야 한다."""
    flagged = _rule_ids([MONEY_CLAIM], [sentence])
    assert "CIV.CONTRACT_BREACH_MENTAL_DISTRESS" in flagged


@pytest.mark.parametrize("sentence", [
    # 반례 1: 특별한 사정 및 예견가능성을 요건으로 주장하는 적법한 주장
    "피고의 채무불이행으로 특별한 사정으로 인한 정신적 고통이 발생하였고, 피고도 이를 알았거나 알 수 있었으므로 배상책임이 있습니다.",
    # 반례 2: 불법행위에 기한 위자료 청구 주장
    "피고의 고의적인 불법행위로 인하여 원고가 입은 정신적 고통에 대하여 위자료를 청구합니다.",
    # 반례 3: 계약 위반에 따른 통상 손해(재산적 손해) 배상 청구
    "피고의 계약 불이행으로 인하여 원고에게 발생한 통상의 재산적 손해 1,000만 원의 배상을 구합니다.",
])
def test_contract_breach_mental_distress_benign(sentence):
    """특별손해 요건(특별한 사정·알았거나 알 수 있었음)을 갖춘 주장이나 불법행위 위자료 청구는 오탐되지 않아야 한다."""
    flagged = _rule_ids([MONEY_CLAIM], [sentence])
    assert "CIV.CONTRACT_BREACH_MENTAL_DISTRESS" not in flagged


# ==============================================================================
# 3. CIV.UNSUPPORTED_BURDEN_OF_PROOF_SHIFT (근거 없는 입증책임 전환 주장)
# ==============================================================================

@pytest.mark.parametrize("sentence", [
    # 합성 1: 입증책임이 피고에게 전환되어 무과실을 증명하지 못하면 책임진다는 주장
    "입증책임이 피고에게 전환되므로 피고가 스스로 무과실을 증명하지 못하는 한 배상책임을 집니다.",
    # 합성 2: 피고가 책임 없음을 입증하지 못하면 청구 인정 주장
    "피고가 스스로 자신에게 책임이 없음을 입증하지 못하는 한 원고의 청구는 인정되어야 합니다.",
    # 합성 3: 법률상 근거 없이 입증책임이 피고에게 전환된다는 단정
    "법률상 근거 없이 당연히 입증책임이 피고에게 전환되어야 합니다.",
])
def test_unsupported_burden_of_proof_shift_flagged(sentence):
    """법률상 근거 없이 상대방에게 입증책임을 일방적으로 전가하는 주장은 탐지되어야 한다."""
    flagged = _rule_ids([MONEY_CLAIM], [sentence])
    assert "CIV.UNSUPPORTED_BURDEN_OF_PROOF_SHIFT" in flagged


@pytest.mark.parametrize("sentence", [
    # 반례 1: 제조물책임법 등 법률상 결함 추정 규정에 기한 주장
    "제조물 책임법 제3조의2에 따라 결함이 추정되므로 피고가 면책사유를 입증하여야 합니다.",
    # 반례 2: 원고가 자신의 입증책임을 다했다는 정상 주장
    "원고는 계약 체결 및 채무불이행의 요건사실에 대한 입증책임을 충분히 다하였습니다.",
    # 반례 3: 상대방의 증명방해 행위에 따른 입증책임 완화 주장
    "피고가 핵심 증거를 은닉하여 고의로 증명방해를 하였으므로 원고의 입증책임이 완화되어야 합니다.",
])
def test_unsupported_burden_of_proof_shift_benign(sentence):
    """법률상 추정 규정(제조물책임법 등)이나 증명방해 법리에 따른 정당한 주장은 오탐되지 않아야 한다."""
    flagged = _rule_ids([MONEY_CLAIM], [sentence])
    assert "CIV.UNSUPPORTED_BURDEN_OF_PROOF_SHIFT" not in flagged
