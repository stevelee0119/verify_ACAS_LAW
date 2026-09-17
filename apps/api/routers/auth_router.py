"""인증 엔드포인트. 로그인·로그아웃·계정 관리(제21.3장).

모든 인증 사건은 감사추적에 남긴다(제15장). 다만 비밀번호와 토큰 원문은
감사 기록에도 남기지 않는다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.enums import AuditEventType

from ..auth import (
    ROLES,
    SESSION_TTL_HOURS,
    authenticate,
    current_user,
    hash_password,
    issue_session,
    require_admin,
    revoke_all_sessions,
    revoke_session,
    _bearer,
)
from ..db import Organization, SessionToken, User, get_db
from ..services import make_audit

router = APIRouter(tags=["auth"])


def _normalize_email(value: str) -> str:
    """로그인 식별자를 정규화한다.

    정교한 이메일 문법 검사는 하지 않는다. 실질적인 검증은 "저장된 계정과
    일치하는가"이며, 규격 검사를 위해 의존성을 늘릴 이유가 없다.
    오타로 쓸 수 없는 계정이 만들어지는 것만 막는다.
    """
    email = (value or "").strip().lower()
    if len(email) < 3 or email.count("@") != 1 or any(c.isspace() for c in email):
        raise ValueError("이메일 형식이 올바르지 않다")
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        raise ValueError("이메일 형식이 올바르지 않다")
    return email


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    organization_id: Optional[str] = None


class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(min_length=10)
    display_name: str = ""
    role: str = "MEMBER"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


def _out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or "",
        role=str(user.role),
        organization_id=user.organization_id,
    )


@router.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = authenticate(session, payload.email, payload.password)
    token = issue_session(session, user, user_agent=request.headers.get("user-agent", ""))
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "LOGIN_SUCCEEDED", "user_id": user.id, "role": str(user.role)},
        actor=user.email,
    )
    # 브라우저 편의를 위한 쿠키. 토큰은 스크립트가 읽지 못하게 HttpOnly로 둔다.
    # Render 같은 관리형 프록시 뒤에서는 컨테이너가 보는 scheme이 http이므로
    # X-Forwarded-Proto도 함께 본다. 그러지 않으면 HTTPS 사이트인데 쿠키에
    # Secure가 붙지 않는다.
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    is_https = request.url.scheme == "https" or forwarded == "https"
    response.set_cookie(
        "lv_session", token, httponly=True, samesite="strict",
        secure=is_https, max_age=SESSION_TTL_HOURS * 3600,
    )
    return {"access_token": token, "token_type": "bearer",
            "expires_in": SESSION_TTL_HOURS * 3600, "user": _out(user).model_dump()}


@router.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    token = _bearer(request.headers.get("authorization")) or (request.cookies.get("lv_session") or "")
    revoked = revoke_session(session, token)
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "LOGOUT", "user_id": user.id},
        actor=user.email,
    )
    response.delete_cookie("lv_session")
    return {"revoked": revoked}


@router.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return _out(user)


@router.post("/api/auth/password")
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """비밀번호를 바꾼다. 기존 세션은 모두 끊는다."""
    authenticate(session, user.email, payload.current_password)
    user.password_hash = hash_password(payload.new_password)
    session.commit()
    revoked = revoke_all_sessions(session, user.id)
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "PASSWORD_CHANGED", "user_id": user.id, "revoked_sessions": revoked},
        actor=user.email,
    )
    return {"changed": True, "revoked_sessions": revoked,
            "notice": "기존 세션이 모두 종료되었다. 다시 로그인해야 한다."}


# --- 관리자 전용 -------------------------------------------------------------
@router.get("/api/auth/users", response_model=List[UserOut])
def list_users(
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> List[UserOut]:
    rows = session.execute(
        select(User).where(User.organization_id == admin.organization_id).order_by(User.created_at)
    ).scalars().all()
    return [_out(u) for u in rows]


@router.post("/api/auth/users", response_model=UserOut, status_code=201)
def create_user(
    payload: CreateUserRequest,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> UserOut:
    role = payload.role.upper()
    if role not in ROLES:
        raise HTTPException(400, f"허용되지 않는 역할이다: {payload.role}")
    email = payload.email.strip().lower()
    if session.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None:
        raise HTTPException(409, "이미 존재하는 이메일이다")
    user = User(
        email=email,
        display_name=payload.display_name,
        role=role,
        organization_id=admin.organization_id,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    session.commit()
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "USER_CREATED", "user_id": user.id, "role": role},
        actor=admin.email,
    )
    return _out(user)


@router.post("/api/auth/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """계정을 막고 세션을 끊는다. 계정과 감사기록은 삭제하지 않는다(부록 C 제7항)."""
    target = session.get(User, user_id)
    if target is None or target.organization_id != admin.organization_id:
        raise HTTPException(404, "사용자를 찾을 수 없다")
    if target.id == admin.id:
        raise HTTPException(400, "자기 계정은 비활성화할 수 없다")
    target.is_active = False
    session.commit()
    revoked = revoke_all_sessions(session, target.id)
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "USER_DEACTIVATED", "user_id": target.id, "revoked_sessions": revoked},
        actor=admin.email,
    )
    return {"deactivated": True, "revoked_sessions": revoked}


@router.get("/api/auth/sessions")
def my_sessions(
    user: User = Depends(current_user),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """내 활성 세션 목록. 토큰 원문이나 해시는 보여주지 않는다."""
    rows = session.execute(
        select(SessionToken).where(SessionToken.user_id == user.id).order_by(SessionToken.issued_at.desc())
    ).scalars().all()
    return [
        {
            "id": row.id,
            "issued_at": row.issued_at.isoformat() if row.issued_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "revoked": row.revoked_at is not None,
            "user_agent": row.user_agent or "",
        }
        for row in rows
    ]
