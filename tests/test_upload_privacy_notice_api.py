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
from packages.common.privacy_notice import PRIVACY_ACK_ERROR_MESSAGE, PRIVACY_NOTICE_VERSION
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

    # 1. UPLOAD 이벤트에서 privacy_ack 및 notice_version 기록 확인
    upload_event = next((e for e in audit_events if e.event_type == AuditEventType.UPLOAD), None)
    assert upload_event is not None
    assert upload_event.actor is not None, "사용자(actor)가 기록되어야 한다"
    assert upload_event.project_id == project_id
    assert upload_event.document_id == document_id
    assert upload_event.payload.get("privacy_ack") is True
    assert upload_event.payload.get("notice_version") == PRIVACY_NOTICE_VERSION

    # 2. USER_OVERRIDE 이벤트에서 확인 사실 기록 확인
    ack_event = next((e for e in audit_events if e.event_type == AuditEventType.USER_OVERRIDE), None)
    assert ack_event is not None
    assert ack_event.payload.get("action") == "PRIVACY_NOTICE_ACKNOWLEDGED"
    assert ack_event.payload.get("notice_version") == PRIVACY_NOTICE_VERSION

    # 3. 원문 개인정보 배제 검증: 감사 기록 payload에 파일 메타데이터 외에 원문 개인정보가 없어야 함
    for ev in audit_events:
        payload_str = str(ev.payload)
        assert "주민" not in payload_str or "직접 처리 확인" in payload_str
        assert "010-" not in payload_str
        assert "주소" not in payload_str
