"""Authorization and cryptography regressions; no live credentials or network."""
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import access, identity
from apps.api.db import (AuditEventRow, Base, Document, DocumentBlock, DocumentPage, DocumentVersion,
                         ExportArtifactRow, FindingRow, Organization,
                         Project, ProjectMember, ReportRow, VerificationRun, get_db)
from apps.api.routers import audit, identity as identity_router, projects, viewer
from packages.pii_engine.key_provider import (AWSKMSKeyProvider, EnvKeyProvider,
                                             FileKeyProvider, KeyMaterial)
from packages.pii_engine.pseudonym import PseudonymStore


@pytest.fixture
def secured(monkeypatch):
    for name in ("LV_ACCESS_TOKEN", "LV_OIDC_ISSUER", "LV_OIDC_AUDIENCE", "LV_OIDC_JWKS_URL",
                 "LV_OIDC_ALGORITHMS", "LV_PUBLIC_ORIGIN", "LV_TRUSTED_PROXY_IPS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(access, "get_session_factory", lambda: factory)
    users, secrets, token_ids = {}, {}, {}
    with factory() as session:
        session.add_all([Organization(id="oa", name="A", forced_ai_policy="LOCAL_ONLY"), Organization(id="ob", name="B")])
        session.flush()
        for name, org, role in [("admin", "oa", "ADMIN"), ("member", "oa", "MEMBER"),
                                ("viewer", "oa", "VIEWER"), ("other", "ob", "ADMIN")]:
            user = identity.provision_user(session, organization_id=org, email=name + "@example.invalid", role=role)
            users[name] = user.id
            row, secret = identity.issue_token(session, user.id)
            secrets[name], token_ids[name] = secret, row.id
        session.add_all([Project(id="pa", name="A", organization_id="oa", owner_id=users["admin"], creation_key="key-a"),
                         Project(id="pb", name="B", organization_id="ob", owner_id=users["other"], creation_key="key-b"),
                         Project(id="private", name="Private", organization_id="oa", owner_id=users["admin"]),
                         Project(id="orphan", name="Legacy")])
        session.flush()
        session.add_all([ProjectMember(project_id="pa", user_id=users["member"], role="MEMBER"),
                         ProjectMember(project_id="pa", user_id=users["viewer"], role="ADMIN"),
                         ProjectMember(project_id="pb", user_id=users["member"], role="ADMIN")])
        for suffix in ("a", "b"):
            session.add(Document(id="d" + suffix, project_id="p" + suffix, filename="private.pdf", sha256="a" * 64,
                                 storage_key="private.pdf", submitted_on="2026-09-01"))
            session.add(VerificationRun(id="u" + suffix, project_id="p" + suffix))
            session.flush()
            session.add(FindingRow(id="f" + suffix, project_id="p" + suffix, document_id="d" + suffix, run_id="u" + suffix))
            session.add(ReportRow(id="r" + suffix, project_id="p" + suffix, run_id="u" + suffix))
            session.flush()
            session.add(ExportArtifactRow(id="x" + suffix, report_id="r" + suffix, format="pdf", storage_key="private.pdf"))
        session.commit()

    app = FastAPI()
    app.middleware("http")(access.workspace_access)

    def database():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = database
    app.include_router(identity_router.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")

    async def echo(request: Request):
        raw = await request.body()
        return {"actor": identity.actor_id(request), "context_actor": identity.actor_id(),
                "body": json.loads(raw) if raw else None}

    for path in ["/documents/{document_id}/original", "/documents/{document_id}/pages/{page}.png",
                 "/verification-runs/{run_id}/result", "/runs/{run_id}", "/findings/{finding_id}",
                 "/findings/{finding_id}/review", "/findings/{finding_id}/reveal", "/findings/{finding_id}/workflow",
                 "/findings/{finding_id}/review-draft", "/reports/{report_id}/download/{fmt}",
                 "/reports/{report_id}/finalize", "/reports/{report_id}/preflight", "/artifacts/{artifact_id}",
                 "/projects/{project_id}/audit", "/projects/{project_id}/manifest",
                 "/projects/{project_id}/case-matrix", "/projects/{project_id}/compare",
                 "/projects/{project_id}/issues", "/projects/{project_id}/case-profile",
                 "/projects/{project_id}/claim-assessments", "/projects/{project_id}/reviews",
                 "/projects/{project_id}/review-history", "/projects/{project_id}/document-relations",
                 "/projects/{project_id}/search", "/audit/verify", "/settings/providers/example"]:
        app.add_api_route("/api" + path, echo, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    app.add_api_route("/", lambda: {"shell": True}, methods=["GET"])
    app.add_api_route("/static/login.js", lambda: "public login asset", methods=["GET"])
    with TestClient(app, base_url="https://testserver") as client:
        yield SimpleNamespace(client=client, app=app, factory=factory, users=users, secrets=secrets,
                              token_ids=token_ids, headers=lambda name: {"Authorization": "Bearer " + secrets[name]})
    engine.dispose()


def test_authentication_and_no_context_fallback(secured, monkeypatch):
    s = secured
    assert s.client.get("/api/projects").status_code == 401
    monkeypatch.setenv("LV_ACCESS_TOKEN", "ignored-in-multi-user")
    assert s.client.get("/api/projects", headers={"Authorization": "Bearer ignored-in-multi-user"}).status_code == 401
    assert s.client.get("/api/identity/me", headers=s.headers("member")).json()["user_id"] == s.users["member"]
    with pytest.raises(HTTPException) as error:
        identity.current_principal()
    assert error.value.status_code == 401
    monkeypatch.setenv("LV_AUTH_MODE", "invalid")
    assert s.client.get("/api/projects", headers=s.headers("admin")).status_code == 503


def test_projects_filter_owner_org_policy_and_idempotency(secured):
    s = secured
    assert {p["id"] for p in s.client.get("/api/projects", headers=s.headers("member")).json()} == {"pa"}
    assert {p["id"] for p in s.client.get("/api/projects", headers=s.headers("admin")).json()} == {"pa", "private"}
    assert s.client.get("/api/projects/orphan", headers=s.headers("admin")).status_code == 404
    assert s.client.post("/api/projects", json={"creation_key": "key-b"}, headers=s.headers("admin")).status_code == 404
    assert s.client.post("/api/projects", json={"creation_key": "key-a"}, headers=s.headers("member")).json()["id"] == "pa"
    payload = {"name": "New", "creation_key": "unique", "external_ai_policy": "MASKED",
               "owner_id": s.users["other"], "organization_id": "ob"}
    response = s.client.post("/api/projects", json=payload, headers=s.headers("member"))
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["external_ai_policy"] == "LOCAL_ONLY"
    with s.factory() as session:
        row = session.get(Project, created["id"])
        assert (row.owner_id, row.organization_id) == (s.users["member"], "oa")
    response = s.client.patch("/api/projects/pa", json={"external_ai_policy": "MASKED"}, headers=s.headers("member"))
    assert response.status_code == 200 and response.json()["external_ai_policy"] == "LOCAL_ONLY"


@pytest.mark.parametrize("path", ["/projects/pb", "/documents/db", "/documents/db/original", "/documents/db/pages/1.png",
    "/verification-runs/ub/result", "/runs/ub", "/findings/fb", "/findings/fb/workflow", "/findings/fb/review-draft",
    "/reports/rb/download/pdf", "/reports/rb/preflight", "/artifacts/xb", "/projects/pb/audit", "/projects/pb/manifest",
    "/projects/pb/case-matrix", "/projects/pb/search", "/projects/pb/compare"])
def test_foreign_resource_routes_fail_closed(secured, path):
    assert secured.client.get("/api" + path, headers=secured.headers("member")).status_code == 404


@pytest.mark.parametrize("method,path", [("post", "/projects"), ("patch", "/projects/pa"),
    ("patch", "/documents/da"), ("patch", "/findings/fa/review"), ("put", "/findings/fa/workflow"),
    ("put", "/findings/fa/review-draft"), ("post", "/reports/ra/finalize"), ("post", "/projects/pa/reviews"),
    ("put", "/projects/pa/claim-assessments"), ("put", "/projects/pa/case-profile"), ("post", "/projects/pa/issues"),
    ("post", "/projects/pa/document-relations")])
def test_viewer_is_readonly_even_with_project_admin_membership(secured, method, path):
    response = getattr(secured.client, method)("/api" + path, json={}, headers=secured.headers("viewer"))
    assert response.status_code == 403, response.text


def test_related_resource_and_reviewer_spoofing(secured):
    s = secured
    for body in ({"document_ids": ["db"]}, {"left_document_id": "da", "right_document_id": "db"}, {"run_id": "ub"}):
        assert s.client.post("/api/projects/pa/compare", json=body, headers=s.headers("admin")).status_code == 404
    assert s.client.get("/api/projects/pa/compare?document_id=da&document_id=db", headers=s.headers("admin")).status_code == 404
    response = s.client.patch("/api/findings/fa/review", json={"reviewer": "forged-admin"}, headers=s.headers("member"))
    assert response.status_code == 200, response.text
    assert response.json()["body"]["reviewer"] == response.json()["actor"] == s.users["member"]


def test_access_management_is_org_and_project_scoped(secured):
    s = secured
    assert s.client.get("/api/identity/users", headers=s.headers("member")).status_code == 403
    assert s.client.post("/api/identity/users", json={"email": "new@example.invalid", "organization_id": "ob"}, headers=s.headers("admin")).status_code == 422
    response = s.client.post("/api/identity/users", json={"email": "new@example.invalid", "role": "VIEWER"}, headers=s.headers("admin"))
    assert response.status_code == 201 and response.json()["organization_id"] == "oa"
    foreign = f"/api/projects/pa/members/{s.users['other']}"
    assert s.client.put(foreign, json={"role": "ADMIN"}, headers=s.headers("admin")).status_code == 404
    own = f"/api/projects/pa/members/{s.users['member']}"
    assert s.client.put(own, json={"role": "ADMIN"}, headers=s.headers("member")).status_code == 403
    assert s.client.put(own, json={"role": "ADMIN"}, headers=s.headers("admin")).status_code == 200
    assert s.client.get("/api/projects/pa/members", headers=s.headers("member")).status_code == 200
    assert s.client.get("/api/audit/verify", headers=s.headers("admin")).status_code == 403
    assert s.client.patch("/api/settings/providers/example", json={}, headers=s.headers("admin")).status_code == 403


def test_document_null_clearing_and_trusted_audit_actor(secured):
    from apps.api.db import AuditEventRow
    s = secured
    response = s.client.patch("/api/documents/da", json={"submitted_on": None}, headers=s.headers("member"))
    assert response.status_code == 200 and response.json()["submitted_on"] is None
    response = s.client.patch("/api/projects/pa/document-scope", json={"document_ids": ["da"], "included_in_verification": False}, headers=s.headers("member"))
    assert response.status_code == 200
    with s.factory() as session:
        assert session.get(Document, "da").scope_changed_by == s.users["member"]
        assert {r.actor for r in session.scalars(select(AuditEventRow))} == {s.users["member"]}


def test_session_cookie_download_csrf_logout_and_hash_storage(secured):
    s = secured
    assert s.client.get("/").status_code == s.client.get("/static/login.js").status_code == 200
    response = s.client.post("/api/identity/session", headers=s.headers("member"))
    assert response.status_code == 200, response.text
    cookie_header = response.headers["set-cookie"].lower()
    assert all(value in cookie_header for value in ("httponly", "secure", "samesite=lax", "path=/api"))
    secret = s.client.cookies.get(identity.SESSION_COOKIE)
    with s.factory() as session:
        row = session.scalar(select(identity.BrowserSession))
        assert row.secret_hash == hashlib.sha256(secret.encode()).hexdigest()
        assert secret not in repr(row.__dict__)
        assert s.secrets["member"] not in repr(session.get(identity.ApiToken, s.token_ids["member"]).__dict__)
    assert s.client.get("/api/identity/me").json()["authentication"] == "session"
    for path in ("/documents/da/original", "/documents/da/pages/1.png", "/reports/ra/download/pdf", "/artifacts/xa"):
        assert s.client.get("/api" + path).status_code == 200
    assert s.client.get("/api/documents/db/original").status_code == 404
    assert s.client.put("/api/projects/pa/case-profile", json={}).status_code == 403
    assert s.client.put("/api/projects/pa/case-profile", json={}, headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert s.client.put("/api/projects/pa/case-profile", json={}, headers={"Origin": "https://testserver"}).status_code == 200
    assert s.client.get("/api/identity/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert s.client.delete("/api/identity/session", headers={"Origin": "https://testserver"}).status_code == 204
    assert s.client.get("/api/identity/me").status_code == 401
    assert s.client.get("/api/identity/me", headers={"Cookie": identity.SESSION_COOKIE + "=" + secret}).status_code == 401


def test_token_expiry_revocation_and_account_disabling_invalidate_sessions(secured):
    s = secured
    assert s.client.post("/api/identity/session", headers=s.headers("member")).status_code == 200
    assert s.client.delete("/api/identity/tokens/" + s.token_ids["member"], headers=s.headers("admin")).status_code == 204
    assert s.client.get("/api/identity/me").status_code == 401
    assert s.client.get("/api/identity/me", headers=s.headers("member")).status_code == 401
    assert s.client.post("/api/identity/session", headers=s.headers("viewer")).status_code == 200
    response = s.client.patch("/api/identity/users/" + s.users["viewer"], json={"enabled": False}, headers=s.headers("admin"))
    assert response.status_code == 200
    assert s.client.get("/api/identity/me").status_code == 401
    with s.factory() as session:
        session.get(identity.ApiToken, s.token_ids["other"]).expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
    assert s.client.get("/api/identity/me", headers=s.headers("other")).status_code == 401


def test_tls_proxy_and_local_compatibility(secured, monkeypatch):
    s = secured
    with TestClient(s.app, base_url="http://remote.example") as remote:
        assert remote.get("/").status_code == 200
        assert remote.get("/api/projects", headers=s.headers("admin")).status_code == 403
        assert remote.get("/api/projects", headers={**s.headers("admin"), "X-Forwarded-Proto": "https"}).status_code == 403
        monkeypatch.setenv("LV_TRUSTED_PROXY_IPS", "testclient")
        assert remote.get("/api/projects", headers={**s.headers("admin"), "X-Forwarded-Proto": "https"}).status_code == 200
    monkeypatch.setenv("LV_AUTH_MODE", "local")
    assert s.client.get("/api/identity/me").json()["user_id"] == "local-owner"
    assert {p["id"] for p in s.client.get("/api/projects").json()} == {"pa", "pb", "private", "orphan"}
    assert s.client.post("/api/projects", json={}).status_code == 201
    assert s.client.get("/api/projects", headers={"Host": "evil.invalid"}).status_code == 403
    monkeypatch.setenv("LV_ACCESS_TOKEN", "local-test-token")
    root = s.client.get("/")
    assert root.status_code == 401 and root.headers["www-authenticate"].startswith("Basic ")
    basic = {"Authorization": "Basic " + base64.b64encode(b"owner:local-test-token").decode()}
    assert s.client.get("/", headers=basic).status_code == 200
    assert s.client.get("/api/identity/me", headers=basic).json()["authentication"] == "local"
    assert s.client.get("/api/projects").status_code == 401
    assert s.client.get("/api/projects", headers={"Authorization": "Bearer local-test-token"}).status_code == 200


def test_unintegrated_collections_and_invalid_org_policy_are_closed(secured, monkeypatch):
    s = secured
    monkeypatch.delattr(projects.list_projects, "__project_scoped__")
    assert s.client.get("/api/projects", headers=s.headers("admin")).status_code == 503
    with s.factory() as session:
        session.get(Organization, "oa").forced_ai_policy = "INVALID"
        session.commit()
    assert s.client.post("/api/projects", json={}, headers=s.headers("admin")).status_code == 503


def test_idempotency_integrity_error_recovery_does_not_return_foreign_project(secured, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from apps.api.schemas import ProjectCreate
    s = secured
    with s.factory() as session:
        principal = identity.principal_for_user(session, s.users["member"], "token")
        original_scalar = session.scalar
        first = True

        def race_scalar(statement, *args, **kwargs):
            nonlocal first
            if first:
                first = False
                return None
            return original_scalar(statement, *args, **kwargs)

        def collision():
            raise IntegrityError("simulated concurrent creation", {}, Exception())

        monkeypatch.setattr(session, "scalar", race_scalar)
        monkeypatch.setattr(session, "commit", collision)
        token = identity._principal.set(principal)
        try:
            with pytest.raises(HTTPException) as error:
                projects.create_project(ProjectCreate(creation_key="key-b"), session)
            assert error.value.status_code == 404
        finally:
            identity._principal.reset(token)


@pytest.fixture
def signing(monkeypatch):
    import jwt
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="first", alg="RS256", use="sig")
    jwks = jwt.PyJWKClient("https://sso.example.invalid/jwks")
    monkeypatch.setattr(jwks, "fetch_data", lambda: {"keys": [jwk]})
    settings = identity.OIDCSettings("https://sso.example.invalid", "acas-api", "https://sso.example.invalid/jwks")
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"iss": settings.issuer, "aud": settings.audience, "sub": "known-subject", "iat": now - 5, "exp": now + 600}
    return SimpleNamespace(jwt=jwt, private=private, jwk=jwk, jwks=jwks, settings=settings, claims=claims)


@pytest.mark.parametrize("change", [{"iss": "https://evil.invalid"}, {"aud": "another-app"}, {"exp": 1},
    {"nbf": 9999999999}, {"iat": 9999999999}, {"sub": ""}, {"sub": 123}, {"exp": None}, {"iat": None}])
def test_oidc_claims_fail_closed(signing, change):
    s = signing
    claims = {**s.claims, **change}
    claims = {k: v for k, v in claims.items() if v is not None}
    token = s.jwt.encode(claims, s.private, algorithm="RS256", headers={"kid": "first"})
    with pytest.raises(HTTPException) as error:
        identity.verify_oidc(token, s.settings, jwks_client=s.jwks)
    assert error.value.status_code == 401


def test_oidc_signature_algorithm_key_rotation_and_explicit_provisioning(secured, signing, monkeypatch):
    s, j = secured, signing
    for name, value in [("LV_OIDC_ISSUER", j.settings.issuer), ("LV_OIDC_AUDIENCE", j.settings.audience), ("LV_OIDC_JWKS_URL", j.settings.jwks_url)]:
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(identity, "_jwks_client", lambda settings: j.jwks)
    claims = {**j.claims, "role": "ADMIN", "organization_id": "ob", "email": "admin@example.invalid"}
    token = j.jwt.encode(claims, j.private, algorithm="RS256", headers={"kid": "first"})
    headers = {"Authorization": "Bearer " + token}
    assert s.client.get("/api/identity/me", headers=headers).status_code == 401
    response = s.client.post(f"/api/identity/users/{s.users['viewer']}/oidc", json={"subject": claims["sub"]}, headers=s.headers("admin"))
    assert response.status_code == 201
    response = s.client.get("/api/identity/me", headers=headers)
    assert response.status_code == 200 and response.json()["role"] == "VIEWER" and response.json()["organization_id"] == "oa"
    assert s.client.post("/api/projects", json={}, headers=headers).status_code == 403
    bad_tokens = [j.jwt.encode(claims, "a" * 32, algorithm="HS256", headers={"kid": "first"}),
                  j.jwt.encode(claims, None, algorithm="none", headers={"kid": "first"}),
                  j.jwt.encode(claims, j.private, algorithm="RS256", headers={"kid": "unknown"}),
                  j.jwt.encode(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256", headers={"kid": "first"})]
    for invalid in bad_tokens:
        assert s.client.get("/api/identity/me", headers={"Authorization": "Bearer " + invalid}).status_code == 401
    j.jwk["kid"] = "rotated"
    rotated = j.jwt.encode(claims, j.private, algorithm="RS256", headers={"kid": "rotated"})
    assert s.client.get("/api/identity/me", headers={"Authorization": "Bearer " + rotated}).status_code == 200


def test_bootstrap_is_offline_and_one_time(secured):
    with secured.factory() as session:
        with pytest.raises(ValueError, match="already bootstrapped"):
            identity.bootstrap_admin(session, email="root@example.invalid", organization_name="New")


@pytest.fixture
def viewer_audit(secured, monkeypatch, tmp_path):
    from helpers import make_pdf
    from apps.api.services import make_audit
    from packages.common.enums import AuditEventType
    from packages.common.storage import LocalObjectStorage

    storage = LocalObjectStorage(tmp_path / "storage")
    monkeypatch.setattr(viewer, "get_storage", lambda: storage)
    originals = {}
    with secured.factory() as session:
        for document_id, project_id in (("da", "pa"), ("db", "pb"),
                                        ("dprivate", "private"), ("dorphan", "orphan")):
            data = make_pdf(tmp_path / (document_id + ".pdf"), ["Private content " + document_id]).read_bytes()
            originals[document_id] = data
            key = storage.put_derivative(project_id + "/" + document_id + ".pdf", data)
            document = session.get(Document, document_id)
            if document is None:
                document = Document(id=document_id, project_id=project_id, filename=document_id + ".pdf")
                session.add(document)
            document.storage_key, document.sha256 = key, hashlib.sha256(data).hexdigest()
            document.mime_type = "application/pdf"
            session.add(DocumentPage(document_id=document_id, page_number=1, width=612, height=792))
            session.add(DocumentVersion(document_id=document_id, version=1, kind="ORIGINAL",
                                        sha256=document.sha256, storage_key=key, note=document_id))
            for label, visible, layer in (("visible", True, "visible_text"), ("ocr", True, "ocr_layer"),
                                          ("hidden", False, "visible_text"), ("sealed", True, "hidden_text")):
                session.add(DocumentBlock(id=document_id + "-" + label, document_id=document_id,
                                          text=document_id + "-" + label, visible=visible, source_layer=layer))
        session.commit()
        chain = make_audit(session)
        for project_id, label in (("pa", "A1"), ("pb", "B1"), ("pa", "A2"),
                                  ("private", "PRIVATE"), (None, "GLOBAL"), ("pb", "B2")):
            chain.record(AuditEventType.USER_OVERRIDE, {"marker": label}, actor="seed-" + label,
                         project_id=project_id)

    app = FastAPI()
    app.middleware("http")(access.workspace_access)
    app.dependency_overrides[get_db] = secured.app.dependency_overrides[get_db]
    for router in (identity_router.router, viewer.router, audit.router):
        app.include_router(router, prefix="/api")
    with TestClient(app, base_url="https://testserver") as client:
        yield SimpleNamespace(**{**vars(secured), "client": client, "app": app,
                                 "originals": originals, "storage": storage})


@pytest.mark.parametrize("kind,suffix,method", [
    ("documents", "blocks", "get"), ("documents", "versions", "get"),
    ("documents", "original", "get"), ("documents", "pages/1.png", "get"),
    ("documents", "outbound-guard", "post"), ("projects", "audit", "get"),
    ("projects", "manifest", "get"),
])
def test_real_viewer_audit_routes_reject_unavailable_projects(viewer_audit, kind, suffix, method):
    s = viewer_audit
    send = getattr(s.client, method)
    kwargs = {"json": {}} if method == "post" else {}
    own = "da" if kind == "documents" else "pa"
    assert send(f"/api/{kind}/{own}/{suffix}", **kwargs).status_code == 401
    ids = ("db", "dprivate", "dorphan", "missing") if kind == "documents" else ("pb", "private", "orphan", "missing")
    for resource_id in ids:
        response = send(f"/api/{kind}/{resource_id}/{suffix}", headers=s.headers("member"), **kwargs)
        assert response.status_code == 404, response.text
    foreign = "db" if kind == "documents" else "pb"
    assert send(f"/api/{kind}/{foreign}/{suffix}", headers=s.headers("admin"), **kwargs).status_code == 404


def test_viewer_audit_handlers_authorize_without_middleware(viewer_audit, monkeypatch):
    from apps.api.schemas import OutboundRequest
    s = viewer_audit

    def forbidden_storage():
        pytest.fail("Unauthorized handler reached storage")

    monkeypatch.setattr(viewer, "get_storage", forbidden_storage)
    with s.factory() as session:
        def calls(document_id, project_id):
            return [lambda: viewer.get_blocks(document_id, include_hidden=False, session=session),
                    lambda: viewer.get_original(document_id, session),
                    lambda: viewer.render_page(document_id, 1, session),
                    lambda: viewer.list_versions(document_id, session),
                    lambda: viewer.outbound_guard(document_id, OutboundRequest(), session),
                    lambda: audit.list_audit(project_id, limit=1, session=session),
                    lambda: audit.get_manifest(project_id, session)]

        for call in calls("da", "pa") + [lambda: audit.verify_chain(session)]:
            with pytest.raises(HTTPException) as error:
                call()
            assert error.value.status_code == 401

        principal = identity.principal_for_user(session, s.users["member"], "token")
        token = identity._principal.set(principal)
        try:
            for document_id, project_id in (("db", "pb"), ("dprivate", "private"), ("dorphan", "orphan")):
                for call in calls(document_id, project_id):
                    with pytest.raises(HTTPException) as error:
                        call()
                    assert error.value.status_code == 404
            with pytest.raises(HTTPException) as error:
                audit.verify_chain(session)
            assert error.value.status_code == 403
        finally:
            identity._principal.reset(token)

        token = identity._principal.set(identity.principal_for_user(session, s.users["viewer"], "token"))
        try:
            with pytest.raises(HTTPException) as error:
                viewer.outbound_guard("da", OutboundRequest(), session)
            assert error.value.status_code == 403
        finally:
            identity._principal.reset(token)


def test_real_cookie_downloads_and_png_use_trusted_audit_actor(viewer_audit):
    s = viewer_audit
    assert s.client.post("/api/identity/session", headers=s.headers("viewer")).status_code == 200
    forged = {"X-User-ID": s.users["other"], "X-Actor": "forged-admin"}
    response = s.client.get("/api/documents/da/original?actor=forged-admin", headers=forged)
    assert response.status_code == 200 and response.content == s.originals["da"]
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"
    response = s.client.get("/api/documents/da/pages/1.png?reviewer=forged-admin", headers=forged)
    assert response.status_code == 200 and response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert s.client.get("/api/documents/da/pages/99.png").status_code == 404
    assert s.client.get("/api/documents/db/original").status_code == 404
    assert s.client.get("/api/documents/dprivate/pages/1.png").status_code == 404
    with s.factory() as session:
        rows = session.scalars(select(AuditEventRow).where(AuditEventRow.event_type == "EXPORT")
                               .order_by(AuditEventRow.sequence)).all()
        assert [row.payload["action"] for row in rows] == ["ORIGINAL_DOWNLOAD", "PAGE_RENDER"]
        assert all((row.actor, row.project_id, row.document_id) == (s.users["viewer"], "pa", "da") for row in rows)
        assert rows[1].payload["page_number"] == 1


def test_real_viewer_collections_filter_live_and_cached_blocks(viewer_audit):
    s = viewer_audit
    headers = s.headers("viewer")
    response = s.client.get("/api/documents/da/blocks", headers=headers)
    assert response.status_code == 200
    assert {b["text"] for b in response.json()["blocks"]} == {"da-visible", "da-ocr"}
    assert len(response.json()["pages"]) == 1
    versions = s.client.get("/api/documents/da/versions", headers=headers).json()
    assert len(versions) == 1 and versions[0]["note"] == "da"
    with s.factory() as session:
        session.get(VerificationRun, "ua").result_json = {"documents": [{"document_id": "da", "pages": [
            {"page_number": 1, "blocks": [
                {"text": "cached-visible", "visible": True, "source_layer": "visible_text"},
                {"text": "cached-ocr", "visible": True, "source_layer": "ocr_layer"},
                {"text": "secret-hidden", "visible": False, "source_layer": "visible_text"},
                {"text": "secret-layer", "visible": True, "source_layer": "hidden_text"},
                {"text": "secret-unknown"},
            ]}, {"page_number": 2, "blocks": [{"text": "second-page", "visible": True, "source_layer": "visible_text"}]}]}]}
        session.add(VerificationRun(id="uprivate", project_id="private"))
        session.commit()
    response = s.client.get("/api/documents/da/blocks?run_id=ua&page=1", headers=headers)
    assert response.status_code == 200
    assert {b["text"] for b in response.json()["blocks"]} == {"cached-visible", "cached-ocr"}
    assert "secret-" not in response.text and "second-page" not in response.text
    assert s.client.get("/api/documents/da/blocks?run_id=ua&include_hidden=true", headers=headers).status_code == 403
    assert s.client.get("/api/documents/da/blocks?run_id=ub", headers=headers).status_code == 404
    # Even an org admin must not combine a document and a run from different projects.
    assert s.client.get("/api/documents/da/blocks?run_id=uprivate", headers=s.headers("admin")).status_code == 404


def test_audit_export_query_is_project_scoped_and_never_verifies_global_chain(viewer_audit, monkeypatch):
    from sqlalchemy import event
    s = viewer_audit

    def forbidden_global_audit(*args, **kwargs):
        pytest.fail("Tenant export accessed the global audit chain")

    monkeypatch.setattr(audit, "make_audit", forbidden_global_audit)
    statements = []
    with s.factory() as session:
        engine = session.get_bind()

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM audit_events" in statement:
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        for user in ("member", "viewer", "admin"):
            headers = s.headers(user)
            response = s.client.get("/api/projects/pa/audit?limit=1", headers=headers)
            assert response.status_code == 200 and [e["payload"]["marker"] for e in response.json()["events"]] == ["A2"]
            response = s.client.get("/api/projects/pa/manifest", headers=headers)
            assert response.status_code == 200
            manifest = response.json()
            assert [e["payload"]["marker"] for e in manifest["events"]] == ["A1", "A2"]
            assert manifest["event_count"] == 2 and manifest["event_hashes_valid"] is True
            assert manifest["chain_valid"] is None and manifest["verification_scope"] == "project_events"
            assert manifest["head_hash_scope"] == "project_events"
            assert manifest["head_hash"] == manifest["events"][-1]["event_hash"]
            assert all(e["project_id"] == "pa" for e in manifest["events"])
            assert all(marker not in response.text for marker in ("seed-B", "seed-GLOBAL", "seed-PRIVATE"))
        assert statements and all("WHERE audit_events.project_id =" in sql and "pa" in params for sql, params in statements)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    for limit in (0, -1, 1001):
        assert s.client.get(f"/api/projects/pa/audit?limit={limit}", headers=s.headers("member")).status_code == 422
    assert s.client.get("/api/audit/verify", headers=s.headers("admin")).status_code == 403


def test_manifest_tampering_empty_project_and_local_verification(viewer_audit, monkeypatch):
    s = viewer_audit
    with s.factory() as session:
        session.add(Project(id="empty", name="Empty", organization_id="oa", owner_id=s.users["admin"]))
        session.commit()
    empty = s.client.get("/api/projects/empty/manifest", headers=s.headers("admin")).json()
    assert empty["events"] == [] and empty["event_count"] == 0 and empty["head_hash"] == "0" * 64
    with s.factory() as session:
        session.scalar(select(AuditEventRow).where(AuditEventRow.project_id == "pb")).payload = {"tampered": "foreign"}
        session.commit()
    own = s.client.get("/api/projects/pa/manifest", headers=s.headers("member")).json()
    assert own["event_hashes_valid"] is True and own["chain_valid"] is None
    monkeypatch.setenv("LV_AUTH_MODE", "local")
    local = s.client.get("/api/projects/pa/manifest").json()
    assert local["chain_valid"] is False and local["verification_scope"] == "global_chain"
    assert s.client.get("/api/audit/verify").json()["valid"] is False
    assert s.client.get("/api/documents/da/original").status_code == 200
    with s.factory() as session:
        row = session.scalar(select(AuditEventRow).where(AuditEventRow.event_type == "EXPORT"))
        assert row.actor == identity.LOCAL_OWNER
        session.scalar(select(AuditEventRow).where(AuditEventRow.project_id == "pa")).payload = {"tampered": "own"}
        session.commit()
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    own = s.client.get("/api/projects/pa/manifest", headers=s.headers("member")).json()
    assert own["event_hashes_valid"] is False and own["chain_valid"] is None


def test_outbound_export_requires_member_and_uses_trusted_actor(viewer_audit, tmp_path):
    from helpers import make_docx
    s = viewer_audit
    body = ('<w:p><w:r><w:t>Submission</w:t></w:r></w:p>'
            '<w:p><w:del w:author="A" w:date="2026-01-01T00:00:00Z">'
            '<w:r><w:delText>Internal memo</w:delText></w:r></w:del></w:p>')
    data = make_docx(tmp_path / "out.docx", body).read_bytes()
    key = s.storage.put_derivative("pa/out.docx", data)
    with s.factory() as session:
        session.add(Document(id="out", project_id="pa", filename="out.docx", storage_key=key,
                             sha256=hashlib.sha256(data).hexdigest(),
                             mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        session.commit()
    path = "/api/documents/out/outbound-guard"
    payload = {"generate_sanitized": True, "actor": "forged-admin", "reviewer": s.users["other"]}
    assert s.client.post(path, json=payload, headers=s.headers("viewer")).status_code == 403
    assert s.client.post("/api/identity/session", headers=s.headers("member")).status_code == 200
    assert s.client.post(path, json=payload).status_code == 403
    assert s.client.post(path, json=payload, headers={"Origin": "https://evil.invalid"}).status_code == 403
    response = s.client.post(path, json=payload, headers={"Origin": "https://testserver"})
    assert response.status_code == 200, response.text
    assert response.json()["sanitized"]["removed"]["tracked_delete_removed"] >= 1
    assert s.storage.get(key) == data
    with s.factory() as session:
        rows = session.scalars(select(AuditEventRow).where(AuditEventRow.event_type == "EXPORT")).all()
        assert len(rows) == 1
        assert (rows[0].actor, rows[0].project_id, rows[0].document_id) == (s.users["member"], "pa", "out")
        assert rows[0].payload["action"] == "OUTBOUND_SANITIZE"
        assert s.secrets["member"] not in json.dumps(rows[0].payload)
        versions = session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == "out")).all()
        assert len(versions) == 1 and versions[0].kind == "SANITIZED"


def test_legacy_sealed_reports_require_editor_before_storage(secured, monkeypatch):
    from apps.api.routers import reports
    s = secured

    def forbidden_storage():
        pytest.fail("Read-only user reached sealed report storage")

    monkeypatch.setattr(reports, "get_storage", forbidden_storage)
    with s.factory() as session:
        report = session.get(ReportRow, "ra")
        report.include_sealed = True
        report.artifacts = {"pdf": {"storage_key": "sealed.pdf"}}
        session.commit()
        token = identity._principal.set(identity.principal_for_user(session, s.users["viewer"], "token"))
        try:
            with pytest.raises(HTTPException) as error:
                reports.download_report("ra", "pdf", session)
            assert error.value.status_code == 403
        finally:
            identity._principal.reset(token)
        token = identity._principal.set(identity.principal_for_user(session, s.users["member"], "token"))
        try:
            assert reports._report_or_404(session, "ra")[0].id == "ra"
        finally:
            identity._principal.reset(token)


def envelope(path):
    return json.loads(base64.b64decode(path.read_bytes()[9:]))


def test_env_vault_rotation_wrong_key_and_project_binding(tmp_path):
    old, new = os.urandom(32), os.urandom(32)
    first = PseudonymStore("p1", EnvKeyProvider({"old": old}, "old"), tmp_path)
    token = first.pseudonym_for("PERSON", "Private Person")
    path = tmp_path / "p1.vault"
    rotated = PseudonymStore("p1", EnvKeyProvider({"old": old, "new": new}, "new"), tmp_path)
    assert rotated.original_for(token) == "Private Person"
    rotated.save()
    assert envelope(path)["key"]["key_id"] == "new"
    before = path.read_bytes()
    assert b"Private Person" not in before and base64.b64encode(new) not in before
    for provider in [EnvKeyProvider({"old": old}, "old"), EnvKeyProvider({"new": os.urandom(32)}, "new")]:
        with pytest.raises(ValueError):
            PseudonymStore("p1", provider, tmp_path)
        assert path.read_bytes() == before
    (tmp_path / "p2.vault").write_bytes(before)
    with pytest.raises(ValueError):
        PseudonymStore("p2", EnvKeyProvider({"new": new}, "new"), tmp_path)
    assert repr(new) not in repr(KeyMaterial(new, {"key_id": "new"}))


def test_file_key_rotation_and_offline_default(tmp_path, monkeypatch):
    for name in ("LV_PSEUDONYM_SECRET", "LV_VAULT_KEYS", "LV_VAULT_KEY_PROVIDER", "LV_VAULT_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LV_DATA_DIR", str(tmp_path))
    store = PseudonymStore("default", root=tmp_path / "vault")
    assert isinstance(store.key_provider, FileKeyProvider)
    token = store.pseudonym_for("PERSON", "Original")
    key_id = store.key_provider.rotate()
    store.save()
    assert envelope(tmp_path / "vault" / "default.vault")["key"]["key_id"] == key_id
    assert PseudonymStore("default", root=tmp_path / "vault").original_for(token) == "Original"
    with pytest.raises(ValueError):
        FileKeyProvider(tmp_path / "missing.json")


@pytest.mark.parametrize("format", ["aes", "stream"])
def test_legacy_vaults_read_and_migrate(tmp_path, monkeypatch, format):
    secret = b"legacy-test-secret"
    monkeypatch.setenv("LV_PSEUDONYM_SECRET", secret.decode())
    payload = json.dumps({"mapping": {"PERSON:original": "PERSON_001"}, "originals": {"PERSON_001": "Original"}, "counters": {"PERSON": 1}}).encode()
    if format == "aes":
        nonce = os.urandom(12)
        blob = b"ACAS2:" + base64.b64encode(nonce + AESGCM(hashlib.sha256(secret).digest()).encrypt(nonce, payload, b"legacy"))
    else:
        nonce = os.urandom(16)
        stream = b"".join(hmac.new(secret, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest() for i in range((len(payload) + 31) // 32))
        body = bytes(a ^ b for a, b in zip(payload, stream))
        blob = base64.b64encode(nonce + hmac.new(secret, nonce + body, hashlib.sha256).digest() + body)
    path = tmp_path / "legacy.vault"
    path.write_bytes(blob)
    store = PseudonymStore("legacy", root=tmp_path)
    assert store.original_for("PERSON_001") == "Original"
    store.save()
    assert path.read_bytes().startswith(b"ACAS2:K3:")


class FakeKMS:
    def __init__(self):
        self.master = AESGCM(os.urandom(32))
        self.calls = []

    def generate_data_key(self, **args):
        self.calls.append(args)
        plaintext, nonce = os.urandom(32), os.urandom(12)
        context = json.dumps([args["KeyId"], args["EncryptionContext"]], sort_keys=True).encode()
        return {"KeyId": args["KeyId"], "Plaintext": plaintext,
                "CiphertextBlob": nonce + self.master.encrypt(nonce, plaintext, context)}

    def decrypt(self, **args):
        self.calls.append(args)
        blob = args["CiphertextBlob"]
        context = json.dumps([args["KeyId"], args["EncryptionContext"]], sort_keys=True).encode()
        return {"KeyId": args["KeyId"], "Plaintext": self.master.decrypt(blob[:12], blob[12:], context)}


def test_kms_envelopes_rotation_and_wrong_master_fail_closed(tmp_path):
    first, second = "arn:aws:kms:region:123456789012:key/first", "arn:aws:kms:region:123456789012:key/second"
    fake = FakeKMS()
    store = PseudonymStore("kms", AWSKMSKeyProvider(first, client=fake), tmp_path)
    token = store.pseudonym_for("PERSON", "Hidden Name")
    provider = AWSKMSKeyProvider(second, decrypt_key_ids=[first], client=fake)
    rotated = PseudonymStore("kms", provider, tmp_path)
    assert rotated.original_for(token) == "Hidden Name"
    rotated.save()
    path = tmp_path / "kms.vault"
    assert envelope(path)["key"]["key_id"] == second
    before = path.read_bytes()
    with pytest.raises(ValueError):
        PseudonymStore("kms", AWSKMSKeyProvider(second, client=FakeKMS()), tmp_path)
    assert before == path.read_bytes()
    assert all(c["EncryptionContext"]["project_id"] == "kms" for c in fake.calls)
    assert any(c.get("KeySpec") == "AES_256" for c in fake.calls)
