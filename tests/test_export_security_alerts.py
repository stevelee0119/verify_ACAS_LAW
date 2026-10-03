"""평가 도구 `scripts/export_security_alerts.py`의 요약 로직 시험(평가 에이전트).

입력은 GitHub REST 문서의 코드 스캔 경고 응답 형식(`rule`·`most_recent_instance.location`)을 따른 **합성 자료**이며
실제 경고가 아니다. 네트워크를 쓰지 않는다.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "export_security_alerts", Path(__file__).resolve().parents[1] / "scripts" / "export_security_alerts.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def _alert(number, rule_id, level, path, line, severity="warning"):
    return {"number": number, "state": "open", "html_url": f"https://example.invalid/{number}",
            "created_at": "2026-01-01T00:00:00Z",
            "rule": {"id": rule_id, "severity": severity, "security_severity_level": level, "description": rule_id},
            "most_recent_instance": {"ref": "refs/heads/main", "message": {"text": "합성 메시지"},
                                     "location": {"path": path, "start_line": line, "end_line": line}}}


SAMPLE = [
    _alert(1, "rule/b", "medium", "b.py", 9), _alert(2, "rule/a", "high", "z.py", 3),
    _alert(3, "rule/a", "high", "a.py", 20), _alert(4, "rule/a", "high", "a.py", 5),
    _alert(5, "rule/c", None, "c.js", 1, severity="note"),
]


def test_groups_by_rule_and_orders_by_severity_then_rule():
    summary = tool.summarise(SAMPLE)
    assert summary["total"] == 5
    assert [g["rule_id"] for g in summary["rules"]] == ["rule/a", "rule/b", "rule/c"]
    assert [g["count"] for g in summary["rules"]] == [3, 1, 1]
    assert summary["by_severity"] == {"high": 3, "medium": 1, "note": 1}


def test_locations_are_sorted_and_complete():
    group = tool.summarise(SAMPLE)["rules"][0]
    assert [(loc["path"], loc["start_line"]) for loc in group["locations"]] == [("a.py", 5), ("a.py", 20), ("z.py", 3)]
    assert all(loc["alert_number"] for loc in group["locations"])


def test_markdown_has_counts_but_no_file_paths():
    text = tool.markdown(tool.summarise(SAMPLE))
    assert "합계 **5건**" in text and "rule/a" in text
    for path in ("a.py", "z.py", "b.py", "c.js"):
        assert path not in text, f"요약에 파일 경로가 실렸다: {path}"


def test_empty_alert_list():
    summary = tool.summarise([])
    assert summary == {"total": 0, "by_severity": {}, "rules": []}
    assert "열린 경고가 없다" in tool.markdown(summary)


def test_cli_from_file_writes_json_and_summary(tmp_path, monkeypatch, capsys):
    source = tmp_path / "alerts.json"
    source.write_text(json.dumps(SAMPLE), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["export", "--from-file", str(source), "--out-dir", str(tmp_path / "out")])
    assert tool.main() == 0
    written = json.loads((tmp_path / "out" / "code_scanning_alerts.json").read_text(encoding="utf-8"))
    assert written["total"] == 5 and (tmp_path / "out" / "summary.md").exists()


def test_location_lines_and_print_option(tmp_path, monkeypatch, capsys):
    summary = tool.summarise(SAMPLE)
    lines = tool.location_lines(summary)
    assert lines[0] == "rule/a | a.py:5 | #4" and len(lines) == 5
    saved = tmp_path / "s.json"
    saved.write_text(json.dumps(summary), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["export", "--print-locations", str(saved)])
    assert tool.main() == 0
    assert "rule/b | b.py:9 | #1" in capsys.readouterr().out
