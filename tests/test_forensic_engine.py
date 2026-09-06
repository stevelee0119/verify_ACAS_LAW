"""제7-A장 은닉 메타메시지 엔진 및 제14장 Document Forensics."""
from __future__ import annotations

from pathlib import Path

import pytest
from helpers import make_docx, make_pdf

from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.document_engine import parse_document
from packages.forensic_engine import (
    AdvisoryContext,
    ForensicContext,
    ForensicEngine,
    PrivilegeGate,
    inspect_outbound,
    sanitize,
    scan_advisory,
    scan_forensics,
)

TRACKED_BODY = (
    "<w:p><w:r><w:t>피고는 원고에게 금원을 지급할 의무가 있다.</w:t></w:r></w:p>"
    '<w:p><w:ins w:author="김변호사" w:date="2026-01-02T00:00:00Z">'
    "<w:r><w:t>추가된 문장이다.</w:t></w:r></w:ins>"
    '<w:del w:author="김변호사" w:date="2026-01-02T00:00:00Z">'
    "<w:r><w:delText>삭제된 내부 검토 의견이다.</w:delText></w:r></w:del></w:p>"
)
COMMENTS = (
    '<w:comment w:id="1" w:author="이변호사" w:date="2026-01-03T00:00:00Z">'
    "<w:p><w:r><w:t>이 부분은 사실과 다르다.</w:t></w:r></w:p></w:comment>"
)
CORE = (
    '<?xml version="1.0"?><cp:coreProperties '
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:creator>홍길동</dc:creator><cp:lastModifiedBy>다른법무법인</cp:lastModifiedBy></cp:coreProperties>"
)


@pytest.fixture()
def tracked_docx(tmp_path):
    path = make_docx(tmp_path / "tracked.docx", TRACKED_BODY, comments_xml=COMMENTS, core_xml=CORE)
    return parse_document(str(path), document_id="D1", filename="tracked.docx", mime_type="", sha256="h"), path


# --- MM-2 잔류형 ------------------------------------------------------------
def test_mm2_residual_findings(tracked_docx):
    doc, _ = tracked_docx
    findings = scan_forensics(doc).findings
    types = {f.type for f in findings}
    assert FindingType.RESIDUAL_TRACKED_CHANGE in types
    assert FindingType.DELETED_TEXT_RECOVERABLE in types
    assert FindingType.RESIDUAL_COMMENT in types
    assert FindingType.AUTHORSHIP_METADATA_LEAK in types


def test_mm2_findings_are_grade_a_deterministic(tracked_docx):
    """MM-2는 존재 자체를 결정론적으로 증명할 수 있으므로 Finding으로 확정한다."""
    doc, _ = tracked_docx
    residual = [
        f for f in scan_forensics(doc).findings
        if f.type in (FindingType.RESIDUAL_TRACKED_CHANGE, FindingType.DELETED_TEXT_RECOVERABLE)
    ]
    assert residual
    assert all(f.evidence_grade == EvidenceGrade.A for f in residual)


def test_sealed_content_not_exposed_by_default(tracked_docx):
    """MM-2·MM-3 원문은 사용자 확인 전 노출하지 않는다(부록 C 제11항)."""
    doc, _ = tracked_docx
    sealed = [f for f in scan_forensics(doc).findings if f.sealed_excerpt]
    assert sealed
    for finding in sealed:
        public = finding.to_dict()
        assert public["sealed_excerpt"] is None
        assert public["has_sealed_content"] is True
        assert "삭제된 내부 검토 의견" not in str(public)


def test_llm_safe_summary_excludes_raw_text(tracked_docx):
    """LLM Context에는 유형·위치·길이·해시만 전달한다(제7-A.5장)."""
    doc, _ = tracked_docx
    summary = scan_forensics(doc).data["llm_safe_summary"]
    assert summary
    blob = str(summary)
    assert "삭제된 내부 검토 의견" not in blob
    assert all(item["content_included"] is False for item in summary)
    assert all(item["content_sha256"] for item in summary if item["content_length"])


def test_redaction_failure_is_critical(tmp_path):
    path = make_pdf(
        tmp_path / "redact.pdf",
        ["증인 진술서이다.", "주민등록번호 900101-1234567 이다."],
        black_box_over="주민등록번호 900101-1234567 이다.",
    )
    doc = parse_document(str(path), document_id="D", filename="redact.pdf", mime_type="application/pdf", sha256="h")
    findings = scan_forensics(doc).findings
    redaction = [f for f in findings if f.type == FindingType.REDACTION_FAILURE]
    assert redaction and redaction[0].severity == Severity.CRITICAL
    assert redaction[0].sealed_excerpt is not None


def test_privilege_gate_blocks_reveal_without_confirmation(tracked_docx):
    doc, _ = tracked_docx
    findings = scan_forensics(doc).findings
    sealed = next(f for f in findings if f.sealed_excerpt)
    gate = PrivilegeGate()
    assert gate.request_reveal(sealed, user_confirmed=False).allowed is False
    assert gate.request_reveal(sealed, user_confirmed=True).allowed is True


def test_org_policy_can_block_reveal(tracked_docx):
    doc, _ = tracked_docx
    sealed = next(f for f in scan_forensics(doc).findings if f.sealed_excerpt)
    gate = PrivilegeGate(org_block_reveal=True)
    assert gate.request_reveal(sealed, user_confirmed=True).allowed is False


def test_privilege_warning_attached(tracked_docx):
    doc, _ = tracked_docx
    findings = scan_forensics(doc, ForensicContext(counterparty_document=True)).findings
    assert any(f.type == FindingType.PRIVILEGE_EXPOSURE_RISK for f in findings)
    flagged = [f for f in findings if "PRIVILEGE_EXPOSURE_RISK" in f.tags]
    assert flagged and any("열람 전 경고" in f.detail for f in flagged)


# --- 7-A.7 Outbound Guard ---------------------------------------------------
def test_outbound_guard_sanitizes_without_touching_original(tracked_docx, tmp_path):
    doc, source = tracked_docx
    original_bytes = source.read_bytes()
    findings = scan_forensics(doc).findings
    report = inspect_outbound(doc, findings)
    assert report.risk_items

    target = tmp_path / "clean.docx"
    result = sanitize(doc, str(source), str(target))
    assert result.removed["tracked_delete_removed"] >= 1
    assert result.removed["comment_part_removed"] >= 1
    assert source.read_bytes() == original_bytes  # 원본 불변(부록 C 제8항)

    cleaned = parse_document(str(target), document_id="D2", filename="clean.docx", mime_type="", sha256="h2")
    assert "삭제된 내부 검토 의견" not in cleaned.full_text
    assert cleaned.structure["comments"] == []
    assert not cleaned.metadata.get("creator")


# --- MM-4 참고 신호 가드레일 -------------------------------------------------
def _doc_with(text: str):
    from packages.common.schemas import Block, NormalizedDocument, Page

    doc = NormalizedDocument(document_id="D", filename="f.txt", mime_type="text/plain", sha256="x")
    page = Page(page_number=1)
    page.blocks.append(Block(block_id="B1", text=text, page=1))
    doc.pages.append(page)
    return doc


def test_mm4_signals_are_capped_and_advisory():
    doc = _doc_with(
        "피고는 원고를 형사 고소하겠다고 하였고 언론에 공개하겠다고도 하였다. "
        "이는 본안과 무관한 불이익 언급이다."
    )
    signals = scan_advisory(doc)
    assert signals
    for signal in signals:
        assert signal.severity.rank <= Severity.MEDIUM.rank
        assert signal.evidence_grade == EvidenceGrade.D
        assert signal.status == VerificationStatus.UNVERIFIED
        assert signal.advisory_only is True
        assert signal.block_id and signal.span  # 근거 span 없으면 신호를 만들지 않는다


def test_mm4_signal_requires_evidence_span():
    """근거 span이 없으면 신호를 생성하지 않는다(제7-A.4장)."""
    doc = _doc_with("정상적인 서면 내용이다.")
    context = AdvisoryContext(truncated_quotations=[{"block_id": "MISSING", "citation": "x", "omitted_chars": 50}])
    assert scan_advisory(doc, context) == []


def test_mm4_signals_can_be_disabled():
    doc = _doc_with("피고는 원고를 형사 고소하겠다고 하였다.")
    assert scan_advisory(doc, AdvisoryContext(enabled_signals=set())) == []


def test_mm4_issue_evasion_uses_claim_graph_input():
    doc = _doc_with("피고는 계약의 성립만을 다툰다.")
    context = AdvisoryContext(requested_issues=["변제 여부", "지연손해금 기산일"])
    signals = scan_advisory(doc, context)
    assert any(f.type == FindingType.ISSUE_EVASION_SIGNAL for f in signals)


# --- 템플릿 잔재 -------------------------------------------------------------
def test_template_residue_detects_foreign_case_number(tmp_path):
    path = make_pdf(tmp_path / "tpl.pdf", ["이 사건 2020가합5555 사건과 관련하여 주장한다."])
    doc = parse_document(str(path), document_id="D", filename="tpl.pdf", mime_type="application/pdf", sha256="h")
    findings = scan_forensics(doc, ForensicContext(project_case_number="2026가합1234")).findings
    assert any(f.type == FindingType.TEMPLATE_RESIDUE for f in findings)


def test_forensic_disclaimer_present(tmp_path):
    """포렌식 휴리스틱만으로 위조를 단정하지 않는다(부록 C 제6항)."""
    path = make_pdf(tmp_path / "f.pdf", ["정상 본문이다."])
    doc = parse_document(str(path), document_id="D", filename="f.pdf", mime_type="application/pdf", sha256="h")
    from packages.forensic_engine import scan_document_forensics

    findings = scan_document_forensics(doc)
    assert all("고의나 위조 목적에 관한 판단이 아니다" in f.detail for f in findings)
