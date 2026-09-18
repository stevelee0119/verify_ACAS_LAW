"""Regression contracts for the attorney workspace and conservative verification."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from test_api import client, project, upload, run_and_wait
from helpers import make_pdf
from packages.claim_engine.calculation import parse_amounts
from packages.claim_engine.contradiction import analyze_timeline, cross_document_contradictions
from packages.common.enums import ExternalAIPolicy, VerificationProfile, VerificationStatus, EvidenceGrade
from packages.common.schemas import Event
from packages.pii_engine import PseudonymStore, PIIEngine


@pytest.mark.parametrize("text,value", [("1억 5천만 원", "150000000"), ("1.5억 원", "150000000"),
    ("-100원", "-100"), ("금 2억 3천만 4백만 5천 원", "234005000"), ("1,234.50원", "1234.50")])
def test_compound_signed_decimal_amounts(text, value):
    assert [a.value for a in parse_amounts(text)] == [Decimal(value)]


def test_default_project_no_typing_and_retry(client):
    defaults = client.get("/api/project-defaults").json()
    assert defaults["name"] and defaults["external_ai_policy"] == "LOCAL_ONLY"
    assert defaults["incident_date"] is None and defaults["parties"] == []
    first = client.post("/api/projects", json=defaults).json()
    second = client.post("/api/projects", json=defaults).json()
    assert first["id"] == second["id"]
    assert client.post("/api/projects", json={}).json()["name"]
    assert client.post("/api/projects", json={"incident_date": "2026-02-30"}).status_code == 422


def test_scope_is_reversible_and_rejects_foreign_documents(client, project, tmp_path, monkeypatch):
    from apps.api.services import get_runner
    monkeypatch.setattr(get_runner(), "submit", lambda run_id: None)
    d = upload(client, project["id"], make_pdf(tmp_path / "scope.pdf", ["검토 자료"])).json()
    base = client.get(f"/api/projects/{project['id']}").json()["scope_revision"]
    url = f"/api/projects/{project['id']}/document-scope"
    response = client.patch(url, json={"document_ids": [d["id"]], "included_in_verification": False, "exclusion_reason": "중복 증거"})
    assert response.status_code == 200 and not response.json()[0]["included_in_verification"]
    assert client.get(f"/api/projects/{project['id']}").json()["scope_revision"] == base + 1
    assert client.post(f"/api/projects/{project['id']}/verify", json={}).status_code == 400
    assert client.get(f"/api/documents/{d['id']}/original").status_code == 200
    assert not upload(client, project["id"], tmp_path / "scope.pdf").json()["included_in_verification"]
    client.patch(url, json={"document_ids": [d["id"]], "included_in_verification": True})
    assert client.post(f"/api/projects/{project['id']}/verify", json={"document_ids": []}).status_code == 400
    run = client.post(f"/api/projects/{project['id']}/verify", json={"profile": "QUICK"}).json()
    assert run["document_ids"] == [d["id"]]
    assert run["input_snapshot"]["context"]["profile"] == "QUICK"
    other = client.post("/api/projects", json={}).json()
    assert client.post(f"/api/projects/{other['id']}/verify", json={"document_ids": [d["id"]]}).status_code == 404
    assert client.patch(f"/api/projects/{other['id']}/document-scope", json={"document_ids": [d["id"]], "included_in_verification": False}).status_code == 404
    client.patch(url, json={"document_ids": [d["id"]], "included_in_verification": False})
    saved = client.get(f"/api/verification-runs/{run['id']}").json()
    assert saved["document_ids"] == [d["id"]] and saved["input_snapshot"] == run["input_snapshot"]


def test_report_snapshot_and_viewer(client, project, tmp_path):
    d = upload(client, project["id"], make_pdf(tmp_path / "자료.pdf", ["원고는 2020. 3. 15. 계약을 체결하였다."])).json()
    run = run_and_wait(client, f"/api/documents/{d['id']}/verify")
    assert run["state"] in ("COMPLETED", "PARTIAL_COMPLETED"), run["errors"]
    result = client.get(f"/api/verification-runs/{run['id']}/result").json()
    assert result["documents"][0]["pages"][0]["blocks"]
    assert run["timeline"]
    image = client.get(f"/api/documents/{d['id']}/pages/1.png")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{d['id']}/pages/0.png").status_code == 404
    original = client.get(f"/api/documents/{d['id']}/original")
    assert "filename*=UTF-8" in original.headers["content-disposition"]
    report = client.post(f"/api/projects/{project['id']}/reports", json={"run_id": run["id"], "formats": ["pdf", "json", "xlsx"]})
    assert report.status_code == 201
    for item in report.json()["artifacts"].values():
        assert "error" not in item, item
    exported = client.get(report.json()["artifacts"]["json"]["download"]).json()
    assert exported["input_snapshot"] == run["input_snapshot"]
    assert exported["product"] == "ACAS_LAW Verifier"
    other = client.post("/api/projects", json={}).json()
    assert client.post(f"/api/projects/{other['id']}/reports", json={"run_id": run["id"]}).status_code == 404
    assert client.post(f"/api/projects/{project['id']}/reports", json={"run_id": run["id"], "include_sealed": True}).status_code == 403


def test_partial_result_not_reused(client, project):
    from apps.api.db import VerificationRun, get_session_factory
    from apps.api.services import find_reusable_run
    with get_session_factory()() as session:
        session.add(VerificationRun(project_id=project["id"], state="PARTIAL_COMPLETED", verification_key="partial", document_ids=[]))
        session.commit()
        assert find_reusable_run(session, project["id"], "partial") is None


def test_interest_boundaries(client):
    data = {"principal": "100000000", "rate": "5", "start": "2024-01-01", "end": "2025-01-01"}
    response = client.post("/api/calculations/interest", json=data).json()
    assert response["days"] == 366 and response["interest"] == "5013699"
    assert client.post("/api/calculations/interest", json={**data, "end": "2023-01-01"}).status_code == 422
    assert client.post("/api/calculations/interest", json={**data, "principal": "NaN"}).status_code == 422


def test_workspace_boundary(client, monkeypatch):
    assert client.get("/api/projects", headers={"host": "evil.example"}).status_code == 403
    assert client.post("/api/projects", json={}, headers={"origin": "https://evil.example"}).status_code == 403
    monkeypatch.setenv("LV_ACCESS_TOKEN", "test-owner-token")
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers={"authorization": "Bearer test-owner-token"}).status_code == 200


def test_vault_authentication_and_concurrent_handles(tmp_path):
    a = PseudonymStore("secure", root=tmp_path)
    b = PseudonymStore("secure", root=tmp_path)
    one = a.pseudonym_for("PERSON", "홍길동")
    two = b.pseudonym_for("PERSON", "김철수")
    a.save()
    assert one != two
    vault = tmp_path / "secure.vault"
    assert vault.read_bytes().startswith(b"ACAS2:")
    reloaded = PseudonymStore("secure", root=tmp_path)
    assert reloaded.original_for(two) == "김철수"
    corrupted = vault.read_bytes()[:-8] + b"AAAAAAAA"
    vault.write_bytes(corrupted)
    with pytest.raises(ValueError, match="무결성"):
        PseudonymStore("secure", root=tmp_path)
    assert vault.read_bytes() == corrupted


def test_unrelated_contracts_not_marked_contradictory():
    first = Event.create(date(2020,1,1), "계약 체결", event_kind="CONTRACT", document_id="a")
    second = Event.create(date(2021,1,1), "계약 체결", event_kind="CONTRACT", document_id="b")
    assert cross_document_contradictions({"a": [first], "b": [second]}) == []
    payment = Event.create(date(2019,1,1), "선급금 지급", event_kind="PAYMENT")
    assert analyze_timeline([first, payment]) == []


def test_repeated_citations_preserve_occurrences():
    from test_pii_and_claims import make_doc
    from packages.legal_engine import extract_citations
    citations = extract_citations(make_doc("대법원 2024. 1. 15. 선고 2023도12345 판결", "대법원 2024. 1. 15. 선고 2023도12345 판결", "10.1234/alpha 10.1234/beta"))
    assert len([c for c in citations if c.case_number]) == 2
    assert {c.doi for c in citations if c.doi} == {"10.1234/alpha", "10.1234/beta"}


def test_mixed_pdf_page_scope(tmp_path):
    from reportlab.pdfgen import canvas
    from packages.document_engine import parse_document
    from packages.document_engine.ocr import get_ocr_adapter, set_ocr_adapter, NullOCRAdapter
    path = tmp_path / "mixed.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(20, 700, "Readable page")
    pdf.showPage()
    pdf.rect(20,20,100,100,fill=1)
    pdf.save()
    original = get_ocr_adapter()
    try:
        set_ocr_adapter(NullOCRAdapter())
        doc = parse_document(str(path), document_id="mixed", filename=path.name, mime_type="application/pdf", sha256="test")
        coverage = doc.structure["page_coverage"]
        assert coverage[0]["status"] == "EXTRACTED"
        assert coverage[1]["status"] == "UNVERIFIED"
    finally:
        set_ocr_adapter(original)


def test_semantic_review_masks_and_requires_source_quotes(tmp_path, registry):
    from packages.verification_engine.pipeline import VerificationPipeline, DocumentResult, ProjectContext
    from packages.legal_engine import extract_from_text
    from packages.llm_router.router import CascadeOutcome, ModelExecution
    citations = extract_from_text('대법원 2024. 1. 15. 선고 2023도12345 판결. 원고 홍길동 연락처 010-1234-5678')
    citation = citations[0]
    observed = []
    class Router:
        async def cascade(self, **kwargs):
            observed.append(kwargs)
            return CascadeOutcome(VerificationStatus.PARTIALLY_VERIFIED, EvidenceGrade.D, "참고 검토",
                stages=[{"used":True,"verdict":{"evidence_quotes":["실제 판결 문구"]}}],
                executions=[ModelExecution("PRIMARY_REASONER", "stub", "test", True)])
    pipeline = VerificationPipeline(registry=registry, router=Router())
    result = DocumentResult("d", "sample")
    result.engine_data["legal_verdicts"] = [{"citation_id":citation.citation_id,"levels":{"level4":"PENDING_LLM"},"official_record":{"full_text":"실제 판결 문구"}}]
    context = ProjectContext("semantic-test",external_ai_policy=ExternalAIPolicy.MASKED)
    pipeline._semantic_review(result,citations,context,PIIEngine(PseudonymStore("semantic-test",root=tmp_path)))
    assert len(observed)==1
    assert "홍길동" not in observed[0]["evidence"]["document"]
    assert "010-1234-5678" not in observed[0]["evidence"]["document"]
    assert result.engine_data["semantic_reviews"][0]["source_quotes_validated"]
    assert result.engine_data["semantic_reviews"][0]["status"]=="UNVERIFIED"
    result.quarantined=True
    pipeline._semantic_review(result,citations,context,PIIEngine(PseudonymStore("semantic-test",root=tmp_path)))
    assert len(observed)==1
