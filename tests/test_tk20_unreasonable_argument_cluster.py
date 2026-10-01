"""TK-20 3절: 무리한 법리 주장(4단 구조 규칙) 일반화 단위 시험.

기초 사실 인정/가정 -> 3대 법리 군집(헌법 기본권, 민법 일반원칙, 위법성조각사유) 원용 ->
구체적 요건 및 판례 논증 없는 범주적 무효·면책 단정 구조를 탐지하는
GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS 규칙의 양성 및 대조군 검증.
"""
from __future__ import annotations

import pytest
from packages.common.schemas import Block, NormalizedDocument, Page, new_id
from packages.legal_engine.legal_rules import review_legal_rules


def _make_doc(text: str) -> NormalizedDocument:
    """테스트용 단일 문장 정규화 문서를 생성한다."""
    doc = NormalizedDocument(
        document_id="doc_cluster_test",
        filename="cluster_test.txt",
        mime_type="text/plain",
        sha256="0" * 64,
    )
    page = Page(page_number=1)
    page.blocks.append(Block(block_id=new_id("B"), text=text, page=1))
    doc.pages.append(page)
    doc.raw_layers["raw_text"] = text
    return doc


# 양성 예시 5건: 3대 법리군과 가정-범주적 결론 구조가 결합된 과대 주장
POSITIVE_CASES = [
    # 양성 1: 헌법 제23조 재산권 + 사정변경 원칙 -> 당연무효 및 제재 불허
    (
        "설령 위반 사실이 인정되더라도, 헌법 제23조의 재산권 보장과 사정변경의 원칙에 따라 영업정지는 당연히 무효이고 어떠한 제재도 허용될 수 없다.",
        "헌법 제23조 및 사정변경 원칙을 통한 당연무효 단정",
    ),
    # 양성 2: 헌법 제119조 경제민주화 + 신의성실 원칙 -> 법리상 허용 불가
    (
        "가사 채무불이행 책임이 문제된다 하더라도, 헌법 제119조의 경제민주화 조항과 신의성실의 원칙에 비추어 볼 때 배상 청구는 법리상 허용될 수 없다.",
        "헌법 제119조 및 신의칙을 통한 청구 배척 단정",
    ),
    # 양성 3: 헌법 제34조 생존권 + 권리남용금지 원칙 -> 전면 면책
    (
        "백보 양보하여 납품 지연 사실이 인정되더라도, 헌법 제34조의 생존권 보장과 권리남용금지 원칙에 따라 피고의 책임은 전면 면책되어야 마땅하다.",
        "헌법 제34조 생존권 및 권리남용을 통한 전면 면책 단정",
    ),
    # 양성 4: 민법상 비용상환청구권 + 정당행위 -> 위법성 조각 및 징계책임 성립 불가
    (
        "가령 회계 처리상 하자가 있다 하더라도, 민법상 비용상환청구권 법리 및 정당행위 법리에 따라 위법성이 조각되어 어떠한 징계책임도 성립할 수 없다.",
        "비용상환청구권 및 정당행위를 통한 위법성 조각 단정",
    ),
    # 양성 5: 민법상 사무관리 + 불가항력 -> 당연무효
    (
        "설령 승인 없는 예산 집행 사실이 인정되더라도, 민법상 사무관리 법리와 불가항력 원칙에 의하여 원고의 환수 처분은 당연히 무효이다.",
        "사무관리 및 불가항력을 통한 당연무효 단정",
    ),
]

# 대조군 3건: 정상적 판례 인용, 단순 사실 부인, 상대방 주장 배척
NEGATIVE_CASES = [
    # 대조군 1: 대법원 판례 및 구체적 성립 요건을 적시한 정상적인 법률상 항변
    (
        "대법원 판례에 따르면 사정변경으로 인한 계약 해제는 당사자의 책임 없는 사유로 현저한 변경이 발생한 경우에 인정되는바, 본 사안은 이에 해당하여 적법하다.",
        "판례 요건을 갖춘 정상적 사정변경 항변",
    ),
    # 대조군 2: 단순 사실관계 부인 및 증거 불충분 항변
    (
        "피고는 원고가 주장하는 위반 행위를 한 사실이 전혀 없으며, 원고가 제출한 증거만으로는 이를 인정하기 부족하므로 청구는 기각되어야 한다.",
        "단순 사실관계 부인",
    ),
    # 대조군 3: 상대방의 무리한 주장을 배척하는 문맥 (반박/부정)
    (
        "설령 원고가 헌법상 재산권 침해를 주장한다 하더라도, 공공복리를 위한 적법한 제한이므로 당연무효라는 원고의 주장은 이유 없다.",
        "상대방 주장을 배척하는 반박 문맥",
    ),
]


@pytest.mark.parametrize("text, desc", POSITIVE_CASES)
def test_unreasonable_argument_cluster_positives(text: str, desc: str):
    """양성 예시 5건: 4단 구조의 무리한 법리 주장이 OVERCLAIM 또는 LEGAL_ARGUMENT_INVALID로 탐지되어야 한다."""
    doc = _make_doc(text)
    findings = review_legal_rules(doc)
    matched = [
        f for f in findings
        if f.confidence_features.get("rule_id") == "GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS"
        or "무리한 주장" in f.title or "법리 검토" in f.title
    ]
    assert len(matched) >= 1, f"탐지 실패: {desc} (text: {text})"


@pytest.mark.parametrize("text, desc", NEGATIVE_CASES)
def test_unreasonable_argument_cluster_negatives(text: str, desc: str):
    """대조군 3건: 정상 논증, 사실 부인, 상대방 주장 배척 문장은 오탐되지 않아야 한다."""
    doc = _make_doc(text)
    findings = review_legal_rules(doc)
    overclaims = [
        f for f in findings
        if f.confidence_features.get("rule_id") == "GEN.DEFENSE_OVERCLAIM_WITHOUT_REQUIREMENTS"
    ]
    assert len(overclaims) == 0, f"오탐 발생: {desc} (findings: {overclaims})"
