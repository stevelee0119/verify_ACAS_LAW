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


def test_storage_quota_calculation_and_limit(bootstrap_data):
    """요구사항 7: 1GB 쿼터 및 사용량 집계 검증."""
    factory = get_session_factory()
    with factory() as session:
        user = session.get(User, bootstrap_data["admin_id"])
        # 현재 사용량은 0
        used = get_user_storage_usage_bytes(session, user.id)
        assert used == 0

        # 1GB 이하 추가는 허용
        exceeded, cur, quota = check_user_quota(session, user, additional_bytes=500 * 1024 * 1024)
        assert not exceeded
        assert quota == 1073741824

        # 1GB 초과 추가는 차단
        exceeded_over, _, _ = check_user_quota(session, user, additional_bytes=1073741824 + 1)
        assert exceeded_over


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
    assert admin_user["monthly_metrics"]["storage_quota_mb"] == 1024.0

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
    assert "누적저장용량(MB)" in csv_text
    assert "접속횟수" in csv_text
    assert "검증분석횟수" in csv_text
    assert "컴퓨팅소요시간(분)" in csv_text
    # 관리자 정보 포함 검증
    assert "이창민" in csv_text
    assert "종합행정학교 법무교육단" in csv_text
