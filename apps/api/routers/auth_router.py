"""인증 엔드포인트. 로그인·로그아웃·계정 관리(제21.3장).

모든 인증 사건은 감사추적에 남긴다(제15장). 다만 비밀번호와 토큰 원문은
감사 기록에도 남기지 않는다.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.common.enums import AuditEventType

from ..auth import (
    ROLES,
    authenticate,
    current_user,
    hash_password,
    issue_session,
    require_admin,
    revoke_all_sessions,
)
from ..db import Organization, SessionToken, User, UserApprovalStatus, get_db
from ..access import check_origin, secure_transport
from ..identity import (PASSWORD_SESSION_COOKIE, SESSION_COOKIE, auth_mode, current_principal,
                        provision_user, require_org_admin, revoke_principal_credential,
                        set_account_enabled)
from ..services import make_audit
from ..session_policy import session_lifetimes

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
    email: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=4096)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class UserOut(BaseModel):
    id: str
    email: str = Field(max_length=200)
    display_name: str
    role: str
    organization_id: Optional[str] = None
    phone_number: str = ""
    affiliation: str = ""
    registration_reason: str = ""
    approval_status: str = "APPROVED"
    approved_at: Optional[str] = None
    storage_quota_bytes: int = 1073741824
    monthly_metrics: Optional[Dict[str, Any]] = None


class RegisterRequest(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=10, max_length=4096)
    display_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(default="", max_length=30)
    affiliation: str = Field(default="", max_length=150)
    registration_reason: str = Field(default="", max_length=1000)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(min_length=10, max_length=4096)
    display_name: str = Field(default="", max_length=120)
    role: str = "MEMBER"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=4096)
    new_password: str = Field(min_length=10, max_length=4096)


def _out(user: User, metrics: Optional[Dict[str, Any]] = None) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or "",
        role=str(user.role),
        organization_id=user.organization_id,
        phone_number=getattr(user, "phone_number", "") or "",
        affiliation=getattr(user, "affiliation", "") or "",
        registration_reason=getattr(user, "registration_reason", "") or "",
        approval_status=getattr(user, "approval_status", "APPROVED") or "APPROVED",
        approved_at=user.approved_at.isoformat() if getattr(user, "approved_at", None) else None,
        storage_quota_bytes=getattr(user, "storage_quota_bytes", 1073741824) or 1073741824,
        monthly_metrics=metrics,
    )


@router.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    if auth_mode() != "multi-user":
        raise HTTPException(409, "Password login requires multi-user mode")
    is_https = secure_transport(request)
    # Also enforce login CSRF at the handler boundary, before checking a password.
    check_origin(request, secure=is_https,
                 required=bool(request.headers.get("sec-fetch-site") or request.headers.get("cookie")))
    if not is_https and not (
            request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}
            and request.url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}):
        raise HTTPException(403, "HTTPS is required for password authentication")
    user = authenticate(session, payload.email, payload.password)
    token = issue_session(session, user, user_agent=request.headers.get("user-agent", ""))
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "LOGIN_SUCCEEDED", "user_id": user.id, "role": str(user.role)},
        actor=user.id,
    )
    # 브라우저 편의를 위한 쿠키. 토큰은 스크립트가 읽지 못하게 HttpOnly로 둔다.
    lifetime_seconds = int(session_lifetimes()[0].total_seconds())
    response.set_cookie(
        PASSWORD_SESSION_COOKIE, token, httponly=True, samesite="strict", path="/",
        secure=is_https, max_age=int(session_lifetimes()[1].total_seconds()),
    )
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True, secure=is_https, samesite="lax")
    return {"access_token": token, "token_type": "bearer",
            "expires_in": lifetime_seconds, "user": _out(user).model_dump()}


@router.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    revoked = revoke_principal_credential(session, current_principal())
    session.commit()
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "LOGOUT", "user_id": user.id},
        actor=user.id,
    )
    response.delete_cookie(PASSWORD_SESSION_COOKIE, path="/", httponly=True,
                           secure=request.state.secure_transport, samesite="strict")
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True,
                           secure=request.state.secure_transport, samesite="lax")
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
    revoked = revoke_all_sessions(session, user.id)
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "PASSWORD_CHANGED", "user_id": user.id, "revoked_sessions": revoked},
        actor=user.id,
    )
    return {"changed": True, "revoked_sessions": revoked,
            "notice": "기존 세션이 모두 종료되었다. 다시 로그인해야 한다."}


@router.post("/api/auth/register", status_code=201)
def register_user(
    payload: RegisterRequest,
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """신규 사용자 등록 신청."""
    email = payload.email.strip().lower()
    existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "이미 등록된 이메일 주소입니다.")

    import os
    organizations = session.scalars(select(Organization).limit(1)).all()
    organization = organizations[0] if organizations else None
    if organization is None:
        organization = Organization(name=os.getenv("LV_ORG_NAME", "종합행정학교 법무교육단"))
        session.add(organization)
        session.flush()

    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        role="MEMBER",
        organization_id=organization.id,
        password_hash=hash_password(payload.password),
        phone_number=payload.phone_number.strip(),
        affiliation=payload.affiliation.strip() or "종합행정학교 법무교육단",
        registration_reason=payload.registration_reason.strip(),
        approval_status=UserApprovalStatus.PENDING,
        is_active=True,
    )
    session.add(user)
    session.flush()

    from ..identity import IdentityAccount
    account = session.get(IdentityAccount, user.id)
    if account is None:
        account = IdentityAccount(user_id=user.id, enabled=False)
        session.add(account)
    session.commit()

    make_audit(session).record(
        AuditEventType.API_QUERY,
        {
            "event": "USER_REGISTRATION_SUBMITTED",
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "affiliation": user.affiliation,
        },
        actor=user.id,
    )
    return {
        "status": "PENDING_APPROVAL",
        "message": "사용자 등록 신청이 접수되었습니다. 관리자 승인 후 안내 메일이 발송됩니다.",
        "user_id": user.id,
    }


# --- 관리자 전용 -------------------------------------------------------------
@router.get("/api/auth/users", response_model=List[UserOut])
def list_users(
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> List[UserOut]:
    require_org_admin()
    rows = session.execute(
        select(User).where(User.organization_id == admin.organization_id).order_by(User.created_at)
    ).scalars().all()
    return [_out(u) for u in rows]


@router.get("/api/admin/pending-registrations")
def list_pending_registrations(
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """승인 대기 중인 신규 가입 신청자 목록 조회."""
    rows = session.execute(
        select(User)
        .where(User.approval_status == UserApprovalStatus.PENDING)
        .order_by(User.created_at.desc())
    ).scalars().all()
    users_data = [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name or "",
            "phone_number": getattr(u, "phone_number", "") or "",
            "affiliation": getattr(u, "affiliation", "") or "",
            "registration_reason": getattr(u, "registration_reason", "") or "",
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]
    return {"count": len(users_data), "users": users_data}


@router.post("/api/admin/users/{user_id}/approve")
def approve_user(
    user_id: str,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """사용자 등록 신청 승인 및 안내 메일 발송."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    user.approval_status = UserApprovalStatus.APPROVED
    user.approved_at = datetime.utcnow()
    user.approved_by = admin.id
    user.is_active = True
    set_account_enabled(session, user, True)
    session.commit()

    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "USER_APPROVED", "user_id": user.id, "approved_by": admin.id},
        actor=admin.id,
    )

    try:
        from packages.notification_engine.mailer import send_approval_email_background
        send_approval_email_background(user.email, user.display_name or user.email)
    except Exception:
        pass

    return {"approved": True, "user_id": user.id}


@router.post("/api/admin/users/{user_id}/reject")
def reject_user(
    user_id: str,
    payload: RejectRequest,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """사용자 등록 신청 반려."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    user.approval_status = UserApprovalStatus.REJECTED
    user.rejection_reason = payload.reason
    set_account_enabled(session, user, False)
    session.commit()

    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "USER_REJECTED", "user_id": user.id, "rejected_by": admin.id, "reason": payload.reason},
        actor=admin.id,
    )
    return {"rejected": True, "user_id": user.id}


@router.delete("/api/admin/users/{user_id}")
def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """사용자 삭제 및 비활성화."""
    if user_id == admin.id:
        raise HTTPException(400, "자기 자신(관리자 계정)은 삭제할 수 없습니다.")
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")

    revoke_all_sessions(session, user.id)
    set_account_enabled(session, user, False)
    user.is_active = False
    user.approval_status = UserApprovalStatus.REJECTED
    user.rejection_reason = "관리자에 의한 계정 삭제"
    session.commit()

    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "USER_DELETED", "user_id": user.id, "deleted_by": admin.id},
        actor=admin.id,
    )
    return {"deleted": True, "user_id": user_id}


@router.get("/api/admin/users", response_model=List[UserOut])
def list_admin_users(
    year: Optional[int] = None,
    month: Optional[int] = None,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> List[UserOut]:
    """관리자용 전체 사용자 목록 및 월별 사용 통계(접속수, 분석빈도, 저장량, 컴퓨팅시간) 조회."""
    now = datetime.utcnow()
    target_year = year or now.year
    target_month = month or now.month

    from ..user_metrics import get_all_users_monthly_metrics
    metrics_by_user = get_all_users_monthly_metrics(session, target_year, target_month)

    rows = session.execute(
        select(User).order_by(User.created_at)
    ).scalars().all()

    return [_out(u, metrics_by_user.get(u.id)) for u in rows]


@router.get("/api/admin/users/{user_id}/monthly-stats")
def user_monthly_stats(
    user_id: str,
    months: int = 12,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """특정 사용자의 최근 N개월간 월별 활동 지표 추이 조회."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    from ..user_metrics import get_user_historical_metrics
    return get_user_historical_metrics(session, user_id, months=min(max(1, months), 36))


@router.get("/api/admin/users/export.csv")
def export_users_csv(
    year: Optional[int] = None,
    month: Optional[int] = None,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> Response:
    """사용자 가입 정보 및 월별 활동/자원 통계를 UTF-8 BOM 지원 CSV로 다운로드."""
    now = datetime.utcnow()
    target_year = year or now.year
    target_month = month or now.month

    from ..user_metrics import get_all_users_monthly_metrics
    metrics_by_user = get_all_users_monthly_metrics(session, target_year, target_month)

    rows = session.execute(select(User).order_by(User.created_at)).scalars().all()

    output = io.StringIO()
    # Excel 한글 깨짐 방지 UTF-8 BOM
    output.write("\ufeff")
    writer = csv.writer(output)

    header = [
        "사용자ID", "성명", "이메일", "연락처", "소속", "등록사유",
        "승인상태", "역할", "등록일시", "승인일시", "승인자",
        "누적저장용량(MB)", "저장소한도(MB)", "용량사용률(%)",
        f"[{target_year}년{target_month}월]접속횟수",
        f"[{target_year}년{target_month}월]검증분석횟수",
        f"[{target_year}년{target_month}월]신규업로드(MB)",
        f"[{target_year}년{target_month}월]컴퓨팅소요시간(분)",
    ]
    writer.writerow(header)

    for u in rows:
        m = metrics_by_user.get(u.id, {})
        writer.writerow([
            u.id,
            u.display_name or "",
            u.email,
            getattr(u, "phone_number", "") or "",
            getattr(u, "affiliation", "") or "",
            getattr(u, "registration_reason", "") or "",
            getattr(u, "approval_status", "") or "",
            str(u.role),
            u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "",
            u.approved_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(u, "approved_at", None) else "",
            getattr(u, "approved_by", "") or "",
            m.get("storage_used_mb", 0.0),
            m.get("storage_quota_mb", 1024.0),
            f"{m.get('storage_usage_percent', 0.0)}%",
            m.get("login_count", 0),
            m.get("verification_count", 0),
            m.get("monthly_upload_mb", 0.0),
            m.get("compute_minutes", 0.0),
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    filename = f"acasia_users_{target_year}{target_month:02d}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/auth/users", response_model=UserOut, status_code=201)
def create_user(
    payload: CreateUserRequest,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> UserOut:
    require_org_admin()
    role = payload.role.upper()
    if role not in ROLES:
        raise HTTPException(400, f"허용되지 않는 역할이다: {payload.role}")
    email = payload.email.strip().lower()
    if session.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None:
        raise HTTPException(409, "이미 존재하는 이메일이다")
    user = provision_user(session, email=email, display_name=payload.display_name,
                          role=role, organization_id=admin.organization_id)
    user.password_hash = hash_password(payload.password)
    session.commit()
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "USER_CREATED", "user_id": user.id, "role": role},
        actor=admin.id,
    )
    return _out(user)


@router.post("/api/auth/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """계정을 막고 세션을 끊는다. 계정과 감사기록은 삭제하지 않는다(부록 C 제7항)."""
    require_org_admin()
    target = session.get(User, user_id)
    if target is None or target.organization_id != admin.organization_id:
        raise HTTPException(404, "사용자를 찾을 수 없다")
    if target.id == admin.id:
        raise HTTPException(400, "자기 계정은 비활성화할 수 없다")
    revoked = set_account_enabled(session, target, False)
    session.commit()
    make_audit(session).record(
        AuditEventType.API_QUERY,
        {"event": "USER_DEACTIVATED", "user_id": target.id, "revoked_sessions": revoked},
        actor=admin.id,
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
