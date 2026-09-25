"""v6 P0-3 하드코딩 감사 후속: 감사 대상 규칙마다 값·문장 구조가 다른 합성 입력 3건 이상과 대조군.

모든 문장은 시험용으로 새로 지었다(특정 평가 문서의 당사자명·사건번호·금액·날짜·문구를 쓰지 않는다).
"""
from __future__ import annotations

import importlib.util

import pytest

from packages.claim_engine.cross_document_entities import verify_cross_document_entities
from packages.claim_engine.date_verifier import verify_dates_in_document
from packages.claim_engine.vote_verifier import verify_vote_counts
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.legal_rules import load_rules
from packages.legal_engine.pleading_structure import pleading_structure_findings


def _doc(*texts, ident="d"):
    return NormalizedDocument(document_id=ident, filename=f"{ident}.pdf", mime_type="application/pdf", sha256="0",
                              pages=[Page(page_number=1, blocks=[Block(block_id=f"{ident}{i}", text=t, page=1)
                                                                 for i, t in enumerate(texts)])])


# --- 하드코딩 제거 확인 --------------------------------------------------------------------------------
def test_static_case_and_statute_text_tables_are_removed():
    assert importlib.util.find_spec("packages.legal_engine.precedent_verifier") is None
    ids = {r["rule_id"] for r in load_rules().get("rules", [])}
    assert not {i for i in ids if i.startswith("LABOR.")}


# --- 표결 인원 산술(표결 합계 > 재적) ------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "징계위원회는 재적위원 5명 중 5명이 출석하여 찬성 4명, 반대 2명으로 의결하였다.",
    "이사회는 재적이사 7명 전원 출석, 찬성 5표 반대 2표 기권 1표로 가결하였다.",
    "총회는 재적 120명 중 찬성 80명, 반대 30명, 기권 15명으로 의결하였다.",
])
def test_vote_totals_exceeding_membership_are_found(text):
    assert len(verify_vote_counts(_doc(text))) == 1


@pytest.mark.parametrize("text", [
    "재적위원 5명 중 찬성 3명, 반대 2명으로 의결하였다.",
    "이사회는 재적이사 9명 중 찬성 6표, 반대 2표, 기권 1표로 가결하였다.",
    "재적 40명의 총회에서 찬성 21명으로 가결되었다.",
])
def test_consistent_votes_are_not_flagged(text):
    assert verify_vote_counts(_doc(text)) == []


# --- 날짜: 요일·달력·경과 일수·발송 선후 ------------------------------------------------------------------
@pytest.mark.parametrize("text, tag", [
    ("통지서는 2025. 7. 14.(화) 발송되었다.", "DATE-WEEKDAY"),
    ("회의는 2023년 11월 2일(금요일)에 열렸다.", "DATE-WEEKDAY"),
    ("2024. 1. 1.(수) 공고", "DATE-WEEKDAY"),
    ("계약일은 2023. 2. 29.이다.", "DATE-INVALID"),
    ("2025년 4월 31일 납부하였다.", "DATE-INVALID"),
    ("2025. 6. 31. 작성", "DATE-INVALID"),
    ("2024. 3. 1.로부터 30일이 지난 2024. 4. 5.에 신청하였다.", "DAYS"),
    ("2025. 1. 10.부터 45일 후의 2025. 2. 20.까지 제출한다.", "DAYS"),
    ("2022. 5. 1.로부터 100일이 지난 2022. 8. 20.에 통보하였다.", "DAYS"),
])
def test_calendar_errors_across_formats(text, tag):
    assert any(tag in f.tags for f in verify_dates_in_document(_doc(text)))


@pytest.mark.parametrize("lines", [
    ("발송일: 2025. 5. 10.", "2025. 5. 12. 개최된 위원회의 의결에 따라 통지합니다."),
    ("작성일 2024. 8. 1.", "2024. 8. 3. 열린 이사회 결의에 따라 알립니다."),
    ("통지일: 2021. 10. 4.", "2021. 10. 20. 이루어진 결정에 따라 조치합니다."),
])
def test_future_event_cited_as_past_in_a_notice(lines):
    assert any("DATE-INVERSION" in f.tags for f in verify_dates_in_document(_doc(*lines)))


@pytest.mark.parametrize("text", [
    "2025. 7. 15.(화) 발송되었다.",                                    # 요일 맞음
    "2024. 2. 29. 계약하였다.",                                         # 윤년
    "2023. 12. 1.로부터 10일이 지난 2023. 12. 11.에 도달하였다.",        # 일수 맞음
    "2023. 12. 1.로부터 11일이 지난 2023. 12. 11.에 도달하였다.",        # 1일 차이: 초일 산입 여부로 달라질 수 있음
    "통지일 2023. 3. 2.\n2023. 3. 1. 개최된 위원회의 의결에 따라 통지합니다.",  # 과거 의결
])
def test_valid_dates_are_not_flagged(text):
    assert verify_dates_in_document(_doc(*text.split("\n"))) == []


# --- 문서 간 판정일: 기관명 리터럴 없이 ---------------------------------------------------------------------
@pytest.mark.parametrize("body", ["지방노동위원회", "중앙노동위원회", "징계위원회"])
def test_decision_dates_use_generic_committee_names(body):
    first = _doc(f"{body} 판정일 2024. 5. 7.", ident="A")
    second = _doc(f"{body} 판정일 2024. 6. 7.", ident="B")
    findings = verify_cross_document_entities([first, second])
    assert findings and all(f.advisory_only for f in findings)


# --- 청구 구조(전제 대립쌍) --------------------------------------------------------------------------------
def _relief(*items):
    return _doc("청 구 취 지", *items, "청 구 원 인", "본문 서술.")


@pytest.mark.parametrize("pair, items", [
    ("EMPLOYMENT", ["1. 피고가 원고에게 한 해고는 무효임을 확인한다.", "2. 피고는 원고에게 퇴직금 12,000,000원을 지급하라."]),
    ("EMPLOYMENT", ["1. 원고가 피고의 근로자 지위에 있음을 확인한다.", "2. 피고는 원고에게 퇴직금 및 지연이자를 지급하라."]),
    ("EMPLOYMENT", ["1. 원고와 피고 사이에 근로관계가 존재함을 확인한다.", "2. 피고는 원고에게 퇴직급여 3,300,000원을 지급하라."]),
    ("CONTRACT", ["1. 원고와 피고 사이의 매매계약이 유효함을 확인한다.", "2. 피고는 원고에게 부당이득금을 반환하라."]),
    ("CONTRACT", ["1. 원고가 이 사건 도급계약의 수급인 지위에 있음을 확인한다.", "2. 피고는 원고에게 원상회복으로 선급금을 반환하라."]),
    ("CONTRACT", ["1. 원고와 피고의 위임계약은 유효함을 확인한다.", "2. 위임계약이 해지되었음을 전제로 피고는 원고에게 부당이득 반환하라."]),
    ("LEASE", ["1. 원고와 피고 사이의 임대차계약이 존속함을 확인한다.", "2. 피고는 원고에게 임대차보증금을 반환하라."]),
    ("LEASE", ["1. 원고의 이 사건 건물에 대한 임차권이 존재함을 확인한다.", "2. 피고는 원고에게 보증금 50,000,000원을 지급하라."]),
    ("LEASE", ["1. 원고가 임차인의 지위에 있음을 확인한다.", "2. 피고는 원고에게 보증금을 반환하라."]),
    ("MARRIAGE", ["1. 원고와 피고는 이혼한다.", "2. 원고와 피고 사이의 혼인은 무효임을 확인한다."]),
    ("MARRIAGE", ["1. 원고와 피고 사이의 혼인이 부존재함을 확인한다.", "2. 피고는 원고에게 재산분할로 1억 원을 지급하라."]),
    ("MARRIAGE", ["1. 원고와 피고의 혼인은 무효임을 확인한다.", "2. 원고의 이혼 청구를 구한다."]),
])
def test_incompatible_claims_joined_without_order_are_flagged(pair, items):
    findings = pleading_structure_findings(_relief(*items))
    assert [f.confidence_features["pair"] for f in findings] == [pair]
    finding = findings[0]
    assert finding.status.value == "SUSPICIOUS" and finding.evidence_grade.value == "C"
    assert finding.confidence_features["human_review"]


@pytest.mark.parametrize("items", [
    ["1. 주위적으로, 피고의 원고에 대한 해고는 무효임을 확인한다.", "2. 예비적으로, 피고는 원고에게 퇴직금을 지급하라."],
    ["1. 피고는 원고에게 퇴직금 5,000,000원을 지급하라."],
    ["1. 원고와 피고 사이의 임대차계약이 존속함을 확인한다.", "2. 소송비용은 피고가 부담한다."],
    ["1. 원고와 피고는 이혼한다.", "2. 피고는 원고에게 위자료 3,000만 원을 지급하라."],
])
def test_compatible_or_ordered_claims_are_not_flagged(items):
    assert pleading_structure_findings(_relief(*items)) == []


def test_opposite_premises_outside_the_relief_section_are_not_reviewed():
    doc = _doc("청 구 취 지", "1. 피고는 원고에게 퇴직금을 지급하라.", "청 구 원 인", "해고는 무효라는 피고의 주장은 이유 없다.")
    assert pleading_structure_findings(doc) == []
