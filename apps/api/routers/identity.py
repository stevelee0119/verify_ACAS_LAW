"""Explicit organization provisioning and project access management."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import ProjectMember, User, get_db
from ..identity import (ApiToken, ExternalIdentity, OIDCSettings,
                        current_principal, issue_token, provision_user,
                        require_org_admin, require_project, issue_browser_session, SESSION_COOKIE,
                        PASSWORD_SESSION_COOKIE, revoke_principal_credential, set_account_enabled,
                        user_is_enabled)

router = APIRouter(tags=["identity"])
Role = Literal["ADMIN", "MEMBER", "VIEWER"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserCreate(Input):
    email: str = Field(min_length=3, max_length=200)
    display_name: str = Field(default="", max_length=120)
    role: Role = "MEMBER"


class UserUpdate(Input):
    role: Role | None = None
    enabled: bool | None = None


class TokenCreate(Input):
    label: str = Field(default="", max_length=120)
    days: int = Field(default=30, ge=1, le=365)


class OIDCBinding(Input):
    subject: str = Field(min_length=1, max_length=255)


class Membership(Input):
    role: Role = "MEMBER"


def _user(session: Session, user_id: str) -> User:
    principal = current_principal()
    user = session.get(User, user_id)
    if (principal.is_local or user is None or user.organization_id != principal.organization_id
            or (not principal.organization_id and user.id != principal.user_id)):
        raise HTTPException(404, "Identity resource not found")
    return user


def _commit(session: Session):
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Identity or membership already exists") from None


def _user_out(session, user):
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "role": user.role, "organization_id": user.organization_id,
            "enabled": user_is_enabled(session, user)}


@router.get("/identity/me")
def me():
    principal = current_principal()
    return {"user_id": principal.user_id, "organization_id": principal.organization_id,
            "role": principal.role, "authentication": principal.authentication}


@router.post("/identity/session")
def exchange_session(request: Request, response: Response, session: Session = Depends(get_db)):
    row, secret = issue_browser_session(session, current_principal())
    _commit(session)
    response.set_cookie(SESSION_COOKIE, secret, httponly=True, secure=request.state.secure_transport,
                        samesite="lax", path="/api", expires=row.expires_at.replace(tzinfo=timezone.utc),
                        max_age=max(0, int((row.expires_at - datetime.utcnow()).total_seconds())))
    response.delete_cookie(PASSWORD_SESSION_COOKIE, path="/", httponly=True,
                           secure=request.state.secure_transport, samesite="strict")
    return {**me(), "expires_at": row.expires_at.isoformat() + "Z"}


@router.delete("/identity/session", status_code=204)
def logout(request: Request, session: Session = Depends(get_db)):
    principal = current_principal()
    revoke_principal_credential(session, principal)
    _commit(session)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True,
                           secure=request.state.secure_transport, samesite="lax")
    response.delete_cookie(PASSWORD_SESSION_COOKIE, path="/", httponly=True,
                           secure=request.state.secure_transport, samesite="strict")
    return response


@router.get("/identity/users")
def users(session: Session = Depends(get_db)):
    principal = require_org_admin()
    return [_user_out(session, user) for user in session.scalars(select(User).where(
        User.organization_id == principal.organization_id).order_by(User.created_at))]


@router.post("/identity/users", status_code=201)
def create_user(payload: UserCreate, session: Session = Depends(get_db)):
    principal = require_org_admin()
    try:
        user = provision_user(session, organization_id=principal.organization_id, **payload.model_dump())
        _commit(session)
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Identity already exists") from None
    return _user_out(session, user)


@router.patch("/identity/users/{user_id}")
def update_user(user_id: str, payload: UserUpdate, session: Session = Depends(get_db)):
    principal = require_org_admin()
    user = _user(session, user_id)
    if user.id == principal.user_id and (payload.enabled is False or payload.role not in {None, "ADMIN"}):
        raise HTTPException(409, "Administrators cannot disable or demote themselves")
    if payload.role is not None:
        user.role = payload.role
    if payload.enabled is not None:
        set_account_enabled(session, user, payload.enabled)
    _commit(session)
    return _user_out(session, user)


@router.post("/identity/users/{user_id}/tokens", status_code=201)
def create_token(user_id: str, payload: TokenCreate, session: Session = Depends(get_db)):
    principal = current_principal()
    _user(session, user_id)
    if principal.user_id != user_id:
        require_org_admin()
    row, secret = issue_token(session, user_id, **payload.model_dump())
    _commit(session)
    return {"id": row.id, "token": secret, "expires_at": row.expires_at.isoformat() + "Z"}


@router.get("/identity/users/{user_id}/tokens")
def list_tokens(user_id: str, session: Session = Depends(get_db)):
    _user(session, user_id)
    if current_principal().user_id != user_id:
        require_org_admin()
    return [{"id": row.id, "label": row.label, "expires_at": row.expires_at,
             "revoked_at": row.revoked_at} for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user_id))]


@router.delete("/identity/tokens/{token_id}", status_code=204)
def revoke_token(token_id: str, session: Session = Depends(get_db)):
    row = session.get(ApiToken, token_id)
    if row is None:
        raise HTTPException(404, "Identity resource not found")
    _user(session, row.user_id)
    if row.user_id != current_principal().user_id:
        require_org_admin()
    row.revoked_at = datetime.utcnow()
    _commit(session)
    return Response(status_code=204)


@router.post("/identity/users/{user_id}/oidc", status_code=201)
def bind_oidc(user_id: str, payload: OIDCBinding, session: Session = Depends(get_db)):
    require_org_admin()
    _user(session, user_id)
    settings = OIDCSettings.from_env()
    if settings is None:
        raise HTTPException(409, "OIDC is not configured")
    row = ExternalIdentity(user_id=user_id, issuer=settings.issuer, subject=payload.subject)
    session.add(row)
    _commit(session)
    return {"id": row.id, "issuer": row.issuer, "subject": row.subject, "user_id": row.user_id}


@router.delete("/identity/oidc/{binding_id}", status_code=204)
def unbind_oidc(binding_id: str, session: Session = Depends(get_db)):
    require_org_admin()
    row = session.get(ExternalIdentity, binding_id)
    if row is None:
        raise HTTPException(404, "Identity resource not found")
    _user(session, row.user_id)
    session.delete(row)
    _commit(session)
    return Response(status_code=204)


@router.get("/projects/{project_id}/members")
def members(project_id: str, session: Session = Depends(get_db)):
    require_project(session, project_id, "ADMIN")
    return [{"user_id": row.user_id, "role": row.role} for row in session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project_id))]


@router.put("/projects/{project_id}/members/{user_id}")
def set_member(project_id: str, user_id: str, payload: Membership, session: Session = Depends(get_db)):
    project = require_project(session, project_id, "ADMIN")
    user = _user(session, user_id)
    if user.organization_id != project.organization_id or not user_is_enabled(session, user):
        raise HTTPException(404, "Identity resource not found")
    row = session.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
    if row is None:
        row = ProjectMember(project_id=project_id, user_id=user_id)
        session.add(row)
    row.role = payload.role
    _commit(session)
    return {"user_id": user_id, "role": row.role}


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: str, user_id: str, session: Session = Depends(get_db)):
    require_project(session, project_id, "ADMIN")
    row = session.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
    if row is not None:
        session.delete(row)
        _commit(session)
    return Response(status_code=204)
