"""인증과 접근통제 (제21.3장).

가장 중요한 시험은 test_no_endpoint_is_unauthenticated이다. 엔드포인트를
새로 추가하면서 의존성을 빠뜨리는 것이 이 종류의 결함이 생기는 경로이므로,
개별 경로를 하나씩 세는 대신 "무방비 경로가 있으면 실패"로 고정한다.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.auth import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_VIEWER,
    hash_password,
    issue_session,
    verify_password,
)
from apps.api.db import Organization, Project, User, get_session_factory
from apps.api.main import create_app

# 인증 없이 열려 있어도 되는 경로. 그 밖은 모두 막혀 있어야 한다.
PUBLIC_PATHS = {
    ("GET", "/"),
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
}


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LV_PSEUDONYM_SECRET", "test-secret")
    return TestClient(create_app())


PASSWORD = "test-password-1234"


@pytest.fixture()
def org_and_users():
    """관리자·구성원·열람자와 서로 다른 기관의 사용자를 만든다.

    DB가 테스트 간 유지되므로 이메일은 매번 새로 만든다.
    """
    suffix = uuid.uuid4().hex[:8]
    session = get_session_factory()()
    org = Organization(name="테스트 기관")
    other = Organization(name="다른 기관")
    session.add_all([org, other])
    session.flush()
    users, emails = {}, {}
    for role in (ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER):
        email = f"{role.lower()}-{suffix}@example.com"
        user = User(
            email=email, display_name=role, role=role,
            organization_id=org.id, password_hash=hash_password(PASSWORD),
        )
        session.add(user)
        users[role] = user
        emails[role] = email
    outsider_email = f"outsider-{suffix}@example.com"
    outsider = User(
        email=outsider_email, display_name="외부", role=ROLE_MEMBER,
        organization_id=other.id, password_hash=hash_password(PASSWORD),
    )
    session.add(outsider)
    session.commit()
    tokens = {role: issue_session(session, user) for role, user in users.items()}
    tokens["OUTSIDER"] = issue_session(session, outsider)
    emails["OUTSIDER"] = outsider_email
    result = {"tokens": tokens, "emails": emails, "orgs": {"org": org.id, "other": other.id}}
    session.close()
    return result


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- 전수 검사 ---------------------------------------------------------------
def test_no_endpoint_is_unauthenticated(app_client, org_and_users):
    """공개 목록에 없는 모든 경로는 인증 없이 접근되면 안 된다."""
    schema = app_client.app.openapi()
    unprotected = []
    for path, operations in schema["paths"].items():
        for method in operations:
            method_upper = method.upper()
            if method_upper not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                continue
            if (method_upper, path) in PUBLIC_PATHS:
                continue
            # 경로 파라미터는 존재하지 않는 값으로 채운다. 인증이 먼저 걸려야 하므로
            # 404가 나오면 그것은 인증을 통과했다는 뜻이다.
            concrete = path
            for name in ("document_id", "project_id", "run_id", "finding_id",
                         "report_id", "user_id", "name", "fmt"):
                concrete = concrete.replace("{" + name + "}", "probe")
            if "{" in concrete:
                continue
            response = app_client.request(method_upper, concrete)
            if response.status_code not in (401, 403, 503):
                unprotected.append(f"{method_upper} {path} -> {response.status_code}")
    assert unprotected == [], "인증 없이 접근되는 엔드포인트가 있다:\n" + "\n".join(unprotected)


# --- 로그인 -----------------------------------------------------------------
def test_login_succeeds_and_returns_token(app_client, org_and_users):
    response = app_client.post(
        "/api/auth/login",
        json={"email": org_and_users["emails"][ROLE_MEMBER], "password": PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["user"]["role"] == ROLE_MEMBER


@pytest.mark.parametrize("which,password", [
    ("existing", "wrong-password-xx"),
    ("missing", PASSWORD),
])
def test_login_failure_does_not_reveal_whether_account_exists(app_client, org_and_users, which, password):
    """계정 없음과 비밀번호 오류를 구분해 주지 않는다."""
    email = org_and_users["emails"][ROLE_MEMBER] if which == "existing" else "nosuchuser@example.com"
    response = app_client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "이메일 또는 비밀번호가 올바르지 않다"


def test_password_is_not_stored_in_plaintext(org_and_users):
    session = get_session_factory()()
    try:
        user = session.query(User).filter(User.email == org_and_users["emails"][ROLE_MEMBER]).one()
        assert user.password_hash.startswith("scrypt$")
        assert PASSWORD not in user.password_hash
        assert verify_password(PASSWORD, user.password_hash) is True
    finally:
        session.close()


def test_login_response_never_contains_password_hash(app_client, org_and_users):
    body = app_client.post(
        "/api/auth/login",
        json={"email": org_and_users["emails"][ROLE_MEMBER], "password": PASSWORD},
    ).text
    assert "scrypt$" not in body and "password_hash" not in body


# --- 세션 -------------------------------------------------------------------
def test_logout_revokes_the_token(app_client, org_and_users):
    token = app_client.post(
        "/api/auth/login",
        json={"email": org_and_users["emails"][ROLE_MEMBER], "password": PASSWORD},
    ).json()["access_token"]
    assert app_client.get("/api/auth/me", headers=_auth(token)).status_code == 200
    app_client.post("/api/auth/logout", headers=_auth(token))
    assert app_client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_garbage_token_is_rejected(app_client, org_and_users):
    assert app_client.get("/api/auth/me", headers=_auth("not-a-real-token")).status_code == 401


# --- 역할 기반 접근통제 ------------------------------------------------------
def test_viewer_cannot_create_project(app_client, org_and_users):
    response = app_client.post(
        "/api/projects", json={"name": "열람자 시도"},
        headers=_auth(org_and_users["tokens"][ROLE_VIEWER]),
    )
    assert response.status_code == 403


def test_member_can_create_project(app_client, org_and_users):
    response = app_client.post(
        "/api/projects", json={"name": "구성원 사건"},
        headers=_auth(org_and_users["tokens"][ROLE_MEMBER]),
    )
    assert response.status_code == 201


def test_only_admin_can_list_users(app_client, org_and_users):
    tokens = org_and_users["tokens"]
    assert app_client.get("/api/auth/users", headers=_auth(tokens[ROLE_MEMBER])).status_code == 403
    assert app_client.get("/api/auth/users", headers=_auth(tokens[ROLE_ADMIN])).status_code == 200


def test_only_admin_sees_runtime_configuration(app_client, org_and_users):
    """설정에는 어떤 키가 들어 있는지가 드러난다."""
    tokens = org_and_users["tokens"]
    assert app_client.get("/api/diagnostics", headers=_auth(tokens[ROLE_MEMBER])).status_code == 403
    assert app_client.get("/api/diagnostics", headers=_auth(tokens[ROLE_ADMIN])).status_code == 200


def test_health_does_not_leak_configuration(app_client):
    """헬스체크는 무인증이므로 설정을 담으면 안 된다."""
    body = app_client.get("/api/health").json()
    assert "capabilities" not in body
    assert "source_keys_present" not in str(body)


# --- 테넌트 격리 -------------------------------------------------------------
def test_other_org_project_is_not_visible(app_client, org_and_users):
    tokens = org_and_users["tokens"]
    created = app_client.post(
        "/api/projects", json={"name": "내부 사건"}, headers=_auth(tokens[ROLE_MEMBER]),
    ).json()

    listing = app_client.get("/api/projects", headers=_auth(tokens["OUTSIDER"])).json()
    assert all(p["id"] != created["id"] for p in listing), "다른 기관 사건이 목록에 보인다"


def test_cross_tenant_access_returns_404_not_403(app_client, org_and_users):
    """403은 '그 ID의 사건이 존재한다'는 사실을 알려 준다. 404로 감춘다."""
    tokens = org_and_users["tokens"]
    created = app_client.post(
        "/api/projects", json={"name": "비공개 사건"}, headers=_auth(tokens[ROLE_MEMBER]),
    ).json()
    response = app_client.get(f"/api/projects/{created['id']}", headers=_auth(tokens["OUTSIDER"]))
    assert response.status_code == 404, "존재 여부가 드러나면 안 된다"


def test_sealed_reveal_is_denied_for_viewer(app_client, org_and_users):
    """봉인 원문은 읽기 전용 권한으로 열 수 없다(제7-A.6장)."""
    response = app_client.post(
        "/api/findings/probe/reveal",
        json={"confirmed": True, "reason": "검토", "reviewer": "viewer"},
        headers=_auth(org_and_users["tokens"][ROLE_VIEWER]),
    )
    # 없는 Finding이므로 404, 권한 문제면 403. 200이 나오면 안 된다.
    assert response.status_code in (403, 404)
    assert response.status_code != 200
