"""README의 '버전별 변경 내역' 표를 docs/releases.json에서 다시 만든다.

- 표는 README의 `<!-- RELEASES:START -->`와 `<!-- RELEASES:END -->` 사이에 쓴다(최신 버전이 위).
- 프로그램 버전(packages/common/config.py)이 releases.json에 없으면, 마지막 커밋 제목으로 항목을 추가한다.
  버전을 올리고 기록을 빠뜨려도 README 표가 비지 않게 하기 위해서다.
- `--check`: 바꿀 것이 있으면 종료 코드 1(파일은 고치지 않음).

사용: python scripts/update_readme.py [--check]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
RELEASES = ROOT / "docs" / "releases.json"
CONFIG = ROOT / "packages" / "common" / "config.py"
START, END = "<!-- RELEASES:START -->", "<!-- RELEASES:END -->"
TAG_RE = re.compile(r"\s*\[(?:run-eval|fetch-sources|skip ci)\]")


def current_version() -> str:
    match = re.search(r'^\s*version:\s*str\s*=\s*"([^"]+)"', CONFIG.read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit("packages/common/config.py에서 버전을 찾지 못했습니다")
    return match.group(1)


def _version_key(version: str):
    return tuple(int(part) if part.isdigit() else 0 for part in re.split(r"[.\-]", version))


def _last_commit_subject() -> str:
    try:
        subject = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=ROOT, capture_output=True,
                                 text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "변경 내역 기록 없음"
    return TAG_RE.sub("", subject).strip() or "변경 내역 기록 없음"


def load_releases(add_missing: bool = True) -> list:
    releases = json.loads(RELEASES.read_text(encoding="utf-8"))
    version = current_version()
    if add_missing and version not in {item["version"] for item in releases}:
        releases.append({"version": version, "date": date.today().isoformat(), "changes": [_last_commit_subject()]})
    return sorted(releases, key=lambda item: _version_key(item["version"]))


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_table(releases: list) -> str:
    lines = ["| 버전 | 날짜 | 주요 변경 사항 |", "|---|---|---|"]
    for item in reversed(releases):
        changes = "<br>".join(f"• {_cell(change)}" for change in item["changes"])
        lines.append(f"| {item['version']} | {item['date']} | {changes} |")
    return "\n".join(lines)


def updated_readme(releases: list) -> str:
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"README에 {START}·{END} 표시가 없습니다")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    note = ("\n\n> 이 표는 `docs/releases.json`에서 자동으로 만들어집니다(`python scripts/update_readme.py`). "
            "푸시하면 CI가 README를 다시 확인해 갱신합니다.\n\n")
    return f"{head}{START}{note}{render_table(releases)}\n\n{END}{tail}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="바꿀 것이 있으면 1로 끝낸다")
    args = parser.parse_args()
    releases = load_releases()
    readme = updated_readme(releases)
    releases_text = json.dumps(releases, ensure_ascii=False, indent=2) + "\n"
    changed = [path for path, content in ((README, readme), (RELEASES, releases_text))
               if path.read_text(encoding="utf-8") != content]
    if args.check:
        for path in changed:
            print(f"갱신 필요: {path.relative_to(ROOT)}")
        return 1 if changed else 0
    for path, content in ((README, readme), (RELEASES, releases_text)):
        if path in changed:
            path.write_text(content, encoding="utf-8")
            print(f"갱신: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
