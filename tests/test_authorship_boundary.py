"""Astra 재검토 보고서 [P0] AI 판정 과대해석 및 서식/인용 오탐 방지 단위 테스트.

1. 일반 문장 대조군 -> UNCERTAIN, objective_traces=0
2. 마크다운 제목 및 굵은 글씨 서식 -> UNCERTAIN, objective_traces=0
3. 고객센터 안내문구 따옴표 인용 -> UNCERTAIN, objective_traces=0
4. 편집 가능한 메타데이터 AI 힌트만 존재 -> UNCERTAIN, objective_traces=0
5. 마크다운 + 메타데이터 AI 힌트 -> UNCERTAIN, objective_traces=0
6. 제외 대상으로 지정된 블록/지시문 -> UNCERTAIN, objective_traces=0
"""
from __future__ import annotations

import pytest
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.verification_engine.ai_document_detector import _rule_based_ai_detection
from packages.verification_engine.ai_residue import scan_residue


def _make_dummy_doc(doc_id: str, text: str) -> NormalizedDocument:
    """단위 테스트용 더미 문서를 생성한다."""
    block = Block(
        block_id=f"{doc_id}_b1",
        text=text,
        page=1,
    )
    page = Page(page_number=1, blocks=[block])
    return NormalizedDocument(
        document_id=doc_id,
        filename=f"{doc_id}.pdf",
        mime_type="application/pdf",
        sha256="dummy_sha256",
        pages=[page],
        raw_layers={"rendered_text": text, "raw_text": text},
    )


def test_clean_control_document():
    """1. 일반 문장 대조군: 객관적 흔적 없음(UNCERTAIN, traces=0)."""
    text = (
        "원고는 피고 회사의 부당한 해고 처분에 대하여 노동위원회에 구제신청을 제기하였습니다. "
        "피고 회사는 정당한 이유 없이 근로자를 해고하였으므로 이는 무효입니다. "
        "원고의 청구를 인용하여 주시기 바랍니다."
    )
    doc = _make_dummy_doc("clean_doc", text)
    res = _rule_based_ai_detection(doc, [], metadata_indications=False)

    assert res.verdict == "UNCERTAIN"
    assert res.signals.get("objective_traces", 0) == 0


def test_markdown_formatting_does_not_trigger_ai_verdict():
    """2. 마크다운 서식(제목, 굵은 글씨): 단순 서식만으로 AI_PARTIAL_GENERATION이 되지 않아야 함."""
    text = (
        "# 1. 사건의 개요\n\n"
        "원고는 피고 회사의 **부당해고 처분**에 대하여 본 소송을 제기합니다. "
        "피고는 **근로기준법 제27조**를 위반하여 서면 통지를 하지 않았습니다. "
        "따라서 피고의 해고 처분은 무효입니다."
    )
    doc = _make_dummy_doc("markdown_doc", text)
    res = _rule_based_ai_detection(doc, [], metadata_indications=False)

    assert res.verdict == "UNCERTAIN"
    assert res.signals.get("objective_traces", 0) == 0


def test_quoted_chatbot_text_is_not_treated_as_author_residue():
    """3. 고객센터 안내문구 따옴표 인용: 인용된 챗봇 문구는 작성자의 작성 흔적으로 오탐되지 않아야 함."""
    text = (
        '피고 회사의 고객센터 챗봇은 "물론입니다! 무엇이든 작성해 드리겠습니다. 추가 질문이 있으시면 알려주세요!"라고 '
        '기계적으로 응답하였을 뿐, 실질적인 사실 확인을 거치지 않았습니다. '
        '따라서 피고의 주장은 이유 없습니다.'
    )
    doc = _make_dummy_doc("quote_doc", text)
    res = _rule_based_ai_detection(doc, [], metadata_indications=False)

    assert res.verdict == "UNCERTAIN"
    assert res.signals.get("objective_traces", 0) == 0


def test_metadata_ai_hint_alone_does_not_cause_ai_verdict():
    """4. 편집 가능한 메타데이터 AI 힌트 단독: 본문 객관적 흔적 없이 AI 확정 판정으로 승격되지 않아야 함."""
    text = (
        "원고는 2021. 3. 4. 피고 회사에 입사하여 성실히 근무하였습니다. "
        "피고는 경영상 어려움을 이유로 일방적 해고 통보를 하였습니다. "
        "이는 정당한 이유가 없는 부당해고입니다."
    )
    doc = _make_dummy_doc("meta_hint_doc", text)
    res = _rule_based_ai_detection(doc, [], metadata_indications=True)

    assert res.verdict == "UNCERTAIN"
    assert res.signals.get("objective_traces", 0) == 0


def test_markdown_plus_metadata_hint_does_not_escalate_to_full_ai():
    """5. 마크다운 서식 + 메타데이터 힌트: 본문 객관적 흔적(objective_traces=0)이 없으면 AI_FULL로 치솟지 않아야 함."""
    text = (
        "## 제1항 청구취지\n\n"
        "피고는 원고에게 **금 50,000,000원** 및 이에 대한 지연손해금을 지급하라. "
        "소송비용은 피고가 부담한다라는 판결을 구합니다."
    )
    doc = _make_dummy_doc("markdown_meta_doc", text)
    res = _rule_based_ai_detection(doc, [], metadata_indications=True)

    assert res.verdict == "UNCERTAIN"
    assert res.signals.get("objective_traces", 0) == 0


def test_excluded_instructions_are_filtered_from_residue_scan():
    """6. 제외 대상으로 지정된 프롬프트 지시문: 잔재 스캔에서 완전히 제외되어야 함."""
    injection = "물론입니다! 요청하신 법률 서면을 정리해 드리겠습니다."
    text = (
        f"{injection}\n"
        "원고는 피고 회사를 상대로 해고무효확인의 소를 제기합니다. "
        "원고의 청구를 인용하여 주시기 바랍니다."
    )
    doc = _make_dummy_doc("excluded_doc", text)
    # 지시문을 제외 목록에 전달
    res = _rule_based_ai_detection(doc, [], metadata_indications=False, exclude_texts=[injection])

    assert res.verdict == "UNCERTAIN"
    assert res.signals.get("objective_traces", 0) == 0


def test_genuine_ai_residue_is_properly_detected():
    """7. 실제 본문에 남은 객관적 챗봇 잔재: 정상적으로 AI_FULL_GENERATION_LIKELY 탐지."""
    genuine_ai_text = (
        "물론입니다! 변호사님께서 요청하신 답변서를 작성해 드리겠습니다.\n"
        "피고는 원고의 청구를 전부 부인합니다.\n"
        "본 서면은 AI 언어 모델로서 학습 데이터 기준으로 작성되었으며 법률 자문을 대체하지 않습니다. "
        "추가적인 질문이 있으시면 언제든지 말씀해 주십시오!"
    )
    doc = _make_dummy_doc("genuine_ai_doc", genuine_ai_text)
    res = _rule_based_ai_detection(doc, [], metadata_indications=False)

    assert res.verdict in ("AI_FULL_GENERATION_LIKELY", "AI_PARTIAL_GENERATION")
    assert res.signals.get("objective_traces", 0) >= 2
