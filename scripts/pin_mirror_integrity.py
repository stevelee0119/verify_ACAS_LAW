"""준비서면 시험용 미러(tests/fixtures/prepared_brief_mirror)의 항목별 SHA-256을 `integrity.json`에 기록한다(평가 에이전트 도구).

목적: 시험이 항목의 일부 필드만 보던 탓에 판시 본문·공식 링크 문서 번호·조문 본문이 바뀌어도 통과한다는 6차 독립 감사 지적
(2026-10-03)에 대한 보완이다. 항목 전체의 정규화한 JSON을 해시로 고정해 어떤 필드가 바뀌어도 시험이 실패하게 한다.
이 파일은 자료를 **정당한 사유로 고칠 때만** 다시 만들며, 그때는 SOURCES.md에 사유와 출처를 함께 적는다(둘 다 보호 경로).

사용: python scripts/pin_mirror_integrity.py            (integrity.json 다시 쓰기)
      python scripts/pin_mirror_integrity.py --check    (기록과 현재 자료가 같은지만 확인, 다르면 종료 코드 1)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "prepared_brief_mirror"


def canonical_hash(entry: dict) -> str:
    text = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def entry_hashes(root: Path = ROOT) -> dict:
    laws = json.loads((root / "laws.json").read_text(encoding="utf-8"))
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    return {
        "laws": {f"{row['law_name']}|{row['article']}|{row['effective_from']}": canonical_hash(row) for row in laws},
        "cases": {row["case_number"]: canonical_hash(row) for row in cases},
    }


def problems(root: Path = ROOT) -> list:
    """기록(integrity.json)과 현재 자료의 차이를 사람이 읽는 문장 목록으로 돌려준다. 비어 있으면 같다."""
    pinned = json.loads((root / "integrity.json").read_text(encoding="utf-8"))
    current = entry_hashes(root)
    found = []
    for group in ("laws", "cases"):
        for key, digest in pinned.get(group, {}).items():
            if key not in current[group]:
                found.append(f"{group}: 기록에 있는 항목이 자료에 없다 — {key}")
            elif current[group][key] != digest:
                found.append(f"{group}: 항목 내용이 기록과 다르다 — {key}")
        for key in current[group]:
            if key not in pinned.get(group, {}):
                found.append(f"{group}: 기록에 없는 항목이 자료에 있다 — {key}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        issues = problems()
        for issue in issues:
            print(issue)
        print("일치" if not issues else f"불일치 {len(issues)}건")
        return 1 if issues else 0
    (ROOT / "integrity.json").write_text(json.dumps(entry_hashes(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("integrity.json 기록:", {k: len(v) for k, v in entry_hashes().items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
