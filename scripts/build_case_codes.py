"""공식 재판예규 별표에서 사건부호표(config/legal_rules/case_codes.yaml)를 만든다(v3 D2).

근거: 「사건별 부호문자의 부여에 관한 예규」(재일 2003-1) [별표] — 국가법령정보센터 행정규칙 ID 2200000102523.
입력: scripts/fetch_official_sources.py 출력(JSON Lines, 별표 HWP 원본 raw_base64 포함) 또는 HWP 파일.

사건부호 → 사건 유형(별표 원문 그대로) → 심급. 심급은 사건 유형 이름으로 정한다.
- 상고·재항고·특별항고·비상상고 사건 → SUPREME(대법원). 근거: 민사소송법 제422조(상고), 제442조(재항고),
  제449조(특별항고), 형사소송법 제371조(상고), 제441조(비상상고) — 원문은 공식 원문 수집 결과로 확인한다.
- 항소·항고 사건 → APPELLATE, 1심·합의·단독 사건 → FIRST(둘 다 대법원·헌법재판소가 아닌 법원).
- 준항고·신청·조정·보호·감치 등 그 밖의 사건과, 여러 유형을 한 부호로 묶은 칸 → ANY(판단하지 않음).
별표에 없는 부호는 표에 넣지 않는다(unknown).

현행본(재판예규 제1812호)에 대해 국가법령정보센터가 주는 별표 파일은 개정된 쪽(가사·행정 등)뿐이다. 민사·형사 일반
부호(가합·나·다·고단·노·도 …)가 실린 첫 부분이 없다. 그래서 `--supplement` 옵션을 두었다. 이 옵션은 연혁본 별표
(행정규칙 연혁 API로 받은 원본 HWP)에서 현행 표에 없는 부호만 보충한다. 규칙은 다음과 같다.
- 현행 표에 있는 부호는 덮어쓰지 않는다.
- 받은 모든 연혁본 별표에서 사건명이 하나로 같은 부호만 넣는다. 버전마다 사건명이 다르면 넣지 않는다(unknown).
- 보충한 부호에는 `source: SUPPLEMENT`를 붙이고, 출처 버전·파일 해시·일치한 연혁본 수를 `supplement_source`에 남긴다.

    python scripts/build_case_codes.py --sources official_sources.jsonl --out config/legal_rules/case_codes.yaml \
        [--supplement 20200210]   # 보충에 쓸 연혁본의 발령일자
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CODE_RE = re.compile(r"^[가-힣]{1,4}$")


def code_pairs(tables: Iterable[List[List[str]]]) -> List[Tuple[str, str]]:
    """[사건명, 부호, 사건명, 부호] 4열 표 → (부호, 사건명). 부호 칸이 빈 행은 위 칸(병합)의 사건명을 잇는다."""
    pairs: Dict[str, str] = {}
    order: List[str] = []
    for table in tables:
        for side in range(0, max((len(r) for r in table), default=0), 2):
            last = None
            for row in table:
                name = (row[side] if side < len(row) else "").strip()
                code = (row[side + 1] if side + 1 < len(row) else "").strip().replace(" ", "")
                if code and CODE_RE.match(code) and name:
                    if code not in pairs:
                        order.append(code)
                    pairs[code] = name
                    last = code
                elif name and not code and last and pairs[last].endswith(","):
                    pairs[last] = f"{pairs[last]} {name}"  # 병합된 부호 칸: 쉼표로 이어진 사건명
                else:
                    last = None if not name else last
    return [(code, pairs[code]) for code in order]


def level_of(case_type: str) -> str:
    name = case_type.replace(" ", "")
    if "," in name or "준항고" in name or "(준)" in name:
        return "ANY"
    if re.search(r"상고|재항고|특별항고", name):
        return "SUPREME"
    if re.search(r"항소|항고", name):
        return "APPELLATE"
    if re.search(r"1심|합의사건|단독사건", name) and not re.search(r"신청|조정", name):
        return "FIRST"
    return "ANY"


def tables_from_sources(path: Path) -> Tuple[List[List[List[str]]], List[Dict[str, str]]]:
    from packages.document_engine.hwp_parser import _extract_hwp_tables

    tables, files = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("kind") == "attachment" and record.get("raw_base64"):
            tables += _extract_hwp_tables(base64.b64decode(record["raw_base64"]))
            files.append({"url": record["url"], "sha256": record.get("sha256", "")})
    return tables, files


def _records(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def history_tables(path: Path) -> Dict[str, Dict]:
    """행정규칙 연혁 경로로 받은 별표(case_code_attachment) → 발령일자별 {pairs, files}. HWP로 읽을 수 없는 파일은 건너뛴다."""
    from packages.document_engine.hwp_parser import _extract_hwp_tables

    out: Dict[str, Dict] = {}
    for record in _records(path):
        if record.get("kind") != "case_code_attachment" or not record.get("raw_base64"):
            continue
        match = re.search(r"nw=2 (\d{8})$", record.get("route") or "")
        if not match:
            continue
        try:
            tables = _extract_hwp_tables(base64.b64decode(record["raw_base64"]))
        except Exception:  # noqa: BLE001 - 2003~2005년 별표 등 HWP 5.x가 아닌 파일
            continue
        entry = out.setdefault(match.group(1), {"pairs": {}, "files": []})
        entry["pairs"].update(dict(code_pairs(tables)))
        entry["files"].append({"url": record["url"], "sha256": record.get("sha256", "")})
    return out


def version_rows(path: Path) -> Dict[str, Dict]:
    """연혁 목록(admrul_versions nw=2) → 발령일자별 행(발령번호·시행일자·행정규칙일련번호)."""
    rows: Dict[str, Dict] = {}
    for record in _records(path):
        if record.get("kind") == "admrul_versions" and str(record.get("nw")) == "2":
            for row in record.get("rows") or []:
                rows[str(row.get("발령일자"))] = row
    return rows


def _korean_date(value: str) -> str:
    return f"{value[:4]}. {int(value[4:6])}. {int(value[6:8])}."


def supplement(table: Dict, history: Dict[str, Dict], rows: Dict[str, Dict], issued: str) -> Dict:
    """연혁본(발령일자 issued) 별표에서 현행 표에 없는 부호를 보충한다. 모든 연혁본에서 사건명이 같은 부호만 넣는다."""
    chosen = history.get(issued)
    if not chosen:
        raise SystemExit(f"발령일자 {issued} 연혁본 별표가 입력에 없다")
    row = rows.get(issued) or {}
    added, conflicts = [], []
    for code, case_type in chosen["pairs"].items():
        if code in table["codes"]:
            continue
        names = {d["pairs"][code] for d in history.values() if code in d["pairs"]}
        if len(names) != 1:
            conflicts.append(code)
            continue
        agreeing = sorted(k for k, d in history.items() if code in d["pairs"])
        table["codes"][code] = {"case_type": case_type, "level": level_of(case_type), "source": "SUPPLEMENT",
                                "versions_agreeing": len(agreeing)}
        added.append(code)
    dates = sorted(history)
    table["supplement_source"] = {
        "title": "사건별 부호문자의 부여에 관한 예규(재일 2003-1) [별표] 연혁본",
        "version": (f"재판예규 제{row.get('발령번호', '?')}호, {_korean_date(issued)} 발령, "
                    f"{_korean_date(row['시행일자']) if row.get('시행일자') else '시행일 미확인'} 시행"),
        "admrul_serial": row.get("행정규칙일련번호"),
        "url": "https://www.law.go.kr/행정규칙/사건별부호문자의부여에관한예규",
        "files": chosen["files"],
        "added_codes": added,
        "excluded_conflicting_codes": conflicts,
        "consistency": (f"받은 연혁본 별표 {len(history)}개({_korean_date(dates[0])}~{_korean_date(dates[-1])} 발령)에서 "
                        f"보충 부호마다 그 부호가 실린 연혁본(부호별 versions_agreeing개) 모두에서 사건명이 같았다. "
                        f"사건명이 버전마다 다른 부호는 넣지 않았다."),
        "note": ("현행 재판예규 제1812호(2022. 7. 29. 시행)의 별표 제공 파일에 없는 민사·형사 일반 부호 등을 보충했다. "
                 "현행본에서 바뀌었는지는 현행 별표 원문으로 확인하지 못했다. 현행 표에 있는 부호는 덮어쓰지 않았다."),
    }
    return table


def build(tables, files) -> Dict:
    codes = {}
    for code, case_type in code_pairs(tables):
        codes[code] = {"case_type": case_type, "level": level_of(case_type)}
    return {
        "source": {"title": "사건별 부호문자의 부여에 관한 예규(재일 2003-1) [별표]",
                   "version": "재판예규 제1812호, 2022. 7. 29. 시행", "admrul_id": "2200000102523",
                   "url": "https://www.law.go.kr/행정규칙/사건별부호문자의부여에관한예규", "files": files},
        "coverage_note": ("국가법령정보센터가 제공하는 별표 파일 2개에 실린 부호만 담았다. 민사·형사 일반 사건부호"
                          "(별표 첫 부분)는 제공 파일에 없어 표에 넣지 않았다(unknown)."),
        "codes": codes,
    }


def main() -> int:
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--supplement", help="현행 표에 없는 부호를 보충할 연혁본의 발령일자(YYYYMMDD)")
    args = parser.parse_args()
    tables, files = tables_from_sources(args.sources)
    table = build(tables, files)
    if args.supplement:
        supplement(table, history_tables(args.sources), version_rows(args.sources), args.supplement)
        table["coverage_note"] = ("현행 별표 제공 파일 2개의 부호에, 제공 파일에 없는 부분을 연혁본 별표에서 보충했다"
                                  "(supplement_source 참조). 두 곳 모두에 없는 부호는 표에 넣지 않았다(unknown).")
    existing = yaml.safe_load(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    for key in ("constitutional_codes", "overrides", "level_basis", "constitutional_source"):
        if key in (existing or {}):
            table[key] = existing[key]
    for code, extra in ((existing or {}).get("overrides") or {}).items():
        table["codes"].setdefault(code, {}).update(extra)
    args.out.write_text(yaml.safe_dump(table, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"{len(table['codes'])}개 부호 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
