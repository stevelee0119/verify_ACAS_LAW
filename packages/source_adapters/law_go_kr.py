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
from .official_legal import OfficialLegalMixin

BASE = "https://www.law.go.kr/DRF"
SEARCH_URL = f"{BASE}/lawSearch.do"
SERVICE_URL = f"{BASE}/lawService.do"


class LawGoKrAdapter(OfficialLegalMixin, SourceAdapter):
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
        # legal_engine이 source_adapters를 불러오므로 모듈 최상단에서 가져오지 않는다.
        from packages.legal_engine.normalize import split_case_number

        wanted = split_case_number(case_number)
        # 조회할 DB는 사건부호가 정한다(헌가·헌바·헌마 … → 헌재결정례). 문서의 법원 표시가 틀려도(예: '대법원 …
        # 2005헌바28 판결') 부호가 가리키는 DB에서 찾는다. 부호가 없으면 문서의 법원 표시를 따른다.
        constitutional = wanted[1].startswith("헌") if wanted else court == "헌법재판소"
        target = "detc" if constitutional else "prec"

        # 사건번호 지정 조회(nb) → 본문검색(search=2) 순서로 시도한다. 본문검색은 사건번호가 본문에 인용된 다른
        # 결정까지 수백 건 돌려주므로(공식 원문 수집에서 확인: 2008헌가23 → 590건) 뒤에 둔다. 기본 검색은 nb와
        # 같은 결과를 돌려줘(실존 결정 11건 모두 동일) 요청만 늘리므로 쓰지 않는다. 채택 조건은 "사건번호
        # 완전일치"뿐이라 시도 순서가 오탐을 만들지 않는다. 법원·선고일을 덧붙인 재검색 질의에는 nb를 쓰지 않는다.
        bare = wanted is not None and re.fullmatch(r"\s*[\d가-힣]+\s*", case_number) is not None
        attempts: List[Dict[str, Any]] = []
        if bare:
            attempts.append({"nb": case_number.strip()})
        attempts.append({"search": 2, "query": case_number, "display": CASE_PAGE_SIZE})

        first: Optional[AdapterResponse] = None
        first_skipped = 0
        tried: List[str] = []
        for extra in attempts:
            label = ",".join(f"{k}={v}" for k, v in extra.items() if k not in ("query", "display")) or "query"
            # 헌재결정례는 정확한 결정이 첫 페이지 밖에 있을 수 있어 페이지를 넘겨 본다(추가지시 J1).
            pages = CASE_MAX_PAGES if target == "detc" and "nb" not in extra else 1
            for page in range(1, pages + 1):
                params = {"OC": self.api_key, "target": target, "type": "JSON", **extra,
                          **({"page": page} if page > 1 else {})}
                try:
                    response = self._http_get(SEARCH_URL, params=params)
                    if response.status_code == 429:
                        return self._unavailable(case_number, AdapterStatus.RATE_LIMITED, "요청 한도 초과")
                    if response.status_code >= 400:
                        if first is not None:
                            break
                        return self._unavailable(case_number, AdapterStatus.ERROR, f"HTTP {response.status_code}")
                    payload = response.json()
                except Exception as exc:  # 네트워크·파싱 오류는 Job을 실패시키지 않는다
                    if first is not None:
                        break
                    return self._transport_unavailable(case_number, exc)
                if not _case_payload_shape_ok(payload):
                    # 빈 결과와 형식이 다른 응답을 구분한다. 형식 이상은 '찾지 못함'이 아니라 조회 실패다.
                    keys = list(payload)[:5] if isinstance(payload, dict) else type(payload).__name__
                    return self._unavailable(case_number, AdapterStatus.ERROR,
                                             f"{target} 응답 형식이 예상과 다름(최상위 {keys})")
                listed = _normalize_case_payload(payload)
                total = _total_count(payload, len(listed))
                tried.append(f"{target}:{label}{'' if page == 1 else f' p{page}'} {total}건")
                # 키워드 검색은 다른 사건도 돌려준다. 사건번호가 정확히 같은 기록만 채택하고, 나머지는
                # 원 응답(payload)에만 남긴다(R4).
                if wanted is None:
                    records, skipped = listed, 0
                else:
                    records = [r for r in listed if split_case_number(str(r.get("case_number") or "")) == wanted]
                    skipped = len(listed) - len(records)
                matched = wanted is not None and bool(records)
                result = AdapterResponse(
                    AdapterStatus.READY, records,
                    self._record(case_number, AdapterStatus.READY, payload=payload,
                                 result_id=records[0].get("case_number") if records else None, url=SEARCH_URL,
                                 used_fields=["사건번호", "법원명", "선고일자", "종국일자", "판시사항", "판결요지"]),
                    f"{target} 조회 방식 {label}에서 사건번호 일치" if matched else "",
                )
                if matched:
                    return result
                if first is None:
                    first, first_skipped = result, skipped
                if wanted is None:
                    return result  # 사건번호가 아닌 키워드 조회(예: "손해배상")는 첫 응답으로 끝낸다
                if page * CASE_PAGE_SIZE >= total:
                    break

        if first is not None and not first.message:
            first = AdapterResponse(first.status, first.records, first.source_record,
                                    f"사건번호 일치 없음(조회 DB {target}, 시도: {' → '.join(tried)}; "
                                    f"다른 사건 {first_skipped}건은 채택하지 않음)")
        return first if first is not None else self._unavailable(
            case_number, AdapterStatus.ERROR, "조회를 수행하지 못했다")

    # -- 법령 -------------------------------------------------------------
    def search_law(self, law_name: str, *, article: Optional[str] = None, as_of: Optional[str] = None) -> AdapterResponse:
        """법령 조문을 조회한다. as_of가 있으면 그 시점 시행 version을 확인한다(제9.4장)."""
        if as_of is not None and not self.mirror.all_versions(law_name, article):
            return self.resolve_statute(law_name, as_of=as_of)
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
            # A promulgation-date filter is not a historical applicability query.
            response = self._http_get(SEARCH_URL, params=params)
            if response.status_code >= 400:
                return self._unavailable(law_name, AdapterStatus.ERROR, f"HTTP {response.status_code}")
            payload = response.json()
        except Exception as exc:
            return self._transport_unavailable(law_name, exc)

        records = _normalize_law_payload(payload)
        # lawSearch.do는 키워드 검색이다. "민법"으로 조회하면 "난민법"·"주민법" 등
        # 부분 문자열을 포함한 법령이 함께 돌아온다. 이름이 정확히 같은 것만 남긴다.
        exact = [r for r in records if _same_law_name(law_name, r.get("law_name"))] or \
            [r for r in records if _same_law_name(law_name, r.get("abbreviation"))]
        for record in exact:
            record["requested_as_of"] = as_of
            record["temporal_scope"] = "CURRENT_LIST_ONLY"
        return AdapterResponse(
            AdapterStatus.READY,
            exact,
            self._record(law_name, AdapterStatus.READY, payload=payload, url=SEARCH_URL,
                         used_fields=["법령명한글", "시행일자", "공포일자"]),
            "이름이 정확히 일치하는 법령이 없다" if records and not exact else "",
        )

    # -- 조문 실존 확인 -----------------------------------------------------
    def fetch_case(self, case: Dict[str, Any], *, constitutional: bool = False) -> AdapterResponse:
        target = "detc" if constitutional else "prec"
        raw = case.get("raw") or {}
        identifier = case.get("source_id") or _first(raw, "판례일련번호", "판례정보일련번호", "헌재결정례일련번호")
        if not identifier or self.status() != AdapterStatus.READY:
            return self._unavailable(str(case.get("case_number")), self.status() if self.status() != AdapterStatus.READY else AdapterStatus.ERROR, "판례 전문을 조회할 수 없다")
        label = str(case.get("case_number"))
        try:
            response = self._http_get(SERVICE_URL, params={"OC": self.api_key, "target": target, "type": "JSON", "ID": identifier})
        except Exception as exc:
            return self._transport_unavailable(label, exc)
        # 전문 조회가 실패하면 의미·적용 검토(세 모델 교차검증)가 통째로 건너뛰어진다.
        # 실패 이유를 한 문장으로 뭉개지 않고 구분해 남긴다. URL·OC는 넣지 않는다.
        if response.status_code >= 400:
            return self._unavailable(label, AdapterStatus.RATE_LIMITED if response.status_code == 429
                                     else AdapterStatus.ERROR, f"판례 전문 조회 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            kind = (response.headers.get("content-type") or "알 수 없음").split(";")[0]
            head = mask_oc(re.sub(r"\s+", " ", response.text[:120]))
            return self._unavailable(label, AdapterStatus.ERROR,
                                     f"판례 전문 응답이 JSON이 아님(content-type {kind}, 앞부분 {head!r})")
        raw_detail = None
        if isinstance(payload, dict):
            raw_detail = payload.get("PrecService") or payload.get("DetcService")
            if raw_detail is None and any(k in payload for k in ("사건번호", "판례내용", "전문")):
                raw_detail = payload  # 감싸는 키 없이 본문이 바로 오는 형태
        if not isinstance(raw_detail, dict):
            keys = list(payload)[:5] if isinstance(payload, dict) else type(payload).__name__
            return self._unavailable(label, AdapterStatus.ERROR, f"판례 전문 응답 형식이 예상과 다름(최상위 {keys})")
        try:
            normalized = _normalize_case_payload([raw_detail])[0]
            from html import unescape
            normalized = {k: unescape(re.sub(r"<[^>]+>", " ", v)) if isinstance(v, str) else v for k, v in normalized.items()}
            normalized = {k: v for k, v in normalized.items() if v is not None}
            record = self._record(str(case.get("case_number")), AdapterStatus.READY, payload=mask_oc(payload),
                result_id=str(identifier), url=f"{SERVICE_URL}?target={target}&ID={identifier}", used_fields=["판례내용", "판시사항", "판결요지"])
            return AdapterResponse(AdapterStatus.READY, [normalized], record)
        except Exception as exc:
            return self._unavailable(label, AdapterStatus.ERROR,
                                     f"판례 전문 응답을 정리하지 못함({type(exc).__name__})")

    def constitutional_history(self, law_name: str, article: str, *, max_details: int = 5) -> Dict[str, Any]:
        """법률 조항에 대한 헌법재판소 결정 이력(추가지시 G4 위헌 주장 대조).

        헌재결정례를 '법률명 제N조'로 검색해 사건명에 그 법률과 조항이 함께 있는 결정만 고르고, 결정 전문의
        주문에서 결과(합헌·위헌·헌법불합치·한정위헌·한정합헌·각하)를 읽는다. 조회 실패·형식 이상은 결과를
        비워 두고 status로 알린다(부존재로 단정하지 않는다).
        """
        status = self.status()
        if status != AdapterStatus.READY:
            return {"status": str(status), "message": "국가법령정보 OC가 없거나 네트워크가 비활성이다"}
        query = f"{law_name} 제{article}조"
        try:
            response = self._http_get(SEARCH_URL, params={"OC": self.api_key, "target": "detc", "type": "JSON",
                                                          "query": query, "display": 100})
            if response.status_code >= 400:
                return {"status": "ERROR", "message": f"헌재결정례 조항 검색 HTTP {response.status_code}"}
            payload = response.json()
        except Exception as exc:  # 네트워크·파싱 오류는 판정을 막지 않고 '확인 불가'로 남긴다
            return {"status": "ERROR", "message": f"헌재결정례 조항 검색 실패({type(exc).__name__})"}
        if not _case_payload_shape_ok(payload):
            return {"status": "ERROR", "message": "헌재결정례 응답 형식이 예상과 다름"}
        rows = _normalize_case_payload(payload)
        compact = lambda value: re.sub(r"\s+", "", str(value or ""))
        wanted_law, wanted_article = compact(law_name), f"제{compact(article)}조"
        matched = [r for r in rows if wanted_law in compact(r.get("case_name"))
                   and wanted_article in compact(r.get("case_name"))]
        decisions = []
        for row in matched[:max_details]:
            detail = self.fetch_case(row, constitutional=True)
            record = detail.records[0] if detail.records else {}
            decisions.append({"case_number": row.get("case_number"), "decision_date": row.get("decision_date"),
                              "case_name": row.get("case_name"), "result": decision_result(record),
                              "url": detail.source_record.url if detail.source_record else "",
                              "summary": str(record.get("summary") or record.get("holding") or "")[:400]})
        return {"status": "READY", "decisions": decisions, "query": query,
                "message": f"헌재결정례 '{query}' 검색 {_total_count(payload, len(rows))}건 중 조항 일치 {len(matched)}건"}

    def fetch_articles(self, law: Dict[str, Any]) -> Optional[List[str]]:
        """법령 본문을 조회해 수록된 조문 번호 목록을 만든다.

        검색 API는 법령의 존재만 알려줄 뿐 조문 목록을 주지 않는다. 조문 번호를 확인하지
        않으면 '민법 제390조의2'처럼 실재하지 않는 조문이 법령만 맞다는 이유로
        확인된 것처럼 처리된다.

        조회에 실패하면 빈 목록이 아니라 None을 돌려준다. 빈 목록을 돌려주면
        "조문이 없음(=허위)"과 "확인 불가"가 구분되지 않는다.
        """
        raw = law.get("raw") or {}
        if law.get("body_complete"):
            return list(law.get("articles", []))
        mst = law.get("version_id") or _first(raw, "법령일련번호", "MST")
        if not mst or self.status() != AdapterStatus.READY:
            return None
        try:
            response = self._http_get(
                SERVICE_URL,
                params={"OC": self.api_key, "target": "law", "type": "JSON", "MST": mst},
            )
            if response.status_code >= 400:
                return None
            payload = response.json()
        except Exception:
            return None
        law["article_source_record"] = self._record(str(law.get("law_name")), AdapterStatus.READY,
            payload=mask_oc(payload), result_id=str(mst), url=f"{SERVICE_URL}?target=law&MST={mst}",
            used_fields=["조문번호", "조문가지번호", "조문내용"]).to_dict()
        law["article_payload"] = mask_oc(payload)
        return _article_numbers(payload)

    def search(self, query: str, **kwargs: Any) -> AdapterResponse:
        if kwargs.get("target") in ("expc", "interpretation"):
            return self.search_interpretation(query)
        if kwargs.get("target") in ("decc", "admin_decision", "admin_appeal"):
            return self.search_admin_decision(query)
        if kwargs.get("target") in ("law", "eflaw"):
            return self.search_law(query, article=kwargs.get("article"), as_of=kwargs.get("as_of"))
        if kwargs.get("target") not in (None, "prec", "detc", "case"):
            return self._unavailable(query, AdapterStatus.ERROR, "Unsupported official legal source target")
        if kwargs.get("target") == "detc":
            return self.search_case(query, court="헌법재판소")
        return self.search_case(query, court=kwargs.get("court"))


# 국가법령정보 응답의 상세링크에는 요청에 쓴 OC가 그대로 들어온다.
# 이 값이 검증보고서에 실려 나가면 이용자의 OPEN API 식별자가 문서와 함께 유출된다.
OC_IN_URL_RE = re.compile(r"((?:[?&]|&amp;)OC=)[^&\s\"'<>]+", re.IGNORECASE)


def mask_oc(value: Any) -> Any:
    """URL 안의 OC 파라미터를 가린다. 문자열이 아니면 그대로 둔다."""
    if isinstance(value, str):
        return OC_IN_URL_RE.sub(r"\1[REDACTED]", value)
    if isinstance(value, dict):
        return {k: "[REDACTED]" if str(k).lower() == "oc" else mask_oc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_oc(v) for v in value]
    return value


def _first(d: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        if key in d and d[key] not in (None, ""):
            return str(d[key])
    return None


CASE_PAGE_SIZE = 100
CASE_MAX_PAGES = 3


def _case_payload_shape_ok(payload: Any) -> bool:
    """판례·헌재결정례 목록 응답의 모양인지(빈 결과도 모양은 맞다)."""
    if isinstance(payload, list):
        return True
    return isinstance(payload, dict) and any(k in payload for k in ("PrecSearch", "DetcSearch"))


def _total_count(payload: Any, fallback: int) -> int:
    container = (payload.get("PrecSearch") or payload.get("DetcSearch")) if isinstance(payload, dict) else None
    try:
        return int((container or {}).get("totalCnt"))
    except (TypeError, ValueError):
        return fallback


def _normalize_case_payload(payload: Any) -> List[Dict[str, Any]]:
    """국가법령정보 응답을 내부 표준 형태로 변환한다."""
    out: List[Dict[str, Any]] = []
    container = (payload.get("PrecSearch") or payload.get("DetcSearch")) if isinstance(payload, dict) else None
    items = []
    if isinstance(container, dict):
        raw = container.get("prec") or container.get("Prec") or container.get("detc") or container.get("Detc") or []
        items = raw if isinstance(raw, list) else [raw]
    elif isinstance(payload, list):
        items = payload
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "case_number": _first(item, "사건번호", "case_number"),
                "source_id": _first(item, "판례일련번호", "판례정보일련번호", "헌재결정례일련번호"),
                "full_text": _first(item, "판례내용", "전문", "full_text"),
                "court": _first(item, "법원명", "court"),
                "decision_date": _canon_date(_first(item, "선고일자", "종국일자", "decision_date") or ""),
                "case_name": _first(item, "사건명", "case_name"),
                "case_kind": _first(item, "판결유형", "선고", "case_kind"),
                "holding": _first(item, "판시사항", "holding"),
                "summary": _first(item, "판결요지", "summary"),
                "detail_link": mask_oc(_first(item, "판례상세링크", "detail_link")),
                "raw": mask_oc(item),
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
                "abbreviation": _first(item, "법령약칭명", "abbreviation"),
                "promulgation_date": _canon_date(_first(item, "공포일자", "") or ""),
                "effective_from": _canon_date(_first(item, "시행일자", "") or ""),
                "law_id": _first(item, "법령ID"),
                "version_id": _first(item, "법령일련번호", "MST"),
                "promulgation_number": _first(item, "공포번호"),
                "amendment_type": _first(item, "제개정구분명"),
                "detail_link": mask_oc(_first(item, "법령상세링크")),
                "raw": mask_oc(item),
            }
        )
    return out


def _same_law_name(left: Optional[str], right: Optional[str]) -> bool:
    """공백·괄호 표기를 무시하고 법령명이 같은지 본다. 부분 포함은 같다고 보지 않는다."""
    from packages.legal_engine.normalize import canonical_law_name

    if not left or not right:
        return False
    return canonical_law_name(left).replace(" ", "") == canonical_law_name(right).replace(" ", "")


def _article_numbers(payload: Any) -> List[str]:
    """응답 어디에 중첩되어 있든 조문번호·조문가지번호를 모아 정규화한다.

    국가법령정보 본문 응답의 중첩 구조는 법령 종류에 따라 다르므로,
    고정 경로를 가정하지 않고 재귀 탐색한다.
    """
    found: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            number = node.get("조문번호")
            if number not in (None, ""):
                branch = str(node.get("조문가지번호") or "").strip()
                try:
                    base = str(int(str(number).strip()))
                except ValueError:
                    base = str(number).strip()
                if branch and branch not in ("0",):
                    try:
                        found.append(f"{base}의{int(branch)}")
                    except ValueError:
                        found.append(f"{base}의{branch}")
                else:
                    found.append(base)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _canon_date(value: str) -> Optional[str]:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return value or None


# 헌재 결정 주문의 결과 문구. 긴 문구부터 본다('헌법에 합치되지 아니한다'가 '위반'보다 먼저).
_RESULT_PATTERNS = [
    ("헌법불합치", r"헌법에\s*합치되지\s*아니한다"),
    ("한정위헌", r"(?:해석하는|적용하는)\s*한[^.]{0,20}헌법에\s*위반된다"),
    ("한정합헌", r"(?:해석하는|적용하는)\s*한[^.]{0,20}헌법에\s*위반되지\s*아니한다"),
    ("합헌", r"헌법에\s*위반되지\s*아니한다"),
    ("위헌", r"헌법에\s*위반된다"),
    ("각하", r"(?:심판\s*청구|청구|제청)(?:를|을)?\s*(?:모두\s*)?각하한다"),
]


def decision_result(record: Dict[str, Any]) -> Optional[str]:
    """결정 전문 기록에서 주문의 결과를 읽는다. 주문을 찾지 못하면 None(추측하지 않는다)."""
    raw = record.get("raw") or {}
    order = _first(raw, "주문") if isinstance(raw, dict) else None
    text = re.sub(r"<[^>]+>", " ", str(order or record.get("full_text") or ""))
    if not order:
        head = re.search(r"주\s*문(.{0,600})", text, re.S)
        text = head.group(1) if head else ""
    for label, pattern in _RESULT_PATTERNS:
        if re.search(pattern, text):
            return label
    return None
