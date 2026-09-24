"""Project trash and cross-project background progress preserve access boundaries."""
from datetime import datetime, timedelta

import pytest

from apps.api.db import AuditEventRow, Document, Project, VerificationRun
from apps.api.job_control import DurableJob, JobConflict, JobStore, enqueue_run, execution_security
from apps.api.routers import jobs, verification
from test_auth_merge import merged_auth  # noqa: F401


@pytest.fixture
def workspace(merged_auth):
    s = merged_auth
    s.app.include_router(jobs.router, prefix="/api")
    s.app.include_router(verification.router, prefix="/api")
    with s.factory() as session:
        session.add(Document(id="document", project_id="pa", filename="evidence.pdf", sha256="a" * 64,
                             storage_key="immutable/original", size_bytes=123))
        session.commit()
    return s


def add_run(s, identifier, project="pa", state="COMPLETED", finished=None):
    with s.factory() as session:
        session.add(VerificationRun(id=identifier, project_id=project, state=state,
                                   document_ids=["document"] if project == "pa" else [],
                                   profile="STANDARD", verification_key=identifier,
                                   finished_at=finished or (datetime.utcnow() if state == "COMPLETED" else None),
                                   result_json={"private_content": "must not appear in job summaries"}))
        session.commit()


def test_trash_hides_resources_and_restore_preserves_originals_and_results(workspace):
    s = workspace
    add_run(s, "complete")
    headers = s.headers("admin")
    assert s.client.delete("/api/projects/pa", headers=headers).status_code == 204
    assert "pa" not in {p["id"] for p in s.client.get("/api/projects", headers=headers).json()}
    for path in ("/api/projects/pa", "/api/projects/pa/documents", "/api/documents/document",
                 "/api/verification-runs/complete", "/api/verification-runs/complete/result"):
        assert s.client.get(path, headers=headers).status_code == 404
    assert s.client.post("/api/projects/pa/verify", headers=headers).status_code == 404
    trash = s.client.get("/api/projects?deleted=true", headers=headers).json()
    assert [(p["id"], p["can_delete"], p["document_count"]) for p in trash] == [("pa", True, 1)]
    assert trash[0]["deleted_at"]
    assert s.client.delete("/api/projects/pa", headers=headers).status_code == 204
    with s.factory() as session:
        assert session.get(Project, "pa").deleted_by == "admin"
        assert session.get(Document, "document").storage_key == "immutable/original"
        assert session.get(VerificationRun, "complete").result_json["private_content"]
        audit_count = session.query(AuditEventRow).count()
        assert audit_count == 1
    restored = s.client.post("/api/projects/pa/restore", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert s.client.get("/api/projects?deleted=true", headers=headers).json() == []
    assert s.client.get("/api/documents/document", headers=headers).status_code == 200
    assert s.client.get("/api/verification-runs/complete/result", headers=headers).json()["private_content"]
    assert s.client.post("/api/projects/pa/restore", headers=headers).status_code == 200
    with s.factory() as session:
        assert session.query(AuditEventRow).count() == audit_count + 1


@pytest.mark.parametrize("user,status", [("member", 403), ("viewer", 403), ("other", 404)])
def test_only_project_administrators_can_delete_or_restore(workspace, user, status):
    s = workspace
    assert s.client.delete("/api/projects/pa", headers=s.headers(user)).status_code == status
    s.client.delete("/api/projects/pa", headers=s.headers("admin"))
    assert s.client.get("/api/projects?deleted=true", headers=s.headers(user)).json() == []
    assert s.client.post("/api/projects/pa/restore", headers=s.headers(user)).status_code == status


def test_member_can_delete_own_project_and_cannot_inject_deletion_fields(workspace):
    s = workspace
    headers = s.headers("member")
    created = s.client.post("/api/projects", headers=headers, json={"name": "Mine", "deleted_at": "2026-01-01"}).json()
    assert created["can_delete"] and created["deleted_at"] is None
    assert s.client.delete(f"/api/projects/{created['id']}", headers=headers).status_code == 204
    assert s.client.post(f"/api/projects/{created['id']}/restore", headers=headers).status_code == 200


@pytest.mark.parametrize("state", ["QUEUED", "VERIFYING", "RUNNING", "EXTRACTING"])
def test_active_run_prevents_deletion(workspace, state):
    s = workspace
    add_run(s, "active", state=state)
    response = s.client.delete("/api/projects/pa", headers=s.headers("admin"))
    assert response.status_code == 409
    with s.factory() as session:
        assert session.get(Project, "pa").deleted_at is None
        assert session.get(Document, "document") is not None


def test_pending_durable_job_also_prevents_deletion(workspace):
    s = workspace
    add_run(s, "recovering", state="FAILED")
    with s.factory() as session:
        session.add(DurableJob(run_id="recovering", project_id="pa", state="BACKOFF", snapshot={},
                               snapshot_hash="a" * 64, budget_run_id="recovering"))
        session.commit()
    assert s.client.delete("/api/projects/pa", headers=s.headers("admin")).status_code == 409


def test_cookie_deletion_and_restoration_require_origin(workspace):
    s = workspace
    s.client.cookies.set("lv_session", "legacy-session-admin", domain="testserver.local", path="/")
    assert s.client.delete("/api/projects/pa").status_code == 403
    assert s.client.delete("/api/projects/pa", headers={"Origin": "https://testserver"}).status_code == 204
    assert s.client.post("/api/projects/pa/restore").status_code == 403
    assert s.client.post("/api/projects/pa/restore", headers={"Origin": "https://testserver"}).status_code == 200


def test_deleted_project_rejects_new_jobs_retries_and_worker_execution(workspace):
    s = workspace
    add_run(s, "failed", state="FAILED")
    s.client.delete("/api/projects/pa", headers=s.headers("admin"))
    with s.factory() as session:
        with pytest.raises(JobConflict):
            execution_security(session, "pa", "LOCAL_ONLY")
        with pytest.raises(JobConflict):
            enqueue_run(session, VerificationRun(project_id="pa", verification_key="new", state="QUEUED"))
    with pytest.raises(JobConflict):
        JobStore(s.factory).retry("failed")


def test_background_summary_is_scoped_compact_and_survives_project_switches(workspace):
    s = workspace
    add_run(s, "mine-active", state="VERIFYING")
    add_run(s, "other-org", project="pb", state="VERIFYING")
    add_run(s, "private", project="private", state="VERIFYING")
    add_run(s, "recent-done")
    add_run(s, "old-done", finished=datetime.utcnow() - timedelta(days=2))
    response = s.client.get("/api/verification-runs", headers=s.headers("member"))
    assert response.status_code == 200
    data = response.json()
    assert data["active_count"] == 1
    assert [row["id"] for row in data["runs"]] == ["mine-active", "recent-done"]
    assert "private_content" not in response.text and "input_snapshot" not in response.text
    assert s.client.get("/api/verification-runs?limit=0", headers=s.headers("member")).status_code == 422
    limited = s.client.get("/api/verification-runs?limit=1", headers=s.headers("member")).json()
    assert limited["active_count"] == 1 and len(limited["runs"]) == 1
    with s.factory() as session:
        session.get(VerificationRun, "mine-active").state = "COMPLETED"
        session.get(VerificationRun, "mine-active").finished_at = datetime.utcnow()
        session.commit()
    assert s.client.delete("/api/projects/pa", headers=s.headers("admin")).status_code == 204
    assert s.client.get("/api/verification-runs", headers=s.headers("member")).json() == {"active_count": 0, "runs": []}


# --- 휴지통에서 영구 삭제 ---------------------------------------------------------
@pytest.fixture
def purge_case(workspace, tmp_path, monkeypatch):
    """두 프로젝트에 자료·실행·판정·보고서와 저장 파일을 두고 한쪽만 영구 삭제한다."""
    from apps.api import project_purge
    from apps.api.db import EvidenceRow, FindingRow, ReportRow
    from packages.common.storage import LocalObjectStorage

    storage = LocalObjectStorage(tmp_path / "storage")
    monkeypatch.setattr(project_purge, "get_storage", lambda: storage)
    monkeypatch.setenv("LV_DATA_DIR", str(tmp_path))
    s = workspace
    add_run(s, "run-a")
    add_run(s, "run-b", project="pb")
    with s.factory() as session:
        session.add_all([
            FindingRow(id="f-a", run_id="run-a", project_id="pa", document_id="document", type="CASE_NOT_FOUND",
                       status="UNVERIFIED", severity="HIGH", evidence_grade="U", title="t", data={}),
            FindingRow(id="f-b", run_id="run-b", project_id="pb", type="CASE_NOT_FOUND",
                       status="UNVERIFIED", severity="HIGH", evidence_grade="U", title="t", data={}),
            ReportRow(id="rpt-a", project_id="pa", run_id="run-a", formats=["json"]),
        ])
        session.flush()
        session.add(EvidenceRow(id="ev-a", finding_id="f-a", data={}))
        session.commit()
    kept = [storage.put_original("pa/aaaa.pdf", b"original"), storage.put_derivative("pa/rpt-a/r.json", b"{}"),
            storage.put_original("pb/bbbb.pdf", b"other project")]
    vault = tmp_path / "pii_vault"
    vault.mkdir()
    (vault / "pa.vault").write_bytes(b"x")
    (vault / "pb.vault").write_bytes(b"y")
    return s, storage, kept, vault


def test_purge_requires_the_project_to_be_in_the_trash(purge_case):
    s, storage, kept, _ = purge_case
    response = s.client.delete("/api/projects/pa/purge", headers=s.headers("admin"))
    assert response.status_code == 409 and "휴지통" in response.json()["detail"]
    assert storage.exists(kept[0])


def test_purge_removes_the_project_rows_and_files_but_keeps_audit_and_other_projects(purge_case):
    from apps.api.db import EvidenceRow, FindingRow, ReportRow
    s, storage, kept, vault = purge_case
    headers = s.headers("admin")
    assert s.client.delete("/api/projects/pa", headers=headers).status_code == 204
    with s.factory() as session:
        audit_before = session.query(AuditEventRow).count()
    response = s.client.delete("/api/projects/pa/purge", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purged"] and body["files_removed"] == 2 and body["file_errors"] == []
    assert body["rows"]["projects"] == 1 and body["rows"]["findings"] == 1 and body["rows"]["evidence"] == 1
    with s.factory() as session:
        assert session.get(Project, "pa") is None and session.get(Document, "document") is None
        assert session.get(VerificationRun, "run-a") is None and session.get(ReportRow, "rpt-a") is None
        assert session.query(EvidenceRow).count() == 0
        # 다른 프로젝트는 그대로다.
        assert session.get(Project, "pb") and session.get(VerificationRun, "run-b") and session.get(FindingRow, "f-b")
        # 감사기록은 지우지 않고 영구 삭제 사실을 하나 더 남긴다.
        events = session.query(AuditEventRow).order_by(AuditEventRow.sequence).all()
        assert len(events) == audit_before + 1
        assert events[-1].event_type == "DELETE" and events[-1].payload["action"] == "PROJECT_PURGED"
    assert not storage.exists(kept[0]) and not storage.exists(kept[1]) and storage.exists(kept[2])
    assert not (vault / "pa.vault").exists() and (vault / "pb.vault").exists()
    assert s.client.get("/api/projects?deleted=true", headers=headers).json() == []
    assert s.client.delete("/api/projects/pa/purge", headers=headers).status_code == 404


@pytest.mark.parametrize("user,status", [("member", 403), ("viewer", 403), ("other", 404)])
def test_only_project_administrators_can_purge(purge_case, user, status):
    s, storage, kept, _ = purge_case
    s.client.delete("/api/projects/pa", headers=s.headers("admin"))
    assert s.client.delete("/api/projects/pa/purge", headers=s.headers(user)).status_code == status
    with s.factory() as session:
        assert session.get(Project, "pa") is not None
    assert storage.exists(kept[0])
