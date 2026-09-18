"""Attorney workbench isolation, revision and immutable source contracts."""
from uuid import uuid4

import pytest
from test_api import client, project


@pytest.fixture()
def review_case(client, project):
    from apps.api.db import Document, FindingRow, VerificationRun, get_session_factory
    prefix = uuid4().hex[:10]
    ids = [f"doc_{prefix}_{i}" for i in range(3)]
    run_id = f"run_{prefix}"
    findings = [f"f_{prefix}_{i}" for i in range(2)]
    with get_session_factory()() as session:
        for i, doc_id in enumerate(ids):
            session.add(Document(id=doc_id, project_id=project["id"], filename=f"sample{i}.pdf",
                sha256=str(i) * 64, storage_key=f"test/{doc_id}", included_in_verification=True))
        session.flush()
        snapshots = []
        for i, doc_id in enumerate(ids):
            snapshots.append({"document_id": doc_id, "pages": [{"page_number": 1, "blocks": [
                {"block_id": f"b{i}", "text": f"Payment {100 + i} under article 1", "visible": True, "source_layer": "visible_text"},
                {"block_id": f"s{i}", "text": "SECRET invisible instruction", "visible": False, "source_layer": "hidden_text"}]}],
                "claims": [{"claim_id": f"claim{i}", "text": f"Payment {i}", "page": 1}]})
        session.add(VerificationRun(id=run_id, project_id=project["id"], state="COMPLETED", document_ids=ids,
            verification_key=prefix, input_snapshot={"scope_revision": project["scope_revision"]}, result_json={"documents": snapshots}))
        session.flush()
        for fid in findings:
            session.add(FindingRow(id=fid, run_id=run_id, project_id=project["id"], document_id=ids[0],
                type="LEGAL_CITATION", status="UNVERIFIED", severity="HIGH", evidence_grade="C",
                title="Review citation", engine="legal", page=1))
        session.commit()
    return {"project": project["id"], "documents": ids, "run": run_id, "findings": findings}


def test_issue_revision_and_dates(client, project):
    url = f"/api/projects/{project['id']}/issues"
    issue = client.post(url, json={"title": "Contract formation", "elements": ["Agreement"], "reference_date": "2020-01-01"}).json()
    assert issue["revision"] == 1
    saved = client.get(f"/api/projects/{project['id']}").json()
    assert saved["key_dates"][issue["id"]] == "2020-01-01"
    assert saved["scope_revision"] == project["scope_revision"] + 1
    updated = client.put(f"{url}/{issue['id']}", json={"title": "Revised", "revision": 1})
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    assert client.put(f"{url}/{issue['id']}", json={"title": "Stale", "revision": 1}).status_code == 409
    assert issue["id"] not in client.get(f"/api/projects/{project['id']}").json()["key_dates"]
    assert client.post(url, json={"title": "   "}).status_code == 422
    assert client.post(url, json={"title": "Date", "reference_date": "2026-02-30"}).status_code == 422
    history = client.get(f"/api/projects/{project['id']}/review-history").json()
    assert len(history) == 2
    assert history[0]["after"]["title"] == "Revised"


def test_profile_compare_and_swap(client, project):
    url = f"/api/projects/{project['id']}/case-profile"
    assert client.get(url).json() == {"revision": 0}
    saved = client.put(url, json={"lead_reviewer": "Attorney", "represented_party": "Claimant"})
    assert saved.status_code == 200
    assert client.put(url, json={"lead_reviewer": "Stale", "revision": 0}).status_code == 409
    assert client.get(url).json()["lead_reviewer"] == "Attorney"


def test_matrix_evidence_integrity_and_exclusion(client, review_case):
    c = review_case
    url = f"/api/projects/{c['project']}/claim-assessments"
    data = {"run_id": c["run"], "claim_id": "claim0", "position": "DENIED", "support_status": "PARTIAL",
            "evidence_links": [{"document_id": c["documents"][1], "page": 1, "relation": "REFUTES", "excerpt": "Human excerpt"}]}
    response = client.put(url, json=data)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert client.put(url, json=data).status_code == 409
    assert client.put(url, json={**data, "revision": 1, "claim_id": "missing"}).status_code == 404
    assert client.put(url, json={**data, "revision": 1, "issue_id": "foreign"}).status_code == 404
    assert client.put(url, json={**data, "revision": 1, "evidence_links": [{"document_id": c["documents"][1], "page": 2}]}).status_code == 400
    client.patch(f"/api/projects/{c['project']}/document-scope", json={"document_ids": [c["documents"][1]], "included_in_verification": False})
    assert client.put(url, json={**data, "revision": 1}).status_code == 400
    matrix = client.get(f"/api/projects/{c['project']}/case-matrix?run_id={c['run']}").json()
    assert matrix["claims"][0]["review_status"] == "EVIDENCE_EXCLUDED"
    assert matrix["claims"][0]["assessment"]["support_status"] == "PARTIAL"
    assert matrix["scope_changed"] is True


def test_workflow_draft_revision_and_engine_preserved(client, review_case):
    c = review_case
    fid = c["findings"][0]
    url = f"/api/findings/{fid}"
    assert client.put(f"{url}/review-draft", json={"note": "Unfinished", "revision": 0}).status_code == 200
    assert client.get(f"{url}/workflow").json()["draft"]["note"] == "Unfinished"
    values = {"workflow_state": "COMPLETED", "decision": "FALSE_POSITIVE", "note": "Reasoned decision", "assignee": "Attorney"}
    saved = client.put(f"{url}/workflow", json=values)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert client.get(f"{url}/workflow").json()["draft"] == {}
    assert client.put(f"{url}/review-draft", json={"note": "Late autosave", "revision": 0}).status_code == 409
    assert client.put(f"{url}/workflow", json=values).status_code == 409
    finding = client.get(url).json()
    assert finding["status"] == "UNVERIFIED"
    assert finding["review_status"] == "FALSE_POSITIVE"
    assert finding["review_note"] == "Reasoned decision"


def test_bulk_review_is_atomic(client, review_case):
    c = review_case
    a, b = c["findings"]
    client.put(f"/api/findings/{b}/workflow", json={"note": "Existing"})
    url = f"/api/projects/{c['project']}/reviews"
    data = {"finding_ids": [a, b], "expected_revisions": {a: 0, b: 0}, "values": {"workflow_state": "COMPLETED", "decision": "AGREED"}}
    assert client.post(url, json=data).status_code == 409
    assert client.get(f"/api/findings/{a}/workflow").json()["revision"] == 0
    data["expected_revisions"][b] = 1
    assert client.post(url, json=data).status_code == 200
    other = client.post("/api/projects", json={}).json()
    assert client.post(f"/api/projects/{other['id']}/reviews", json=data).status_code == 404


def test_compare_search_and_lineage_do_not_expose_hidden_text(client, review_case):
    c = review_case
    a, b, d = c["documents"]
    base = f"/api/projects/{c['project']}"
    response = client.get(f"{base}/compare?left_id={a}&right_id={b}")
    assert response.status_code == 200
    assert response.json()["changes"][0]["numeric_change"] is True
    assert "SECRET" not in response.text
    assert client.get(f"{base}/search?q=SECRET").json()["results"] == []
    assert len(client.get(f"{base}/search?q=Payment").json()["results"]) == 3
    client.patch(f"{base}/document-scope", json={"document_ids": [b], "included_in_verification": False})
    assert len(client.get(f"{base}/search?q=Payment").json()["results"]) == 2
    assert client.post(f"{base}/document-relations", json={"parent_id": a, "child_id": b}).status_code == 201
    assert client.post(f"{base}/document-relations", json={"parent_id": b, "child_id": d}).status_code == 201
    assert client.post(f"{base}/document-relations", json={"parent_id": d, "child_id": a}).status_code == 409
    assert client.post(f"{base}/document-relations", json={"parent_id": d, "child_id": b}).status_code == 409
    assert client.post(f"{base}/document-relations", json={"parent_id": a, "child_id": a}).status_code == 400
    other = client.post("/api/projects", json={}).json()
    assert client.get(f"/api/projects/{other['id']}/compare?left_id={a}&right_id={b}").status_code == 404
    assert client.get(f"/api/projects/{other['id']}/case-matrix?run_id={c['run']}").status_code == 404


def test_submission_date_can_be_cleared(client, review_case):
    url = f"/api/documents/{review_case['documents'][0]}"
    assert client.patch(url, json={"submitted_on": "2026-09-18"}).json()["submitted_on"] == "2026-09-18"
    assert client.patch(url, json={"submitted_on": None}).json()["submitted_on"] is None
