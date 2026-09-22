"""Server-owned work leases survive idle expiry without weakening revocation."""
import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from apps.api import identity
from apps.api.db import Document, Project, ProjectMember, SessionToken, User, VerificationRun
from apps.api.identity import AnalysisSessionLease
from apps.api.routers import jobs, verification
from test_auth_merge import merged_auth  # noqa: F401
from test_session_activity import clock  # noqa: F401


@pytest.fixture
def workspace(merged_auth, clock, monkeypatch):
    s = merged_auth
    monkeypatch.setenv("LV_ANALYSIS_SESSION_HOURS", "168")
    monkeypatch.setenv("LV_ANALYSIS_RESULT_HOURS", "24")
    s.app.include_router(jobs.router, prefix="/api")
    s.app.include_router(verification.router, prefix="/api")
    monkeypatch.setattr(verification, "get_runner", lambda: SimpleNamespace(submit=lambda _: None))
    with s.factory() as session:
        row = session.get(SessionToken, "old-member")
        row.issued_at = clock.utcnow() - timedelta(days=7) + timedelta(minutes=1)
        row.expires_at = clock.utcnow() + timedelta(minutes=1)
        session.add(Document(id="doc", project_id="pa", filename="synthetic.pdf", sha256="a" * 64,
                             storage_key="synthetic.pdf", mime_type="application/pdf", size_bytes=100))
        session.commit()
    s.client.cookies.set("lv_session", "legacy-session-member", domain="testserver.local", path="/")
    return s


def active_run(s, clock, identifier="run", project="pa"):
    with s.factory() as session:
        session.add(VerificationRun(id=identifier, project_id=project, state="VERIFYING",
                                   started_at=clock.utcnow(), document_ids=[], verification_key=identifier,
                                   result_json={"documents": [], "test_result": True}))
        session.commit()
    return identifier


def protect(s, run="run", **kwargs):
    return s.client.post(f"/api/verification-runs/{run}/session",
                         headers={"Origin": "https://testserver"}, **kwargs)


def test_verification_start_binds_session_before_dispatch_and_survives_absence(workspace, clock):
    s = workspace
    response = s.client.post("/api/projects/pa/verify", json={}, headers={"Origin": "https://testserver"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert "credential_id" not in response.text
    assert "Max-Age=691" in response.headers["set-cookie"]
    with s.factory() as session:
        lease = session.get(AnalysisSessionLease, ("password", "old-member", run_id))
        assert lease is not None and lease.user_id == "member"
    # No requests or worker heartbeats during this simulated two-day absence.
    clock.now_value += timedelta(days=2)
    for path in (f"/api/verification-runs/{run_id}", f"/api/verification-runs/{run_id}/result"):
        assert s.client.get(path).status_code == 200
    with s.factory() as session:
        assert session.get(SessionToken, "old-member").expires_at < clock.utcnow()
        run = session.get(VerificationRun, run_id)
        run.state, run.finished_at = "COMPLETED", clock.utcnow()
        session.commit()
    clock.now_value += timedelta(hours=23)
    assert s.client.get(f"/api/verification-runs/{run_id}/result").status_code == 200
    clock.now_value += timedelta(hours=2)
    assert s.client.get(f"/api/verification-runs/{run_id}/result").status_code == 401


def test_existing_run_binding_is_idempotent_and_cannot_target_other_sessions(workspace, clock):
    s = workspace
    active_run(s, clock)
    assert protect(s, json={"user_id": "admin", "credential_id": "old-admin"}).json() == {"protected": True}
    with s.factory() as session:
        original = session.query(AnalysisSessionLease).one().active_until
    clock.now_value += timedelta(hours=2)
    assert protect(s).status_code == 200
    with s.factory() as session:
        lease = session.query(AnalysisSessionLease).one()
        assert lease.credential_id == "old-member" and lease.active_until == original
    assert s.client.get("/api/identity/me", headers=s.headers("admin")).status_code == 401


@pytest.mark.parametrize("change", ["logout", "password", "disabled", "revoked", "membership", "organization", "trashed"])
def test_work_protection_does_not_override_security_changes(workspace, clock, change):
    s = workspace
    active_run(s, clock)
    assert protect(s).status_code == 200
    clock.now_value += timedelta(hours=2)
    if change == "logout":
        assert s.client.delete("/api/identity/session", headers={"Origin": "https://testserver"}).status_code == 204
    else:
        with s.factory() as session:
            if change == "password":
                identity.revoke_user_credentials(session, "member")
            elif change == "disabled":
                identity.set_account_enabled(session, session.get(User, "member"), False)
            elif change == "revoked":
                session.get(SessionToken, "old-member").revoked_at = clock.utcnow()
            elif change == "membership":
                session.query(ProjectMember).filter_by(project_id="pa", user_id="member").delete()
            elif change == "organization":
                session.get(User, "member").organization_id = "ob"
            else:
                session.get(Project, "pa").deleted_at = clock.utcnow()
            session.commit()
    assert s.client.get("/api/identity/me", headers=s.headers("member")).status_code == 401


def test_finished_run_cannot_create_new_protection_and_csrf_is_required(workspace, clock):
    s = workspace
    active_run(s, clock)
    assert s.client.post("/api/verification-runs/run/session").status_code == 403
    assert s.client.post("/api/verification-runs/run/session", headers={"Origin": "https://evil.invalid"}).status_code == 403
    active_run(s, clock, "foreign", project="pb")
    assert protect(s, "foreign").status_code == 404
    with s.factory() as session:
        session.get(VerificationRun, "run").state = "COMPLETED"
        session.get(VerificationRun, "run").finished_at = clock.utcnow()
        session.commit()
    assert protect(s).json() == {"protected": False}
    clock.now_value += timedelta(hours=2)
    assert protect(s).status_code == 401
    with s.factory() as session:
        assert session.query(AnalysisSessionLease).count() == 0


def test_stuck_work_has_a_fixed_bound_and_late_finish_cannot_revive_session(workspace, clock):
    s = workspace
    active_run(s, clock)
    assert protect(s).status_code == 200
    clock.now_value += timedelta(days=7, seconds=1)
    assert s.client.get("/api/identity/me").status_code == 401
    with s.factory() as session:
        run = session.get(VerificationRun, "run")
        run.state, run.finished_at = "COMPLETED", clock.utcnow()
        session.commit()
    assert s.client.get("/api/identity/me").status_code == 401


def test_another_pending_run_keeps_session_after_first_finishes(workspace, clock):
    s = workspace
    for run in ("first", "second"):
        active_run(s, clock, run)
        assert protect(s, run).status_code == 200
    with s.factory() as session:
        run = session.get(VerificationRun, "first")
        run.state, run.finished_at = "CANCELLED", clock.utcnow()
        session.commit()
    clock.now_value += timedelta(days=2)
    assert s.client.get("/api/identity/me").status_code == 200


def test_password_backed_browser_session_protects_source_and_browser(workspace, clock):
    s = workspace
    assert s.client.post("/api/identity/session", headers=s.headers("member")).status_code == 200
    active_run(s, clock)
    assert protect(s).json() == {"protected": True}
    with s.factory() as session:
        assert {row.credential_kind for row in session.scalars(select(AnalysisSessionLease))} == {"password", "session"}
    clock.now_value += timedelta(days=2)
    assert s.client.get("/api/identity/me").status_code == 200
    with s.factory() as session:
        session.get(SessionToken, "old-member").revoked_at = clock.utcnow()
        session.commit()
    assert s.client.get("/api/identity/me").status_code == 401


def test_active_work_does_not_keep_another_login_of_same_user_alive(workspace, clock):
    s = workspace
    active_run(s, clock)
    assert protect(s).status_code == 200
    with s.factory() as session:
        session.add(SessionToken(id="other-login", user_id="member", issued_at=clock.utcnow(),
                                 token_hash=hashlib.sha256(b"other-login-secret").hexdigest(),
                                 expires_at=clock.utcnow() + timedelta(minutes=1)))
        session.commit()
    clock.now_value += timedelta(hours=2)
    assert s.client.get("/api/identity/me").status_code == 200
    assert s.client.get("/api/identity/me", headers={"Authorization": "Bearer other-login-secret"}).status_code == 401


def test_protected_idle_session_can_resume_normal_activity_without_extending_absolute_limit(workspace, clock):
    s = workspace
    with s.factory() as session:
        session.get(SessionToken, "old-member").issued_at = clock.utcnow()
        session.commit()
    active_run(s, clock)
    assert protect(s).status_code == 200
    clock.now_value += timedelta(days=2)
    assert s.client.get("/api/identity/me").status_code == 200
    with s.factory() as session:
        assert session.get(SessionToken, "old-member").expires_at == clock.utcnow() + timedelta(hours=12)


def test_source_token_expiry_is_not_overridden_by_work(workspace, clock):
    s = workspace
    with s.factory() as session:
        token, secret = identity.issue_token(session, "member")
        token.expires_at = clock.utcnow() + timedelta(minutes=1)
        session.commit()
    assert s.client.post("/api/identity/session", headers={"Authorization": "Bearer " + secret}).status_code == 200
    active_run(s, clock)
    assert protect(s).json() == {"protected": False}
    clock.now_value += timedelta(hours=2)
    assert s.client.get("/api/identity/me").status_code == 401


def test_readonly_reviewer_can_protect_own_session_without_edit_permission(workspace, clock):
    s = workspace
    active_run(s, clock)
    headers = {**s.headers("viewer"), "Origin": "https://testserver"}
    assert s.client.post("/api/verification-runs/run/session", headers=headers).json() == {"protected": True}
    assert s.client.post("/api/projects/pa/verify", headers=headers).status_code == 403
    clock.now_value += timedelta(hours=2)
    assert s.client.get("/api/verification-runs/run", headers=s.headers("viewer")).status_code == 200


def test_retry_binds_the_authenticated_session_before_dispatch(workspace, clock, monkeypatch):
    from apps.api.job_control import DurableJob, JobStore

    s = workspace
    response = s.client.post("/api/projects/pa/verify", json={}, headers={"Origin": "https://testserver"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    with s.factory() as session:
        run = session.get(VerificationRun, run_id)
        run.state, run.finished_at = "FAILED", clock.utcnow()
        session.get(DurableJob, run_id).state = "FAILED"
        session.commit()
    monkeypatch.setattr(jobs, "JobStore", lambda: JobStore(s.factory))
    dispatched = []

    def submit(child_id):
        with s.factory() as session:
            assert session.get(AnalysisSessionLease, ("password", "old-member", child_id)) is not None
        dispatched.append(child_id)

    monkeypatch.setattr(jobs, "get_runner", lambda: SimpleNamespace(submit=submit))
    clock.now_value += timedelta(hours=2)
    response = s.client.post(f"/api/verification-runs/{run_id}/retry", headers={"Origin": "https://testserver"})
    assert response.status_code == 202, response.text
    child_id = response.json()["id"]
    assert dispatched == [child_id] and child_id != run_id
    clock.now_value += timedelta(days=2)
    assert s.client.get(f"/api/verification-runs/{child_id}").status_code == 200


def test_lease_storage_on_configured_database(clock, monkeypatch):
    """Exercise the actual PostgreSQL dialect in CI, SQLite on local runs."""
    from fastapi import HTTPException
    from apps.api.db import Organization, get_session_factory, init_db, new_uuid

    monkeypatch.setenv("LV_ANALYSIS_SESSION_HOURS", "168")
    monkeypatch.setenv("LV_ANALYSIS_RESULT_HOURS", "24")
    init_db()
    with get_session_factory()() as session:
        org = Organization(id=new_uuid("org_"), name="Analysis session test")
        session.add(org)
        session.flush()
        user = User(id=new_uuid("usr_"), email=new_uuid() + "@example.invalid",
                    organization_id=org.id, role="MEMBER", is_active=True)
        session.add(user)
        session.flush()
        session.add(identity.IdentityAccount(user_id=user.id, enabled=True))
        project = Project(id=new_uuid("prj_"), name="Lease test", owner_id=user.id, organization_id=org.id)
        secret = new_uuid("test_secret_")
        credential = SessionToken(id=new_uuid("ses_"), user_id=user.id,
                                  token_hash=hashlib.sha256(secret.encode("ascii")).hexdigest(),
                                  issued_at=clock.utcnow() - timedelta(days=7) + timedelta(minutes=1),
                                  expires_at=clock.utcnow() + timedelta(minutes=1))
        session.add_all([project, credential])
        session.flush()
        run = VerificationRun(id=new_uuid("run_"), project_id=project.id, state="VERIFYING",
                              started_at=clock.utcnow(), document_ids=[])
        session.add(run)
        session.flush()
        principal = identity.authenticate_password_session(session, secret)
        for _ in range(2):
            assert identity.bind_analysis_session(session, run, principal)
        assert len(list(session.scalars(select(AnalysisSessionLease).where(
            AnalysisSessionLease.run_id == run.id)))) == 1
        clock.now_value += timedelta(days=2)
        assert identity.authenticate_password_session(session, secret).user_id == user.id
        credential.revoked_at = clock.utcnow()
        session.flush()
        with pytest.raises(HTTPException) as error:
            identity.authenticate_password_session(session, secret)
        assert error.value.status_code == 401
        session.rollback()
