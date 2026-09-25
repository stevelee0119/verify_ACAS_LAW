"""규칙표·법리 규칙의 근거가 될 공식 원문을 국가법령정보 공동활용 API에서 받아 출력한다.

코드에 법률 사실(사건부호의 심급, 조문 내용)을 추측으로 넣지 않기 위해, 이 스크립트가 출력한 공식 원문만
config/legal_rules/의 근거로 쓴다. 인증키(LV_LAW_GO_KR_OC)와 네트워크가 있는 환경(GitHub Actions)에서 실행한다.
출력은 JSON 한 줄씩(대상·조회 URL·본문)이며 --out을 주면 파일로도 저장한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.source_adapters.law_go_kr import SERVICE_URL, SEARCH_URL, LawGoKrAdapter, mask_oc  # noqa: E402
from packages.source_adapters.transport import source_lookup_session  # noqa: E402

ADMIN_RULES = ["사건별 부호문자의 부여에 관한 예규"]
STATUTES = [("행정소송법", ["4", "13", "20", "38"]), ("군인사법", ["51의2", "57", "60"]), ("국가배상법", ["2"]),
            ("국가공무원법", ["83"]), ("행정기본법", []),
            # 헌법재판소 사건부호(헌가·헌바·헌마 등)의 근거. "*"는 전체 조문을 남긴다.
            ("헌법재판소 사건의 접수에 관한 규칙", ["*"])]
CASES = ["95다38677", "94누4615", "2006두16274", "2006두20631", "2012두26401", "2021두62148"]
MAX_TEXT = 12000
# 헌재결정례(target=detc) 조회 방식 점검용(G1). 널리 알려진 실존 결정만 둔다. 결과로 실존을 다시 확인한다.
DETC_PROBES = ["2004헌마554", "2016헌나1", "2004헌나1", "2017헌바127", "2008헌가23", "2011헌바379",
               "2009헌바17", "2013헌다1", "2015헌마236", "96헌가2", "89헌마82"]
STATUTES_EXTRA = [("민사소송법", ["422", "442", "449"]), ("형사소송법", ["246", "368", "371", "441"]), ("형법", ["1", "51"]), ("법원조직법", ["14"]),
                  # 추가지시 G4(주장 유형별 근거): 위헌심판 대상, 소송요건, 손해배상 유형의 법률 근거
                  ("대한민국헌법", ["111"]), ("헌법재판소법", ["41", "45", "68"]), ("행정소송법", ["18", "19", "12"]),
                  ("민법", ["162", "166", "393", "394", "750", "751", "763", "764", "766"]), ("국가배상법", ["8", "9"]),
                  ("제조물 책임법", ["3"])]
# 추가지시 G4: 조항별 헌재 결정 이력 조회 방식 점검. 검색어는 법률 조항, 결과 행과 상세의 키를 기록한다.
DETC_PROVISION_PROBES = ["국가배상법 제2조", "군인사법 제57조", "행정소송법 제20조"]
DETC_DETAIL_PROBES = ["95헌바3", "94헌바20", "2008헌가23", "89헌마160"]


def emit(record, sink):
    line = json.dumps(record, ensure_ascii=False)
    print(line)
    if sink:
        sink.write(line + "\n")


def raw_get(adapter, url, params):
    try:
        response = adapter._http_get(url, params={"OC": adapter.api_key, "type": "JSON", **params})
    except Exception as exc:  # 한 요청의 실패가 나머지 수집을 막지 않게 한다
        return None, {"error": f"{type(exc).__name__}: {exc}"}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"text": response.text[:MAX_TEXT]}


def download_text(url):
    """별표 파일(HWP·PDF 등)을 받아 저장소 파서로 글자를 뽑는다."""
    import base64
    import hashlib
    import tempfile

    import httpx

    from packages.document_engine import parse_document

    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    name = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", name)
    filename = match.group(1) if match else "attachment.bin"
    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(response.content)
    doc = parse_document(handle.name, document_id="attachment", filename=filename,
                         mime_type=response.headers.get("content-type", ""),
                         sha256=hashlib.sha256(response.content).hexdigest())
    text = "\n".join(b.text for b in doc.blocks if b.text)
    tables = [t.get("cells") for t in doc.structure.get("tables") or []]
    return {"status": response.status_code, "filename": filename, "content_type": response.headers.get("content-type"),
            "size": len(response.content), "text": text[:60000], "tables": json.dumps(tables, ensure_ascii=False)[:60000],
            "warnings": doc.parse_warnings[:5], "sha256": hashlib.sha256(response.content).hexdigest(),
            # 공개 별표 원본(64KB 이하)을 로그에 남겨 추출 결과를 오프라인에서 원본과 대조할 수 있게 한다.
            **({"raw_base64": base64.b64encode(response.content).decode()}
               if len(response.content) <= 64 * 1024 else {})}


# 대법원 「사건구분안내」(사건부호표). 국가법령정보가 주는 예규 별표 파일에는 민사·형사 일반 사건부호가 빠져 있어
# 법원 누리집의 공식 안내 표를 따로 받아 로그에 남긴다(규칙표 반영은 사람이 원문과 대조한 뒤).
SCOURT_CODE_PAGES = ["https://www.scourt.go.kr/portal/information/event/guide/index.html",
                     "https://seoul.scourt.go.kr/common/util/sagubun_all.jsp",
                     "https://slgodung.scourt.go.kr/common/util/sagubun_all.jsp"]


def html_tables(html: str):
    """HTML의 표를 [[칸 글자, …], …]로. 태그·공백만 걷어낸다."""
    import html as _html

    tables = []
    for table in re.findall(r"<table.*?</table>", html, flags=re.S | re.I):
        rows = []
        for row in re.findall(r"<tr.*?</tr>", table, flags=re.S | re.I):
            cells = [_html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cell))).strip()
                     for cell in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S | re.I)]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def fetch_scourt_codes(sink):
    import httpx

    for url in SCOURT_CODE_PAGES:
        try:
            response = httpx.get(url, timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (official-source audit)"})
            text = response.text
            emit({"kind": "scourt_case_codes", "url": url, "status": response.status_code,
                  "tables": html_tables(text)[:20], "text_sample": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:4000]},
                 sink)
        except Exception as exc:  # 한 쪽의 실패가 나머지 수집을 막지 않게 한다
            emit({"kind": "scourt_case_codes", "url": url, "error": f"{type(exc).__name__}: {exc}"}, sink)


def _opinion_counts(record):
    from packages.legal_engine.opinion_attribution import split_opinions

    counts = {}
    for key in ("full_text", "summary"):
        parts = split_opinions(record.get(key) or "")
        counts[key] = {kind: (len(v) if isinstance(v, list) else len(v)) for kind, v in parts.items()}
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    sink = open(args.out, "w", encoding="utf-8") if args.out else None
    fetch_scourt_codes(sink)
    adapter = LawGoKrAdapter()
    if not adapter.api_key:
        print("LV_LAW_GO_KR_OC가 없어 실행하지 않았다", file=sys.stderr)
        return 1
    seen_rules: set = set()
    with source_lookup_session(600):
        for name in ADMIN_RULES:
            status, listing = raw_get(adapter, SEARCH_URL, {"target": "admrul", "query": name})
            emit({"kind": "admrul_list", "query": name, "status": status, "payload": mask_oc(listing)}, sink)
            rows = (listing.get("AdmRulSearch") or {}).get("admrul") or [] if isinstance(listing, dict) else []
            rows = rows if isinstance(rows, list) else [rows]
            for row in rows[:3]:
                identifier = row.get("행정규칙일련번호")
                # 검색어를 이름에 담은 규칙만, 한 번씩만 받는다(유사 이름의 다른 규칙·중복 조회 제외).
                if identifier in seen_rules or name.replace(" ", "") not in (row.get("행정규칙명") or "").replace(" ", ""):
                    continue
                seen_rules.add(identifier)
                status, detail = raw_get(adapter, SERVICE_URL, {"target": "admrul", "ID": identifier})
                text = json.dumps(mask_oc(detail), ensure_ascii=False)
                emit({"kind": "admrul_detail", "id": identifier, "name": row.get("행정규칙명"), "status": status,
                      "url": f"{SERVICE_URL}?target=admrul&ID={identifier}", "payload_text": text[:60000]}, sink)
                for link in sorted(set(re.findall(r"/LSW/flDownload\.do\?flSeq=\d+", text))):
                    emit({"kind": "attachment", "rule_id": identifier, "url": "https://www.law.go.kr" + link,
                          **download_text("https://www.law.go.kr" + link)}, sink)
        for number in DETC_PROBES:
            for extra in ({"query": number}, {"query": number, "search": 2}, {"nb": number}):
                status, payload = raw_get(adapter, SEARCH_URL, {"target": "detc", "display": 20, **extra})
                container = payload.get("DetcSearch") or payload.get("detcSearch") or {} if isinstance(payload, dict) else {}
                rows = next((container.get(k) for k in ("detc", "Detc") if container.get(k) is not None), [])
                rows = rows if isinstance(rows, list) else [rows]
                emit({"kind": "detc_probe", "case_number": number, "params": extra, "status": status,
                      "top_keys": list(payload)[:5] if isinstance(payload, dict) else str(type(payload)),
                      "container_keys": list(container)[:12] if isinstance(container, dict) else None,
                      "total": container.get("totalCnt") if isinstance(container, dict) else None,
                      "first_rows": mask_oc([{k: r.get(k) for k in list(r)[:8]} for r in rows[:3] if isinstance(r, dict)])}, sink)
        # 실제 조회 경로(adapter.search_case)로 실존 헌재 결정을 모두 확인하는지 회귀 점검(추가지시 G1)
        found = []
        for number in DETC_PROBES:
            try:
                response = adapter.search_case(number, court="헌법재판소")
                ok = bool(response.records) and response.records[0].get("case_number") == number
                found.append(ok)
                emit({"kind": "detc_regression", "case_number": number, "found": ok,
                      "decision_date": (response.records[0].get("decision_date") if response.records else None),
                      "message": response.message}, sink)
            except Exception as exc:
                found.append(False)
                emit({"kind": "detc_regression", "case_number": number, "found": False, "error": str(exc)}, sink)
        emit({"kind": "detc_regression_summary", "found": sum(found), "total": len(found)}, sink)
        for query in DETC_PROVISION_PROBES:
            for extra in ({"query": query}, {"query": query, "search": 2}):
                status, payload = raw_get(adapter, SEARCH_URL, {"target": "detc", "display": 20, **extra})
                container = payload.get("DetcSearch") or {} if isinstance(payload, dict) else {}
                rows = container.get("Detc") or container.get("detc") or [] if isinstance(container, dict) else []
                rows = rows if isinstance(rows, list) else [rows]
                emit({"kind": "detc_provision_probe", "query": query, "params": extra, "status": status,
                      "total": container.get("totalCnt") if isinstance(container, dict) else None,
                      "rows": mask_oc([{k: r.get(k) for k in ("사건번호", "사건명", "종국일자", "헌재결정례일련번호")}
                                       for r in rows[:20] if isinstance(r, dict)])}, sink)
        for number in DETC_DETAIL_PROBES:
            status, payload = raw_get(adapter, SEARCH_URL, {"target": "detc", "nb": number, "display": 5})
            container = payload.get("DetcSearch") or {} if isinstance(payload, dict) else {}
            rows = container.get("Detc") or container.get("detc") or [] if isinstance(container, dict) else []
            rows = rows if isinstance(rows, list) else [rows]
            row = next((r for r in rows if isinstance(r, dict) and r.get("사건번호") == number), None)
            if not row:
                emit({"kind": "detc_detail", "case_number": number, "found": False, "status": status}, sink)
                continue
            status, detail = raw_get(adapter, SERVICE_URL, {"target": "detc", "ID": row.get("헌재결정례일련번호")})
            body = detail.get("DetcService") if isinstance(detail, dict) else None
            body = body if isinstance(body, dict) else (detail if isinstance(detail, dict) else {})
            emit({"kind": "detc_detail", "case_number": number, "found": True, "status": status,
                  "keys": list(body)[:40], "case_name": row.get("사건명"), "decision_date": row.get("종국일자"),
                  "fields": mask_oc({k: (str(v)[:1500] if v is not None else None) for k, v in body.items()
                                     if k not in ("전문",)}),
                  "full_text_head": str(body.get("전문") or "")[:1500]}, sink)
        for law_name, articles in STATUTES + STATUTES_EXTRA:
            try:
                response = adapter.resolve_statute(law_name)
            except Exception as exc:
                emit({"kind": "statute", "law": law_name, "error": str(exc)}, sink)
                continue
            record = response.records[0] if response.records else {}
            texts = {}
            if articles == ["*"]:
                articles = [str(r.get("number")) for r in record.get("provisions") or [] if r.get("number")]
            for article in articles:
                from packages.source_adapters.legal_history import select_provision
                provision = select_provision(record, article, None, None, None) if record else {}
                texts[article] = (provision or {}).get("text")
            emit({"kind": "statute", "law": law_name, "status": str(response.status), "message": response.message,
                  "version_id": record.get("version_id"), "effective_from": record.get("effective_from"),
                  "article_count": len(record.get("articles") or []), "articles": texts,
                  "url": f"{SERVICE_URL}?target=law&MST={record.get('version_id')}"}, sink)
        for number in CASES:
            try:
                response = adapter.search_case(number)
            except Exception as exc:
                emit({"kind": "case", "case_number": number, "error": str(exc)}, sink)
                continue
            record = response.records[0] if response.records else {}
            if record and not record.get("full_text"):
                try:
                    detail = adapter.fetch_case(record)
                    record = {**record, **(detail.records[0] if detail.records else {})}
                except Exception as exc:
                    record = {**record, "detail_error": str(exc)}
            emit({"kind": "case", "case_number": number, "status": str(response.status),
                  "court": record.get("court"), "decision_date": record.get("decision_date"),
                  "case_name": record.get("case_name"), "case_kind": record.get("case_kind"),
                  "holding": (record.get("holding") or "")[:3000], "summary": (record.get("summary") or "")[:3000],
                  "source_id": record.get("source_id"),
                  # 의견 구간 분리(v3 D3)가 실제 판결 전문 형식에서 동작하는지 확인하는 값
                  "full_text_length": len(record.get("full_text") or ""),
                  "opinion_sections": _opinion_counts(record)}, sink)
    if sink:
        sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
