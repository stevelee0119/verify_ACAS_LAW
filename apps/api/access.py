"""Workspace authentication and route-aware authorization before handler execution."""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.routing import Match
from sqlalchemy.exc import SQLAlchemyError

from .db import (Document, ExportArtifactRow, FindingRow, ReportRow, VerificationRun,
                 get_session_factory)
from .identity import (LOCAL_OWNER, Principal, _principal, auth_mode, authenticate_bearer,
                       authenticate_session, authenticate_password_session, require_project,
                       SESSION_COOKIE, PASSWORD_SESSION_COOKIE, renew_browser_activity)
from .session_policy import RENEW_INTERVAL, session_lifetimes

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
RESOURCE_MODELS = {"document_id": Document, "run_id": VerificationRun,
                   "finding_id": FindingRow, "report_id": ReportRow,
                   "artifact_id": ExportArtifactRow}


def project_scoped(endpoint):
    """Mark a collection handler after its query/create integration is installed."""
    endpoint.__project_scoped__ = True
    return endpoint


def _route(request):
    def match_routes(routes, scope):
        for route in routes:
            # New FastAPI versions retain included routers with effective prefixes.
            candidates = getattr(route, "effective_candidates", None)
            if callable(candidates):
                found, params = match_routes(candidates(), scope)
                if found is not None:
                    return found, params
                continue
            match, child = route.matches(scope)
            if match == Match.FULL:
                nested = getattr(route, "routes", None)
                if nested:
                    return match_routes(nested, {**scope, **child})
                return route, child.get("path_params", {})
        return None, {}
    return match_routes(request.app.router.routes, request.scope)


def _resource_project(session, key: str, value: str) -> str:
    if key == "project_id":
        return value
    row = session.get(RESOURCE_MODELS[key], value)
    if row is None:
        raise HTTPException(404, "Resource not found")
    if key == "artifact_id":
        row = session.get(ReportRow, row.report_id) if row.report_id else None
        if row is None:
            raise HTTPException(404, "Resource not found")
    return row.project_id


def _references(value):
    """Check related IDs before handlers combine resources across projects."""
    if isinstance(value, dict):
        for key, item in value.items():
            singular = key[:-1] if key.endswith("_ids") else key
            singular = next((name for name in {"project_id", *RESOURCE_MODELS}
                             if singular == name or singular.endswith("_" + name)), singular)
            if singular in {"project_id", *RESOURCE_MODELS}:
                for identifier in (item if isinstance(item, list) else [item]):
                    if identifier is not None:
                        if not isinstance(identifier, str):
                            raise HTTPException(422, "Resource identifiers must be strings")
                        yield singular, identifier
            elif isinstance(item, (dict, list)):
                yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def _authorize(session, request, principal, route, params, payload):
    if principal.is_local:
        return
    path = request.url.path.rstrip("/")
    if path in {"", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"} or path.startswith("/static/"):
        return
    if route is None:
        raise HTTPException(404, "Route not found")
    template = getattr(route, "path", path).rstrip("/")
    read = request.method in READ_METHODS
    minimum = "VIEWER" if read else "MEMBER"
    if "/members" in template or "/access" in template or request.method == "DELETE":
        minimum = "ADMIN"
    trash_access = ((template == "/api/projects/{project_id}/restore" and request.method == "POST")
                    or (template == "/api/projects/{project_id}" and request.method == "DELETE"))
    if trash_access:
        minimum = "ADMIN"
    project_ids = set()
    for key, value in params.items():
        if key == "project_id" or key in RESOURCE_MODELS:
            project_ids.add(_resource_project(session, key, value))
    if project_ids:
        if len(project_ids) != 1:
            raise HTTPException(404, "Resources must belong to the same project")
        project_id = next(iter(project_ids))
        require_project(session, project_id, minimum, principal, include_deleted=trash_access)
        query_values = {key: request.query_params.getlist(key) for key in request.query_params}
        references = list(_references(payload)) + list(_references(query_values))
        for key, value in references:
            if _resource_project(session, key, value) != project_id:
                raise HTTPException(404, "Resource not found in this project")
        return
    if template == "/api/verification-runs" and read:
        if not getattr(getattr(route, "endpoint", None), "__project_scoped__", False):
            raise HTTPException(503, "Run collection identity integration is required")
        return
    if template.endswith("/projects"):
        if request.method not in {"GET", "HEAD", "POST"}:
            raise HTTPException(403, "Unsupported project collection operation")
        if not read and principal.role not in {"ADMIN", "MEMBER"}:
            raise HTTPException(403, "Project creation requires membership")
        if not getattr(getattr(route, "endpoint", None), "__project_scoped__", False):
            raise HTTPException(503, "Project collection identity integration is required")
        return
    if "/identity/" in template or template.startswith("/api/auth/"):
        return
    if template.endswith("/audit/verify") or "/audit" in template:
        raise HTTPException(403, "Global audit access is available only in local mode")
    if "/settings/" in template:
        if principal.role != "ADMIN":
            raise HTTPException(403, "Administrator required")
        if not read:
            raise HTTPException(403, "Global settings changes require local administration")
        return
    if template.endswith("/diagnostics") and principal.role != "ADMIN":
        raise HTTPException(403, "Administrator required")
    if read and template.endswith(("/health", "/diagnostics", "/project-defaults")):
        return
    if template.endswith("/calculations/interest") and principal.role in {"MEMBER", "ADMIN"}:
        return
    raise HTTPException(403, "No authorization policy for this route")


def _authenticate_local(request) -> Principal:
    token = os.getenv("LV_ACCESS_TOKEN", "")
    peer = request.client.host if request.client else ""
    if token:
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() == "basic":
            try:
                supplied = base64.b64decode(supplied, validate=True).decode().partition(":")[2]
            except (ValueError, UnicodeDecodeError):
                supplied = ""
        elif scheme.lower() != "bearer":
            supplied = ""
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "Workspace authentication required", headers={
                "WWW-Authenticate": 'Basic realm="ACASia_LAW", charset="UTF-8"'})
    elif peer not in {"127.0.0.1", "::1", "testclient"} or request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        raise HTTPException(403, "Remote access requires LV_ACCESS_TOKEN and HTTPS")
    return Principal(LOCAL_OWNER, None, "ADMIN", "local")


def _authenticate(request):
    request.state.cookie_authenticated = False
    if auth_mode() == "local":
        return _authenticate_local(request)
    authorization = request.headers.getlist("authorization")
    if not authorization:
        cookies = [part.strip().partition("=")[0] for header in request.headers.getlist("cookie")
                   for part in header.split(";")
                   if part.strip().partition("=")[0] in {SESSION_COOKIE, PASSWORD_SESSION_COOKIE}]
        if len(cookies) == 1:
            with get_session_factory()() as session:
                name = cookies[0]
                authenticate = authenticate_session if name == SESSION_COOKIE else authenticate_password_session
                principal = authenticate(session, request.cookies.get(name, ""))
                request.state.cookie_authenticated = True
                request.state.session_cookie_name = name
                return principal
    if len(authorization) != 1:
        raise HTTPException(401, "Bearer authentication required", headers={"WWW-Authenticate": "Bearer"})
    scheme, _, token = authorization[0].partition(" ")
    if scheme.lower() != "bearer" or not token or token != token.strip():
        raise HTTPException(401, "Bearer authentication required", headers={"WWW-Authenticate": "Bearer"})
    with get_session_factory()() as session:
        return authenticate_bearer(session, token)


def _check_policy(request, principal, route, params, payload):
    if not principal.is_local:
        with get_session_factory()() as session:
            _authorize(session, request, principal, route, params, payload)


def _origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(403, "Invalid request origin")
    return parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def secure_transport(request) -> bool:
    if request.url.scheme == "https":
        return True
    trusted = {p.strip() for p in os.getenv("LV_TRUSTED_PROXY_IPS", "").split(",") if p.strip()}
    peer = request.client.host if request.client else ""
    forwarded = request.headers.getlist("x-forwarded-proto")
    return peer in trusted and forwarded == ["https"]


def _public_shell(request) -> bool:
    return request.method in {"GET", "HEAD"} and (request.url.path == "/" or request.url.path.startswith("/static/"))


def check_origin(request, *, secure: bool, required: bool = False):
    origins = request.headers.getlist("origin")
    if len(origins) > 1 or (required and not origins):
        raise HTTPException(403, "Cookie-authenticated changes require one Origin header")
    expected = os.getenv("LV_PUBLIC_ORIGIN") or str(request.url.replace(scheme="https" if secure else request.url.scheme))
    if origins and _origin(origins[0]) != _origin(expected):
        raise HTTPException(403, "Cross-origin changes are not allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site changes are not allowed")


def _renew_cookie(request, response, principal, secure):
    if not request.state.cookie_authenticated or not 200 <= response.status_code < 400:
        return
    if request.url.path.rstrip("/") in {"/api/auth/logout", "/api/auth/password", "/api/identity/session"}:
        return
    # Read-only cross-site requests must not keep an otherwise idle session alive.
    if request.headers.get("sec-fetch-site") == "cross-site":
        return
    try:
        check_origin(request, secure=secure)
    except HTTPException:
        return
    idle, _ = session_lifetimes()
    if principal.expires_at and principal.expires_at > datetime.utcnow() + idle - RENEW_INTERVAL:
        return
    name = request.state.session_cookie_name
    secret = request.cookies.get(name, "")
    try:
        with get_session_factory()() as session:
            deadline = renew_browser_activity(session, name, secret)
    except HTTPException:
        # Logout, expiry or an account change may have happened during the request.
        return
    except SQLAlchemyError:
        logging.getLogger(__name__).warning("Browser session renewal unavailable")
        return
    if deadline is not None:
        response.set_cookie(name, secret, httponly=True, secure=secure,
                            path="/" if name == PASSWORD_SESSION_COOKIE else "/api",
                            samesite="strict" if name == PASSWORD_SESSION_COOKIE else "lax",
                            expires=deadline.replace(tzinfo=timezone.utc),
                            max_age=max(0, int((deadline - datetime.utcnow()).total_seconds())))


async def workspace_access(request, call_next):
    try:
        mode = auth_mode()
        if mode == "multi-user" and _public_shell(request):
            return await call_next(request)
        if mode == "multi-user" and request.method in {"GET", "HEAD"} and request.url.path == "/api/health":
            # Readiness probes are public, never configuration or principal data.
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        secure = secure_transport(request)
        loopback = (request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}
                    and request.url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"})
        if (mode == "multi-user" or os.getenv("LV_ACCESS_TOKEN")) and not secure and not loopback:
            raise HTTPException(403, "HTTPS is required for multi-user authentication")
        request.state.secure_transport = secure
        if mode == "multi-user" and request.method == "POST" and request.url.path.rstrip("/") == "/api/auth/login":
            # Login CSRF must be checked even though no principal exists yet.
            check_origin(request, secure=secure,
                         required=bool(request.headers.get("sec-fetch-site") or request.headers.get("cookie")))
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Vary"] = "Origin, Cookie, Authorization"
            return response
        principal = await run_in_threadpool(_authenticate, request)
        if request.method not in READ_METHODS:
            check_origin(request, secure=secure, required=request.state.cookie_authenticated)
        route, params = _route(request)
        payload = None
        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if request.method not in READ_METHODS and (media_type == "application/json" or media_type.endswith("+json") or not media_type):
            try:
                body = await request.body()
                payload = json.loads(body) if body else None
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, "Invalid JSON body") from None
        await run_in_threadpool(_check_policy, request, principal, route, params, payload)
        # Legacy reviewer fields must never become an impersonation boundary.
        template = getattr(route, "path", "")
        if isinstance(payload, dict) and template.endswith(("/review", "/reveal")) and "finding_id" in params:
            payload["reviewer"] = principal.user_id
            request._body = json.dumps(payload).encode("utf-8")
        request.state.principal = principal
        request.state.actor = principal.user_id
        request.state.user_id = principal.user_id
        request.state.secure_transport = secure
        context_token = _principal.set(principal)
        try:
            response = await call_next(request)
        finally:
            _principal.reset(context_token)
        await run_in_threadpool(_renew_cookie, request, response, principal, secure)
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    except ValueError:
        response = JSONResponse({"detail": "Invalid authentication configuration or request"}, status_code=503)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = ", ".join(filter(None, [response.headers.get("Vary"), "Authorization", "Cookie"]))
    return response
