"""제8장 PII, 제11장 Claim·Entity·Timeline·계산 검증."""
from __future__ import annotations

from datetime import date

import pytest

from packages.common.enums import ClaimType, EvidenceGrade, FindingType
from packages.common.schemas import Block, Event, NormalizedDocument, Page
from packages.claim_engine import (
    CalculationEngine,
    analyze_timeline,
    classify_claim,
    cross_document_contradictions,
    day_count,
    extract_claims,
    extract_entities,
    extract_events,
    resolve_entities,
    simple_interest,
)
from packages.pii_engine import PIIEngine, PseudonymStore, detect, validate_rrn


def make_doc(*texts: str, block_type: str = "paragraph") -> NormalizedDocument:
    doc = NormalizedDocument(document_id="D", filename="f.txt", mime_type="text/plain", sha256="x")
    page = Page(page_number=1)
    for index, text in enumerate(texts, start=1):
        page.blocks.append(Block(block_id=f"B{index}", text=text, page=1, block_type=block_type))
    doc.pages.append(page)
    return doc


# --- 제8장 PII ---------------------------------------------------------------
def test_detects_korean_pii():
    matches = {m.kind for m in detect("원고 홍길동(010-1234-5678, hong@example.com)은 서울특별시 서초구 서초동 100-1에 거주한다.")}
    assert {"PERSON", "PHONE", "EMAIL", "ADDRESS"} <= matches


@pytest.mark.parametrize(
    "text",
    [
        "대법원 2023도12345 판결",
        "형법 제250조 제1항",
        "법률 제12345호",
        "2024. 1. 15. 선고",
        "제308조의2",
    ],
)
def test_legal_identifiers_are_not_masked(text):
    """사건번호·법령번호를 개인정보로 오탐하지 않는다(제8장)."""
    assert detect(text) == []


def test_rrn_checksum_validation():
    assert validate_rrn("8001011234567") is False
    assert any(m.kind == "RRN" for m in detect("주민등록번호는 800101-1234567 이다."))


def test_project_stable_pseudonym(tmp_path):
    store = PseudonymStore(project_id="P1", root=tmp_path)
    engine = PIIEngine(store)
    first = engine.mask_text("원고 홍길동은 계약을 체결하였다.")
    second = engine.mask_text("피고 홍길동은 이를 부인한다.")
    token = first.masked_text.split("[")[1].split("]")[0]
    assert token in second.masked_text  # 동일 프로젝트에서 동일 pseudonym
    assert "홍길동" not in first.masked_text


def test_pseudonym_vault_roundtrip(tmp_path):
    store = PseudonymStore(project_id="P2", root=tmp_path)
    token = store.pseudonym_for("PERSON", "김철수")
    store.save()
    reloaded = PseudonymStore(project_id="P2", root=tmp_path)
    assert reloaded.original_for(token) == "김철수"
    assert reloaded.pseudonym_for("PERSON", "김철수") == token


def test_masked_document_excludes_original_names(tmp_path):
    store = PseudonymStore(project_id="P3", root=tmp_path)
    doc = make_doc("원고 홍길동은 010-1234-5678로 연락하였다.")
    masked = PIIEngine(store).mask_document(doc)
    assert "홍길동" not in masked.text and "010-1234-5678" not in masked.text
    assert masked.match_count >= 2


# --- 제11.1장 Claim ----------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("피고는 2020. 3. 15. 계약을 체결하였다.", ClaimType.FACT),
        ("형법 제250조는 살인죄를 규정하고 있다.", ClaimType.LEGAL_RULE),
        ("대법원은 손해배상책임이 있다고 판시하였다.", ClaimType.CASE_HOLDING),
        ("갑 제3호증을 제출하였다.", ClaimType.DOCUMENT_EXISTENCE),
        ("이는 부당하다고 생각한다.", ClaimType.OPINION),
    ],
)
def test_claim_classification(text, expected):
    assert classify_claim(text) == expected


def test_opinion_excluded_from_fact_verification():
    doc = make_doc("이 사건 처분은 부당하다고 생각한다.")
    claims = extract_claims(doc)
    assert all(c.type == ClaimType.OPINION for c in claims)


# --- 제11.3~11.4장 Entity / Timeline ------------------------------------------
def test_entity_extraction_and_merge():
    doc = make_doc("원고 홍길동은 계약하였다.", "피고 홍길동은 이를 다툰다.", "서울중앙지방법원에 접수되었다.")
    entities = resolve_entities(extract_entities(doc))
    people = [e for e in entities if str(e.type) == "PERSON"]
    courts = [e for e in entities if str(e.type) == "COURT"]
    assert len(people) == 1 and len(people[0].mentions) == 2
    assert courts


def test_timeline_contradiction_detected():
    events = [
        Event.create(date(2020, 5, 1), "회사 설립", event_kind="INCORPORATION", document_id="D", block_id="B1"),
        Event.create(date(2019, 3, 1), "계약 체결", event_kind="CONTRACT", document_id="D", block_id="B2"),
    ]
    findings = analyze_timeline(events)
    assert findings and findings[0].type == FindingType.TIMELINE_CONTRADICTION


def test_no_timeline_finding_when_order_is_valid():
    events = [
        Event.create(date(2018, 1, 1), "회사 설립", event_kind="INCORPORATION"),
        Event.create(date(2019, 3, 1), "계약 체결", event_kind="CONTRACT"),
    ]
    assert analyze_timeline(events) == []


def test_cross_document_contradiction():
    a = [Event.create(date(2020, 3, 15), "계약 체결", event_kind="CONTRACT", document_id="D1", block_id="B1")]
    b = [Event.create(date(2020, 4, 20), "계약 체결", event_kind="CONTRACT", document_id="D2", block_id="B2")]
    findings = cross_document_contradictions({"D1": a, "D2": b})
    assert findings and findings[0].type == FindingType.CROSS_DOCUMENT_CONTRADICTION


def test_event_extraction_keeps_dates_intact():
    doc = make_doc("원고는 2020. 3. 15. 피고와 계약을 체결하였다.")
    events = extract_events(doc)
    assert events and events[0].date == date(2020, 3, 15)
    assert events[0].event_kind == "CONTRACT"


# --- 제11.5장 계산 검증 -------------------------------------------------------
def test_arithmetic_mismatch_is_grade_a():
    doc = make_doc("치료비 1,000,000원, 위자료 3,000,000원, 일실수입 5,000,000원, 합계 10,000,000원을 청구한다.")
    findings = CalculationEngine().verify_document(doc)
    assert findings
    assert findings[0].type == FindingType.ARITHMETIC_MISMATCH
    assert findings[0].evidence_grade == EvidenceGrade.A
    assert "1,000,000" in findings[0].title


def test_correct_sum_produces_no_finding():
    doc = make_doc("치료비 1,000,000원, 위자료 3,000,000원, 합계 4,000,000원을 청구한다.")
    assert CalculationEngine().verify_document(doc) == []


def test_table_total_mismatch():
    doc = make_doc("항목 | 금액\n치료비 | 1,000,000원\n위자료 | 2,000,000원\n합계 | 3,500,000원", block_type="table")
    findings = CalculationEngine().verify_document(doc)
    assert len(findings) == 1
    assert findings[0].type == FindingType.ARITHMETIC_MISMATCH


def test_line_item_sum_mismatch_detected():
    """실무 서면처럼 항목이 줄마다 나뉜 경우도 검산한다(제11.5장)."""
    doc = make_doc(
        "가. 직접손해   금 12,000,000원",
        "나. 일실이익   금 8,000,000원",
        "다. 위자료     금 5,000,000원",
        "라. 합계       금 30,000,000원을 청구한다.",
    )
    findings = CalculationEngine().verify_document(doc)
    assert len(findings) == 1
    assert findings[0].type == FindingType.ARITHMETIC_MISMATCH
    assert findings[0].evidence_grade == EvidenceGrade.A
    assert "5,000,000" in findings[0].title


def test_line_item_sum_correct_produces_no_finding():
    doc = make_doc(
        "가. 직접손해   금 12,000,000원",
        "나. 일실이익   금 8,000,000원",
        "다. 위자료     금 5,000,000원",
        "라. 합계       금 25,000,000원을 청구한다.",
    )
    assert CalculationEngine().verify_document(doc) == []


@pytest.mark.parametrize(
    "lines",
    [
        # 금액 없는 줄이 끼면 서로 무관한 금액을 합산하지 않는다
        ("계약금은 금 1,000,000원이었다.", "피고는 이를 부인한다.", "원고 주장 합계 금 5,000,000원"),
        # 내역이 1건뿐이면 검산하지 않는다
        ("가. 치료비 금 1,000,000원", "나. 합계 금 2,000,000원"),
        # 합계 표기가 없으면 대상이 아니다
        ("가. 치료비 금 1,000,000원", "나. 위자료 금 2,000,000원"),
    ],
)
def test_line_item_scan_avoids_false_positives(lines):
    assert CalculationEngine().verify_document(make_doc(*lines)) == []


def test_interest_and_day_count_are_deterministic():
    from decimal import Decimal

    assert simple_interest(Decimal("10000000"), Decimal("5"), 365) == Decimal("500000")
    assert day_count(date(2020, 1, 1), date(2020, 1, 31)) == 30
    assert day_count(date(2020, 1, 1), date(2020, 1, 31), inclusive=True) == 31
