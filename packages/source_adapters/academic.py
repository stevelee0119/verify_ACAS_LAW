"""제10장 학술자료 Source Adapter.

AcademicSourceAdapter
 ├─ KCIAdapter            (국내 법률논문 우선)
 ├─ OpenAlexAdapter
 ├─ SemanticScholarAdapter
 └─ CrossrefAdapter
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from packages.common.enums import AdapterStatus

from .base import AdapterResponse, SourceAdapter


class AcademicSourceAdapter(SourceAdapter):
    kind = "academic"

    def search_work(self, title: str, *, authors: Optional[List[str]] = None, year: Optional[int] = None,
                    doi: Optional[str] = None) -> AdapterResponse:
        return self.search(title, authors=authors, year=year, doi=doi)


class KCIAdapter(AcademicSourceAdapter):
    name = "kci"
    requires_key = True
    key_env = "LV_KCI_KEY"
    homepage = "https://www.kci.go.kr/"
    ENDPOINT = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"

    @property
    def api_key(self) -> Optional[str]:
        return self.settings.kci_key

    def search(self, query: str, **kwargs: Any) -> AdapterResponse:
        status = self.status()
        if status != AdapterStatus.READY:
            return self._unavailable(query, status, "KCI API Key가 없어 해당 항목은 UNVERIFIED로 표시한다.")
        try:
            response = self._http_get(
                self.ENDPOINT,
                params={"apiCode": "articleSearch", "key": self.api_key, "title": query, "displayCount": 10},
            )
            if response.status_code >= 400:
                return self._unavailable(query, AdapterStatus.ERROR, f"HTTP {response.status_code}")
            body = response.text
        except Exception as exc:
            status = AdapterStatus.TIMEOUT if "timeout" in str(exc).lower() else AdapterStatus.ERROR
            return self._unavailable(query, status, f"조회 실패: {exc}")

        records = _parse_kci_xml(body)
        return AdapterResponse(
            AdapterStatus.READY,
            records,
            self._record(query, AdapterStatus.READY, payload={"body_len": len(body)}, url=self.ENDPOINT,
                         used_fields=["title", "authors", "year", "journal"]),
        )


class OpenAlexAdapter(AcademicSourceAdapter):
    name = "openalex"
    requires_key = False
    homepage = "https://developers.openalex.org/"
    ENDPOINT = "https://api.openalex.org/works"

    def search(self, query: str, **kwargs: Any) -> AdapterResponse:
        status = self.status()
        if status != AdapterStatus.READY:
            return self._unavailable(query, status, "네트워크 비활성")
        doi = kwargs.get("doi")
        params: Dict[str, Any] = {"per-page": 5}
        if doi:
            params["filter"] = f"doi:{doi}"
        else:
            params["search"] = query
        try:
            response = self._http_get(self.ENDPOINT, params=params, headers={"User-Agent": "legal-verifier/0.2"})
            if response.status_code >= 400:
                return self._unavailable(query, AdapterStatus.ERROR, f"HTTP {response.status_code}")
            payload = response.json()
        except Exception as exc:
            status = AdapterStatus.TIMEOUT if "timeout" in str(exc).lower() else AdapterStatus.ERROR
            return self._unavailable(query, status, f"조회 실패: {exc}")

        records = []
        for item in (payload.get("results") or [])[:5]:
            records.append(
                {
                    "title": item.get("title"),
                    "year": item.get("publication_year"),
                    "doi": (item.get("doi") or "").replace("https://doi.org/", "") or None,
                    "authors": [
                        a.get("author", {}).get("display_name")
                        for a in (item.get("authorships") or [])
                        if a.get("author")
                    ],
                    "journal": ((item.get("primary_location") or {}).get("source") or {}).get("display_name"),
                    "id": item.get("id"),
                }
            )
        return AdapterResponse(
            AdapterStatus.READY,
            records,
            self._record(query, AdapterStatus.READY, payload=payload, url=self.ENDPOINT,
                         used_fields=["title", "publication_year", "doi", "authorships"]),
        )


class SemanticScholarAdapter(AcademicSourceAdapter):
    name = "semantic_scholar"
    requires_key = False
    homepage = "https://www.semanticscholar.org/product/api"
    ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"

    @property
    def api_key(self) -> Optional[str]:
        return self.settings.semantic_scholar_key

    def search(self, query: str, **kwargs: Any) -> AdapterResponse:
        status = self.status()
        if status != AdapterStatus.READY:
            return self._unavailable(query, status, "네트워크 비활성")
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        try:
            response = self._http_get(
                self.ENDPOINT,
                params={"query": query, "limit": 5, "fields": "title,year,authors,venue,externalIds"},
                headers=headers,
            )
            if response.status_code == 429:
                return self._unavailable(query, AdapterStatus.RATE_LIMITED, "요청 한도 초과")
            if response.status_code >= 400:
                return self._unavailable(query, AdapterStatus.ERROR, f"HTTP {response.status_code}")
            payload = response.json()
        except Exception as exc:
            status = AdapterStatus.TIMEOUT if "timeout" in str(exc).lower() else AdapterStatus.ERROR
            return self._unavailable(query, status, f"조회 실패: {exc}")

        records = [
            {
                "title": item.get("title"),
                "year": item.get("year"),
                "authors": [a.get("name") for a in (item.get("authors") or [])],
                "journal": item.get("venue"),
                "doi": (item.get("externalIds") or {}).get("DOI"),
            }
            for item in (payload.get("data") or [])
        ]
        return AdapterResponse(
            AdapterStatus.READY,
            records,
            self._record(query, AdapterStatus.READY, payload=payload, url=self.ENDPOINT,
                         used_fields=["title", "year", "authors", "venue"]),
        )


class CrossrefAdapter(AcademicSourceAdapter):
    name = "crossref"
    requires_key = False
    homepage = "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"
    ENDPOINT = "https://api.crossref.org/works"

    def search(self, query: str, **kwargs: Any) -> AdapterResponse:
        status = self.status()
        if status != AdapterStatus.READY:
            return self._unavailable(query, status, "네트워크 비활성")
        doi = kwargs.get("doi")
        url = f"{self.ENDPOINT}/{doi}" if doi else self.ENDPOINT
        params = None if doi else {"query.bibliographic": query, "rows": 5}
        headers = {"User-Agent": f"legal-verifier/0.2 (mailto:{self.settings.crossref_mailto or 'unknown'})"}
        try:
            response = self._http_get(url, params=params, headers=headers)
            if response.status_code == 404:
                return AdapterResponse(
                    AdapterStatus.READY, [], self._record(query, AdapterStatus.READY, payload={"found": False}, url=url),
                    "DOI를 찾지 못했다",
                )
            if response.status_code >= 400:
                return self._unavailable(query, AdapterStatus.ERROR, f"HTTP {response.status_code}")
            payload = response.json()
        except Exception as exc:
            status = AdapterStatus.TIMEOUT if "timeout" in str(exc).lower() else AdapterStatus.ERROR
            return self._unavailable(query, status, f"조회 실패: {exc}")

        message = payload.get("message", {})
        items = message.get("items") if isinstance(message.get("items"), list) else [message]
        records = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            date_parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
            records.append(
                {
                    "title": (item.get("title") or [None])[0],
                    "year": date_parts[0] if date_parts else None,
                    "authors": [
                        f"{a.get('family', '')} {a.get('given', '')}".strip() for a in (item.get("author") or [])
                    ],
                    "journal": (item.get("container-title") or [None])[0],
                    "doi": item.get("DOI"),
                }
            )
        return AdapterResponse(
            AdapterStatus.READY,
            records,
            self._record(query, AdapterStatus.READY, payload=payload, url=url,
                         used_fields=["title", "issued", "author", "DOI"]),
        )


def _parse_kci_xml(body: str) -> List[Dict[str, Any]]:
    """KCI OpenAPI는 XML을 반환한다. 외부 엔티티를 차단하고 파싱한다."""
    try:
        from lxml import etree

        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        root = etree.fromstring(body.encode("utf-8"), parser=parser)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for record in root.iter("record"):
        def _text(tag: str) -> Optional[str]:
            el = record.find(f".//{tag}")
            return el.text.strip() if el is not None and el.text else None

        authors = [a.text.strip() for a in record.iter("author-name") if a.text]
        out.append(
            {
                "title": _text("article-title"),
                "year": int(_text("pub-year") or 0) or None,
                "authors": authors,
                "journal": _text("journal-name"),
                "doi": _text("doi"),
            }
        )
    return out
