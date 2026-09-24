"""v2 Phase 1: 인용마다 최종 판정 하나, 필수 필드, 비식별 표기 허용, 문서 종류별 문구."""
from __future__ import annotations

from packages.claim_engine.assertion import draft_artifact_findings
from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import BBox, Block, Finding, NormalizedDocument, Page
from packages.forensic_engine.specimen import scan_specimen
from packages.verification_engine.finalize import finalize_document_findings


def _finding(kind, status, grade, *, citation_id="C1", **features):
    return Finding.create(type=kind, status=status, severity=Severity.HIGH, evidence_grade=grade,
                          title=f"{kind}", detail="d", confidence_features={"citation_id": citation_id, **features},
                          engine="test", block_id="b1")


def _doc(*lines):
    page = Page(page_number=1, width=595, height=842)
    for index, text in enumerate(lines):
        page.blocks.append(Block(block_id=f"b{index}", text=text, page=1, bbox=BBox(60, 80 + 18 * index, 300, 92 + 18 * index)))
    return NormalizedDocument(document_id="D", filename="d.pdf", mime_type="application/pdf", sha256="0", pages=[page])


def test_one_final_verdict_per_citation_with_priority_and_merged_evidence():
    findings = [
        _finding(FindingType.LEGAL_ARGUMENT_INVALID, VerificationStatus.UNVERIFIED, EvidenceGrade.C),
        _finding(FindingType.CASE_NOT_FOUND, VerificationStatus.NOT_FOUND, EvidenceGrade.B),
        _finding(FindingType.CASE_NOT_FOUND, VerificationStatus.SUSPICIOUS, EvidenceGrade.A, number_format_valid=False),
        _finding(FindingType.CASE_QUOTE_MISMATCH, VerificationStatus.CONTRADICTED, EvidenceGrade.A, citation_id="C2"),
    ]
    out = finalize_document_findings(findings, _doc("x", "y"), "D")
    by_citation = {f.confidence_features["citation_id"]: f for f in out}
    assert len(out) == 2
    final = by_citation["C1"]
    assert final.confidence_features["number_format_valid"] is False  # 형식상 성립 불가가 최우선
    assert len(final.confidence_features["merged_findings"]) == 2
    assert any("하위 판정" in e.description for e in final.evidence)


def test_required_fields_are_filled_from_the_block():
    finding = Finding.create(type=FindingType.DRAFT_ARTIFACT, status=VerificationStatus.SUSPICIOUS,
                             severity=Severity.MEDIUM, evidence_grade=EvidenceGrade.A, title="t", detail="d",
                             engine="claim_engine.assertion", block_id="b1")
    [out] = finalize_document_findings([finding], _doc("x", "y"), "D")
    assert out.document_id == "D" and out.page == 1 and out.bbox is not None
    assert out.confidence_features["rule_id"] == "claim_engine.assertion:DRAFT_ARTIFACT"


def test_anonymized_names_are_not_placeholders_but_bracket_blanks_are():
    text = "원고 소송대리인 변호사 ○○○ (인) 피고 제△△보병사단장 증인 김○○ 연락처 010-0000-0000"
    assert draft_artifact_findings(text) == []
    blanks = draft_artifact_findings("원고 [원고 주소 입력] 작성일 [날짜]")
    assert {f.title for f in blanks} == {"초안 흔적이 남아 있다: 각괄호 자리표시(미기재 항목)"}
    assert len(blanks) == 2


def test_masked_phone_number_is_not_a_placeholder_identifier():
    findings = scan_specimen(_doc("진 술 서", "연 락 처 010-0000-0000"))
    assert not [f for f in findings if f.type == FindingType.PLACEHOLDER_IDENTIFIER]


def test_specimen_wording_follows_the_document_kind():
    findings = scan_specimen(_doc("준 비 서 면", "이 문서는 검증 프로그램 테스트용 가상 문서(실제 사건과 무관)입니다."))
    declared = [f for f in findings if f.type == FindingType.SPECIMEN_DOCUMENT_DECLARED]
    assert declared and "실제 준비서면으로 취급" in declared[0].detail and "계약서" not in declared[0].detail
