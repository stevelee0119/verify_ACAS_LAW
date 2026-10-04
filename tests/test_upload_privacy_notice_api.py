"""업로드 개인정보 안내 및 확인 서버 API 검증 시험 (새 시험).

요구사항:
1. 확인 없이 업로드하면 422로 저장되지 않는다 (API 우회 불가).
2. 확인하여 업로드하면 201 성공이며, 감사 기록에 확인 사실(사용자, 프로젝트, 문서, 시각, 버전)이 남는다.
3. 감사 기록에 원문 개인정보는 기록되지 않는다.
"""
from __future__ import annotations

import io
import uuid
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from packages.common.enums import AuditEventType
from packages.common.privacy_notice import (
    NOTICE_TITLE,
    PRIVACY_ACK_ERROR_MESSAGE,
    PRIVACY_NOTICE_VERSION,
)
from apps.api import db as db_module
from apps.api.auth import ROLE_ADMIN, hash_password, issue_session
from apps.api.db import AuditEventRow, Document, Organization, Project, User, get_session_factory
from apps.api.main import create_app
from apps.api.services import set_registry


@pytest.fixture
def api_client(registry):
    """관리자로 로그인한 테스트 클라이언트."""
    set_registry(registry)
    db_module.reset_engine()
    app = create_app()

    session = get_session_factory()()
    try:
        organization = session.query(Organization).first()
        if organization is None:
            organization = Organization(name="테스트 기관")
            session.add(organization)
            session.flush()
        user = User(
            email=f"tester-{uuid.uuid4().hex[:8]}@example.com",
            display_name="테스트 관리자",
            role=ROLE_ADMIN,
            organization_id=organization.id,
            password_hash=hash_password("test-password-1234"),
        )
        session.add(user)
        session.commit()
        token = issue_session(session, user)
    finally:
        session.close()

    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.fixture
def db_session():
    """데이터베이스 세션 fixture."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_project(api_client):
    """새 시험을 위한 독립 프로젝트 생성 (합성 데이터)."""
    resp = api_client.post(
        "/api/projects",
        json={
            "name": f"개인정보 안내 시험 {uuid.uuid4().hex[:6]}",
            "case_number": "2026가합9999",
            "court": "서울고등법원",
        },
    )
    assert resp.status_code == 201
    return resp.json()


def make_test_file(filename: str = "합성문서_검증용.pdf") -> tuple:
    """합성 PDF 파일 튜플 (파일명, 파일 스트림, MIME)."""
    return (filename, io.BytesIO(b"%PDF-1.4 synthetic test pdf content bytes 12345"), "application/pdf")


def test_upload_without_privacy_ack_returns_422_and_does_not_save(api_client, test_project, db_session):
    """확인 값(privacy_ack) 없이 업로드 시 422로 거절되고 DB에 저장되지 않는다."""
    project_id = test_project["id"]
    filename, stream, mime = make_test_file("미확인_문서.pdf")

    # privacy_ack 필드 없이 업로드 시도
    response = api_client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (filename, stream, mime)},
    )

    # 422 Unprocessable Entity 거절 확인
    assert response.status_code == 422
    data = response.json()
    assert PRIVACY_ACK_ERROR_MESSAGE in str(data)

    # DB에 문서가 저장되지 않았음을 검증
    saved_doc = db_session.scalar(
        select(Document).where(Document.project_id == project_id, Document.filename == filename)
    )
    assert saved_doc is None, "422 거절 시 DB에 문서가 저장되어서는 안 된다"


def test_upload_with_false_privacy_ack_returns_422(api_client, test_project, db_session):
    """privacy_ack가 False 또는 빈 값인 경우 422로 거절된다 (API 우회 불가)."""
    project_id = test_project["id"]
    filename, stream, mime = make_test_file("거짓확인_문서.pdf")

    # privacy_ack를 false로 명시하여 업로드 시도
    response = api_client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (filename, stream, mime)},
        data={"privacy_ack": "false"},
    )

    assert response.status_code == 422
    assert PRIVACY_ACK_ERROR_MESSAGE in str(response.json())


def test_upload_with_privacy_ack_succeeds_and_creates_audit(api_client, test_project, db_session):
    """확인 값(privacy_ack=True)으로 업로드하면 201 성공하며 감사 기록이 남는다 (원문 개인정보 없음)."""
    project_id = test_project["id"]
    filename, stream, mime = make_test_file("정상확인_문서.pdf")

    response = api_client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (filename, stream, mime)},
        data={"privacy_ack": "true"},
    )

    assert response.status_code == 201
    doc_data = response.json()
    document_id = doc_data["id"]

    # DB에 문서가 정상 저장되었는지 검증
    saved_doc = db_session.scalar(select(Document).where(Document.id == document_id))
    assert saved_doc is not None
    assert saved_doc.filename == filename

    # 감사 기록(AuditEventRow) 검증
    audit_events = db_session.scalars(
        select(AuditEventRow).where(
            AuditEventRow.project_id == project_id,
            AuditEventRow.document_id == document_id,
        )
    ).all()
    assert len(audit_events) > 0, "업로드 시 감사 기록이 생성되어야 한다"

    # 1. UPLOAD 이벤트에서 privacy_ack 및 notice_version 기록 확인 (판 1.1 검증)
    upload_event = next((e for e in audit_events if e.event_type == AuditEventType.UPLOAD), None)
    assert upload_event is not None
    assert upload_event.actor is not None, "사용자(actor)가 기록되어야 한다"
    assert upload_event.project_id == project_id
    assert upload_event.document_id == document_id
    assert upload_event.payload.get("privacy_ack") is True
    assert upload_event.payload.get("notice_version") == PRIVACY_NOTICE_VERSION
    assert upload_event.payload.get("notice_version") == "1.1", "감사 기록의 notice_version이 1.1이어야 한다"

    # 2. USER_OVERRIDE 이벤트에서 확인 사실 기록 확인
    ack_event = next((e for e in audit_events if e.event_type == AuditEventType.USER_OVERRIDE), None)
    assert ack_event is not None
    assert ack_event.payload.get("action") == "PRIVACY_NOTICE_ACKNOWLEDGED"
    assert ack_event.payload.get("notice_version") == PRIVACY_NOTICE_VERSION
    assert ack_event.payload.get("notice_version") == "1.1"

    # 3. 원문 개인정보 배제 검증: 감사 기록 payload에 파일 메타데이터 외에 원문 개인정보가 없어야 함
    for ev in audit_events:
        payload_str = str(ev.payload)
        assert "주민" not in payload_str or "직접 처리 확인" in payload_str or "이외의 개인정보" in payload_str
        assert "010-" not in payload_str
        assert "주소" not in payload_str


def test_privacy_notice_endpoint_returns_centralized_constants(api_client):
    """안내 문구와 판 번호가 /api/privacy-notice에서 올바르게 제공되는지 검증 (제목 포함)."""
    response = api_client.get("/api/privacy-notice")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == NOTICE_TITLE
    assert data["title"] == "제한적 개인정보 가림 기능 제공 안내"
    assert data["version"] == "1.1"
    assert data["version"] == PRIVACY_NOTICE_VERSION
    assert len(data["bullets"]) == 3
    assert "제한적으로 적용됩니다" in data["bullets"][0]
    assert "필수기능으로 제공되지만" in data["bullets"][1]
    assert "직접 가림 처리 하시고" in data["bullets"][2]
    assert "이외의 개인정보는 미포함되었거나 직접 가림 처리" in data["ack_label"]
    assert "제한적 개인정보 가림: 연락처·주민등록번호는 필수 가림" in data["report_header"]
    assert "확인해야 업로드할 수 있습니다" in data["ack_error_message"]


def test_unauthenticated_privacy_notice_get_returns_200_without_sensitive_data(registry, monkeypatch):
    """비로그인 상태(multi-user)에서도 GET /api/privacy-notice는 200이며 개인정보나 내부 설정값이 없다 (3차 보완)."""
    # multi-user 환경 및 비인증 상태 모의
    monkeypatch.setenv("LV_AUTH_MODE", "multi-user")
    monkeypatch.setenv("LV_ACCESS_TOKEN", "")
    set_registry(registry)
    db_module.reset_engine()
    app = create_app()

    # 인증 헤더 없는 순수 클라이언트
    client = TestClient(app)
    response = client.get("/api/privacy-notice")
    assert response.status_code == 200

    data = response.json()
    # 1. 안내문 필수 필드 및 판 1.1 검증
    assert data["title"] == NOTICE_TITLE
    assert data["version"] == PRIVACY_NOTICE_VERSION
    assert data["version"] == "1.1"
    assert len(data["bullets"]) == 3

    # 2. 개인정보 및 내부 설정값 부존재 검증
    sensitive_keys = {
        "user", "users", "account", "token", "password", "secret", "session",
        "email", "phone", "db", "database", "database_url", "storage_key",
        "encryption_key", "internal", "config", "settings",
    }
    for key in sensitive_keys:
        assert key not in data, f"비인증 안내문 응답에 민감 키({key})가 포함되어서는 안 된다"

    # 응답 본문 텍스트 내에도 민감한 설정 문자열이 없음을 확인
    raw_text = response.text.lower()
    for sensitive_word in ("secret", "password", "bearer", "sqlite:", "postgresql:"):
        assert sensitive_word not in raw_text, f"비인증 응답에 내부 구성({sensitive_word})이 노출되어서는 안 된다"

