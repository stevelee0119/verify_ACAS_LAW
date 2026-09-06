"""제10장 Source Adapter 공통 규약.

MISSING_KEY, TIMEOUT, ERROR는 전체 Verification Job을 실패시키지 않는다.
해당 검증항목만 UNVERIFIED로 표시한다.
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from packages.common.config import get_settings
from packages.common.enums import AdapterStatus
from packages.common.schemas import SourceRecord


@dataclass
class AdapterResponse:
    status: AdapterStatus
    records: List[Dict[str, Any]] = field(default_factory=list)
    source_record: Optional[SourceRecord] = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == AdapterStatus.READY

    @property
    def found(self) -> bool:
        return self.ok and bool(self.records)


def response_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


class SourceAdapter(ABC):
    name = "base"
    kind = "generic"  # legal | academic | mirror
    requires_key = False
    key_env = ""
    homepage = ""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.settings = get_settings()

    # -- 상태 ------------------------------------------------------------
    def status(self) -> AdapterStatus:
        if not self.enabled:
            return AdapterStatus.DISABLED
        if self.requires_key and not self.api_key:
            return AdapterStatus.MISSING_KEY
        if not self.settings.allow_network:
            return AdapterStatus.DISABLED
        return AdapterStatus.READY

    @property
    def api_key(self) -> Optional[str]:
        return None

    # -- 조회 ------------------------------------------------------------
    @abstractmethod
    def search(self, query: str, **kwargs: Any) -> AdapterResponse: ...

    # -- 유틸 ------------------------------------------------------------
    def _record(
        self,
        query: str,
        status: AdapterStatus,
        *,
        payload: Any = None,
        result_id: Optional[str] = None,
        url: Optional[str] = None,
        used_fields: Optional[List[str]] = None,
    ) -> SourceRecord:
        return SourceRecord.create(
            adapter=self.name,
            query=query,
            status=status,
            result_id=result_id,
            response_hash=response_hash(payload) if payload is not None else None,
            url=url,
            used_fields=used_fields or [],
            payload=payload if isinstance(payload, dict) else ({"data": payload} if payload is not None else {}),
        )

    def _unavailable(self, query: str, status: AdapterStatus, message: str) -> AdapterResponse:
        return AdapterResponse(
            status=status,
            records=[],
            source_record=self._record(query, status),
            message=message,
        )

    def _http_get(self, url: str, *, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        """제21.1장 SSRF 방어: 허용된 Adapter만 자신의 고정 도메인을 호출한다."""
        import httpx

        return httpx.get(
            url,
            params=params,
            headers=headers or {},
            timeout=self.settings.http_timeout,
            follow_redirects=False,
        )
