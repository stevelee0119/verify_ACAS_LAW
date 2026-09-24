"""공식 재판예규 별표에서 사건부호표(config/legal_rules/case_codes.yaml)를 만든다(v3 D2).

근거: 「사건별 부호문자의 부여에 관한 예규」(재일 2003-1) [별표] — 국가법령정보센터 행정규칙 ID 2200000102523.
입력: scripts/fetch_official_sources.py 출력(JSON Lines, 별표 HWP 원본 raw_base64 포함) 또는 HWP 파일.

사건부호 → 사건 유형(별표 원문 그대로) → 심급. 심급은 사건 유형 이름으로 정한다.
- 상고·재항고·특별항고·비상상고 사건 → SUPREME(대법원). 근거: 민사소송법 제422조(상고), 제442조(재항고),
  제449조(특별항고), 형사소송법 제371조(상고), 제441조(비상상고) — 원문은 공식 원문 수집 결과로 확인한다.
- 항소·항고 사건 → APPELLATE, 1심·합의·단독 사건 → FIRST(둘 다 대법원·헌법재판소가 아닌 법원).
- 준항고·신청·조정·보호·감치 등 그 밖의 사건과, 여러 유형을 한 부호로 묶은 칸 → ANY(판단하지 않음).
별표에 없는 부호는 표에 넣지 않는다(unknown).

    python scripts/build_case_codes.py --sources official_sources.jsonl --out config/legal_rules/case_codes.yaml
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
    args = parser.parse_args()
    tables, files = tables_from_sources(args.sources)
    table = build(tables, files)
    existing = yaml.safe_load(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    for key in ("constitutional_codes", "overrides", "level_basis"):
        if key in (existing or {}):
            table[key] = existing[key]
    for code, extra in ((existing or {}).get("overrides") or {}).items():
        table["codes"].setdefault(code, {}).update(extra)
    args.out.write_text(yaml.safe_dump(table, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"{len(table['codes'])}개 부호 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
