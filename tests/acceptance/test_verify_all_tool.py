"""[평가 에이전트 소관] scripts/verify_all.py의 결과 분류 시험 — strict XPASS는 실패로 세지 않고, 실제 실패는 놓치지 않는다."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("verify_all", ROOT / "scripts" / "verify_all.py")
verify_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_all)

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
 <testcase classname="tests.a" name="test_ok"/>
 <testcase classname="tests.a" name="test_skipped"><skipped message="xfail"/></testcase>
 <testcase classname="tests.a" name="test_promoted"><failure message="[XPASS(strict)] TK-00 알려진 미해결"/></testcase>
 <testcase classname="tests.b" name="test_broken"><failure message="AssertionError: 기대와 다름"/></testcase>
 <testcase classname="tests.b" name="test_crash"><error message="ImportError"/></testcase>
</testsuite></testsuites>
"""


def test_strict_xpass_is_counted_separately_and_real_failures_are_listed(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text(JUNIT, encoding="utf-8")
    r = verify_all.classify_junit(str(p))
    assert r["passed"] == 1
    assert r["strict_xpass"] == 1
    assert r["real_failures"] == ["tests.b::test_broken", "tests.b::test_crash"]


def test_unreadable_junit_is_reported_as_error_not_success(tmp_path):
    r = verify_all.classify_junit(str(tmp_path / "missing.xml"))
    assert "error" in r


def test_dirty_tree_or_missing_base_is_not_measured(tmp_path, monkeypatch, capsys):
    # 존재하지 않는 기준 커밋이면 측정하지 않고 종료 코드 2
    code = verify_all.main(["--base", "0" * 40, "--quick", "--out", str(tmp_path / "o.json")])
    assert code == 2
