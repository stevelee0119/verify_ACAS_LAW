"""v5 3-4: 사실의 양태(확정·예정·가정·상대방 주장)와 대조 대상 확대(계산서 합계↔청구취지, 문맥 금액, 부위 표기).

원인(일반화): '…원으로 확장할 예정'처럼 앞으로의 계획을 확정 청구금액과 대조해 불일치로 판정했고, 피해액·편취금처럼
같은 의미의 금액이나 계산서 합계와 청구취지 금액은 대조하지 않았다. 문서·금액은 모두 시험용 합성이다.
"""
from __future__ import annotations

from pathlib import Path

from packages.claim_engine.fact_store import CONFIRMED, HYPOTHETICAL, OPPONENT, PLANNED, cross_document_facts, modality
from scripts.audit.corpus import build_pdf


def _pdf(tmp_path: Path, name: str, body):
    from packages.document_engine.registry import parse_document

    path = build_pdf({"name": name, "header": "합성 시험 문서", "footer": "시험용 가상 문서", "body": body},
                     tmp_path / f"{name}.pdf")
    return parse_document(str(path), document_id=name, filename=path.name, mime_type="application/pdf", sha256="0" * 64)


def _rules(findings):
    return {f.confidence_features.get("rule_id"): f for f in findings}


def test_modality_of_amount_statements():
    planned = "원고는 청구금액을 94,000,000원으로 확장할 예정입니다."
    assert modality(planned, planned.index("원으로") + 1) == PLANNED
    hypothetical = "설령 피해액이 3,000,000원이라 하더라도 배상 범위는 같다."
    assert modality(hypothetical, hypothetical.index("원이라") + 1) == HYPOTHETICAL
    opponent = "피고인은 편취금이 5,000,000원이라고 주장하나 계좌내역과 다르다."
    assert modality(opponent, opponent.index("원이라") + 1) == OPPONENT
    stated = "피고인은 피해자로부터 12,500,000원을 편취하였다."
    assert modality(stated, stated.index("원을") + 1) == CONFIRMED


# --- 민사: 예정된 청구 확장은 청구금액 불일치가 아니다 ----------------------------------------------
def test_civil_planned_expansion_is_not_a_claim_amount_conflict(tmp_path):
    complaint = _pdf(tmp_path, "complaint", [
        ("h", "소 장"), ("p", "원고 김○○"), ("h", "청 구 취 지"), ("p", "1. 피고는 원고에게 31,350,000원을 지급하라."),
        ("h", "청 구 원 인"), ("p", "원고는 2025. 4. 2. 교통사고로 상해를 입었습니다.")])
    brief = _pdf(tmp_path, "brief", [
        ("h", "준 비 서 면"), ("p", "원고 김○○"),
        ("p", "원고는 신체감정 결과에 따라 청구금액을 94,050,000원으로 확장할 예정입니다.")])
    assert "FACT.CLAIM_AMOUNT" not in _rules(cross_document_facts([complaint, brief]))


# --- 형사: 같은 의미의 금액(편취금)이 문서마다 다르다, 상대방 주장은 제외 -------------------------------
def test_criminal_defrauded_amount_conflict_and_opponent_claim(tmp_path):
    indictment = _pdf(tmp_path, "indictment", [
        ("h", "공 소 장"), ("p", "피고인 박○○"),
        ("p", "피고인은 2025. 3. 1. 피해자를 속여 편취금 12,500,000원을 송금받았다.")])
    settlement = _pdf(tmp_path, "settlement", [
        ("h", "합 의 서"), ("p", "피고인 박○○"),
        ("p", "피고인은 편취금 15,200,000원 전액을 피해자에게 반환하기로 한다."),
        ("p", "피고인 측은 편취금이 5,000,000원이라고 주장하나 이는 받아들이지 않는다.")])
    found = _rules(cross_document_facts([indictment, settlement]))
    conflict = found.get("FACT.CONTEXT_AMOUNT")
    assert conflict is not None and conflict.confidence_features["digit_transposition"]
    assert "5,000,000" not in conflict.title  # 상대방 주장 금액은 비교하지 않았다


# --- 손해배상(국가배상): 계산서 합계와 청구취지 금액, 진단서 약어 부위 표기 ------------------------------
def test_damages_statement_total_and_abbreviated_injury_side(tmp_path):
    complaint = _pdf(tmp_path, "state_liability", [
        ("h", "소 장"), ("p", "원고 이○○"), ("h", "청 구 취 지"), ("p", "1. 피고 대한민국은 원고에게 32,400,000원을 지급하라."),
        ("h", "청 구 원 인"), ("p", "원고는 2025. 6. 3. 훈련 중 좌측 슬관절을 다쳤습니다."),
        ("h", "손해배상 계산서"),
        ("table", [["항목", "금액"], ["치료비", "8,400,000원"], ["일실수입", "10,000,000원"], ["위자료", "5,000,000원"],
                   ["합계", "23,400,000원"]])])
    diagnosis = _pdf(tmp_path, "diagnosis", [
        ("h", "진 단 서"), ("p", "환자 이○○"), ("p", "병명: Rt. 슬관절 내측 반월상 연골 파열")])
    found = _rules(cross_document_facts([complaint, diagnosis]))
    total = found.get("FACT.STATEMENT_TOTAL")
    assert total is not None and total.confidence_features["digit_transposition"]
    assert "FACT.INJURY_SIDE" in found


def test_partial_claim_and_hypothetical_amounts_are_not_compared(tmp_path):
    complaint = _pdf(tmp_path, "partial", [
        ("h", "소 장"), ("p", "원고 최○○"), ("h", "청 구 취 지"), ("p", "1. 피고는 원고에게 10,000,000원을 지급하라."),
        ("h", "청 구 원 인"), ("p", "원고는 손해 중 일부 청구로서 위 금액을 구합니다."),
        ("h", "손해배상 계산서"), ("table", [["항목", "금액"], ["치료비", "6,000,000원"], ["위자료", "9,000,000원"],
                                             ["합계", "15,000,000원"]]),
        ("p", "설령 피해액이 3,000,000원이라 하더라도 배상 범위는 같습니다.")])
    other = _pdf(tmp_path, "other", [("h", "준 비 서 면"), ("p", "원고 최○○"), ("p", "원고의 피해액은 15,000,000원입니다.")])
    found = _rules(cross_document_facts([complaint, other]))
    assert "FACT.STATEMENT_TOTAL" not in found and "FACT.CONTEXT_AMOUNT" not in found
