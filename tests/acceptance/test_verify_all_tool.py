"""[평가 에이전트 소관] scripts/verify_all.py의 결과 분류 시험 — strict XPASS는 실패로 세지 않고, 실제 실패·수집 오류는 놓치지 않는다."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("verify_all", ROOT / "scripts" / "verify_all.py")
verify_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_all)

RECORDS = [
    {"nodeid": "tests/a.py::test_ok", "when": "call", "outcome": "passed", "strict_xpass": False},
    {"nodeid": "tests/a.py::test_xfail", "when": "call", "outcome": "skipped", "strict_xpass": False},
    {"nodeid": "tests/a.py::test_promoted", "when": "call", "outcome": "failed", "strict_xpass": True},
    {"nodeid": "tests/b.py::test_broken", "when": "call", "outcome": "failed", "strict_xpass": False},
    {"nodeid": "tests/b.py::test_fixture", "when": "setup", "outcome": "failed", "strict_xpass": False},
    {"nodeid": "tests/c.py", "when": "collect", "outcome": "failed", "strict_xpass": False},
]


def test_strict_xpass_is_counted_separately_and_real_failures_are_listed(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in RECORDS), encoding="utf-8")
    r = verify_all.classify_results(str(p))
    assert r["passed"] == 1
    assert r["strict_xpass"] == 1
    assert r["real_failures"] == ["tests/b.py::test_broken (call)", "tests/b.py::test_fixture (setup)",
                                  "tests/c.py (collect)"]


def test_missing_or_empty_results_are_errors_not_success(tmp_path):
    assert "error" in verify_all.classify_results(str(tmp_path / "missing.jsonl"))
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert "error" in verify_all.classify_results(str(empty))


def test_option_like_or_unknown_base_is_not_measured(tmp_path):
    out = str(tmp_path / "o.json")
    assert verify_all.main(["--base=--output=x", "--quick", "--out", out]) == 2
    assert verify_all.main(["--base", "0" * 40, "--quick", "--out", out]) == 2
