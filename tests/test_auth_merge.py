"""Password/identity merge regressions. Synthetic credentials; no live SSO/network."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import access, auth, identity
from apps.api.db import (AuditEventRow, Base, Organization, Project, ProjectMember,
                         SessionToken, User, get_db)
from apps.api.routers import auth_router, identity as identity_router

PASSWORD = "merge-test-password-1234"


@pytest.fixture
def merged_auth(monkeypatch):
    from apps.api.routers import projects

    for name in ("LV_ACCESS_TOKEN", "LV_PUBLIC_ORIGIN", "LV_TRUSTED_PROXY_IPS", "LV_OIDC_ISSUER",
                 "LV_OIDC_AUDIENCE", "LV_OIDC_JWKS_URL", "LV_OIDC_ALGORITHMS", "RENDER",
                 "RENDER_SERVICE_ID", "RENDER_EXTERNAL_HOSTNAME", "K_SERVICE", "WEBSITE_SITE_NAME", "DYNO",
                 "LV_BOOTSTRAP_ADMIN_EMAIL", "LV_BOOTSTRAP_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(access, "get_session_factory", lambda: factory)
    password_hash = auth.hash_password(PASSWORD)
    with factory() as session:
        session.add_all([Organization(id="oa", name="A"), Organization(id="ob", name="B")])
        session.flush()
        for name, role, org in (("admin", "ADMIN", "oa"), ("member", "MEMBER", "oa"),
                                ("viewer", "VIEWER", "oa"), ("other", "ADMIN", "ob"),
                                ("unassigned", "ADMIN", None)):
            session.add(User(id=name, email=name + "@example.invalid", role=role, organization_id=org,
                             password_hash=password_hash, is_active=True))
            session.add(SessionToken(id="old-" + name, user_id=name,
                token_hash=hashlib.sha256(("legacy-session-" + name).encode()).hexdigest(),
                expires_at=datetime.utcnow() + timedelta(hours=1)))
        session.add_all([Project(id="pa", name="A", organization_id="oa", owner_id="admin"),
                         Project(id="pb", name="B", organization_id="ob", owner_id="other"),
                         Project(id="private", name="Private", organization_id="oa", owner_id="admin"),
                         Project(id="orphan", name="Local legacy"),
                         Project(id="owned-null", name="Legacy owned", owner_id="unassigned")])
        session.flush()
        session.add_all([ProjectMember(project_id="pa", user_id="member", role="MEMBER"),
                         ProjectMember(project_id="pa", user_id="viewer", role="ADMIN"),
                         ProjectMember(project_id="pb", user_id="member", role="ADMIN")])
        session.commit()
    app = FastAPI()
    app.middleware("http")(access.workspace_access)

    def database():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = database
    app.include_router(auth_router.router)
    app.include_router(identity_router.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")

    @app.get("/api/diagnostics")
    def diagnostics(user=Depends(auth.require_admin)):
        return {"actor": user.id, "trusted_actor": identity.actor_id()}

    @app.get("/api/settings/test")
    def settings(user=Depends(auth.require_admin)):
        return {"actor": user.id}

    @app.get("/")
    def shell():
        return {"shell": True}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "merge-test", "version": "test", "commit": "a" * 40}

    with TestClient(app, base_url="https://testserver") as client:
        yield SimpleNamespace(factory=factory, engine=engine, client=client, app=app,
                              headers=lambda name: {"Authorization": "Bearer legacy-session-" + name})
    engine.dispose()


def test_existing_password_users_and_sessions_are_preserved(merged_auth, monkeypatch):
    s = merged_auth
    with s.factory() as session:
        user = session.get(User, "member")
        before = (user.id, user.password_hash, user.organization_id, user.role)
        old_token = session.get(SessionToken, "old-member").token_hash
        monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_EMAIL", "must-not-create@example.invalid")
        monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)
        assert auth.bootstrap_admin_from_env(session) is None
        assert auth.bootstrap_admin_from_env(session) is None
        user = session.get(User, "member")
        assert before == (user.id, user.password_hash, user.organization_id, user.role)
        assert session.get(identity.IdentityAccount, "member").enabled
        assert session.get(SessionToken, "old-member").token_hash == old_token
        assert session.scalar(select(User).where(User.email == "must-not-create@example.invalid")) is None
        assert session.scalar(select(ProjectMember).where(ProjectMember.user_id == "member",
                                                          ProjectMember.project_id == "pa")) is not None
    assert s.client.get("/api/auth/me", headers=s.headers("member")).json()["id"] == "member"
    assert s.client.get("/api/identity/me", headers=s.headers("member")).json() == {
        "user_id": "member", "role": "MEMBER", "organization_id": "oa", "authentication": "password"}


def test_old_cookie_and_bearer_session_use_project_rbac(merged_auth):
    s = merged_auth
    for headers in (s.headers("member"), {"Cookie": "lv_session=legacy-session-member"}):
        response = s.client.get("/api/projects", headers=headers)
        assert response.status_code == 200 and {p["id"] for p in response.json()} == {"pa"}
        assert s.client.get("/api/projects/pb", headers=headers).status_code == 404
        assert s.client.get("/api/projects/private", headers=headers).status_code == 404
        assert s.client.get("/api/auth/users", headers=headers).status_code == 403
    response = s.client.post("/api/projects", json={"name": "New"}, headers=s.headers("member"))
    assert response.status_code == 201, response.text
    with s.factory() as session:
        row = session.get(Project, response.json()["id"])
        assert (row.owner_id, row.organization_id) == ("member", "oa")
    assert s.client.patch("/api/projects/pa", json={"memo": "No"}, headers=s.headers("viewer")).status_code == 403


def test_password_login_secure_cookie_and_csrf(merged_auth):
    s = merged_auth
    payload = {"email": "member@example.invalid", "password": PASSWORD}
    assert s.client.post("/api/auth/login", json=payload, headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert s.client.post("/api/auth/login", json=payload, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    result = s.client.post("/api/auth/login", json=payload, headers={"Origin": "https://testserver"})
    assert result.status_code == 200, result.text
    cookie = next(h.lower() for h in result.headers.get_list("set-cookie") if h.startswith("lv_session="))
    assert all(flag in cookie for flag in ("httponly", "secure", "samesite=strict", "path=/"))
    assert result.headers["cache-control"] == "no-store"
    raw = result.json()["access_token"]
    with s.factory() as session:
        assert session.scalar(select(SessionToken).where(SessionToken.token_hash == hashlib.sha256(raw.encode()).hexdigest()))
        assert PASSWORD not in json.dumps([row.payload for row in session.scalars(select(AuditEventRow))])
        assert {row.actor for row in session.scalars(select(AuditEventRow))} == {"member"}
    assert s.client.get("/api/identity/me").json()["user_id"] == "member"
    assert s.client.patch("/api/projects/pa", json={"memo": "No origin"}).status_code == 403
    assert s.client.patch("/api/projects/pa", json={"memo": "Allowed"},
                          headers={"Origin": "https://testserver"}).status_code == 200
    assert s.client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert s.client.delete("/api/identity/session", headers={"Origin": "https://testserver"}).status_code == 204
    assert s.client.get("/api/projects", headers={"Authorization": "Bearer " + raw}).status_code == 401
    assert not s.client.cookies.get("lv_session") and not s.client.cookies.get("acas_session")


def test_new_api_tokens_work_on_old_endpoints_and_revoke(merged_auth):
    s = merged_auth
    created = s.client.post("/api/identity/users/member/tokens", json={}, headers=s.headers("member"))
    assert created.status_code == 201, created.text
    headers = {"Authorization": "Bearer " + created.json()["token"]}
    assert s.client.get("/api/auth/me", headers=headers).json()["id"] == "member"
    assert s.client.get("/api/auth/sessions", headers=headers).status_code == 200
    assert s.client.get("/api/auth/users", headers=headers).status_code == 403
    assert s.client.post("/api/auth/logout", headers=headers).json()["revoked"] is True
    assert s.client.get("/api/identity/me", headers=headers).status_code == 401


def test_password_bearer_exchange_is_bound_to_source_session(merged_auth):
    s = merged_auth
    assert s.client.post("/api/identity/session", headers=s.headers("member")).status_code == 200
    assert s.client.get("/api/auth/me").json()["id"] == "member"
    assert s.client.get("/api/identity/me").json()["authentication"] == "session"
    with s.factory() as session:
        assert auth.revoke_session(session, "legacy-session-member")
    assert s.client.get("/api/projects").status_code == 401


@pytest.mark.parametrize("logout", ["/api/auth/logout", "/api/identity/session"])
def test_logout_handles_identity_browser_sessions(merged_auth, logout):
    s = merged_auth
    with s.factory() as session:
        _, token = identity.issue_token(session, "member")
        session.commit()
    assert s.client.post("/api/identity/session", headers={"Authorization": "Bearer " + token}).status_code == 200
    raw = s.client.cookies.get("acas_session")
    send = s.client.post if logout.endswith("logout") else s.client.delete
    assert send(logout, headers={"Origin": "https://testserver"}).status_code in (200, 204)
    assert s.client.get("/api/auth/me", headers={"Cookie": "acas_session=" + raw}).status_code == 401


@pytest.mark.parametrize("endpoint", ["identity", "password"])
def test_disabling_from_either_api_revokes_all_sessions_and_syncs_flags(merged_auth, endpoint):
    s = merged_auth
    with s.factory() as session:
        _, token = identity.issue_token(session, "member")
        session.commit()
    assert s.client.post("/api/identity/session", headers={"Authorization": "Bearer " + token}).status_code == 200
    cookie = s.client.cookies.get("acas_session")
    if endpoint == "identity":
        response = s.client.patch("/api/identity/users/member", json={"enabled": False}, headers=s.headers("admin"))
    else:
        response = s.client.post("/api/auth/users/member/deactivate", headers=s.headers("admin"))
    assert response.status_code == 200, response.text
    with s.factory() as session:
        assert not session.get(User, "member").is_active
        assert not session.get(identity.IdentityAccount, "member").enabled
    for headers in (s.headers("member"), {"Authorization": "Bearer " + token}, {"Cookie": "acas_session=" + cookie}):
        assert s.client.get("/api/auth/me", headers=headers).status_code == 401
    assert s.client.patch("/api/identity/users/member", json={"enabled": True}, headers=s.headers("admin")).status_code == 200
    assert s.client.get("/api/projects", headers=s.headers("member")).status_code == 401
    s.client.cookies.clear()
    assert s.client.post("/api/auth/login", json={"email": "member@example.invalid", "password": PASSWORD}).status_code == 200


def test_password_change_revokes_both_session_types_and_api_tokens(merged_auth):
    s = merged_auth
    with s.factory() as session:
        _, token = identity.issue_token(session, "member")
        session.commit()
    assert s.client.post("/api/identity/session", headers={"Authorization": "Bearer " + token}).status_code == 200
    cookie = s.client.cookies.get("acas_session")
    new_password = "replacement-password-1234"
    response = s.client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": new_password},
                             headers=s.headers("member"))
    assert response.status_code == 200 and response.json()["changed"]
    for headers in (s.headers("member"), {"Authorization": "Bearer " + token}, {"Cookie": "acas_session=" + cookie}):
        assert s.client.get("/api/identity/me", headers=headers).status_code == 401
    s.client.cookies.clear()
    assert s.client.post("/api/auth/login", json={"email": "member@example.invalid", "password": PASSWORD}).status_code == 401
    assert s.client.post("/api/auth/login", json={"email": "member@example.invalid", "password": new_password}).status_code == 200


def test_activity_flags_and_roles_fail_closed_without_startup_reconciliation(merged_auth):
    s = merged_auth
    with s.factory() as session:
        session.add(identity.IdentityAccount(user_id="member", enabled=False))
        session.get(User, "viewer").is_active = False
        session.commit()
    assert s.client.get("/api/projects", headers=s.headers("member")).status_code == 401
    assert s.client.get("/api/projects", headers=s.headers("viewer")).status_code == 401
    with s.factory() as session:
        auth.bootstrap_admin_from_env(session)
        assert not session.get(User, "member").is_active
        assert not session.get(identity.IdentityAccount, "viewer").enabled
        session.get(User, "admin").role = "VIEWER"
        session.commit()
    assert s.client.get("/api/auth/users", headers=s.headers("admin")).status_code == 403
    assert s.client.patch("/api/projects/pa", json={"memo": "denied"}, headers=s.headers("admin")).status_code == 403


def test_orgless_legacy_admin_has_only_explicit_project_access(merged_auth):
    s = merged_auth
    headers = s.headers("unassigned")
    assert s.client.get("/api/auth/me", headers=headers).status_code == 200
    assert {p["id"] for p in s.client.get("/api/projects", headers=headers).json()} == {"owned-null"}
    assert s.client.get("/api/projects/orphan", headers=headers).status_code == 404
    assert s.client.get("/api/projects/pa", headers=headers).status_code == 404
    assert s.client.get("/api/auth/users", headers=headers).status_code == 403
    assert s.client.get("/api/identity/users", headers=headers).status_code == 403


def test_password_admin_creation_is_provisioned_and_org_scoped(merged_auth):
    s = merged_auth
    response = s.client.post("/api/auth/users", json={"email": "new@example.invalid", "password": PASSWORD},
                             headers=s.headers("admin"))
    assert response.status_code == 201, response.text
    new = response.json()["id"]
    with s.factory() as session:
        assert session.get(identity.IdentityAccount, new).enabled
        assert session.get(User, new).organization_id == "oa"
    assert s.client.post("/api/auth/users/other/deactivate", headers=s.headers("admin")).status_code == 404
    users = s.client.get("/api/auth/users", headers=s.headers("admin")).json()
    assert {u["organization_id"] for u in users} == {"oa"}


def test_public_host_never_falls_back_to_local_owner_and_proxy_is_explicit(merged_auth, monkeypatch):
    s = merged_auth
    monkeypatch.delenv("LV_AUTH_MODE")
    monkeypatch.setenv("RENDER_SERVICE_ID", "synthetic-render-service")
    assert s.client.get("/").status_code == 200
    health = s.client.get("/api/health")
    assert health.json() == {"status": "ok", "app": "merge-test", "version": "test", "commit": "a" * 40}
    assert health.headers["cache-control"] == "no-store"
    assert s.client.get("/api/projects").status_code == 401
    assert s.client.get("/api/identity/me", headers=s.headers("member")).json()["user_id"] == "member"
    monkeypatch.setenv("LV_AUTH_MODE", "local")
    assert s.client.get("/api/projects").status_code == 503
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    with TestClient(s.app, base_url="http://public.example") as remote:
        payload = {"email": "member@example.invalid", "password": PASSWORD}
        assert remote.post("/api/auth/login", json=payload).status_code == 403
        headers = {"X-Forwarded-Proto": "https", "Origin": "https://public.example"}
        assert remote.post("/api/auth/login", json=payload, headers=headers).status_code == 403
        monkeypatch.setenv("LV_TRUSTED_PROXY_IPS", "testclient")
        result = remote.post("/api/auth/login", json=payload, headers=headers)
        assert result.status_code == 200, result.text
        assert "Secure" in result.headers["set-cookie"]
        assert remote.get("/api/auth/me", headers={**s.headers("member"), "X-Forwarded-Proto": "https,http"}).status_code == 403


def test_local_dependency_bridge_and_ambiguous_cookies(merged_auth, monkeypatch):
    s = merged_auth
    assert s.client.get("/api/diagnostics", headers=s.headers("member")).status_code == 403
    assert s.client.get("/api/diagnostics", headers=s.headers("admin")).json()["actor"] == "admin"
    for cookie in ("lv_session=legacy-session-member; lv_session=legacy-session-admin",
                   "lv_session=legacy-session-member; acas_session=invalid"):
        assert s.client.get("/api/projects", headers={"Cookie": cookie}).status_code == 401
    monkeypatch.setenv("LV_AUTH_MODE", "local")
    assert s.client.get("/api/diagnostics").json() == {"actor": "local-owner", "trusted_actor": "local-owner"}
    assert s.client.get("/api/settings/test").json()["actor"] == "local-owner"
    monkeypatch.setenv("LV_ACCESS_TOKEN", "local-test-token")
    assert s.client.get("/api/diagnostics").status_code == 401
    assert s.client.get("/api/diagnostics", headers={"Authorization": "Bearer local-test-token"}).status_code == 200


def test_oidc_on_old_auth_endpoints_uses_database_roles_and_activity(merged_auth, monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    s = merged_auth
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="merge", alg="RS256", use="sig")
    for name, value in (("LV_OIDC_ISSUER", "https://sso.example.invalid"), ("LV_OIDC_AUDIENCE", "acas-api"),
                        ("LV_OIDC_JWKS_URL", "https://sso.example.invalid/jwks")):
        monkeypatch.setenv(name, value)
    jwks = jwt.PyJWKClient("https://sso.example.invalid/jwks")
    monkeypatch.setattr(jwks, "fetch_data", lambda: {"keys": [jwk]})
    monkeypatch.setattr(identity, "_jwks_client", lambda settings: jwks)
    with s.factory() as session:
        session.add(identity.ExternalIdentity(user_id="viewer", issuer="https://sso.example.invalid", subject="known"))
        session.commit()
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"iss": "https://sso.example.invalid", "aud": "acas-api", "sub": "known", "iat": now - 1,
              "exp": now + 600, "role": "ADMIN", "organization_id": "ob"}
    raw = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "merge"})
    headers = {"Authorization": "Bearer " + raw}
    result = s.client.get("/api/auth/me", headers=headers)
    assert result.status_code == 200 and result.json()["role"] == "VIEWER" and result.json()["organization_id"] == "oa"
    assert s.client.get("/api/auth/users", headers=headers).status_code == 403
    assert s.client.get("/api/projects/pb", headers=headers).status_code == 404
    assert s.client.post("/api/identity/session", headers=headers).status_code == 200
    assert s.client.post("/api/auth/users/viewer/deactivate", headers=s.headers("admin")).status_code == 200
    assert s.client.get("/api/auth/me", headers=headers).status_code == 401
    assert s.client.get("/api/auth/me").status_code == 401


def test_bootstrap_creates_one_password_identity_and_never_uses_unset_credentials(merged_auth, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        assert auth.bootstrap_admin_from_env(session) is None
        monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_EMAIL", "bootstrap@example.invalid")
        monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)
        user = auth.bootstrap_admin_from_env(session)
        assert user is not None and session.get(identity.IdentityAccount, user.id).enabled
        assert auth.verify_password(PASSWORD, user.password_hash)
        assert auth.bootstrap_admin_from_env(session) is None
        assert len(list(session.scalars(select(User)))) == 1
    engine.dispose()


@pytest.mark.parametrize("kind", ["password", "token"])
def test_migrated_local_owner_does_not_block_explicit_first_bootstrap(merged_auth, monkeypatch, kind):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add(User(id=identity.LOCAL_OWNER, email="local-owner@localhost", role="ADMIN"))
        session.flush()
        session.add(identity.IdentityAccount(user_id=identity.LOCAL_OWNER, enabled=True))
        session.add(Project(id="legacy", name="Local case", owner_id=identity.LOCAL_OWNER))
        session.commit()
        if kind == "password":
            monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_EMAIL", "first@example.invalid")
            monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)
            user = auth.bootstrap_admin_from_env(session)
            assert user is not None
        else:
            user, token = identity.bootstrap_admin(session, email="first@example.invalid", organization_name="First")
            session.commit()
            assert identity.authenticate_bearer(session, token).user_id == user.id
        assert session.get(User, identity.LOCAL_OWNER).organization_id is None
        assert session.get(Project, "legacy").owner_id == identity.LOCAL_OWNER
        assert user.organization_id and identity.has_provisioned_users(session)
        principal = identity.principal_for_user(session, user.id, "token")
        assert identity.visible_project_ids(session, principal) == []
        assert auth.bootstrap_admin_from_env(session) is None
    engine.dispose()


def test_legacy_password_session_expiry_and_prefix_collision(merged_auth):
    s = merged_auth
    raw = "acas_legacy-password-session-secret"
    with s.factory() as session:
        session.add(SessionToken(id="legacy-prefixed", user_id="member",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(hours=1)))
        session.get(SessionToken, "old-member").expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
    assert s.client.get("/api/auth/me", headers=s.headers("member")).status_code == 401
    assert s.client.get("/api/auth/me", headers={"Cookie": "lv_session=legacy-session-member"}).status_code == 401
    assert s.client.get("/api/auth/me", headers={"Authorization": "Bearer " + raw}).json()["id"] == "member"
