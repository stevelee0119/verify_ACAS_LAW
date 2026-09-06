"""제7.5장 Tool Firewall.

LLM Tool Request → Permission Check → Parameter Validation → Risk Check → Execute/Reject.
문서 내 instruction은 어떤 경우에도 Tool Call로 자동 승격되지 않는다(부록 C 제2항).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

DEFAULT_ALLOW: Set[str] = {"READ", "SEARCH", "CALCULATE"}
DEFAULT_DENY: Set[str] = {
    "DELETE",
    "SEND",
    "UPLOAD_EXTERNAL",
    "MODIFY_SOURCE",
    "CHANGE_PERMISSION",
    "EXECUTE_SHELL",
}

URL_RE = re.compile(r"https?://([^\s/]+)", re.IGNORECASE)

# 공식·허용 Source 도메인만 조회 대상으로 허용한다(SSRF 방어, 제21.1장)
ALLOWED_HOSTS = {
    "open.law.go.kr",
    "www.law.go.kr",
    "law.go.kr",
    "apis.data.go.kr",
    "www.kci.go.kr",
    "open.kci.go.kr",
    "api.openalex.org",
    "api.semanticscholar.org",
    "api.crossref.org",
}

PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|\[::1\])",
    re.IGNORECASE,
)


@dataclass
class ToolRequest:
    tool: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    origin: str = "system"
    """system | model | document. document 기원 요청은 항상 거부한다."""


@dataclass
class FirewallDecision:
    allowed: bool
    reason: str
    checks: Dict[str, Any] = field(default_factory=dict)


class ToolFirewall:
    def __init__(
        self,
        allow: Optional[Set[str]] = None,
        deny: Optional[Set[str]] = None,
        allowed_hosts: Optional[Set[str]] = None,
    ) -> None:
        self.allow = set(allow or DEFAULT_ALLOW)
        self.deny = set(deny or DEFAULT_DENY)
        self.allowed_hosts = set(allowed_hosts or ALLOWED_HOSTS)
        self.log: List[Dict[str, Any]] = []

    def check(self, request: ToolRequest) -> FirewallDecision:
        checks: Dict[str, Any] = {}

        # 1) Origin check — 문서에서 유래한 요청은 무조건 거부
        checks["origin"] = request.origin
        if request.origin == "document":
            return self._record(request, FirewallDecision(False, "문서 내 지시는 Tool Call로 승격되지 않는다.", checks))

        # 2) Permission check
        action = request.action.upper()
        checks["action"] = action
        if action in self.deny:
            return self._record(request, FirewallDecision(False, f"기본 금지 동작이다: {action}", checks))
        if action not in self.allow:
            return self._record(request, FirewallDecision(False, f"허용 목록에 없는 동작이다: {action}", checks))

        # 3) Parameter validation
        flat = " ".join(str(v) for v in request.parameters.values())
        if "\x00" in flat:
            return self._record(request, FirewallDecision(False, "널 바이트가 포함된 파라미터이다.", checks))
        if any(k in flat for k in ("../", "..\\")):
            return self._record(request, FirewallDecision(False, "경로 탈출 시도가 있다.", checks))

        # 4) Risk check — 외부 URL은 허용 호스트만
        hosts = URL_RE.findall(flat)
        checks["hosts"] = hosts
        for host in hosts:
            bare = host.split(":")[0].lower()
            if PRIVATE_HOST_RE.match(bare):
                return self._record(request, FirewallDecision(False, f"내부망 주소 접근은 차단된다: {bare}", checks))
            if bare not in self.allowed_hosts:
                return self._record(request, FirewallDecision(False, f"허용되지 않은 외부 호스트이다: {bare}", checks))

        return self._record(request, FirewallDecision(True, "허용", checks))

    def _record(self, request: ToolRequest, decision: FirewallDecision) -> FirewallDecision:
        self.log.append(
            {
                "tool": request.tool,
                "action": request.action,
                "origin": request.origin,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "checks": decision.checks,
            }
        )
        return decision

    @property
    def block_count(self) -> int:
        return sum(1 for e in self.log if not e["allowed"])
