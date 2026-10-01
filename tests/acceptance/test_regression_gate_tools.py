"""회귀 게이트·하드코딩 변경분 점검 도구 자체 시험(평가 에이전트 소관, 보호 경로).

측정 도구가 틀리면 게이트가 틀린다. 순수 함수의 동작과, 2차 구현(cf7c739 이후)에서 실제로 있었던 조문 키 규칙이 걸리는지를 본다.
이력이 필요한 시험은 이력이 없는 얕은 복제본(CI 기본 설정)이면 건너뛴다(CI 작업은 fetch-depth 0이라 건너뛰지 않는다).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


gate = _load("regression_gate")
hard = _load("check_hardcoding_diff")


def _has_commit(sha: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT, capture_output=True).returncode == 0


# --------------------------------------------------------------------------- regression_gate ---
def test_diff_rows_reports_only_pass_to_fail_as_regression():
    regressions, improved = gate.diff_rows({"A": True, "B": True, "C": False, "D": False},
                                           {"A": True, "B": False, "C": True, "D": False})
    assert regressions == ["B"] and improved == ["C"]


def test_diff_rows_treats_missing_head_item_as_failure_and_ignores_new_items():
    regressions, improved = gate.diff_rows({"A": True}, {"NEW": True})
    assert regressions == ["A"] and improved == []


def test_failed_tests_parses_pytest_rf_output():
    out = "FAILED tests/test_a.py::test_x - assert 1\nFAILED tests/test_b.py::test_y[param]\n3 failed, 10 passed"
    assert gate.failed_tests(out) == {"tests/test_a.py::test_x", "tests/test_b.py::test_y[param]"}


def test_jobs_cover_every_dev_spec_and_skip_online_specs():
    names = {(spec.stem, text) for spec, text in gate.jobs()}
    assert ("case9_state_compensation", False) in names and ("variant2_food_license", True) in names
    assert not any(stem.endswith("_online") for stem, _ in names)


# ---------------------------------------------------------------------- check_hardcoding_diff ---
@pytest.mark.parametrize("text, expected", [
    (r"헌법\s*제\s*(?:119|34)\s*조", {"119", "34"}),
    ("제14조의2", {"14의2"}),
    ("제 76 조의 3", {"76의3"}),
    ("2025. 9. 1. 개정", set()),
])
def test_article_numbers_reads_regex_fragments_and_branch_articles(text, expected):
    assert hard.article_numbers(text) == expected


def test_added_lines_skips_python_comments_and_tracks_line_numbers():
    diff = ("--- a/packages/a.py\n+++ b/packages/a.py\n@@ -1,0 +5,3 @@\n+# 주석\n+PAT = 'x'\n+ONE = 1\n"
            "--- a/config/r.json\n+++ b/config/r.json\n@@ -2 +2 @@\n+\"pattern\": \"y\"\n")
    assert hard.added_lines(diff) == [("packages/a.py", 6, "PAT = 'x'"), ("packages/a.py", 7, "ONE = 1"),
                                      ("config/r.json", 2, '"pattern": "y"')]


def test_json_items_flattens_lists_under_their_field_name():
    items = hard.json_items('{"a": {"articles": ["10", "23"], "pattern": "p"}}')
    assert ("articles", "10") in items and ("articles", "23") in items and ("pattern", "p") in items


def test_fixture_tokens_include_spec_terms_and_article_numbers_of_dev_documents():
    tokens = hard.fixture_tokens()
    assert "203" in tokens["article"] and "119" in tokens["article"]
    assert "사정변경" in tokens["spec_term"]


@pytest.mark.skipif(not _has_commit("cf7c739"), reason="이력이 없는 얕은 복제본")
def test_round2_article_keyed_rules_are_flagged_against_cf7c739():
    """2차 구현이 설정에 넣은 조문 키 규칙(민법 제203조·헌법 제119조·제34조)은 강한 신호로 걸려야 한다."""
    result = hard.scan("cf7c739")
    flagged = {(h["file"], h["token"]) for h in result["hard"] if h["kind"] == "article_key"}
    assert ("config/legal_rules/rules.json", "제203조") in flagged
    assert ("config/legal_rules/rules.json", "제119조") in flagged
    assert ("config/legal_rules/rules.json", "제34조") in flagged
