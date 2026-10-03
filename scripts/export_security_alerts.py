"""코드 스캔(CodeQL) 열린 경고를 규칙·파일·줄 단위로 내보낸다(평가 에이전트 점검 도구, 읽기 전용).

평가 세션의 GitHub 연동에는 Code scanning alerts 읽기 권한이 없어 경고 목록을 읽지 못한다.
워크플로의 `GITHUB_TOKEN`(`security-events: read`)으로 같은 목록을 읽어 JSON·요약으로 남기면
평가 측이 Actions 아티팩트로 가져올 수 있다. 설정을 바꾸지 않는다. 게이트가 아니라 측정 도구다.

사용:
  python scripts/export_security_alerts.py --repo OWNER/REPO --out-dir out      (환경변수 GITHUB_TOKEN 필요)
  python scripts/export_security_alerts.py --from-file alerts.json --out-dir out (저장된 응답으로 요약만 다시 만들기)

  python scripts/export_security_alerts.py --print-locations out/code_scanning_alerts.json  (저장된 요약의 위치를 한 줄씩 출력)

산출: `<out-dir>/code_scanning_alerts.json`(규칙별 묶음과 위치 전체), `<out-dir>/summary.md`(규칙별 건수만).
요약에는 파일 경로를 싣지 않는다(위치는 아티팩트에 둔다). 아티팩트는 평가 세션의 도구로 내려받을 수 없는 경우가 있어,
워크플로를 수동 실행하며 `show_locations`를 켠 경우에만 `--print-locations`로 로그에 위치를 남긴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

API = "https://api.github.com"
PER_PAGE = 100
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "error": 1, "warning": 2, "note": 3}


def fetch_alerts(repo: str, token: str, state: str = "open") -> list[dict[str, Any]]:
    """열린 코드 스캔 경고를 모두 가져온다(기본 브랜치 기준). 접근이 거부되면 사유를 담아 종료한다."""
    alerts: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{API}/repos/{repo}/code-scanning/alerts?state={state}&per_page={PER_PAGE}&page={page}"
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "acas-law-security-export"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                batch = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"코드 스캔 경고를 읽지 못했다: HTTP {exc.code} {body}") from exc
        alerts.extend(batch)
        if len(batch) < PER_PAGE:
            return alerts
        page += 1


def _location(alert: dict[str, Any]) -> dict[str, Any]:
    instance = alert.get("most_recent_instance") or {}
    location = instance.get("location") or {}
    return {"path": location.get("path"), "start_line": location.get("start_line"),
            "end_line": location.get("end_line"), "ref": instance.get("ref"),
            "message": ((instance.get("message") or {}).get("text") or "")[:300],
            "alert_number": alert.get("number"), "html_url": alert.get("html_url"),
            "created_at": alert.get("created_at")}


def summarise(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """규칙별로 묶는다. 규칙의 심각도는 보안 심각도(security_severity_level)를 우선하고 없으면 규칙 심각도를 쓴다."""
    groups: dict[str, dict[str, Any]] = {}
    locations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in alerts:
        rule = alert.get("rule") or {}
        rule_id = rule.get("id") or "(규칙 없음)"
        severity = rule.get("security_severity_level") or rule.get("severity") or "unknown"
        group = groups.setdefault(rule_id, {"rule_id": rule_id, "name": rule.get("description") or rule.get("name"),
                                            "severity": severity, "count": 0})
        group["count"] += 1
        locations[rule_id].append(_location(alert))
    rules = sorted(groups.values(), key=lambda g: (SEVERITY_ORDER.get(str(g["severity"]).lower(), 9), g["rule_id"]))
    for group in rules:
        group["locations"] = sorted(locations[group["rule_id"]],
                                    key=lambda loc: (loc["path"] or "", loc["start_line"] or 0))
    by_severity: dict[str, int] = defaultdict(int)
    for group in rules:
        by_severity[str(group["severity"])] += group["count"]
    return {"total": len(alerts), "by_severity": dict(by_severity), "rules": rules}


def markdown(summary: dict[str, Any]) -> str:
    lines = ["## 코드 스캔 열린 경고(기본 브랜치)", ""]
    if summary["total"]:
        lines.append(f"합계 **{summary['total']}건** — "
                     + ", ".join(f"{severity} {count}" for severity, count in summary["by_severity"].items()))
    else:
        lines.append("열린 경고가 없다.")
    lines.append("")
    if summary["rules"]:
        lines += ["| 규칙 | 심각도 | 건수 |", "|---|---|---|"]
        lines += [f"| {g['name'] or g['rule_id']} (`{g['rule_id']}`) | {g['severity']} | {g['count']} |" for g in summary["rules"]]
        lines += ["", "파일·줄은 실행 요약에 싣지 않았다. 아티팩트 `security-alerts`의 `code_scanning_alerts.json`에 있다."]
    return "\n".join(lines) + "\n"


def location_lines(summary: dict[str, Any]) -> list[str]:
    """규칙별 위치를 `규칙 | 파일:줄 | #경고번호` 한 줄씩으로 펼친다."""
    lines = []
    for group in summary["rules"]:
        for loc in group["locations"]:
            where = f"{loc['path']}:{loc['start_line']}" if loc["start_line"] else str(loc["path"])
            lines.append(f"{group['rule_id']} | {where} | #{loc['alert_number']}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print-locations", metavar="SUMMARY_JSON",
                        help="저장된 code_scanning_alerts.json의 위치를 한 줄씩 출력하고 끝낸다(네트워크 없음)")
    parser.add_argument("--repo", help="OWNER/REPO (기본: 환경변수 GITHUB_REPOSITORY)")
    parser.add_argument("--out-dir", default="out")
    parser.add_argument("--from-file", help="이미 저장한 경고 응답(JSON 배열)으로 요약만 만든다")
    args = parser.parse_args()
    if args.print_locations:
        saved = json.loads(Path(args.print_locations).read_text(encoding="utf-8"))
        print("\n".join(location_lines(saved)))
        return 0
    if args.from_file:
        alerts = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
    else:
        repo = args.repo or os.environ.get("GITHUB_REPOSITORY")
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not repo or not token:
            raise SystemExit("--repo(또는 GITHUB_REPOSITORY)와 GITHUB_TOKEN이 필요하다")
        alerts = fetch_alerts(repo, token)
    summary = summarise(alerts)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "code_scanning_alerts.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(markdown(summary), encoding="utf-8")
    print(markdown(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
