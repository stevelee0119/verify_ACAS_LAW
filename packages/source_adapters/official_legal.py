"""Official history, interpretation, and administrative appeal operations.

Contracts checked 2026-09-18 at
https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=...
lsEfYdListGuide, lsEfYdInfoGuide, expcListGuide, expcInfoGuide,
deccListGuide, deccInfoGuide. lsHistory is HTML-only, not a JSON API.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlencode

from packages.common.enums import AdapterStatus
from .base import AdapterResponse, response_hash
from .legal_history import body_text, legal_date, objects, parse_law_body, select_version, today_korea

_USED_FIELDS = {
    "eflaw": ["법령ID", "법령일련번호", "시행일자", "공포일자", "공포번호",
              "조문번호", "조문가지번호", "조문시행일자", "조문내용",
              "항번호", "항내용", "호번호", "호내용", "목번호", "목내용", "부칙내용"],
    "expc": ["법령해석례일련번호", "안건번호", "회신일자", "해석일자",
             "회신기관명", "해석기관명", "질의요지", "회답", "이유"],
    "admrul": ["행정규칙일련번호", "행정규칙명", "행정규칙종류", "발령일자", "발령번호",
               "소관부처명", "시행일자", "조문내용"],
    "decc": ["행정심판재결례일련번호", "행정심판례일련번호", "사건번호",
             "처분일자", "의결일자", "재결청", "주문", "청구취지", "이유", "재결요지"],
}


EXACT_LAW_NOT_FOUND = "EXACT_LAW_NOT_FOUND:"


class OfficialLegalMixin:
    """Bounded pagination, immutable snapshots, and exact source identities."""

    def _record(self, query, status, *, payload=None, **kwargs):
        from .law_go_kr import mask_oc

        if payload is not None:
            sanitized = mask_oc(payload)
            canonical = json.dumps(sanitized, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False)
            payload = {"response": sanitized, "snapshot": {
                "format": "canonical-json", "encoding": "utf-8", "canonical_json": canonical,
                "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "sanitized": True,
            }}
        return super()._record(query, status, payload=payload, **kwargs)

    def _legal_json(self, audit_query, *, detail=False, **params):
        from .law_go_kr import SEARCH_URL, SERVICE_URL, mask_oc

        status = self.status()
        if status != AdapterStatus.READY:
            return self._unavailable(audit_query, status, "Official source unavailable"), None
        url = SERVICE_URL if detail else SEARCH_URL
        params = {"type": "JSON", **params}
        public_url = url + "?" + urlencode(params)
        try:
            response = self._http_get(url, params={"OC": self.api_key, **params})
            content = getattr(response, "content", None)
            body_hash = hashlib.sha256(content).hexdigest() if isinstance(content, bytes) else None
            status = (AdapterStatus.RATE_LIMITED if response.status_code == 429 else
                      AdapterStatus.ERROR if response.status_code >= 300 else AdapterStatus.READY)
            try:
                payload = mask_oc(response.json())
            except (ValueError, TypeError):
                payload, status = None, AdapterStatus.ERROR
            record = self._record(audit_query, status, payload=payload, url=public_url,
                                  result_id=str(params.get("MST") or params.get("ID") or "") or None,
                                  used_fields=list(_USED_FIELDS.get(params.get("target"), [])))
            if body_hash:
                record.payload.setdefault("snapshot", {})["response_body_sha256"] = body_hash
                record.response_hash = response_hash(record.payload)
            result = AdapterResponse(status, source_record=record,
                                     message="" if status == AdapterStatus.READY else "Official request failed")
            return result, payload if status == AdapterStatus.READY else None
        except Exception as exc:
            return self._transport_unavailable(audit_query, exc), None

    def _legal_list(self, audit_query, target, root, key, **filters):
        records, sources = [], []
        total = None
        seen_pages = set()
        for page in range(1, 101):
            response, payload = self._legal_json(
                audit_query, target=target, display=100, page=page, **filters)
            sources.extend(response.source_records)
            if not response.ok:
                return AdapterResponse(response.status, [], sources[0] if sources else None,
                                       response.message, sources)
            try:
                container = payload.get(root)
                if container is None and isinstance(payload, dict):
                    # 응답 최상위 키의 대소문자 표기가 대상마다 다르다(AdmRulSearch 등).
                    container = next((v for k, v in payload.items() if k.lower() == root.lower()), None)
                if not isinstance(container, dict):
                    raise ValueError("Unexpected official list root")
                count = int(container["totalCnt"])
                if count < 0 or int(container.get("page", page)) != page:
                    raise ValueError("Invalid pagination metadata")
                if total is not None and total != count:
                    raise ValueError("History changed during pagination")
                total = count
                rows = objects(container.get(key))
                fingerprint = json.dumps(rows, sort_keys=True, ensure_ascii=False)
                if fingerprint in seen_pages or (not rows and len(records) < count):
                    raise ValueError("Incomplete or repeated pagination")
                seen_pages.add(fingerprint)
                records.extend(rows)
                if len(records) > count:
                    raise ValueError("List count disagrees with response")
                if len(records) == count:
                    return AdapterResponse(AdapterStatus.READY, records, sources[0], "", sources, True)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                return AdapterResponse(AdapterStatus.ERROR, [], sources[0], str(exc), sources)
        return AdapterResponse(AdapterStatus.ERROR, [], sources[0], "Pagination limit reached", sources)

    def search_law_history(self, law_name):
        from .law_go_kr import _normalize_law_payload, _same_law_name

        listed = self._legal_list(law_name, "eflaw", "LawSearch", "law",
                                  query=law_name, nw="1,2,3", sort="efasc")
        if not listed.ok or not listed.complete:
            return listed
        normalized = _normalize_law_payload({"LawSearch": {"law": listed.records}})
        named = [r for r in normalized if _same_law_name(law_name, r.get("law_name"))]
        if not named:
            # 공식 목록이 약칭(법령약칭명)을 함께 주면 그 값과도 정확히 대조한다. 부분 일치는 쓰지 않는다.
            named = [r for r in normalized if _same_law_name(law_name, r.get("abbreviation"))]
            for record in named:
                record["matched_by"] = "OFFICIAL_ABBREVIATION"
        if not named:
            # 목록 조회는 성공했으나 같은 이름의 법령이 없다. '조회 범위 내 미발견'이지 조회 실패가 아니다.
            candidates = list(dict.fromkeys(str(r.get("law_name")) for r in normalized if r.get("law_name")))[:5]
            return AdapterResponse(AdapterStatus.READY, [], listed.source_record,
                                   EXACT_LAW_NOT_FOUND + json.dumps(candidates, ensure_ascii=False),
                                   listed.source_records, True)
        identities = {str(r.get("law_id") or "").lstrip("0") for r in named}
        if len(identities) != 1 or "" in identities:
            return AdapterResponse(AdapterStatus.ERROR, [], listed.source_record,
                                   "Missing or ambiguous exact law identity", listed.source_records)
        # Resolve the lineage by ID so earlier titles are not lost on renaming.
        history = self._legal_list(law_name, "eflaw", "LawSearch", "law",
                                   LID=next(iter(identities)), nw="1,2,3", sort="efasc")
        history.source_records = listed.source_records + history.source_records
        if history.ok:
            history.records = _normalize_law_payload({"LawSearch": {"law": history.records}})
            if any(str(r.get("law_id") or "").lstrip("0") not in identities for r in history.records):
                history.status, history.complete = AdapterStatus.ERROR, False
                history.records = []
                history.message = "History contains an unrelated law identity"
        return history

    def resolve_statute(self, law_name, *, as_of=None, current_date=None):
        current = legal_date(current_date) if current_date is not None else today_korea()
        when = legal_date(as_of) if as_of is not None else current
        if not current or not when or when > current:
            return self._unavailable(law_name, AdapterStatus.ERROR, "Invalid or future reference date")
        history = self.search_law_history(law_name)
        if not history.ok or not history.complete or history.message.startswith(EXACT_LAW_NOT_FOUND):
            return history
        try:
            selected = select_version(history.records, when)
            try:
                now = select_version(history.records, current)
                selected["current_version"] = {k: now[k] for k in (
                    "version_id", "law_id", "effective_from", "promulgation_date")}
            except ValueError:
                selected["current_version"] = None
            selected.update(review_as_of=as_of, current_as_of=current,
                            date_basis="EXPLICIT_REFERENCE" if as_of else "CURRENT_ONLY")
        except ValueError as exc:
            return AdapterResponse(AdapterStatus.ERROR, [], history.source_record, str(exc), history.source_records)
        detail = self.fetch_law_version(selected)
        detail.source_records = history.source_records + detail.source_records
        return detail

    def fetch_law_version(self, selected):
        mst, effective = str(selected.get("version_id") or ""), legal_date(selected.get("effective_from"))
        if not mst.isdigit() or not effective:
            return self._unavailable(str(selected.get("law_name")), AdapterStatus.ERROR,
                                     "Exact MST and effective date are required")
        response, payload = self._legal_json(str(selected.get("law_name")), detail=True,
                                            target="eflaw", MST=mst, efYd=effective.replace("-", ""))
        if response.ok:
            try:
                response.records = [parse_law_body(payload, selected)]
                response.complete = True
            except (ValueError, TypeError, KeyError) as exc:
                response.status, response.message = AdapterStatus.ERROR, str(exc)
        return response

    # -- 행정규칙(훈령·예규·고시·지침) ---------------------------------------
    # 목록: lawSearch.do?target=admrul, 본문: lawService.do?target=admrul&ID=일련번호.
    # 응답 필드 이름은 행정규칙명·행정규칙종류·발령번호·소관부처명·시행일자 등이다.
    # 운영 응답 형식은 실연동 점검으로 확인해야 하며, 형식이 다르면 ERROR(미확인)로 남긴다.
    def search_admin_rule(self, name):
        response = self._legal_list(name, "admrul", "AdmRulSearch", "admrul", query=name)
        if response.ok:
            response.records = [_admin_rule(row) for row in response.records]
        return response

    def fetch_admin_rule(self, record):
        identifier = str(record.get("source_id") or "")
        name = str(record.get("rule_name") or identifier)
        if not identifier.isdigit():
            return self._unavailable(name, AdapterStatus.ERROR, "Missing official administrative rule identifier")
        response, payload = self._legal_json(name, detail=True, target="admrul", ID=identifier)
        if not response.ok:
            return response
        try:
            raw = payload.get("AdmRulService") or next(
                (v for k, v in payload.items() if k.lower() == "admrulservice"), None)
            if not isinstance(raw, dict):
                raise ValueError("Unexpected administrative rule detail shape")
            info = raw.get("행정규칙기본정보") if isinstance(raw.get("행정규칙기본정보"), dict) else raw
            detail = _admin_rule(info)
            content = raw.get("조문내용")
            # 조문내용은 문자열 목록이거나 {"조문내용": …} 객체 목록일 수 있다.
            lines = [body_text(item.get("조문내용") if isinstance(item, dict) else item)
                     for item in (content if isinstance(content, list) else [content]) if item]
            full_text = "\n".join(filter(None, lines))
            articles, texts = _rule_articles(full_text)
            if detail["source_id"] and detail["source_id"] != identifier:
                raise ValueError("Official list/detail identity mismatch")
            detail.update(full_text=full_text, articles=articles if full_text else None, article_texts=texts,
                          source_id=identifier)
            response.records = [detail]
            response.complete = bool(full_text)
        except (ValueError, TypeError, AttributeError) as exc:
            response.status, response.message = AdapterStatus.ERROR, str(exc)
        return response

    def search_interpretation(self, query):
        filters = {"itmno": query.replace("-", "")} if re.fullmatch(r"\d{2}-\d{4}", query) else {"query": query}
        return self._search_decision(query, "expc", **filters)

    def search_admin_decision(self, query):
        return self._search_decision(query, "decc", query=query, search=2)

    def _search_decision(self, audit_query, target, **filters):
        response = self._legal_list(audit_query, target, target.title() + "Search", target, **filters)
        if response.ok:
            try:
                response.records = [_decision(row, target) for row in response.records]
            except (ValueError, TypeError):
                response.status, response.complete = AdapterStatus.ERROR, False
                response.records = []
                response.message = "Unsupported official decision list"
        return response

    def fetch_interpretation(self, record):
        return self._fetch_decision(record, "expc")

    def fetch_admin_decision(self, record):
        return self._fetch_decision(record, "decc")

    def _fetch_decision(self, listed, target):
        identifier = str(listed.get("source_id") or "")
        query = str(listed.get("case_number") or identifier)
        if not identifier.isdigit() or listed.get("source_target") != target:
            return self._unavailable(query, AdapterStatus.ERROR, "Missing or incompatible official identifier")
        response, payload = self._legal_json(query, detail=True, target=target, ID=identifier)
        if not response.ok:
            return response
        try:
            raw = payload.get(target.title() + "Service", payload)
            if not isinstance(raw, dict):
                raise ValueError("Unexpected official detail shape")
            detail = _decision(raw, target, detail=True)
            if detail["source_id"] != identifier or detail["case_number"] != listed.get("case_number"):
                raise ValueError("Official list/detail identity mismatch")
            response.records = [detail]
            response.complete = detail["full_text_complete"]
        except (ValueError, TypeError, AttributeError) as exc:
            response.status, response.message = AdapterStatus.ERROR, str(exc)
        return response


def _decision(raw, target, *, detail=False):
    expc = target == "expc"
    identifier = raw.get("법령해석례일련번호") if expc else (
        raw.get("행정심판례일련번호") if detail else raw.get("행정심판재결례일련번호"))
    sections = ("질의요지", "회답", "이유") if expc else ("주문", "청구취지", "이유")
    bodies = {key: body_text(raw.get(key)) for key in sections} if detail else {}
    number = body_text(raw.get("안건번호" if expc else "사건번호"))
    return {
        "source_id": str(identifier) if identifier is not None else None,
        "source_target": target, "case_number": re.sub(r"\s+", "", number),
        "case_name": body_text(raw.get("안건명" if expc else "사건명")),
        "court": body_text(raw.get(("해석기관명" if detail else "회신기관명") if expc else "재결청")),
        "decision_date": legal_date(raw.get(("해석일자" if detail else "회신일자") if expc else "의결일자")),
        "disposition_date": legal_date(raw.get("처분일자")),
        "sections": bodies, "full_text": "\n".join(filter(None, bodies.values())),
        "full_text_complete": bool(detail and all(bodies.values())),
        "summary": body_text(raw.get("재결요지")), "raw": raw,
        "applicability_advisory_only": True,
    }


def _admin_rule(raw):
    return {
        "source_id": str(raw.get("행정규칙일련번호")) if raw.get("행정규칙일련번호") is not None else None,
        "rule_id": body_text(raw.get("행정규칙ID")) or None,
        "rule_name": body_text(raw.get("행정규칙명")),
        "rule_kind": body_text(raw.get("행정규칙종류")),
        "agency": body_text(raw.get("소관부처명")),
        "number": re.sub(r"\s+", "", body_text(raw.get("발령번호")) or ""),
        "issued_date": legal_date(raw.get("발령일자")),
        "effective_from": legal_date(raw.get("시행일자")),
        "current_status": body_text(raw.get("현행연혁구분")),
    }


def _rule_articles(full_text):
    """행정규칙 본문에서 조 번호와 조별 본문을 나눈다. 줄 첫머리의 '제N조'만 조로 본다."""
    from packages.legal_engine.normalize import canonical_article

    heads = list(re.finditer(r"(?m)^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?", full_text or ""))
    articles, texts = [], {}
    for index, head in enumerate(heads):
        number = f"{head.group(1)}의{head.group(2)}" if head.group(2) else head.group(1)
        key = canonical_article(number)
        articles.append(number)
        end = heads[index + 1].start() if index + 1 < len(heads) else len(full_text)
        texts[key] = full_text[head.start():end].strip()
    return articles, texts
