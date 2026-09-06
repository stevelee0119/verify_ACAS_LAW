"""국가법령정보 공동활용 Adapter (https://open.law.go.kr/).

공식 Source로서 최우선 순위를 가진다(제12.4장 Judge Source Priority).
OC(이메일 ID) 미발급 시 MISSING_KEY로 표시하고 검증항목만 UNVERIFIED로 남긴다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from packages.common.enums import AdapterStatus

from .base import AdapterResponse, SourceAdapter
from .local_mirror import LocalLegalMirror

BASE = "https://www.law.go.kr/DRF"
SEARCH_URL = f"{BASE}/lawSearch.do"
SERVICE_URL = f"{BASE}/lawService.do"


class LawGoKrAdapter(SourceAdapter):
    name = "law_go_kr"
    kind = "legal"
    requires_key = True
    key_env = "LV_LAW_GO_KR_OC"
    homepage = "https://open.law.go.kr/"

    def __init__(self, *, enabled: bool = True, mirror: Optional[LocalLegalMirror] = None) -> None:
        super().__init__(enabled=enabled)
        self.mirror = mirror or LocalLegalMirror()

    @property
    def api_key(self) -> Optional[str]:
        return self.settings.law_go_kr_oc

    # -- 판례 -------------------------------------------------------------
    def search_case(self, case_number: str, *, court: Optional[str] = None) -> AdapterResponse:
        """사건번호로 판례를 조회한다."""
        mirrored = self.mirror.find_case(case_number)
        if mirrored is not None:
            record = self._record(
                case_number,
                AdapterStatus.READY,
                payload=mirrored,
                result_id=mirrored.get("case_number"),
                url=self.mirror.source_url,
                used_fields=["case_number", "court", "decision_date", "holding"],
            )
            record.adapter = f"{self.name}:mirror"
            return AdapterResponse(AdapterStatus.READY, [mirrored], record, "내부 Mirror에서 확인")

        status = self.status()
        if status != AdapterStatus.READY:
            return self._unavailable(
                case_number,
                status,
                "국가법령정보 OC가 없거나 네트워크가 비활성이다. 해당 항목은 UNVERIFIED로 표시한다.",
            )
        try:
            response = self._http_get(
                SEARCH_URL,
                params={"OC": self.api_key, "target": "prec", "type": "JSON", "search": 2, "query": case_number},
            )
            if response.status_code == 429:
                return self._unavailable(case_number, AdapterStatus.RATE_LIMITED, "요청 한도 초과")
            if response.status_code >= 400:
                return self._unavailable(case_number, AdapterStatus.ERROR, f"HTTP {response.status_code}")
            payload = response.json()
        except Exception as exc:  # 네트워크·파싱 오류는 Job을 실패시키지 않는다
            status = AdapterStatus.TIMEOUT if "timeout" in str(exc).lower() else AdapterStatus.ERROR
            return self._unavailable(case_number, status, f"조회 실패: {exc}")

        records = _normalize_case_payload(payload)
        return AdapterResponse(
            AdapterStatus.READY,
            records,
            self._record(
                case_number,
                AdapterStatus.READY,
                payload=payload,
                result_id=records[0].get("case_number") if records else None,
                url=SEARCH_URL,
                used_fields=["사건번호", "법원명", "선고일자", "판시사항", "판결요지"],
            ),
        )

    # -- 법령 -------------------------------------------------------------
    def search_law(self, law_name: str, *, article: Optional[str] = None, as_of: Optional[str] = None) -> AdapterResponse:
        """법령 조문을 조회한다. as_of가 있으면 그 시점 시행 version을 확인한다(제9.4장)."""
        mirrored = self.mirror.find_law(law_name, article=article, as_of=as_of)
        if mirrored is not None:
            record = self._record(
                f"{law_name} 제{article}조",
                AdapterStatus.READY,
                payload=mirrored,
                result_id=mirrored.get("law_name"),
                url=self.mirror.source_url,
                used_fields=["law_name", "article", "effective_from", "effective_to", "text"],
            )
            record.adapter = f"{self.name}:mirror"
            return AdapterResponse(AdapterStatus.READY, [mirrored], record, "내부 Mirror에서 확인")

        status = self.status()
        if status != AdapterStatus.READY:
            return self._unavailable(law_name, status, "국가법령정보 OC가 없거나 네트워크가 비활성이다.")
        try:
            params: Dict[str, Any] = {"OC": self.api_key, "target": "law", "type": "JSON", "query": law_name}
            if as_of:
                params["ancYd"] = as_of.replace("-", "")
            response = self._http_get(SEARCH_URL, params=params)
            if response.status_code >= 400:
                return self._unavailable(law_name, AdapterStatus.ERROR, f"HTTP {response.status_code}")
            payload = response.json()
        except Exception as exc:
            status = AdapterStatus.TIMEOUT if "timeout" in str(exc).lower() else AdapterStatus.ERROR
            return self._unavailable(law_name, status, f"조회 실패: {exc}")

        records = _normalize_law_payload(payload)
        return AdapterResponse(
            AdapterStatus.READY,
            records,
            self._record(law_name, AdapterStatus.READY, payload=payload, url=SEARCH_URL,
                         used_fields=["법령명한글", "시행일자", "공포일자"]),
        )

    def search(self, query: str, **kwargs: Any) -> AdapterResponse:
        if kwargs.get("target") == "law":
            return self.search_law(query, article=kwargs.get("article"), as_of=kwargs.get("as_of"))
        return self.search_case(query, court=kwargs.get("court"))


def _first(d: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        if key in d and d[key] not in (None, ""):
            return str(d[key])
    return None


def _normalize_case_payload(payload: Any) -> List[Dict[str, Any]]:
    """국가법령정보 응답을 내부 표준 형태로 변환한다."""
    out: List[Dict[str, Any]] = []
    container = payload.get("PrecSearch") if isinstance(payload, dict) else None
    items = []
    if isinstance(container, dict):
        raw = container.get("prec") or container.get("Prec") or []
        items = raw if isinstance(raw, list) else [raw]
    elif isinstance(payload, list):
        items = payload
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "case_number": _first(item, "사건번호", "case_number"),
                "court": _first(item, "법원명", "court"),
                "decision_date": _canon_date(_first(item, "선고일자", "decision_date") or ""),
                "case_name": _first(item, "사건명", "case_name"),
                "case_kind": _first(item, "판결유형", "선고", "case_kind"),
                "holding": _first(item, "판시사항", "holding"),
                "summary": _first(item, "판결요지", "summary"),
                "detail_link": _first(item, "판례상세링크", "detail_link"),
                "raw": item,
            }
        )
    return out


def _normalize_law_payload(payload: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    container = payload.get("LawSearch") if isinstance(payload, dict) else None
    items = []
    if isinstance(container, dict):
        raw = container.get("law") or []
        items = raw if isinstance(raw, list) else [raw]
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "law_name": _first(item, "법령명한글", "law_name"),
                "promulgation_date": _canon_date(_first(item, "공포일자", "") or ""),
                "effective_from": _canon_date(_first(item, "시행일자", "") or ""),
                "law_id": _first(item, "법령ID", "법령일련번호"),
                "detail_link": _first(item, "법령상세링크"),
                "raw": item,
            }
        )
    return out


def _canon_date(value: str) -> Optional[str]:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return value or None
