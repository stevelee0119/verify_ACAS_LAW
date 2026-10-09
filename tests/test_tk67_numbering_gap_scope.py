"""TK-67: 증거번호 결번 판정 범위 정상화 시험 (목록 구역 존재 시 구역 번호 및 최소 번호 기준).

문서·문장·증거명은 모두 시험용 가상 합성 데이터이다 (은퇴 세트 및 실제 사건의 문장·고유값을 일절 포함하지 않음).
"""
from __future__ import annotations

from pathlib import Path
import pytest

from packages.claim_engine.evidence_consistency import check_document
from packages.document_engine.registry import parse_document
from scripts.audit.corpus import build_pdf


def _doc(tmp_path: Path, name: str, body):
    """합성 PDF 문서를 생성하고 파싱된 NormalizedDocument를 반환한다."""
    path = build_pdf({"name": name, "header": "합성 시험 문서", "footer": "시험용 가상 문서", "body": body},
                     tmp_path / f"{name}.pdf")
    return parse_document(str(path), document_id=name, filename=path.name, mime_type="application/pdf", sha256="0" * 64)


# ======================================================================================
# 1. 양성 유지 시험 (목록 구역 안의 중간 결번은 당사자 구분 없이 정상 검출)
# ======================================================================================

def test_positive_gap_in_section_갑_middle_missing(tmp_path):
    """[합성 양성 1] '갑' 목록 구역에서 제1, 2, 4호증이 있고 제3호증이 누락된 경우 결번(B)을 정상 검출한다."""
    doc = _doc(tmp_path, "pos_gap_gap_middle", [
        ("h", "소 장"),
        ("p", "1. 원고의 청구원인 사실입니다."),
        ("p", "입증방법"),
        ("p", "1. 갑 제1호증 도급계약서"),
        ("p", "2. 갑 제2호증 세금계산서"),
        ("p", "3. 갑 제4호증 준공확인서"),  # 제3호증 누락
        ("p", "2026. 5. 1."),
        ("p", "원고 소송대리인 변호사 대리 (인)")
    ])
    findings = check_document(doc)
    gaps = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBERING_GAP"
            or "결번" in f.title]
    gap_titles = [f.title for f in gaps]
    assert any("갑 제3호증 결번" in t for t in gap_titles), f"갑 제3호증 결번이 검출되어야 함: {gap_titles}"


def test_positive_gap_in_section_을_middle_missing(tmp_path):
    """[합성 양성 2] '을' 목록 구역에서 제1, 3, 4호증이 있고 제2호증이 누락된 경우 결번(B)을 정상 검출한다."""
    doc = _doc(tmp_path, "pos_gap_eul_middle", [
        ("h", "답 변 서"),
        ("p", "1. 피고의 답변 요지입니다."),
        ("p", "다. 입증방법"),
        ("p", "1. 을 제1호증 사업자등록증"),
        ("p", "2. 을 제3호증 거래명세표"),  # 제2호증 누락
        ("p", "3. 을 제4호증 입금증"),
        ("p", "2026. 6. 10."),
        ("p", "피고 변호인 변호사 법무 (인)")
    ])
    findings = check_document(doc)
    gaps = [f for f in findings if "결번" in f.title]
    gap_titles = [f.title for f in gaps]
    assert any("을 제2호증 결번" in t for t in gap_titles), f"을 제2호증 결번이 검출되어야 함: {gap_titles}"


def test_positive_gap_in_section_증_middle_missing(tmp_path):
    """[합성 양성 3] '증' 목록 구역에서 제1, 3호증이 제출되고 제2호증이 누락된 경우 결번(B)을 정상 검출한다."""
    doc = _doc(tmp_path, "pos_gap_jeung_middle", [
        ("h", "증거설명서"),
        ("p", "입증방법"),
        ("p", "1. 증 제1호증 수사보고서"),
        ("p", "2. 증 제3호증 압수조서"),  # 제2호증 누락
        ("p", "2026. 7. 15."),
        ("p", "제출인 검찰관 검사 (인)")
    ])
    findings = check_document(doc)
    gaps = [f for f in findings if "결번" in f.title]
    gap_titles = [f.title for f in gaps]
    assert any("증 제2호증 결번" in t for t in gap_titles), f"증 제2호증 결번이 검출되어야 함: {gap_titles}"


# ======================================================================================
# 2. 대조군 오탐 방지 시험 (목록 2번 시작, 본문 큰 번호 언급, 가지번호 목록)
# ======================================================================================

def test_control_section_starts_from_two_no_prior_gap_false_positive(tmp_path):
    """[합성 대조 1] 목록 구역이 제2호증부터 시작하는 경우, 제1호증 결번 오탐이 발생하지 않는다."""
    doc = _doc(tmp_path, "ctrl_starts_from_two", [
        ("h", "준 비 서 면"),
        ("p", "1. 추가 제출 증거에 대한 설명입니다."),
        ("p", "다. 입증방법"),
        ("p", "1. 갑 제2호증의 1 사실확인서"),
        ("p", "2. 갑 제2호증의 2 현장사진"),
        ("p", "3. 갑 제3호증 납품확인서"),
        ("p", "2026. 8. 20."),
        ("p", "원고 소송대리인 변호사 대리 (인)")
    ])
    findings = check_document(doc)
    gaps = [f for f in findings if "호증 결번" in f.title and "가지번호" not in f.title]
    assert len(gaps) == 0, f"앞선 번호가 목록에 없더라도 제1호증 결번 오탐이 없어야 함: {[f.title for f in gaps]}"


def test_control_body_mentions_higher_number_section_continuous_no_gap(tmp_path):
    """[합성 대조 2] 목록 구역은 제1, 2호증으로 연속인데, 본문에서 큰 번호(제17호증)를 단순 언급한 경우 결번 오탐이 없다."""
    doc = _doc(tmp_path, "ctrl_body_high_number", [
        ("h", "답 변 서"),
        ("p", "1. 사실관계에 관한 설명입니다."),
        ("p", "갑 제17호증의 기재 내용은 별건 소송 기록에 불과합니다."),  # 본문 단순 언급
        ("p", "3. 입증방법"),
        ("p", "1. 을 제1호증 합의서"),
        ("p", "2. 을 제2호증 영수증"),
        ("p", "2026. 9. 1."),
        ("p", "피고 변호인 변호사 공익 (인)")
    ])
    findings = check_document(doc)
    # 을 호증 및 갑 호증에 대한 번호 결번 오탐이 없어야 함
    gaps = [f for f in findings if "호증 결번" in f.title and "가지번호" not in f.title]
    assert len(gaps) == 0, f"본문 단순 언급으로 인한 대량 결번 오탐이 없어야 함: {[f.title for f in gaps]}"


def test_control_section_branch_numbers_continuous_no_gap(tmp_path):
    """[합성 대조 3] 목록 구역에 제1호증의 가지번호만 정상 연속으로 존재하는 경우 결번 오탐이 없다."""
    doc = _doc(tmp_path, "ctrl_branch_only", [
        ("h", "증거설명서"),
        ("p", "입증방법"),
        ("p", "1. 갑 제1호증의 1 견적서"),
        ("p", "2. 갑 제1호증의 2 발주서"),
        ("p", "2026. 9. 15."),
        ("p", "원고 변호사 법무 (인)")
    ])
    findings = check_document(doc)
    gaps = [f for f in findings if "결번" in f.title]
    assert len(gaps) == 0, f"정상 가지번호 목록에서 결번 오탐이 없어야 함: {[f.title for f in gaps]}"


# ======================================================================================
# 3. 목록 구역 미존재 서면의 기존 동작 유지 시험
# ======================================================================================

def test_prose_only_without_section_preserves_gap_from_one(tmp_path):
    """[합성 기존 동작 유지] 목록 구역이 없는 서면의 본문 문장에서 제2, 3호증만 언급된 경우 1번부터 계산하는 기존 결번 동작을 유지한다."""
    doc = _doc(tmp_path, "prose_only_gap_from_one", [
        ("h", "준 비 서 면"),
        ("p", "1. 원고의 주장 사실입니다."),
        ("p", "갑 제2호증 사실확인서 2026. 3. 1. 기재에 따르면 약정이 인정됩니다."),
        ("p", "2. 추가 증거 설명입니다."),
        ("p", "갑 제3호증 금융거래내역서 2026. 4. 1. 기재와 같이 입금되었습니다."),
        ("p", "2026. 10. 1."),
        ("p", "원고 소송대리인 변호사 법률 (인)")
    ])
    findings = check_document(doc)
    gaps = [f for f in findings if "갑 제1호증 결번" in f.title]
    assert len(gaps) >= 1, f"목록 구역이 없는 서면에서는 1번부터 계산하여 갑 제1호증 결번을 기존대로 검출해야 함: {[f.title for f in findings]}"
