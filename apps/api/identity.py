"""Authenticated principals, credential storage and organization/project policy.

Import this module before creating/migrating Base.metadata. Request helpers fail
closed without workspace_access; offline provisioning is deliberately separate.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint, or_, select
from sqlalchemy.orm import Session

from .db import Base, Organization, Project, ProjectMember, User, new_uuid

ROLES = {"VIEWER": 1, "MEMBER": 2, "ADMIN": 3}
LOCAL_OWNER = "local-owner"
TOKEN_PREFIX = "acas_"
SESSION_COOKIE = "acas_session"


class IdentityAccount(Base):
    __tablename__ = "identity_accounts"
    user_id = Column(String(40), ForeignKey("users.id"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ApiToken(Base):
    __tablename__ = "identity_api_tokens"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("tok_"))
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    label = Column(String(120), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime)


class ExternalIdentity(Base):
    __tablename__ = "identity_external"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("sso_"))
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    issuer = Column(String(500), nullable=False)
    subject = Column(String(255), nullable=False)


class BrowserSession(Base):
    __tablename__ = "identity_browser_sessions"
    id = Column(String(40), primary_key=True, default=lambda: new_uuid("ses_"))
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    secret_hash = Column(String(64), nullable=False, unique=True)
    source_kind = Column(String(12), nullable=False)
    source_id = Column(String(40), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime)


@dataclass(frozen=True)
class Principal:
    user_id: str
    organization_id: str | None
    role: str
    authentication: str
    credential_id: str | None = None
    expires_at: datetime | None = None

    @property
    def is_local(self) -> bool:
        return self.authentication == "local" and self.user_id == LOCAL_OWNER


_principal: ContextVar[Principal | None] = ContextVar("acas_principal", default=None)


def current_principal(request: Request | None = None) -> Principal:
    principal = getattr(request.state, "principal", None) if request is not None else _principal.get()
    if not isinstance(principal, Principal):
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return principal


def actor_id(request: Request | None = None) -> str:
    return current_principal(request).user_id


def auth_mode() -> str:
    mode = os.getenv("LV_AUTH_MODE", "local").strip().lower()
    if mode not in {"local", "multi-user"}:
        raise ValueError("LV_AUTH_MODE must be local or multi-user")
    return mode


def _unauthorized() -> HTTPException:
    return HTTPException(401, "Invalid or expired credentials", headers={"WWW-Authenticate": "Bearer"})


def principal_for_user(session: Session, user_id: str, authentication: str,
                       credential_id: str | None = None, expires_at: datetime | None = None) -> Principal:
    user = session.get(User, user_id)
    account = session.get(IdentityAccount, user_id)
    if (user is None or account is None or not account.enabled or user.role not in ROLES
            or not user.organization_id or session.get(Organization, user.organization_id) is None):
        raise _unauthorized()
    return Principal(user.id, user.organization_id, user.role, authentication, credential_id, expires_at)


def issue_token(session: Session, user_id: str, *, label: str = "", days: int = 30) -> tuple[ApiToken, str]:
    """Stage a high-entropy token. Only its SHA-256 digest is persisted."""
    principal_for_user(session, user_id, "token")
    if not 1 <= days <= 365 or len(label) > 120:
        raise HTTPException(422, "Invalid token lifetime or label")
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(user_id=user_id, token_hash=hashlib.sha256(secret.encode("ascii")).hexdigest(),
                   label=label, expires_at=datetime.utcnow() + timedelta(days=days))
    session.add(row)
    session.flush()
    return row, secret


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    audience: str
    jwks_url: str
    algorithms: tuple[str, ...] = ("RS256",)

    def __post_init__(self) -> None:
        for value in (self.issuer, self.jwks_url):
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("OIDC issuer and JWKS URL must be trusted HTTPS URLs")
        if not self.audience or not self.algorithms or not set(self.algorithms) <= {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}:
            raise ValueError("Invalid OIDC audience or asymmetric algorithm allowlist")

    @classmethod
    def from_env(cls) -> OIDCSettings | None:
        values = [os.getenv(k, "").strip() for k in ("LV_OIDC_ISSUER", "LV_OIDC_AUDIENCE", "LV_OIDC_JWKS_URL")]
        if not any(values):
            return None
        if not all(values):
            raise ValueError("OIDC issuer, audience and JWKS URL must all be configured")
        return cls(*values, tuple(s.strip() for s in os.getenv("LV_OIDC_ALGORITHMS", "RS256").split(",")))


@lru_cache(maxsize=8)
def _jwks_client(settings: OIDCSettings):
    import jwt

    return jwt.PyJWKClient(settings.jwks_url, cache_keys=False, cache_jwk_set=True, lifespan=300, timeout=5)


def verify_oidc(token: str, settings: OIDCSettings, *, jwks_client=None) -> dict:
    """Verify a JWT against pinned issuer/audience and administrator-selected JWKS.

    Never use jku/x5u, email, roles or organization claims to select trust or access.
    See https://pyjwt.readthedocs.io/en/stable/usage.html#retrieve-rsa-signing-keys-from-a-jwks-endpoint
    """
    try:
        import jwt
    except ImportError:
        raise HTTPException(503, "SSO dependency PyJWT[crypto] is not installed") from None
    try:
        if len(token) > 16384:
            raise ValueError("Token too large")
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in settings.algorithms or not isinstance(header.get("kid"), str) or not header["kid"] or header.get("crit"):
            raise ValueError("Invalid JWT header")
        key = (jwks_client or _jwks_client(settings)).get_signing_key_from_jwt(token)
        if key.algorithm_name not in settings.algorithms or key.algorithm_name != header["alg"]:
            raise ValueError("Signing algorithm mismatch")
        claims = jwt.decode(token, key.key, algorithms=list(settings.algorithms),
                            issuer=settings.issuer, audience=settings.audience, leeway=0,
                            options={"require": ["exp", "iss", "aud", "sub", "iat"],
                                     "verify_signature": True, "verify_exp": True,
                                     "verify_nbf": True, "verify_iat": True,
                                     "verify_iss": True, "verify_aud": True})
        if (not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 255
                or any(type(claims[name]) not in (int, float) for name in ("iat", "exp"))
                or claims["exp"] <= claims["iat"]):
            raise ValueError("Invalid JWT claims")
        return claims
    except Exception:
        # Provider/network/parser errors must neither leak credentials nor enable fallback.
        raise _unauthorized() from None


def authenticate_bearer(session: Session, token: str) -> Principal:
    if not token or len(token) > 16384:
        raise _unauthorized()
    if token.startswith(TOKEN_PREFIX):
        try:
            digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            raise _unauthorized() from None
        row = session.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
        if row is None or not hmac.compare_digest(row.token_hash, digest) or row.revoked_at is not None or row.expires_at <= datetime.utcnow():
            raise _unauthorized()
        return principal_for_user(session, row.user_id, "token", row.id, row.expires_at)
    settings = OIDCSettings.from_env()
    if settings is None:
        raise _unauthorized()
    claims = verify_oidc(token, settings)
    binding = session.scalar(select(ExternalIdentity).where(
        ExternalIdentity.issuer == settings.issuer, ExternalIdentity.subject == claims["sub"]))
    if binding is None:
        raise _unauthorized()
    return principal_for_user(session, binding.user_id, "oidc", binding.id, datetime.utcfromtimestamp(claims["exp"]))


def issue_browser_session(session: Session, principal: Principal) -> tuple[BrowserSession, str]:
    if principal.authentication not in {"token", "oidc"} or not principal.credential_id or not principal.expires_at:
        raise HTTPException(401, "Exchange requires a valid bearer credential")
    secret = secrets.token_urlsafe(32)
    row = BrowserSession(user_id=principal.user_id, secret_hash=hashlib.sha256(secret.encode("ascii")).hexdigest(),
        source_kind=principal.authentication, source_id=principal.credential_id,
        expires_at=min(datetime.utcnow() + timedelta(hours=8), principal.expires_at))
    session.add(row)
    session.flush()
    return row, secret


def authenticate_session(session: Session, secret: str) -> Principal:
    if not secret or len(secret) > 128 or not secret.isascii():
        raise _unauthorized()
    digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
    row = session.scalar(select(BrowserSession).where(BrowserSession.secret_hash == digest))
    now = datetime.utcnow()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise _unauthorized()
    if row.source_kind == "token":
        source = session.get(ApiToken, row.source_id)
        if source is None or source.user_id != row.user_id or source.revoked_at is not None or source.expires_at <= now:
            raise _unauthorized()
    elif row.source_kind == "oidc":
        source = session.get(ExternalIdentity, row.source_id)
        settings = OIDCSettings.from_env()
        if source is None or source.user_id != row.user_id or settings is None or source.issuer != settings.issuer:
            raise _unauthorized()
    else:
        raise _unauthorized()
    return principal_for_user(session, row.user_id, "session", row.id, row.expires_at)


def project_role(session: Session, project: Project, principal: Principal | None = None) -> str | None:
    principal = principal or current_principal()
    if principal.is_local:
        return "ADMIN"
    if not principal.organization_id or project.organization_id != principal.organization_id:
        return None
    if principal.role == "ADMIN":
        return "ADMIN"
    member = session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project.id, ProjectMember.user_id == principal.user_id))
    role = "ADMIN" if project.owner_id == principal.user_id else (member.role if member else None)
    if role not in ROLES or principal.role not in ROLES:
        return None
    if principal.role == "VIEWER":
        return "VIEWER"
    return role


def require_project(session: Session, project_id: str, minimum: str = "VIEWER",
                    principal: Principal | None = None) -> Project:
    project = session.get(Project, project_id)
    role = project_role(session, project, principal) if project is not None else None
    if role is None:
        raise HTTPException(404, "Project not found")
    if ROLES[role] < ROLES[minimum]:
        raise HTTPException(403, "Insufficient project permission")
    return project


def require_org_admin(principal: Principal | None = None) -> Principal:
    principal = principal or current_principal()
    if principal.is_local or principal.role != "ADMIN" or not principal.organization_id:
        raise HTTPException(403, "Organization administrator required")
    return principal


def visible_project_ids(session: Session, principal: Principal | None = None) -> list[str] | None:
    principal = principal or current_principal()
    if principal.is_local:
        return None
    if not principal.organization_id or principal.role not in ROLES:
        return []
    query = select(Project.id).where(Project.organization_id == principal.organization_id)
    if principal.role != "ADMIN":
        memberships = select(ProjectMember.project_id).where(
            ProjectMember.user_id == principal.user_id, ProjectMember.role.in_(ROLES))
        query = query.where(or_(Project.owner_id == principal.user_id, Project.id.in_(memberships)))
    return list(session.scalars(query))


def filter_project_query(query, session: Session, project_column=Project.id):
    """Apply BEFORE count/order/offset/limit, also for audit and export queries."""
    ids = visible_project_ids(session)
    return query if ids is None else query.filter(project_column.in_(ids))


def project_creation_defaults(session: Session) -> dict:
    principal = current_principal()
    if principal.is_local:
        if session.get(User, LOCAL_OWNER) is None:
            session.add(User(id=LOCAL_OWNER, email="local-owner@localhost", display_name="Local owner", role="ADMIN"))
            session.flush()
        return {"owner_id": LOCAL_OWNER, "organization_id": None}
    if principal.role not in {"MEMBER", "ADMIN"} or not principal.organization_id:
        raise HTTPException(403, "Project creation requires membership")
    return {"owner_id": principal.user_id, "organization_id": principal.organization_id}


def apply_organization_policy(session: Session, values: dict, project: Project | None = None) -> dict:
    from packages.common.enums import ExternalAIPolicy

    principal = current_principal()
    organization_id = project.organization_id if project is not None else principal.organization_id
    result = dict(values)
    if organization_id:
        organization = session.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(503, "Project organization policy is unavailable")
        if organization.forced_ai_policy:
            try:
                result["external_ai_policy"] = ExternalAIPolicy(organization.forced_ai_policy).value
            except ValueError:
                raise HTTPException(503, "Invalid organization AI policy") from None
    return result


def provision_user(session: Session, *, organization_id: str, email: str,
                   display_name: str = "", role: str = "MEMBER") -> User:
    """Offline primitive; HTTP callers must first require_org_admin()."""
    if role not in ROLES or not email.strip() or len(email) > 200 or len(display_name) > 120:
        raise HTTPException(422, "Invalid user attributes")
    if session.get(Organization, organization_id) is None:
        raise HTTPException(404, "Organization not found")
    user = User(email=email.strip().lower(), display_name=display_name, role=role, organization_id=organization_id)
    session.add(user)
    session.flush()
    session.add(IdentityAccount(user_id=user.id, enabled=True))
    session.flush()
    return user


def bootstrap_admin(session: Session, *, email: str, organization_name: str) -> tuple[User, str]:
    """One-time offline bootstrap. Never exposed as an HTTP endpoint."""
    if session.scalar(select(IdentityAccount.user_id).limit(1)) is not None:
        raise ValueError("Identity is already bootstrapped; use an organization administrator")
    if not organization_name.strip() or len(organization_name) > 200:
        raise ValueError("Invalid organization name")
    org = Organization(name=organization_name.strip())
    session.add(org)
    session.flush()
    user = provision_user(session, organization_id=org.id, email=email, role="ADMIN")
    _, secret = issue_token(session, user.id, label="bootstrap", days=1)
    return user, secret


def _bootstrap_cli() -> None:
    import argparse
    from .db import get_session_factory

    parser = argparse.ArgumentParser(description="Offline, one-time identity bootstrap (apply migrations first)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True)
    args = parser.parse_args()
    with get_session_factory()() as session:
        user, secret = bootstrap_admin(session, email=args.email, organization_name=args.organization)
        session.commit()
        print(f"User: {user.id}\nOrganization: {user.organization_id}\nOne-day token (shown once): {secret}")


if __name__ == "__main__":
    _bootstrap_cli()
