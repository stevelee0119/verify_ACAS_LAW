"""Sliding browser sessions must preserve absolute expiry and revocation."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from apps.api import access, identity
from apps.api.db import SessionToken
from apps.api.session_policy import session_lifetimes
from test_auth_merge import PASSWORD, merged_auth  # noqa: F401


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        now_value = datetime.utcnow()

        @classmethod
        def utcnow(cls):
            return cls.now_value

    monkeypatch.setattr(identity, "datetime", Clock)
    monkeypatch.setattr(access, "datetime", Clock)
    monkeypatch.setenv("LV_SESSION_TTL_HOURS", "12")
    monkeypatch.setenv("LV_SESSION_ABSOLUTE_HOURS", "168")
    return Clock


def near_expiry(s, clock):
    with s.factory() as session:
        row = session.get(SessionToken, "old-member")
        row.issued_at = clock.utcnow() - timedelta(hours=11)
        row.expires_at = clock.utcnow() + timedelta(minutes=1)
        session.commit()
    s.client.cookies.set("lv_session", "legacy-session-member", domain="testserver.local", path="/")


def test_default_login_is_24_hours_with_seven_day_cap(merged_auth, monkeypatch):
    for key in ("LV_SESSION_TTL_HOURS", "LV_SESSION_ABSOLUTE_HOURS"):
        monkeypatch.delenv(key, raising=False)
    assert session_lifetimes() == (timedelta(hours=24), timedelta(days=7))
    response = merged_auth.client.post("/api/auth/login", json={
        "email": "member@example.invalid", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["expires_in"] == 86400
    assert "Max-Age=604800" in response.headers["set-cookie"]


def test_cookie_activity_slides_legacy_12_hour_setting_and_throttles_writes(merged_auth, clock):
    s = merged_auth
    near_expiry(s, clock)
    first = s.client.get("/api/identity/me")
    assert first.status_code == 200
    cookie = first.headers["set-cookie"]
    for value in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=565200"):
        assert value in cookie
    with s.factory() as session:
        expiry = session.get(SessionToken, "old-member").expires_at
        assert expiry == clock.utcnow() + timedelta(hours=12)
    clock.now_value += timedelta(minutes=14)
    second = s.client.get("/api/identity/me")
    assert second.status_code == 200
    assert "set-cookie" in second.headers
    with s.factory() as session:
        assert session.get(SessionToken, "old-member").expires_at == expiry
    clock.now_value += timedelta(minutes=2)
    assert "set-cookie" in s.client.get("/api/identity/me").headers


def test_repeated_long_analysis_requests_stop_at_absolute_limit(merged_auth, clock):
    s = merged_auth
    near_expiry(s, clock)
    hard_limit = clock.utcnow() + timedelta(hours=157)
    for _ in range(15):
        assert s.client.get("/api/identity/me").status_code == 200
        with s.factory() as session:
            expiry = session.get(SessionToken, "old-member").expires_at
            assert clock.utcnow() < expiry <= hard_limit
        clock.now_value += timedelta(hours=11)
    response = s.client.get("/api/identity/me")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("condition", ["expired", "revoked", "absolute", "disabled"])
def test_invalid_sessions_cannot_be_revived(merged_auth, clock, condition):
    from apps.api.db import User

    s = merged_auth
    near_expiry(s, clock)
    with s.factory() as session:
        row = session.get(SessionToken, "old-member")
        if condition == "expired":
            row.expires_at = clock.utcnow()
        elif condition == "revoked":
            row.revoked_at = clock.utcnow()
        elif condition == "absolute":
            row.issued_at = clock.utcnow() - timedelta(days=7)
        else:
            identity.set_account_enabled(session, session.get(User, "member"), False)
        session.commit()
        with pytest.raises(HTTPException) as exc:
            identity.renew_browser_activity(session, "lv_session", "legacy-session-member")
        assert exc.value.status_code == 401
    response = s.client.get("/api/identity/me")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("path,headers,expected", [
    ("/api/identity/me", {"Authorization": "Bearer legacy-session-member"}, 200),
    ("/api/diagnostics", {}, 403),
    ("/api/identity/me", {"Sec-Fetch-Site": "cross-site"}, 200),
    ("/api/identity/me", {"Origin": "https://untrusted.invalid"}, 200),
    ("/api/health", {}, 200),
])
def test_non_browser_or_denied_requests_do_not_renew(merged_auth, clock, path, headers, expected):
    s = merged_auth
    near_expiry(s, clock)
    response = s.client.get(path, headers=headers)
    assert response.status_code == expected
    assert "set-cookie" not in response.headers
    with s.factory() as session:
        assert session.get(SessionToken, "old-member").expires_at == clock.utcnow() + timedelta(minutes=1)


@pytest.mark.parametrize("path,method,body", [
    ("/api/auth/logout", "POST", None),
    ("/api/identity/session", "DELETE", None),
    ("/api/auth/password", "POST", {"current_password": PASSWORD, "new_password": "replacement-password-1234"}),
])
def test_logout_and_password_change_never_set_a_live_cookie(merged_auth, clock, path, method, body):
    s = merged_auth
    near_expiry(s, clock)
    response = s.client.request(method, path, json=body, headers={"Origin": "https://testserver"})
    assert response.status_code in {200, 204}
    for cookie in response.headers.get_list("set-cookie"):
        assert "Max-Age=0" in cookie
    assert s.client.get("/api/identity/me", headers=s.headers("member")).status_code == 401


def test_password_backed_browser_cookie_renews_source_and_keeps_hard_cap(merged_auth, clock):
    s = merged_auth
    near_expiry(s, clock)
    response = s.client.post("/api/identity/session", headers=s.headers("member"))
    assert response.status_code == 200
    assert s.client.get("/api/identity/me").status_code == 200
    with s.factory() as session:
        source = session.get(SessionToken, "old-member")
        browser = session.query(identity.BrowserSession).one()
        assert source.expires_at == browser.expires_at == clock.utcnow() + timedelta(hours=12)
        source.revoked_at = clock.utcnow()
        session.commit()
    assert s.client.get("/api/identity/me").status_code == 401


def test_token_browser_cannot_outlive_source_token(merged_auth, clock):
    s = merged_auth
    with s.factory() as session:
        token, raw = identity.issue_token(session, "member")
        token.expires_at = clock.utcnow() + timedelta(minutes=90)
        principal = identity.authenticate_bearer(session, raw)
        browser, secret = identity.issue_browser_session(session, principal)
        browser.expires_at = clock.utcnow() + timedelta(minutes=1)
        session.commit()
        assert identity.renew_browser_activity(session, "acas_session", secret) == token.expires_at
        assert browser.expires_at == token.expires_at


def test_oidc_browser_expiry_is_not_extended(merged_auth, clock, monkeypatch):
    s = merged_auth
    for key, value in {"LV_OIDC_ISSUER": "https://sso.invalid", "LV_OIDC_AUDIENCE": "acas",
                       "LV_OIDC_JWKS_URL": "https://sso.invalid/keys"}.items():
        monkeypatch.setenv(key, value)
    with s.factory() as session:
        source = identity.ExternalIdentity(user_id="member", issuer="https://sso.invalid", subject="member")
        session.add(source)
        session.flush()
        deadline = clock.utcnow() + timedelta(minutes=1)
        principal = identity.principal_for_user(session, "member", "oidc", source.id, deadline)
        browser, secret = identity.issue_browser_session(session, principal)
        session.commit()
        assert identity.renew_browser_activity(session, "acas_session", secret) is None
        assert browser.expires_at == deadline


@pytest.mark.parametrize("value", ["0", "721", "broken"])
def test_invalid_lifetime_configuration_fails_closed(monkeypatch, value):
    monkeypatch.setenv("LV_SESSION_TTL_HOURS", value)
    with pytest.raises(ValueError):
        session_lifetimes()


def test_browser_update_conflict_rolls_back_source_extension(merged_auth, clock, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.sql.dml import Update

    s = merged_auth
    near_expiry(s, clock)
    with s.factory() as session:
        principal = identity.authenticate_password_session(session, "legacy-session-member")
        browser, secret = identity.issue_browser_session(session, principal)
        session.commit()
        original_expiry = browser.expires_at
        execute = session.execute

        def conflict(statement, *args, **kwargs):
            if isinstance(statement, Update) and statement.table.name == "identity_browser_sessions":
                return SimpleNamespace(rowcount=0)
            return execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", conflict)
        assert identity.renew_browser_activity(session, "acas_session", secret) is None
        assert session.get(SessionToken, "old-member").expires_at == original_expiry
        assert session.get(identity.BrowserSession, browser.id).expires_at == original_expiry


def test_diagnostics_reports_effective_legacy_policy(monkeypatch):
    from apps.api.capabilities import runtime_capabilities

    monkeypatch.setenv("LV_SESSION_TTL_HOURS", "12")
    monkeypatch.setenv("LV_SESSION_ABSOLUTE_HOURS", "168")
    assert runtime_capabilities()["browser_session"] == {
        "idle_hours": 12, "absolute_hours": 168, "renew_on_activity": True,
        "analysis_protection_hours": 168, "result_review_hours": 24}
