"""추가지시 G5·J2: 사실 튜플 저장소·기간 재계산·증거 목록 대조. 분야를 바꾼 합성 문서로 시험한다."""
from __future__ import annotations

from packages.claim_engine.evidence_consistency import check_exhibits
from packages.claim_engine.fact_checks import check_periods
from packages.claim_engine.fact_store import build_fact_store, cross_document_facts
from packages.common.enums import FindingType
from packages.common.schemas import Block, NormalizedDocument, Page


def doc(*lines, doc_id="d", tables=()):
    blocks = [Block(block_id=f"{doc_id}{i}", text=t, page=1) for i, t in enumerate(lines)]
    d = NormalizedDocument(document_id=doc_id, filename=f"{doc_id}.pdf", mime_type="application/pdf", sha256="0",
                           pages=[Page(page_number=1, blocks=blocks)])
    d.structure["tables"] = [{"table_ref": f"t{i}", "page": 1, "cells": c} for i, c in enumerate(tables)]
    return d


# --- 날짜 구간 일수 ---------------------------------------------------------------
def test_date_range_day_count_mismatch_when_both_counting_rules_fail():
    # 국가배상: 입원기간 12일(초일 산입) 또는 11일인데 21일이라고 적음
    [f] = check_periods(doc("원고는 2025. 3. 2. ~ 2025. 3. 13.(21일간) 입원 치료를 받았다."))
    assert f.type == FindingType.ARITHMETIC_MISMATCH and "12일" in f.detail and "11일" in f.detail


def test_date_range_accepts_either_counting_rule():
    assert check_periods(doc("피고인은 2024. 1. 10. ~ 2024. 1. 20. (11일간) 구금되었다.")) == []   # 형사: 초일 산입
    assert check_periods(doc("임차인은 2024. 1. 10.부터 2024. 1. 20.까지 10일간 사용하였다.")) == []  # 민사: 불산입


# --- N년 경과 만료일 -------------------------------------------------------------
def test_elapsed_years_claim_before_expiry_is_flagged():
    # 민사: 소멸시효 3년 경과 주장인데 만료 전 날짜
    [f] = check_periods(doc("2021. 5. 10.부터 3년이 경과한 2024. 4. 30. 소멸시효가 완성되었다."))
    assert "2024. 5. 9." in f.detail or "2024. 5. 10." in f.detail


def test_elapsed_claim_after_expiry_is_fine():
    assert check_periods(doc("2019. 3. 1.부터 5년이 경과한 2024. 6. 1. 제척기간이 지났다.")) == []   # 행정


def test_stated_span_between_two_dates():
    [f] = check_periods(doc("사고일인 2020. 2. 1.부터 소 제기일인 2022. 8. 1.까지 3년이 경과하였다."))  # 국가배상
    assert "2년" in f.detail


# --- 서증 작성일 ↔ 사건일, 가지번호, 목록 ↔ 첨부 원문 ---------------------------
def test_medical_record_issued_before_the_injury_it_proves():
    table = [["호증", "서증명", "작성일", "작성자", "입증취지"],
             ["갑 제1호증", "진단서", "2025. 3. 1.", "○○병원", "2025. 3. 5. 폭행으로 입은 상해"]]
    findings = check_exhibits(doc("증거목록", tables=[table]))
    assert any(f.type == FindingType.EVIDENCE_TIMELINE_INVERSION for f in findings)


def test_record_before_incident_date_from_the_body():
    table = [["호증", "서증명", "작성일", "작성자", "입증취지"],
             ["갑 제2호증", "사고 사실 확인서", "2024. 7. 1.", "○○경찰서", "사고 경위"]]
    findings = check_exhibits(doc("원고는 2024. 7. 10. 교통사고가 발생하여 부상을 입었다.", tables=[table]))
    assert any(f.type == FindingType.EVIDENCE_TIMELINE_INVERSION for f in findings)


def test_branch_number_without_the_first_branch():
    table = [["호증", "서증명", "작성일", "작성자", "입증취지"],
             ["갑 제1호증", "계약서", "2023. 1. 1.", "원고", "계약 체결"],
             ["갑 제2호증의 2", "영수증", "2023. 2. 1.", "피고", "대금 지급"]]
    findings = check_exhibits(doc("증거목록", tables=[table]))
    assert any(f.type == FindingType.EVIDENCE_NUMBERING_GAP and "제2호증의 1" in f.title for f in findings)


def test_list_issuer_differs_from_attached_original():
    table = [["호증", "서증명", "작성일", "작성자", "입증취지"],
             ["갑 제3호증", "진단서", "2025. 4. 2.", "서울○○병원", "상해 부위와 정도"]]
    findings = check_exhibits(doc("증거목록", "진 단 서", "환자 성명: 김○○  상병명: 요추 염좌",
                                  "발행기관: 부산△△의원  의사 이○○", tables=[table]))
    assert any(f.type == FindingType.EVIDENCE_LIST_MISMATCH and "발급기관" in f.title for f in findings)


# --- 사건 단위 사실 저장소 -------------------------------------------------------
def test_fact_store_extracts_tuples():
    store = build_fact_store([doc("원고는 2024. 7. 10. 교통사고로 좌측 슬관절 부상을 입었다.",
                                  "청구취지", "1. 피고는 원고에게 금 30,000,000원을 지급하라.", doc_id="A")])
    kinds = {f["attribute"] for f in store}
    assert {"injury_side", "incident_date", "claim_amount"} <= kinds


def test_cross_document_body_part_side_and_amount_mismatch():
    a = doc("원고는 2024. 7. 10. 교통사고로 좌측 슬관절 부상을 입었다.", "청구취지",
            "1. 피고는 원고에게 금 30,000,000원을 지급하라.", doc_id="A")
    b = doc("진단 결과 원고는 우측 슬관절 염좌로 3주 치료를 요한다.", "사고일 2024. 7. 11. 교통사고", doc_id="B")
    c = doc("청구취지", "1. 피고는 원고에게 금 35,000,000원을 지급하라.", doc_id="C")
    findings = cross_document_facts([a, b, c])
    titles = " ".join(f.title for f in findings)
    assert "슬관절" in titles and "좌" in titles and "우" in titles
    assert any("청구금액" in f.title for f in findings)
    assert any("사고일" in f.title or "사건일" in f.title for f in findings)
    assert all(f.type == FindingType.CROSS_DOCUMENT_CONTRADICTION for f in findings)


def test_consistent_documents_have_no_cross_document_findings():
    a = doc("원고는 2024. 7. 10. 교통사고로 좌측 슬관절 부상을 입었다.", doc_id="A")
    b = doc("진단: 좌측 슬관절 염좌. 사고일 2024. 7. 10.", doc_id="B")
    assert cross_document_facts([a, b]) == []


def test_pipeline_reports_nonzero_cross_document_issues(tmp_path, monkeypatch):
    """완료 기준: 교차검증 합성 문서에서 internal_consistency.cross_document_issues가 0이 아니다."""
    from packages.pii_engine import PseudonymStore
    from packages.verification_engine import pipeline as module
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline

    docs = {"A": doc("원고는 2024. 7. 10. 교통사고로 좌측 슬관절 부상을 입었다.", doc_id="A"),
            "B": doc("진단 결과 원고는 우측 슬관절 염좌로 3주 치료를 요한다.", doc_id="B")}
    monkeypatch.setattr(module, "parse_document", lambda path, document_id=None, **kw: docs[document_id])
    monkeypatch.setattr(module, "PseudonymStore", lambda project_id: PseudonymStore(project_id, root=tmp_path))
    result = VerificationPipeline().run("run-g5", ProjectContext("project-g5"),
                                       [DocumentInput("A", "A.txt", "A.txt"), DocumentInput("B", "B.txt", "B.txt")])
    assert result.scores["axes"]["internal_consistency"]["cross_document_issues"] >= 1
