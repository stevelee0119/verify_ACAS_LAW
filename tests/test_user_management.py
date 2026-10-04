"""사용자 관리, 승인 워크플로, 테넌트 격리 및 월별 통계 단위 테스트.

- 회원가입 신청 및 대기 (PENDING) 상태 확인
- 가입 대기 계정 로그인 차단 및 승인 후 정상 로그인
- 가입 반려 및 반려 사유 안내
- 관리자 계정 삭제 방어 및 타 사용자 계정 삭제/비활성화
- 부트스트랩 관리자 기본 정보 (이창민, 종합행정학교 법무교육단 등) 보장
- 사용자별 프로젝트 strict 격리 (본인 프로젝트만 조회, 타인 프로젝트 404 은닉)
- 저장소 용량 1GB 쿼터 및 70% 초과 경고
- 매월 단위 활동 지표 (접속수, 분석빈도, 저장량, 컴퓨팅시간) 및 CSV 내보내기
"""
from __future__ import annotations

import io
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from apps.api.auth import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    bootstrap_admin_from_env,
    hash_password,
    issue_session,
)
from apps.api.db import Organization, Project, User, UserApprovalStatus, get_session_factory
from sqlalchemy import select
from apps.api.storage_quota import get_user_storage_usage_bytes, check_user_quota
from apps.api.user_metrics import get_user_monthly_metrics, get_all_users_monthly_metrics


@pytest.fixture(autouse=True)
def isolated_user_mgmt_db(tmp_path, monkeypatch):
    from apps.api import db
    from packages.common.config import reset_settings

    monkeypatch.setenv("LV_DATABASE_URL", "sqlite:///" + str(tmp_path / "user_mgmt.db"))
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_EMAIL", "admin@acas-law.mil.kr")
    monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_PASSWORD", "AdminPass123!@")
    reset_settings()
    db.reset_engine()
    db.init_db()
    engine = db.get_engine()
    yield
    engine.dispose()
    db.reset_engine()
    reset_settings()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from apps.api.main import create_app

    monkeypatch.setenv("LV_PSEUDONYM_SECRET", "test-secret")
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    return TestClient(create_app(), base_url="https://testserver")


@pytest.fixture()
def bootstrap_data():
    from sqlalchemy import select
    factory = get_session_factory()
    with factory() as session:
        admin = bootstrap_admin_from_env(session)
        if admin is None:
            admin = session.scalars(select(User).where(User.role == ROLE_ADMIN)).first()
        admin_id = admin.id
        admin_token = issue_session(session, admin)
        session.commit()
    return {"admin_id": admin_id, "admin_token": admin_token}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_bootstrap_admin_profile(bootstrap_data):
    """요구사항 2: 기존 부트스트랩 관리자의 성명, 소속, 연락처, 사유 기본값 보장 검증."""
    factory = get_session_factory()
    with factory() as session:
        admin = session.get(User, bootstrap_data["admin_id"])
        assert admin.display_name == "이창민"
        assert admin.affiliation == "종합행정학교 법무교육단"
        assert admin.phone_number == "010-4724-1500"
        assert admin.registration_reason == "프로그램 개발"
        assert admin.approval_status == UserApprovalStatus.APPROVED


def test_registration_approval_and_login_workflow(client, bootstrap_data):
    """요구사항 1, 2, 4, 5: 회원가입 신청 → 대기 → 로그인 거절 → 관리자 승인 → 정상 로그인 워크플로 검증."""
    admin_headers = _auth(bootstrap_data["admin_token"])

    # 1. 신규 사용자 가입 신청 (POST /api/auth/register)
    reg_payload = {
        "email": "officer@army.mil",
        "password": "Password123!@",
        "display_name": "김군법",
        "phone_number": "010-9876-5432",
        "affiliation": "육군종합행정학교 법무교육단",
        "registration_reason": "법률문서 검증 실무 수행",
    }
    res = client.post("/api/auth/register", json=reg_payload)
    assert res.status_code == 201
    user_id = res.json()["user_id"]

    # 2. 승인 대기 중 로그인 시도 -> 403 차단
    login_res = client.post("/api/auth/login", json={"email": "officer@army.mil", "password": "Password123!@"})
    assert login_res.status_code == 403
    assert "승인 대기" in login_res.json()["detail"]

    # 3. 관리자: 대기 신청자 목록 확인 (GET /api/admin/pending-registrations)
    pending_res = client.get("/api/admin/pending-registrations", headers=admin_headers)
    assert pending_res.status_code == 200
    pending_users = pending_res.json()["users"]
    assert any(u["id"] == user_id for u in pending_users)
    target = next(u for u in pending_users if u["id"] == user_id)
    assert target["display_name"] == "김군법"
    assert target["phone_number"] == "010-9876-5432"

    # 4. 관리자: 승인 처리 (POST /api/admin/users/{user_id}/approve)
    approve_res = client.post(f"/api/admin/users/{user_id}/approve", headers=admin_headers)
    assert approve_res.status_code == 200
    assert approve_res.json()["approved"] is True

    # 5. 승인 후 정상 로그인 확인
    login_ok = client.post("/api/auth/login", json={"email": "officer@army.mil", "password": "Password123!@"})
    assert login_ok.status_code == 200
    assert "access_token" in login_ok.json()


def test_registration_rejection_workflow(client, bootstrap_data):
    """가입 신청 반려 워크플로 및 사유 안내 검증."""
    admin_headers = _auth(bootstrap_data["admin_token"])

    # 1. 가입 신청
    client.post("/api/auth/register", json={
        "email": "reject_me@army.mil",
        "password": "Password123!@",
        "display_name": "박신청",
        "phone_number": "010-1111-2222",
        "affiliation": "외부 기관",
        "registration_reason": "테스트",
    })

    factory = get_session_factory()
    with factory() as session:
        user = session.scalars(select(User).where(User.email == "reject_me@army.mil")).one()
        user_id = user.id

    # 2. 관리자 반려 처리 (POST /api/admin/users/{user_id}/reject)
    reject_res = client.post(
        f"/api/admin/users/{user_id}/reject",
        headers=admin_headers,
        json={"reason": "소속 정보 불일치"},
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["rejected"] is True

    # 3. 반려된 사용자 로그인 시도 -> 사유 포함 403
    login_res = client.post("/api/auth/login", json={"email": "reject_me@army.mil", "password": "Password123!@"})
    assert login_res.status_code == 403
    assert "반려" in login_res.json()["detail"]
    assert "소속 정보 불일치" in login_res.json()["detail"]


def test_admin_cannot_delete_self(client, bootstrap_data):
    """관리자 계정 자기 자신 삭제 방어 검증."""
    admin_headers = _auth(bootstrap_data["admin_token"])
    admin_id = bootstrap_data["admin_id"]

    res = client.delete(f"/api/admin/users/{admin_id}", headers=admin_headers)
    assert res.status_code == 400
    assert "자기 자신" in res.json()["detail"]


def test_strict_tenant_isolation(client, bootstrap_data):
    """요구사항 6: 사용자가 본인이 생성한 프로젝트만 조회 가능함을 검증."""
    admin_headers = _auth(bootstrap_data["admin_token"])

    # 일반 사용자 계정 2개 생성 및 승인
    user_tokens = {}
    for name in ("user_a", "user_b"):
        email = f"{name}@army.mil"
        client.post("/api/auth/register", json={
            "email": email, "password": "Password123!@",
            "display_name": name, "phone_number": "010-0000-0000",
            "affiliation": "종합행정학교", "registration_reason": "검토",
        })
        factory = get_session_factory()
        with factory() as session:
            u = session.scalars(select(User).where(User.email == email)).one()
            from apps.api.identity import set_account_enabled
            u.approval_status = UserApprovalStatus.APPROVED
            set_account_enabled(session, u, True)
            token = issue_session(session, u)
            session.commit()
            user_tokens[name] = token

    # User A가 프로젝트 A 생성
    res_a = client.post("/api/projects", json={"name": "A의 단독 사건"}, headers=_auth(user_tokens["user_a"]))
    assert res_a.status_code == 201
    proj_a_id = res_a.json()["id"]

    # User B가 프로젝트 B 생성
    res_b = client.post("/api/projects", json={"name": "B의 단독 사건"}, headers=_auth(user_tokens["user_b"]))
    assert res_b.status_code == 201
    proj_b_id = res_b.json()["id"]

    # User A의 프로젝트 목록 조회 -> A의 사건만 존재, B의 사건 없음
    list_a = client.get("/api/projects", headers=_auth(user_tokens["user_a"])).json()
    assert any(p["id"] == proj_a_id for p in list_a)
    assert all(p["id"] != proj_b_id for p in list_a)

    # User A가 User B의 프로젝트 상세 조회 시도 -> 404 (존재 은닉)
    assert client.get(f"/api/projects/{proj_b_id}", headers=_auth(user_tokens["user_a"])).status_code == 404

    # User B의 프로젝트 목록 조회 -> B의 사건만 존재, A의 사건 없음
    list_b = client.get("/api/projects", headers=_auth(user_tokens["user_b"])).json()
    assert any(p["id"] == proj_b_id for p in list_b)
    assert all(p["id"] != proj_a_id for p in list_b)

    # 관리자라도 다른 사용자의 프로젝트는 조회되지 않음 (Strict Isolation)
    list_admin = client.get("/api/projects", headers=admin_headers).json()
    assert all(p["id"] not in (proj_a_id, proj_b_id) for p in list_admin)


@pytest.mark.parametrize("role", ["ADMIN", "MEMBER", "VIEWER"])
def test_storage_quota_calculation_and_limit(bootstrap_data, role):
    """요구사항 7: 1GB 쿼터 및 사용량 집계 검증."""
    factory = get_session_factory()
    with factory() as session:
        user = session.get(User, bootstrap_data["admin_id"])
        user.role = role
        user.storage_quota_bytes = 100  # Legacy values do not override the role policy.
        # 현재 사용량은 0
        used = get_user_storage_usage_bytes(session, user.id)
        assert used == 0

        # 1GB 이하 추가는 허용
        exceeded, cur, quota = check_user_quota(session, user, additional_bytes=500 * 1024 * 1024)
        assert not exceeded
        assert quota == (None if role == "ADMIN" else 1073741824)

        # 1GB 초과 추가는 차단
        exceeded_over, _, _ = check_user_quota(session, user, additional_bytes=1073741824 + 1)
        assert exceeded_over is (role != "ADMIN")


def test_monthly_activity_metrics_and_csv_export(client, bootstrap_data):
    """신규 요구사항: 월별 접속수, 분석빈도, 저장량, 컴퓨팅시간 통계 및 CSV 다운로드 검증."""
    admin_headers = _auth(bootstrap_data["admin_token"])
    now = datetime.utcnow()

    # 1. 월별 통계 집계 함수 단위 테스트
    factory = get_session_factory()
    with factory() as session:
        metrics = get_user_monthly_metrics(session, bootstrap_data["admin_id"], now.year, now.month)
        assert "login_count" in metrics
        assert "verification_count" in metrics
        assert "storage_used_mb" in metrics
        assert "storage_quota_mb" in metrics
        assert "storage_usage_percent" in metrics
        assert "compute_minutes" in metrics

    # 2. 관리자용 사용자 목록 API (GET /api/admin/users?year=YYYY&month=MM)
    users_res = client.get(f"/api/admin/users?year={now.year}&month={now.month}", headers=admin_headers)
    assert users_res.status_code == 200
    user_list = users_res.json()
    assert len(user_list) >= 1
    admin_user = next(u for u in user_list if u["id"] == bootstrap_data["admin_id"])
    assert admin_user["monthly_metrics"] is not None
    assert admin_user["storage_quota_bytes"] is None
    assert admin_user["storage_unlimited"] is True
    assert admin_user["monthly_metrics"]["storage_quota_mb"] is None
    assert admin_user["monthly_metrics"]["storage_usage_percent"] is None

    # 3. 특정 사용자 12개월 추이 API (GET /api/admin/users/{user_id}/monthly-stats)
    history_res = client.get(f"/api/admin/users/{bootstrap_data['admin_id']}/monthly-stats?months=12", headers=admin_headers)
    assert history_res.status_code == 200
    history = history_res.json()
    assert len(history) == 12

    # 4. 사용자 목록 및 월별 통계 CSV 다운로드 (GET /api/admin/users/export.csv)
    csv_res = client.get(f"/api/admin/users/export.csv?year={now.year}&month={now.month}", headers=admin_headers)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    csv_text = csv_res.content.decode("utf-8-sig")

    # CSV 헤더 검증
    assert "사용자ID" in csv_text
    assert "성명" in csv_text
    assert "이메일" in csv_text
    assert "현재원본용량_휴지통포함(MiB)" in csv_text
    assert "제한 없음" in csv_text
    assert "접속횟수" in csv_text
    assert "검증분석횟수" in csv_text
    assert "처리경과시간_대기포함(분)" in csv_text
    # 관리자 정보 포함 검증
    assert "이창민" in csv_text
    assert "종합행정학교 법무교육단" in csv_text


def _register(client, email="applicant@example.test"):
    response = client.post("/api/auth/register", json={
        "email": email, "password": "Password123!", "display_name": "Applicant",
        "phone_number": "010-0000-0000", "affiliation": "Test",
    })
    assert response.status_code == 201, response.text
    return response.json()["user_id"]


def test_approval_is_atomic_with_outbox_and_retry_does_not_reapprove(client, bootstrap_data, monkeypatch):
    from apps.api.db import UserNotification
    from apps.api.notifications import dispatch_once
    from packages.notification_engine.mailer import MailResult
    headers = _auth(bootstrap_data["admin_token"])
    user_id = _register(client)
    monkeypatch.setenv("LV_SMTP_HOST", "")
    response = client.post(f"/api/admin/users/{user_id}/approve", headers=headers)
    assert response.status_code == 200
    mail_id = response.json()["notification"]["id"]
    assert response.json()["notification"]["status"] == "QUEUED"
    assert client.post(f"/api/admin/users/{user_id}/approve", headers=headers).status_code == 409
    assert dispatch_once()
    result = client.get("/api/admin/notifications", headers=headers).json()
    assert result["smtp"]["configured"] is False
    assert result["items"][0]["status"] == "UNAVAILABLE"
    assert not dispatch_once()  # No infinite retry loop.
    with get_session_factory()() as session:
        user = session.get(User, user_id)
        approved_at = user.approved_at
        assert user.approval_status == "APPROVED"
    assert client.post(f"/api/admin/notifications/{mail_id}/retry", headers=headers).status_code == 200
    monkeypatch.setattr("apps.api.notifications.send_approval_email", lambda *args: MailResult("SMTP_ACCEPTED"))
    assert dispatch_once()
    with get_session_factory()() as session:
        assert session.get(UserNotification, mail_id).status == "SMTP_ACCEPTED"
        assert session.get(User, user_id).approved_at == approved_at
    assert client.post(f"/api/admin/notifications/{mail_id}/retry", headers=headers).status_code == 409


def test_rejection_is_password_gated_and_never_emails(client, bootstrap_data):
    from apps.api.db import UserNotification
    headers = _auth(bootstrap_data["admin_token"])
    user_id = _register(client)
    assert client.post(f"/api/admin/users/{user_id}/reject", headers=headers, json={"reason":" "}).status_code == 422
    assert client.post(f"/api/admin/users/{user_id}/reject", headers=headers, json={"reason":"Confirm affiliation"}).status_code == 200
    bad = client.post("/api/auth/login", json={"email":"applicant@example.test", "password":"wrong"})
    assert "Confirm affiliation" not in bad.text
    good = client.post("/api/auth/login", json={"email":"applicant@example.test", "password":"Password123!"})
    assert good.status_code == 403 and "Confirm affiliation" in good.text
    assert client.post(f"/api/admin/users/{user_id}/approve", headers=headers).status_code == 409
    with get_session_factory()() as session:
        assert session.scalars(select(UserNotification)).all() == []


def test_admin_endpoints_are_organization_scoped(client, bootstrap_data):
    from apps.api.notifications import queue_notification
    with get_session_factory()() as session:
        org = Organization(name="Other organization")
        session.add(org)
        session.flush()
        other = User(email="other@example.test", display_name="Other", organization_id=org.id,
                     approval_status="PENDING")
        session.add(other)
        session.flush()
        row = queue_notification(session, other, "APPROVAL")
        row.status = "FAILED"
        session.commit()
        other_id, mail_id = other.id, row.id
    headers = _auth(bootstrap_data["admin_token"])
    assert client.get("/api/admin/pending-registrations", headers=headers).json()["count"] == 0
    assert other_id not in [u["id"] for u in client.get("/api/admin/users", headers=headers).json()]
    assert "other@example.test" not in client.get("/api/admin/users/export.csv", headers=headers).text
    assert client.get("/api/admin/notifications", headers=headers).json()["items"] == []
    for action in ("approve", "reject"):
        assert client.post(f"/api/admin/users/{other_id}/{action}", headers=headers,
                           json={"reason":"test"}).status_code == 404
    assert client.delete(f"/api/admin/users/{other_id}", headers=headers).status_code == 404
    assert client.get(f"/api/admin/users/{other_id}/monthly-stats", headers=headers).status_code == 404
    assert client.post(f"/api/admin/notifications/{mail_id}/retry", headers=headers).status_code == 404


def test_unapproved_account_cannot_bypass_via_identity_api(client, bootstrap_data):
    from apps.api.identity import user_is_enabled, set_account_enabled, principal_for_user
    from fastapi import HTTPException
    user_id = _register(client)
    headers = _auth(bootstrap_data["admin_token"])
    assert client.patch(f"/api/identity/users/{user_id}", headers=headers, json={"enabled": True}).status_code == 409
    with get_session_factory()() as session:
        user = session.get(User, user_id)
        set_account_enabled(session, user, True)  # Simulate an inconsistent old database.
        session.commit()
        assert not user_is_enabled(session, user)
        with pytest.raises(HTTPException):
            principal_for_user(session, user_id, "token")


def test_metrics_count_only_login_success_and_csv_is_safe(client, bootstrap_data):
    from apps.api.services import make_audit
    from packages.common.enums import AuditEventType
    from sqlalchemy import event
    headers = _auth(bootstrap_data["admin_token"])
    now = datetime.utcnow()
    with get_session_factory()() as session:
        user = session.get(User, bootstrap_data["admin_id"])
        user.display_name = "=HYPERLINK(example)"
        user.registration_reason = "  +formula"
        session.commit()
        for name in ("LOGIN_SUCCEEDED", "LOGOUT", "USER_CREATED", "PROJECT_QUERY"):
            make_audit(session).record(AuditEventType.API_QUERY, {"event":name}, actor=user.id)
        counts = []
        def count(*args):
            counts.append(1)
        event.listen(session.get_bind(), "before_cursor_execute", count)
        try:
            result = get_all_users_monthly_metrics(session, now.year, now.month, user.organization_id)
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", count)
        assert len(counts) == 6
        assert result[user.id]["login_count"] == 1
    csv = client.get("/api/admin/users/export.csv", headers=headers)
    assert csv.content.startswith(b"\xef\xbb\xbf")
    assert not csv.content[3:].startswith(b"\xef\xbb\xbf")
    assert "'=HYPERLINK" in csv.text and "'  +formula" in csv.text
    for path in ("/api/admin/users?month=13", "/api/admin/users/export.csv?year=0",
                 f"/api/admin/users/{bootstrap_data['admin_id']}/monthly-stats?months=0"):
        assert client.get(path, headers=headers).status_code == 422
    history = client.get(f"/api/admin/users/{bootstrap_data['admin_id']}/monthly-stats?months=1", headers=headers).json()
    assert history[0]["storage_used_mb"] is None


def test_quota_duplicate_and_rollback_do_not_send_false_warning(client, bootstrap_data, monkeypatch):
    from apps.api.db import Document, UserNotification
    from apps.api.notifications import dispatch_once
    from packages.notification_engine.mailer import MailResult
    headers = _auth(bootstrap_data["admin_token"])
    project = client.post("/api/projects", headers=headers, json={"name":"Quota test"}).json()
    with get_session_factory()() as session:
        session.get(User, bootstrap_data["admin_id"]).role = ROLE_MEMBER
        session.add(Document(project_id=project["id"], filename="retained.txt", sha256="a"*64,
                             storage_key="retained", size_bytes=1073741824 - 100))
        session.commit()
    content = b"Legal document test. " * 4
    url = f"/api/projects/{project['id']}/documents"
    first = client.post(url, headers=headers, files={"file":("test.txt", content, "text/plain")}, data={"privacy_ack": "true"})
    assert first.status_code == 201, first.text
    duplicate = client.post(url, headers=headers, files={"file":("test.txt", content, "text/plain")}, data={"privacy_ack": "true"})
    assert duplicate.status_code == 201 and duplicate.json()["id"] == first.json()["id"]
    assert client.post(url, headers=headers, files={"file":("test.txt", b"x"*30, "text/plain")}, data={"privacy_ack": "true"}).status_code == 413
    with get_session_factory()() as session:
        assert len(session.scalars(select(UserNotification)).all()) == 1
        assert session.get(User, bootstrap_data["admin_id"]).quota_warning_sent_at is None
    monkeypatch.setattr("apps.api.notifications.send_quota_warning_email", lambda *args: MailResult("SMTP_ACCEPTED"))
    assert dispatch_once()
    with get_session_factory()() as session:
        assert session.get(User, bootstrap_data["admin_id"]).quota_warning_sent_at is not None


def test_admin_unlimited_upload_and_legacy_warning_cancelled(client, bootstrap_data, monkeypatch):
    from apps.api.db import Document, UserNotification
    from apps.api.notifications import dispatch_once, queue_notification, queue_quota_warning
    headers = _auth(bootstrap_data["admin_token"])
    project = client.post("/api/projects", headers=headers, json={"name": "Unlimited"}).json()
    with get_session_factory()() as session:
        user = session.get(User, bootstrap_data["admin_id"])
        session.add(Document(project_id=project["id"], filename="large.txt", sha256="a"*64,
                             storage_key="large", size_bytes=2 * 1073741824))
        assert queue_quota_warning(session, user, 2 * 1073741824) is None
        notice = queue_notification(session, user, "QUOTA", {"used_bytes": 100, "quota_bytes": 100})
        notice_id = notice.id
        session.commit()
    response = client.post(f"/api/projects/{project['id']}/documents", headers=headers,
                           files={"file": ("new.txt", b"Another legal document.", "text/plain")},
                           data={"privacy_ack": "true"})
    assert response.status_code == 201, response.text
    def unexpected_mail(*args):
        pytest.fail("An unlimited administrator must not receive quota warnings")
    monkeypatch.setattr("apps.api.notifications.send_quota_warning_email", unexpected_mail)
    assert dispatch_once()
    with get_session_factory()() as session:
        rows = session.scalars(select(UserNotification)).all()
        assert len(rows) == 1
        assert session.get(UserNotification, notice_id).status == "CANCELLED"
        assert session.get(UserNotification, notice_id).error_code == "QUOTA_NOT_APPLICABLE"
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["storage_unlimited"] and me["storage_quota_bytes"] is None


def test_member_storage_counts_trash_until_permanent_deletion(client, bootstrap_data):
    from apps.api.db import Document
    headers = _auth(bootstrap_data["admin_token"])
    with get_session_factory()() as session:
        user = session.get(User, bootstrap_data["admin_id"])
        user.role = ROLE_MEMBER
        user.storage_quota_bytes = 10 * 1073741824
        session.commit()
    old = client.post("/api/projects", headers=headers, json={"name": "Retained"}).json()["id"]
    new = client.post("/api/projects", headers=headers, json={"name": "Current"}).json()["id"]
    with get_session_factory()() as session:
        session.add(Document(project_id=old, filename="full.txt", sha256="b"*64,
                             storage_key="retained-original", size_bytes=1073741824))
        session.commit()
    assert client.delete(f"/api/projects/{old}", headers=headers).status_code == 204
    with get_session_factory()() as session:
        assert get_user_storage_usage_bytes(session, bootstrap_data["admin_id"]) == 1073741824
        now = datetime.utcnow()
        metrics = get_user_monthly_metrics(session, bootstrap_data["admin_id"], now.year, now.month)
        assert metrics["storage_used_mb"] == 1024
        assert metrics["storage_usage_percent"] == 100
        assert metrics["storage_unlimited"] is False
    url = f"/api/projects/{new}/documents"
    files = {"file": ("extra.txt", b"New legal document", "text/plain")}
    assert client.post(url, headers=headers, files=files, data={"privacy_ack": "true"}).status_code == 413
    assert client.post(f"/api/projects/{old}/restore", headers=headers).status_code == 200
    assert client.post(url, headers=headers, files=files, data={"privacy_ack": "true"}).status_code == 413
    assert client.delete(f"/api/projects/{old}", headers=headers).status_code == 204
    assert client.delete(f"/api/projects/{old}/purge", headers=headers).status_code == 200
    assert client.post(url, headers=headers, files=files, data={"privacy_ack": "true"}).status_code == 201


def test_stale_smtp_claim_is_not_automatically_resent(bootstrap_data):
    from datetime import timedelta
    from apps.api.db import UserNotification
    from apps.api.notifications import dispatch_once, queue_notification
    with get_session_factory()() as session:
        row = queue_notification(session, session.get(User, bootstrap_data["admin_id"]), "APPROVAL")
        row.status = "SENDING"
        row.attempted_at = datetime.utcnow() - timedelta(minutes=6)
        session.commit()
        mail_id = row.id
    assert not dispatch_once()
    with get_session_factory()() as session:
        assert session.get(UserNotification, mail_id).status == "UNKNOWN"


def test_bootstrap_never_reapproves_disabled_administrator(bootstrap_data):
    with get_session_factory()() as session:
        user = session.get(User, bootstrap_data["admin_id"])
        user.approval_status = "REJECTED"
        user.is_active = False
        session.commit()
        bootstrap_admin_from_env(session)
        assert user.approval_status == "REJECTED" and not user.is_active


def test_legacy_ownership_transfer_is_once_only_and_preserves_records(client, bootstrap_data, monkeypatch):
    from apps.api.db import Document, LegacyProjectOwnership, VerificationRun
    from apps.api.legacy_ownership import migrate_legacy_project_ownership
    with get_session_factory()() as session:
        old = Project(id="legacy-case", name="Original case", memo="Original memo")
        session.add(old)
        session.flush()
        session.add(Document(id="legacy-doc", project_id=old.id, filename="original.pdf",
                             size_bytes=123, sha256="a"*64, storage_key="immutable-original"))
        session.add(VerificationRun(id="legacy-run", project_id=old.id, state="COMPLETED",
                                    result_json={"preserved":True}))
        session.add(LegacyProjectOwnership(project_id=old.id))
        session.commit()
    assert migrate_legacy_project_ownership() == 1
    result = client.get("/api/admin/ownership-migration", headers=_auth(bootstrap_data["admin_token"]))
    assert result.json() == {"target_user_id": bootstrap_data["admin_id"], "total": 1,
                             "completed": 1, "pending": 0}
    with monkeypatch.context() as changed:
        changed.setenv("LV_BOOTSTRAP_ADMIN_EMAIL", "different@example.test")
        assert client.get("/api/admin/ownership-migration",
                          headers=_auth(bootstrap_data["admin_token"])).status_code == 404
    with get_session_factory()() as session:
        old = session.get(Project, "legacy-case")
        admin = session.get(User, bootstrap_data["admin_id"])
        assert (old.owner_id, old.organization_id) == (admin.id, admin.organization_id)
        assert old.memo == "Original memo"
        assert session.get(Document, "legacy-doc").storage_key == "immutable-original"
        assert session.get(VerificationRun, "legacy-run").result_json == {"preserved":True}
        assert session.get(LegacyProjectOwnership, old.id).previous_owner_id is None
        member = User(email="future@example.test", organization_id=admin.organization_id)
        session.add(member)
        session.flush()
        session.add(Project(id="future-case", name="New case", owner_id=member.id, organization_id=admin.organization_id))
        session.commit()
        member_id = member.id
    assert migrate_legacy_project_ownership() == 0
    with get_session_factory()() as session:
        assert session.get(Project, "future-case").owner_id == member_id


def test_legacy_transfer_missing_target_fails_without_partial_change(bootstrap_data, monkeypatch):
    from apps.api.db import LegacyProjectOwnership
    from apps.api.legacy_ownership import migrate_legacy_project_ownership
    with get_session_factory()() as session:
        session.add(Project(id="legacy-case", name="Unassigned"))
        session.flush()
        session.add(LegacyProjectOwnership(project_id="legacy-case"))
        session.commit()
    monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_EMAIL", "missing@example.test")
    with pytest.raises(RuntimeError, match="LV_BOOTSTRAP_ADMIN_EMAIL"):
        migrate_legacy_project_ownership()
    with get_session_factory()() as session:
        assert session.get(Project, "legacy-case").owner_id is None
        assert session.get(LegacyProjectOwnership, "legacy-case").migrated_at is None


def test_registration_uses_configured_bootstrap_organization(client, bootstrap_data):
    with get_session_factory()() as session:
        session.add(Organization(name="Unrelated organization"))
        session.commit()
        expected = session.get(User, bootstrap_data["admin_id"]).organization_id
    user_id = _register(client)
    with get_session_factory()() as session:
        assert session.get(User, user_id).organization_id == expected


def test_bootstrap_does_not_populate_an_unrelated_administrators_profile(bootstrap_data, monkeypatch):
    with get_session_factory()() as session:
        admin = session.get(User, bootstrap_data["admin_id"])
        admin.display_name = ""
        admin.phone_number = ""
        session.commit()
        monkeypatch.setenv("LV_BOOTSTRAP_ADMIN_EMAIL", "another@example.test")
        bootstrap_admin_from_env(session)
        assert admin.display_name == "" and admin.phone_number == ""
