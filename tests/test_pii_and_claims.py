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
    # An exhibit number alone is not identity. Supply the same explicit project,
    # transaction and corporation before asking for an ordering review candidate.
    events = [
        Event.create(date(2020, 5, 1), "갑 제1호증 회사 설립", event_kind="INCORPORATION", document_id="D", block_id="B1",
                     project_id="P", transaction_id="T", speaker_id="CORPORATION-1", object_id="CORPORATION-1"),
        Event.create(date(2019, 3, 1), "갑 제1호증 계약 체결", event_kind="CONTRACT", document_id="D", block_id="B2",
                     project_id="P", transaction_id="T", speaker_id="CORPORATION-1", object_id="CORPORATION-1"),
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
    a = [Event.create(date(2020, 3, 15), "계약번호 A-123 계약 체결", event_kind="CONTRACT", document_id="D1", block_id="B1")]
    b = [Event.create(date(2020, 4, 20), "계약번호 A-123 계약 체결", event_kind="CONTRACT", document_id="D2", block_id="B2")]
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


# --- 탐지 비용과 위치 정확성 (보고서 생성 지연의 원인이었다) -------------------
def test_detection_cost_stays_linear_in_input_size():
    """탐지 비용이 입력 길이에 비례해야 한다.

    종전에는 탐지 결과 하나마다 본문 전체를 다시 훑어 비용이 제곱으로 늘었다.
    검증 결과 JSON처럼 숫자가 많고 긴 입력에서 한 번의 호출이 수십 초 걸렸고,
    보고서 생성 요청이 응답 없이 끊겼다. 회귀하면 이 시험이 먼저 깨진다.
    """
    import json
    from timeit import repeat

    from packages.pii_engine import detect

    unit = json.dumps(
        [{"claim_id": f"C-{i}", "text": f"원고는 피고에게 금 {i * 1000}원의 지급을 구한다.",
          "page": 1, "span": [i, i + 30], "raw": "대법원 2021. 3. 25. 선고 2018다275017 판결"}
         for i in range(200)],
        ensure_ascii=False,
    )
    small, large = unit, unit * 8

    def elapsed(text):
        # timeit은 GC를 잠시 멈춘다. 반복 최소값으로 CI 스케줄링 지연도 줄인다.
        return min(repeat(lambda: detect(text), number=1, repeat=5))

    detect(small)  # 정규식 캐시 예열
    small_time, large_time = elapsed(small), elapsed(large)

    # 8배 입력이 제곱 비용이면 64배, 선형이면 8배다. 실행 환경 편차를 감안해
    # 24배를 상한으로 둔다. 제곱 복잡도는 이 값을 넘지 못할 수 없다.
    assert large_time < max(small_time * 24, 0.05), (
        f"입력 8배에 소요시간 {large_time / max(small_time, 1e-9):.1f}배. 제곱 비용이 되살아났다"
    )


def test_company_name_after_circled_mark_keeps_its_position():
    """㈜ 뒤의 상호도 본문에서의 위치를 가져야 한다.

    선택지가 둘인 정규식에서 무조건 첫 그룹의 위치를 쓰면 뒤쪽 선택지가
    매치될 때 위치가 (-1, -1)로 남는다. 그 상태로는 마스킹이 상호를 가리지
    못하고 엉뚱한 곳을 건드린다.
    """
    from packages.pii_engine import detect

    text = "계약 상대방 ㈜라마바 대리인 주식회사 가나다"
    companies = {m.text: (m.start, m.end) for m in detect(text) if m.kind == "COMPANY"}
    assert "라마바" in companies, companies
    for name, (start, end) in companies.items():
        assert start >= 0 and text[start:end] == name, f"{name}의 위치가 본문과 어긋난다"


def test_case_numbers_are_still_excluded_from_masking():
    """성능 수정이 법률 식별자 Guard를 무너뜨리지 않았는지 확인한다."""
    from packages.pii_engine import detect

    text = "2023가합12345 사건과 2018다275017 판결, 상법 제341조 제1항을 인용한다."
    assert [m for m in detect(text) if m.kind in ("ACCOUNT", "RRN", "PHONE")] == []
