"""TK-64: 본문 서술 문단을 증거 목록 행으로 오인하여 발생하는 같은 호증 번호 중복(A등급) 오탐 방지 시험.

문서·문장·증거명은 모두 시험용 합성 데이터이다 (은퇴 세트 및 실제 사건의 문장·고유값을 일절 포함하지 않음).
"""
from __future__ import annotations

from pathlib import Path
import pytest

from packages.claim_engine.evidence_consistency import check_document, check_exhibits, exhibit_rows
from packages.document_engine.registry import parse_document
from scripts.audit.corpus import build_pdf


def _doc(tmp_path: Path, name: str, body):
    """합성 PDF 문서를 생성하고 파싱된 NormalizedDocument를 반환한다."""
    path = build_pdf({"name": name, "header": "합성 시험 문서", "footer": "시험용 가상 문서", "body": body},
                     tmp_path / f"{name}.pdf")
    return parse_document(str(path), document_id=name, filename=path.name, mime_type="application/pdf", sha256="0" * 64)


def _titles(findings):
    """CONTRADICTED 상태인 판정 결과의 제목 목록을 반환한다."""
    return [f.title for f in findings if str(f.status) == "CONTRADICTED"]


# ======================================================================================
# 1. 양성 유지 시험 (목록 구역 안의 진짜 중복 번호는 계속 A등급으로 검출)
# ======================================================================================

def test_positive_duplicate_in_section_with_hangul_prefix(tmp_path):
    """[합성 양성 1] 한글 접두어가 붙은 '다. 입증방법' 구역 내에서 같은 호증 번호가 중복 부여된 경우 A등급으로 검출한다."""
    doc = _doc(tmp_path, "dup_hangul_prefix", [
        ("h", "준 비 서 면"),
        ("p", "1. 원고의 청구원인에 대한 답변입니다."),
        ("p", "다. 입증방법"),
        ("p", "1. 을 제1호증 물품공급계약서"),
        ("p", "2. 을 제2호증 세금계산서"),
        ("p", "3. 을 제2호증 금융거래내역서"),  # 을 제2호증 중복 (서로 다른 증거)
        ("p", "2026. 5. 10."),
        ("p", "피고 소송대리인 변호사 변호인 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) >= 1, "목록 구역 안의 을 제2호증 중복이 검출되어야 함"
    assert "을 제2호증" in dup_findings[0].title
    assert str(dup_findings[0].evidence_grade) == "A"


def test_positive_duplicate_in_section_with_number_prefix(tmp_path):
    """[합성 양성 2] 아라비아 숫자 접두어가 붙은 '3. 입증방법' 구역 내에서 같은 호증 번호가 중복 부여된 경우 A등급으로 검출한다."""
    doc = _doc(tmp_path, "dup_number_prefix", [
        ("h", "답 변 서"),
        ("p", "1. 청구취지에 대한 답변을 개진합니다."),
        ("p", "3. 입증방법"),
        ("p", "1. 갑 제1호증 견적서"),
        ("p", "2. 갑 제1호증 발주서"),  # 갑 제1호증 중복 (서로 다른 증거)
        ("p", "3. 갑 제2호증 입금확인증"),
        ("p", "2026. 6. 15."),
        ("p", "원고 소송대리인 변호사 대리인 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) >= 1, "목록 구역 안의 갑 제1호증 중복이 검출되어야 함"
    assert "갑 제1호증" in dup_findings[0].title
    assert str(dup_findings[0].evidence_grade) == "A"


def test_positive_duplicate_in_section_with_parenthesis_prefix(tmp_path):
    """[합성 양성 3] 괄호 번호 접두어가 붙은 '(1) 입증방법' 구역 내에서 같은 호증 번호가 중복 부여된 경우 A등급으로 검출한다."""
    doc = _doc(tmp_path, "dup_parenthesis_prefix", [
        ("h", "준 비 서 면"),
        ("p", "1. 사실관계에 관한 반박입니다."),
        ("p", "(1) 입증방법"),
        ("p", "1. 을 제3호증 사실확인서"),
        ("p", "2. 을 제3호증 진술조서"),  # 을 제3호증 중복 (서로 다른 증거)
        ("p", "3. 을 제4호증 녹취록"),
        ("p", "2026. 7. 20."),
        ("p", "피고 변호인 변호사 법률가 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) >= 1, "목록 구역 안의 을 제3호증 중복이 검출되어야 함"
    assert "을 제3호증" in dup_findings[0].title
    assert str(dup_findings[0].evidence_grade) == "A"


def test_positive_duplicate_in_section_without_prefix(tmp_path):
    """[합성 양성 4] 접두어가 없는 표준 '입증방법' 구역 내에서 같은 호증 번호 중복이 정상 검출된다."""
    doc = _doc(tmp_path, "dup_no_prefix", [
        ("h", "소 장"),
        ("p", "입증방법"),
        ("p", "1. 갑 제5호증 부동산매매계약서"),
        ("p", "2. 갑 제5호증 등기사항전부증명서"),  # 갑 제5호증 중복
        ("p", "2026. 8. 1."),
        ("p", "원고 변호사 법무 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) >= 1
    assert "갑 제5호증" in dup_findings[0].title


# ======================================================================================
# 2. 오탐 제거 시험 (본문 서술 문단과 입증방법 목록이 함께 있을 때 오탐 발생 방지)
# ======================================================================================

def test_fp_elimination_prose_with_topic_marker_eun_neun(tmp_path):
    """[합성 대조 1] 본문에서 주제 조사 '은/는'이 붙은 서술 문단이 있어도 정식 목록과 중복으로 오탐되지 않는다."""
    doc = _doc(tmp_path, "fp_topic_marker", [
        ("h", "준 비 서 면"),
        ("p", "1. 원고의 주장에 대하여 반박합니다."),
        ("p", "을 제2호증은 피고 측 관리자가 2024. 3. 1. 작성한 업무보고서의 일부입니다."),
        ("p", "또한 피고는 업무상 지시사항을 성실히 이행하였습니다."),
        ("p", "다. 입증방법"),
        ("p", "1. 을 제1호증 사업자등록증"),
        ("p", "2. 을 제2호증 업무보고서"),
        ("p", "3. 을 제3호증 정산내역서"),
        ("p", "2026. 9. 1."),
        ("p", "피고 소송대리인 변호사 대리 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) == 0, f"본문 서술 문단으로 인한 을 제2호증 중복 오탐이 없어야 함: {[f.title for f in dup_findings]}"


def test_fp_elimination_prose_multiple_sentences_haera(tmp_path):
    """[합성 대조 2] 본문에서 해라체 종결 어미가 포함된 서술 문단이 있어도 '3. 입증방법' 목록과 중복 오탐이 발생하지 않는다."""
    doc = _doc(tmp_path, "fp_haera_sentences", [
        ("h", "답 변 서"),
        ("p", "1. 사실관계의 요지는 다음과 같습니다."),
        ("p", "갑 제1호증의 1은 피고가 원고에게 송부한 거래명세서에 해당한다. 이는 정상적인 상거래 절차에 따른 것이다."),
        ("p", "2. 원고의 추가 청구는 부당합니다."),
        ("p", "3. 입증방법"),
        ("p", "1. 갑 제1호증의 1 거래명세서"),
        ("p", "2. 갑 제2호증 영수증"),
        ("p", "2026. 9. 15."),
        ("p", "원고 소송대리인 변호사 소송 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) == 0, f"본문 해라체 문단으로 인한 갑 제1호증의 1 중복 오탐이 없어야 함: {[f.title for f in dup_findings]}"


def test_fp_elimination_prose_hapshow_closer_and_annex(tmp_path):
    """[합성 대조 3] 본문에서 합쇼체 종결어미 및 별지 서술 문단이 있어도 '(1) 입증방법' 목록과 중복 오탐이 발생하지 않는다."""
    doc = _doc(tmp_path, "fp_hapshow_annex", [
        ("h", "준 비 서 면"),
        ("p", "1. 피고의 항변에 대한 의견입니다."),
        ("p", "을 제4호증 별지의 견적서 내역에 기재된 금액은 상호 합의된 바에 따른 것입니다."),
        ("p", "또한 원고는 약정된 기일 내에 공사를 완료하였습니다."),
        ("p", "(1) 입증방법"),
        ("p", "1. 을 제3호증 공사도급계약서"),
        ("p", "2. 을 제4호증 견적서"),
        ("p", "2026. 10. 1."),
        ("p", "피고 변호인 변호사 공익 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) == 0, f"본문 합쇼체 별지 문단으로 인한 을 제4호증 중복 오탐이 없어야 함: {[f.title for f in dup_findings]}"


def test_fp_elimination_title_with_trailing_words_not_treated_as_section(tmp_path):
    """[합성 대조 4] 제목 뒤에 다른 말이 이어지는 문장은 구역 제목으로 오인되지 않고 정상 판별된다."""
    doc = _doc(tmp_path, "fp_trailing_title_words", [
        ("h", "준 비 서 면"),
        ("p", "1. 청구원인에 관한 주장입니다."),
        ("p", "3. 내부 기준과 입증방법에 관한 원고의 주장은 사실과 다릅니다."),  # 구역 제목이 아닌 본문 서술문
        ("p", "피고는 관련 제규정을 준수하였습니다."),
        ("p", "입증방법"),
        ("p", "1. 갑 제1호증 운영지침서"),
        ("p", "2. 갑 제2호증 내부결재문서"),
        ("p", "2026. 10. 5."),
        ("p", "원고 변호사 법무 (인)")
    ])
    rows = exhibit_rows(doc)
    assert len(rows) == 2, f"정식 입증방법 구역 아래의 2건만 행으로 수용되어야 함 (실제: {len(rows)})"
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) == 0


# ======================================================================================
# 3. 개정 1 보완 시험 (본문 전용 결함 유지, 괄호 부연 구역 인식 및 대조군 단언)
# ======================================================================================

def test_positive_duplicate_in_prose_when_no_section_exists(tmp_path):
    """[합성 보완 1] 목록 구역이 없는 서면의 본문 문장에서 같은 번호를 서로 다른 증거에 붙이면 중복(A)을 계속 잡는다."""
    doc = _doc(tmp_path, "dup_in_prose_no_section", [
        ("h", "준 비 서 면"),
        ("p", "1. 원고의 주장 사실입니다."),
        ("p", "갑 제1호증 견적서 2026. 1. 10. 기재에 따르면 대금 산정이 확인됩니다."),
        ("p", "2. 추가 증거 설명입니다."),
        ("p", "갑 제1호증 발주서 2026. 2. 15. 기재에 따르면 주문이 확정되었습니다."),  # 갑 제1호증 서로 다른 서증명 중복
        ("p", "2026. 5. 1."),
        ("p", "원고 소송대리인 변호사 대리 (인)")
    ])
    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) >= 1, f"목록 구역이 없어도 본문 행 간의 중복은 A등급으로 잡아야 함: {[f.title for f in findings]}"
    assert "갑 제1호증" in dup_findings[0].title
    assert str(dup_findings[0].evidence_grade) == "A"


def test_positive_invalid_date_in_prose_detected(tmp_path):
    """[합성 보완 2] 본문 문장 속 증거에 기재된 달력에 없는 작성일(2월 30일)을 계속 A등급으로 잡는다."""
    doc = _doc(tmp_path, "invalid_date_in_prose", [
        ("h", "답 변 서"),
        ("p", "1. 피고의 사실관계 설명입니다."),
        ("p", "을 제2호증 사실확인서 2026. 2. 30. 기재와 같이 피고는 합의를 마쳤습니다."),  # 2월 30일: 존재하지 않는 날짜
        ("p", "2026. 6. 1."),
        ("p", "피고 변호인 변호사 법률 (인)")
    ])
    findings = check_document(doc)
    date_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_DATE_INVALID"]
    assert len(date_findings) >= 1, f"본문 행의 달력에 없는 작성일은 A등급으로 잡아야 함: {[f.title for f in findings]}"
    assert "2026. 2. 30" in date_findings[0].title
    assert str(date_findings[0].evidence_grade) == "A"


def test_fp_elimination_section_with_parenthesis_annotation_ignores_body_mention(tmp_path):
    """[합성 보완 3] 괄호 부연 제목('입증방법 (추가 제출)') 아래 목록을 구역으로 알아보고, 그 번호의 본문 언급은 중복으로 잡지 않는다."""
    doc = _doc(tmp_path, "parenthesis_annotation_section", [
        ("h", "준 비 서 면"),
        ("p", "1. 원고의 반박 주장입니다."),
        ("p", "갑 제1호증 물품공급계약서 2026. 3. 1. 내용에 따라 이행을 완료하였습니다."),  # 본문 언급
        ("p", "입증방법 (추가 제출)"),  # 괄호 부연 제목
        ("p", "1. 갑 제1호증 물품공급계약서"),
        ("p", "2. 갑 제2호증 입금확인증"),
        ("p", "2026. 7. 1."),
        ("p", "원고 변호사 법무 (인)")
    ])
    rows = exhibit_rows(doc)
    section_rows = [r for r in rows if r.get("in_section")]
    assert len(section_rows) >= 2, f"괄호 부연 구역 아래의 목록이 in_section으로 파싱되어야 함 (실제 section 행: {len(section_rows)})"

    findings = check_document(doc)
    dup_findings = [f for f in findings if f.confidence_features.get("rule_id") == "EVI.EVIDENCE_NUMBER_DUPLICATE"]
    assert len(dup_findings) == 0, f"괄호 부연 구역의 번호와 본문 언급 간 중복 오탐이 없어야 함: {[f.title for f in dup_findings]}"


def test_exhibit_section_regex_contrasts():
    """[합성 보완 4] _EXHIBIT_SECTION_HEAD_RE 정규식 대조군 2가지가 구역 제목이 아님을 단언하고 부연 구역 제목은 허용됨을 확인한다."""
    from packages.claim_engine.evidence_consistency import _EXHIBIT_SECTION_HEAD_RE

    # 대조군 1: 번호와 제목 사이에 다른 말이 낀 줄은 구역 제목이 아니다.
    assert not _EXHIBIT_SECTION_HEAD_RE.search("3. 내부 기준과 입증방법")

    # 대조군 2: 제목 뒤에 조사로 이어지는 문장은 구역 제목이 아니다.
    assert not _EXHIBIT_SECTION_HEAD_RE.search("입증방법에 관하여 본다.")

    # 정상 부연 제목 (종전 동작 허용)
    assert _EXHIBIT_SECTION_HEAD_RE.search("입증방법 (추가 제출)")
    assert _EXHIBIT_SECTION_HEAD_RE.search("입증방법: 아래와 같음")
    assert _EXHIBIT_SECTION_HEAD_RE.search("다. 입증방법")
    assert _EXHIBIT_SECTION_HEAD_RE.search("(1) 입증방법")

