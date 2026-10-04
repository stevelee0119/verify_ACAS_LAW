"""[평가 에이전트 소관] scripts/ci_failed_tests.py 자체 시험 — pytest -rfE 출력에서 실패·오류 시험을 모으고,
워크플로 명령 예약 문자를 바꾸며, 결과와 관계없이 종료 코드 0이다."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ci_failed_tests", ROOT / "scripts" / "ci_failed_tests.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

OUTPUT = """..F.
=========================== short test summary info ============================
FAILED tests/test_a.py::test_one - KeyError: 'x'
ERROR tests/test_b.py::test_two - fixture 'db' not found
FAILED tests/test_a.py::test_one - KeyError: 'x'
1 failed, 1 error, 2 passed in 0.10s
"""


def test_collects_failed_and_error_lines_once_per_file(tmp_path):
    p = tmp_path / "pytest-sqlite.txt"
    p.write_text(OUTPUT, encoding="utf-8")
    items = tool.failures([str(p), str(tmp_path / "missing.txt")])
    assert items == [("pytest-sqlite.txt", "FAILED tests/test_a.py::test_one"),
                     ("pytest-sqlite.txt", "ERROR tests/test_b.py::test_two")]


def test_annotation_escaping_and_summary(tmp_path, monkeypatch, capsys):
    p = tmp_path / "out.txt"
    p.write_text("FAILED tests/test_c.py::test_p[50%-a,b]\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert tool.main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "::error title=out.txt::FAILED tests/test_c.py::test_p[50%25-a,b]" in out
    assert "실패 시험 1건" in summary.read_text(encoding="utf-8")
    assert tool._escape_property("a:b,c") == "a%3Ab%2Cc"


def test_no_failures_still_exits_zero(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    p = tmp_path / "ok.txt"
    p.write_text("4 passed in 0.1s\n", encoding="utf-8")
    assert tool.main([str(p)]) == 0
