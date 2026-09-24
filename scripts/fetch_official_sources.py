"""규칙표·법리 규칙의 근거가 될 공식 원문을 국가법령정보 공동활용 API에서 받아 출력한다.

코드에 법률 사실(사건부호의 심급, 조문 내용)을 추측으로 넣지 않기 위해, 이 스크립트가 출력한 공식 원문만
data/legal_rules/의 근거로 쓴다. 인증키(LV_LAW_GO_KR_OC)와 네트워크가 있는 환경(GitHub Actions)에서 실행한다.
출력은 JSON 한 줄씩(대상·조회 URL·본문)이며 --out을 주면 파일로도 저장한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.source_adapters.law_go_kr import SERVICE_URL, SEARCH_URL, LawGoKrAdapter, mask_oc  # noqa: E402
from packages.source_adapters.transport import source_lookup_session  # noqa: E402

ADMIN_RULES = ["사건별 부호문자의 부여에 관한 예규"]
STATUTES = [("행정소송법", ["4", "13", "20"]), ("군인사법", ["51의2", "57", "60"]), ("국가배상법", ["2"]),
            ("국가공무원법", ["83"]), ("행정기본법", [])]
CASES = ["95다38677", "94누4615", "2006두16274", "2006두20631", "2012두26401", "2021두62148"]
MAX_TEXT = 12000


def emit(record, sink):
    line = json.dumps(record, ensure_ascii=False)
    print(line)
    if sink:
        sink.write(line + "\n")


def raw_get(adapter, url, params):
    response = adapter._http_get(url, params={"OC": adapter.api_key, "type": "JSON", **params})
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"text": response.text[:MAX_TEXT]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    sink = open(args.out, "w", encoding="utf-8") if args.out else None
    adapter = LawGoKrAdapter()
    if not adapter.api_key:
        print("LV_LAW_GO_KR_OC가 없어 실행하지 않았다", file=sys.stderr)
        return 1
    with source_lookup_session(600):
        for name in ADMIN_RULES:
            status, listing = raw_get(adapter, SEARCH_URL, {"target": "admrul", "query": name})
            emit({"kind": "admrul_list", "query": name, "status": status, "payload": mask_oc(listing)}, sink)
            rows = (listing.get("AdmRulSearch") or {}).get("admrul") or []
            rows = rows if isinstance(rows, list) else [rows]
            for row in rows[:3]:
                identifier = row.get("행정규칙일련번호")
                status, detail = raw_get(adapter, SERVICE_URL, {"target": "admrul", "ID": identifier})
                text = json.dumps(mask_oc(detail), ensure_ascii=False)
                emit({"kind": "admrul_detail", "id": identifier, "name": row.get("행정규칙명"), "status": status,
                      "url": f"{SERVICE_URL}?target=admrul&ID={identifier}", "payload_text": text[:60000]}, sink)
        for law_name, articles in STATUTES:
            response = adapter.resolve_statute(law_name)
            record = response.records[0] if response.records else {}
            texts = {}
            for article in articles:
                from packages.source_adapters.legal_history import select_provision
                provision = select_provision(record, article, None, None, None) if record else {}
                texts[article] = (provision or {}).get("text")
            emit({"kind": "statute", "law": law_name, "status": str(response.status), "message": response.message,
                  "version_id": record.get("version_id"), "effective_from": record.get("effective_from"),
                  "article_count": len(record.get("articles") or []), "articles": texts,
                  "url": f"{SERVICE_URL}?target=law&MST={record.get('version_id')}"}, sink)
        for number in CASES:
            response = adapter.search_case(number)
            record = response.records[0] if response.records else {}
            if record and not record.get("full_text"):
                detail = adapter.fetch_case(record)
                record = {**record, **(detail.records[0] if detail.records else {})}
            emit({"kind": "case", "case_number": number, "status": str(response.status),
                  "court": record.get("court"), "decision_date": record.get("decision_date"),
                  "case_name": record.get("case_name"), "case_kind": record.get("case_kind"),
                  "holding": (record.get("holding") or "")[:3000], "summary": (record.get("summary") or "")[:3000],
                  "source_id": record.get("source_id")}, sink)
    if sink:
        sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
