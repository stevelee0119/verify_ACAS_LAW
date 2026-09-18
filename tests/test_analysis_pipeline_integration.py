"""Ensure structured analysis is wired into persisted run results."""
from datetime import date

from apps.api.services import link_snapshot_evidence
from packages.claim_engine import extract_claims
from packages.common.enums import JobState, VerificationStatus
from packages.common.schemas import Block, Event, NormalizedDocument, Page
from packages.pii_engine import PseudonymStore
from packages.verification_engine import pipeline as module
from packages.verification_engine.pipeline import (
    DocumentInput, DocumentResult, ProjectContext, VerificationPipeline, VerificationRunResult, _events_from,
)


def document(text, document_id="doc"):
    return NormalizedDocument(document_id, "synthetic.txt", "text/plain", "synthetic-hash",
                              pages=[Page(1, blocks=[Block("b1", text, 1)])])


def test_pipeline_preserves_project_and_run_identity(tmp_path, monkeypatch):
    doc = document("원고는 계약번호 T-1 2024. 1. 3. 계약을 체결하였다.")
    monkeypatch.setattr(module, "parse_document", lambda *args, **kw: doc)
    monkeypatch.setattr(module, "PseudonymStore", lambda project_id: PseudonymStore(project_id, root=tmp_path))
    result = VerificationPipeline().run("run-structured", ProjectContext("project-structured"),
                                       [DocumentInput("doc", "synthetic.txt", "synthetic.txt")])
    assert not result.errors
    for rows in (result.documents[0].claims, result.documents[0].events):
        assert rows and all(row["project_id"] == "project-structured" for row in rows)
        assert all(row["source_run_id"] == "run-structured" for row in rows)
    assert result.timeline[0]["transaction_id"] == "T-1"


def test_claim_only_amount_conflicts_reach_cross_check():
    docs = []
    for identifier, amount in (("d1", "100"), ("d2", "200")):
        doc = document(f"원고는 계약번호 T-1 지급번호 PAY-1 speaker_id=S target_id=T {amount}원을 지급하였다.", identifier)
        docs.append(DocumentResult(identifier, doc.filename, claims=[
            claim.to_dict() for claim in extract_claims(doc, project_id="P", source_run_id="R")]))
    result = VerificationRunResult("R", "P", JobState.COMPLETED, "key", documents=docs)
    findings = VerificationPipeline()._cross_check(result)
    assert len(findings) == 1
    assert findings[0].status == VerificationStatus.UNVERIFIED and findings[0].advisory_only
    assert findings[0].confidence_features["differences"]["amount"] == ["100", "200"]
    result.documents[1].quarantined = True
    assert VerificationPipeline()._cross_check(result) == []


def test_event_roundtrip_retains_identity_flags_and_locations():
    event = Event.create(date(2024, 1, 3), "synthetic", project_id="P", source_run_id="R",
                         document_id="d1", transaction_id="T", event_identity="PAY1", negated=True,
                         source_document_sha256="hash", span=(0, 4), amount="100", currency="KRW")
    restored = _events_from(DocumentResult("d1", "sample", events=[event.to_dict()]))[0]
    assert restored.to_dict() == event.to_dict()


def test_snapshot_evidence_matching_keeps_branch_and_page_boundaries():
    source = document("갑 제12호증의 2, 1~2쪽에 지급 내역이 있다.", "source")
    evidence = document("가상 자료", "evidence")
    source_result = DocumentResult("source", source.filename, normalized=source, claims=[
        c.to_dict() for c in extract_claims(source, project_id="P", source_run_id="R")])
    result = VerificationRunResult("R", "P", JobState.COMPLETED, "key", documents=[
        source_result, DocumentResult("evidence", evidence.filename, normalized=evidence)])
    snapshot = {"documents": [{"document_id": "evidence", "sha256": evidence.sha256,
                               "evidence_number": "갑 제12호증의 2"}]}
    link_snapshot_evidence(result, snapshot)
    match = source_result.claims[0]["evidence_matches"][0]
    assert match["status"] == "PAGE_NOT_AVAILABLE"
    assert match["candidates"][0]["document_id"] == "evidence"
    assert match["relationship"] == "UNASSESSED"
    snapshot["documents"][0]["evidence_number"] = "갑 제12호증"
    link_snapshot_evidence(result, snapshot)
    assert source_result.claims[0]["evidence_matches"][0]["status"] == "REFERENCE_MISSING"
