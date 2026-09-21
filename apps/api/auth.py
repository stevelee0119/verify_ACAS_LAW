"""인증과 접근통제 (제21.3장 기관 정책, 제15장 감사추적).

이 모듈의 설계 판단을 먼저 적어 둔다.

- 인증을 끄는 스위치를 두지 않는다. 봉인 원문 열람과 감사추적 조회가 가능한
  도구에서 `AUTH_DISABLED=1` 같은 플래그는 결국 운영에 올라간다.
  사용자가 한 명도 없으면 열어 주는 대신 503으로 거부하고 부트스트랩을 안내한다.
- 세션은 DB에 둔다. 무상태 토큰은 폐기할 수 없고, 폐기할 수 없는 자격증명은
  이 도구가 다루는 자료의 성격에 맞지 않는다.
- 비밀번호는 scrypt로만 보관한다. 원문도, 되돌릴 수 있는 형태도 남기지 않는다.
- 접근 거부는 존재를 알리지 않는다. 남의 프로젝트는 403이 아니라 404다.
  403은 "그 자원이 있다"는 사실을 알려 준다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import (
    Document,
    FindingRow,
    Organization,
    Project,
    ReportRow,
    SessionToken,
    User,
    VerificationRun,
    get_db,
)
from . import identity
from .session_policy import session_deadline

# --- 역할 ------------------------------------------------------------------
ROLE_ADMIN = "ADMIN"
ROLE_MEMBER = "MEMBER"
ROLE_VIEWER = "VIEWER"
ROLES = (ROLE_ADMIN, ROLE_MEMBER, ROLE_VIEWER)
_ROLE_RANK = {ROLE_VIEWER: 0, ROLE_MEMBER: 1, ROLE_ADMIN: 2}

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

# scrypt 파라미터. RFC 7914 권장 범위에서 대화형 로그인에 맞춘 값이다.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
# OpenSSL 기본 한도는 32 MiB이고 위 파라미터가 정확히 그 경계(128*N*r)에 닿는다.
# 명시하지 않으면 "memory limit exceeded"로 로그인 자체가 불가능해진다.
_SCRYPT_MAXMEM = 128 * _SCRYPT_N * _SCRYPT_R * 2


# --- 비밀번호 ---------------------------------------------------------------
def hash_password(password: str) -> str:
    """scrypt로 해시한다. 파라미터를 함께 저장해 나중에 조정할 수 있게 한다."""
    if not password or len(password) < 10:
        raise ValueError("비밀번호는 10자 이상이어야 한다")
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                         p=_SCRYPT_P, dklen=_KEY_BYTES, maxmem=_SCRYPT_MAXMEM)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    """저장된 해시와 대조한다. 형식이 깨졌거나 비어 있으면 실패로 본다."""
    if not stored or not password:
        return False
    try:
        scheme, n, r, p, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(key_hex)),
            maxmem=128 * int(n) * int(r) * 2,
        )
    except (ValueError, TypeError):
        return False
    # 타이밍 차이로 해시를 추측하지 못하게 한다
    return hmac.compare_digest(candidate, bytes.fromhex(key_hex))


# --- 세션 토큰 --------------------------------------------------------------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(session: Session, user: User, *, user_agent: str = "") -> str:
    """새 세션을 만들고 토큰 원문을 돌려준다. 원문은 여기서만 존재한다."""
    identity.principal_for_user(session, user.id, "password")
    now = datetime.utcnow()
    expires_at = session_deadline(now, now)
    token = secrets.token_urlsafe(32)
    session.add(
        SessionToken(
            user_id=user.id,
            token_hash=_token_hash(token),
            issued_at=now,
            expires_at=expires_at,
            user_agent=(user_agent or "")[:300],
        )
    )
    user.last_login_at = datetime.utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    session.commit()
    return token


def revoke_session(session: Session, token: str) -> bool:
    row = session.execute(
        select(SessionToken).where(SessionToken.token_hash == _token_hash(token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.utcnow()
    session.commit()
    return True


def revoke_all_sessions(session: Session, user_id: str) -> int:
    """비밀번호 변경·비활성화 시 기존 세션을 모두 끊는다."""
    count = identity.revoke_user_credentials(session, user_id)
    session.commit()
    return count


def resolve_session(session: Session, token: str) -> Optional[User]:
    """토큰으로 사용자를 찾는다. 만료·폐기·비활성 계정은 통과시키지 않는다."""
    try:
        principal = identity.authenticate_password_session(session, token)
    except HTTPException:
        return None
    return session.get(User, principal.user_id)


# --- 로그인 -----------------------------------------------------------------
def authenticate(session: Session, email: str, password: str) -> User:
    """자격증명을 확인한다. 실패 사유를 구분해 알려주지 않는다."""
    normalized = (email or "").strip().lower()
    user = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()

    if user is not None and user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(429, "로그인 시도가 많아 일시적으로 잠겼다. 잠시 후 다시 시도한다.")

    # 계정이 없어도 같은 비용을 치러, 응답 시간으로 계정 존재 여부를 알 수 없게 한다.
    stored = user.password_hash if user is not None else None
    ok = verify_password(password, stored)
    if not ok and user is None:
        hash_password("dummy-password-for-timing")

    if not ok:
        if user is not None:
            user.failed_login_count = int(user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            session.commit()
        # 계정 없음과 비밀번호 오류를 구분해 주지 않는다
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않다")

    if not user.is_active:
        raise HTTPException(403, "비활성화된 계정이다")
    identity.principal_for_user(session, user.id, "password")
    return user


# --- 의존성 -----------------------------------------------------------------
def _bearer(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(get_db),
) -> User:
    """Compatibility dependency; authentication belongs only to workspace_access."""
    principal = identity.current_principal(request)
    if principal.is_local:
        return User(id=identity.LOCAL_OWNER, email="local-owner@localhost", display_name="Local owner",
                    role=ROLE_ADMIN, is_active=True)
    identity.principal_for_user(session, principal.user_id, principal.authentication,
                                principal.credential_id, principal.expires_at)
    user = session.get(User, principal.user_id)
    request.state.user_id = user.id
    return user


def require_role(*allowed: str):
    """역할 기반 접근통제. 상위 역할은 하위 권한을 포함한다."""
    minimum = min(_ROLE_RANK[r] for r in allowed)

    def dependency(user: User = Depends(current_user)) -> User:
        if _ROLE_RANK.get(str(user.role), -1) < minimum:
            raise HTTPException(403, "이 작업을 수행할 권한이 없다")
        return user

    return dependency


require_admin = require_role(ROLE_ADMIN)
require_editor = require_role(ROLE_MEMBER)  # MEMBER 이상. VIEWER는 쓰기 불가


def is_editor(user: User) -> bool:
    return _ROLE_RANK.get(str(user.role), -1) >= _ROLE_RANK[ROLE_MEMBER]


# --- 프로젝트 단위 접근통제 --------------------------------------------------
def accessible_project(session: Session, user: User, project_id: str) -> Project:
    """접근 가능한 프로젝트만 돌려준다.

    권한이 없으면 403이 아니라 404를 낸다. 403은 "그 ID의 프로젝트가 존재한다"는
    사실을 알려 주어, 사건번호를 넣어 보며 존재를 확인할 수 있게 된다.
    """
    return identity.require_project(session, project_id, principal=_trusted_principal(user))


def _trusted_principal(user: User) -> identity.Principal:
    principal = identity.current_principal()
    if principal.user_id != user.id:
        raise HTTPException(401, "Principal mismatch")
    return principal


def editable_project(session: Session, user: User, project_id: str) -> Project:
    """쓰기 권한까지 확인한다. VIEWER는 읽을 수는 있어도 바꿀 수 없다."""
    return identity.require_project(session, project_id, "MEMBER", _trusted_principal(user))


def visible_project_ids(session: Session, user: User) -> list:
    """목록 조회에 쓸 접근 가능 프로젝트 ID."""
    ids = identity.visible_project_ids(session, _trusted_principal(user))
    return list(session.scalars(select(Project.id))) if ids is None else ids


# --- 하위 자원 접근통제 ------------------------------------------------------
#
# 문서·검증실행·Finding·보고서는 모두 프로젝트에 속한다. 소속 프로젝트에 접근할 수
# 없으면 그 자원의 존재도 알리지 않는다(404).
def accessible_document(session: Session, user: User, document_id: str) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "문서를 찾을 수 없다")
    accessible_project(session, user, document.project_id)
    return document


def editable_document(session: Session, user: User, document_id: str) -> Document:
    document = accessible_document(session, user, document_id)
    editable_project(session, user, document.project_id)
    return document


def accessible_run(session: Session, user: User, run_id: str) -> VerificationRun:
    run = session.get(VerificationRun, run_id)
    if run is None:
        raise HTTPException(404, "검증 실행을 찾을 수 없다")
    accessible_project(session, user, run.project_id)
    return run


def accessible_finding(session: Session, user: User, finding_id: str) -> FindingRow:
    finding = session.get(FindingRow, finding_id)
    if finding is None:
        raise HTTPException(404, "Finding을 찾을 수 없다")
    accessible_project(session, user, finding.project_id)
    return finding


def accessible_report(session: Session, user: User, report_id: str) -> ReportRow:
    report = session.get(ReportRow, report_id)
    if report is None:
        raise HTTPException(404, "보고서를 찾을 수 없다")
    accessible_project(session, user, report.project_id)
    return report


# --- 부트스트랩 -------------------------------------------------------------
def bootstrap_admin_from_env(session: Session) -> Optional[User]:
    """환경변수로 최초 관리자를 만든다. 이미 사용자가 있으면 아무것도 하지 않는다."""
    identity.auth_mode()
    identity.reconcile_password_accounts(session)
    session.commit()
    if identity.has_provisioned_users(session):
        return None
    email = (os.getenv("LV_BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("LV_BOOTSTRAP_ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    organizations = session.scalars(select(Organization).limit(2)).all()
    if len(organizations) > 1:
        raise ValueError("Multiple organizations exist; provision an administrator explicitly")
    organization = organizations[0] if organizations else None
    if organization is None:
        organization = Organization(name=os.getenv("LV_ORG_NAME", "기본 기관"))
        session.add(organization)
        session.flush()
    user = User(
        email=email,
        display_name=os.getenv("LV_BOOTSTRAP_ADMIN_NAME", "관리자"),
        role=ROLE_ADMIN,
        organization_id=organization.id,
        password_hash=hash_password(password),
    )
    session.add(user)
    session.flush()
    identity.set_account_enabled(session, user, True)
    session.commit()
    return user
