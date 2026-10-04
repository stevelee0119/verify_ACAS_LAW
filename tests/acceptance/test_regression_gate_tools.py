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
    work, missing = gate.jobs()
    assert missing == [], missing
    names = {(spec.stem, text) for spec, text in work}
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


# ------------------------------------------------- 측정하지 못한 것은 통과가 아니다(독립 감사 Astra 4차 지적) ---
def test_unmeasured_flags_empty_rows_and_processing_errors_on_either_side():
    ok = ({"A": True}, [])
    assert gate.unmeasured("s", ok, ok) == []
    assert any("비어" in r for r in gate.unmeasured("s", ({}, []), ok))
    assert any("처리 오류" in r and "현재" in r for r in gate.unmeasured("s", ok, ({"A": True}, ["pipeline: boom"])))
    # 양쪽이 같은 오류를 내도 '회귀 없음'으로 보지 않는다
    both = ({"A": True}, ["pii: boom"])
    assert len(gate.unmeasured("s", both, both)) == 2


def test_pytest_counts_reads_summary_line_and_empty_collection_is_visible():
    assert gate.pytest_counts("....\n===== 3 failed, 120 passed, 2 skipped in 10.1s =====") == {
        "failed": 3, "passed": 120, "skipped": 2}
    assert gate.pytest_counts("no tests ran in 0.01s") == {}
    assert gate.pytest_counts("1 error in 0.5s") == {"error": 1}


def test_jobs_reports_specs_whose_input_file_is_missing(tmp_path, monkeypatch):
    spec = tmp_path / "probes"
    spec.mkdir()
    (spec / "x.json").write_text('{"name": "x", "input": "nope.pdf", "text_input": "nope.txt", "checks": []}', encoding="utf-8")
    monkeypatch.setattr(gate, "SPECS", spec)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    work, missing = gate.jobs()
    assert work == [] and len(missing) == 2 and all("입력 파일 없음" in m for m in missing)


# ------------------------------------------------------------------ 독립 감사 5차(c223f7b) F4: ERROR·요약 불일치 ---
CLEAN = (set(), set(), {"passed": 10}, 0)


def test_errored_tests_parses_pytest_rE_output():
    out = "ERROR tests/test_a.py::test_x - fixture 'y' not found\nERROR tests/test_b.py - collection\n== 1 error ==\n"
    assert gate.errored_tests(out) == {"tests/test_a.py::test_x", "tests/test_b.py"}


def test_passed_with_a_new_setup_error_is_not_clean():
    """기준 passed 10, 현재 passed 10 + fixture ERROR 1, 종료 코드 1, FAILED 없음 — 감사가 재현한 구멍(종료 코드 0이었다)."""
    head = (set(), {"tests/test_a.py::test_x"}, {"passed": 10, "error": 1}, 1)
    new_failures, reasons = gate.pytest_findings(CLEAN, head)
    assert new_failures == ["ERROR tests/test_a.py::test_x"]
    assert any("ERROR" in r for r in reasons)


def test_same_error_on_both_sides_is_still_unmeasured_not_clean():
    both = (set(), {"tests/test_a.py::test_x"}, {"passed": 10, "error": 1}, 1)
    new_failures, reasons = gate.pytest_findings(both, both)
    assert new_failures == []
    assert sum("ERROR" in r for r in reasons) == 2          # 기준·현재 모두 '통과가 아니다'


def test_exit_code_one_without_readable_failures_is_unmeasured():
    head = (set(), set(), {"passed": 10}, 1)
    _, reasons = gate.pytest_findings(CLEAN, head)
    assert any("읽지 못했다" in r for r in reasons)


def test_summary_failed_count_must_match_parsed_nodes():
    head = ({"tests/test_a.py::test_x"}, set(), {"passed": 8, "failed": 3}, 1)
    _, reasons = gate.pytest_findings(CLEAN, head)
    assert any("요약의 실패 3건 중 1건만" in r for r in reasons)


def test_fewer_passed_tests_without_failures_is_flagged():
    head = (set(), set(), {"passed": 7}, 0)
    new_failures, reasons = gate.pytest_findings(CLEAN, head)
    assert new_failures == [] and any("통과 건수 감소" in r for r in reasons)


def test_clean_runs_have_no_findings():
    assert gate.pytest_findings(CLEAN, (set(), set(), {"passed": 12}, 0)) == ([], [])


# ------------------------------------------------------------------ 성적표 문서별 비교(probe가 못 본 TC-06 손실) ---
def test_scorecard_diff_flags_a_document_that_dropped_even_if_the_total_is_fine():
    base = {"dev": {"TC-06": 0.357, "TC-01": 0.9}, "holdout": {"HO-01": 0.5}}
    head = {"dev": {"TC-06": 0.321, "TC-01": 1.0}, "holdout": {"HO-01": 0.5}}
    regressions, reasons = gate.scorecard_diff(base, head)
    assert regressions == ["성적표 dev/TC-06: 0.357 → 0.321"] and reasons == []


def test_scorecard_diff_missing_document_or_empty_base_is_unmeasured():
    _, missing = gate.scorecard_diff({"dev": {"TC-06": 0.3}}, {"dev": {}})
    assert any("TC-06" in r for r in missing)
    _, empty = gate.scorecard_diff({}, {"dev": {"TC-06": 0.3}})
    assert any("값이 없다" in r for r in empty)


def test_scorecard_diff_ignores_improvements_and_new_documents():
    regressions, reasons = gate.scorecard_diff({"dev": {"TC-06": 0.3}}, {"dev": {"TC-06": 0.4, "TC-99": 0.1}})
    assert regressions == [] and reasons == []


# ------------------------------------------------------------------ 독립 감사 5차 F5: 평가 자료 표식 분기 ---
def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   env={**__import__("os").environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def test_fixture_tokens_include_evaluation_document_marker_prefixes():
    markers = hard.fixture_tokens()["marker"]
    assert "TC-" in markers and "HO-" in markers


def test_product_code_that_recognises_evaluation_document_markers_is_a_strong_signal(tmp_path):
    """제품 코드가 시험 문서의 표식(`TC-\\d+`, `HO-\\d+`, '홀드아웃용')을 알아보는 분기는 값 토큰이 아니어도 강한 신호다."""
    (tmp_path / "tests" / "fixtures" / "holdout").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "holdout" / "HO-01.pdf").write_bytes(b"%PDF")
    (tmp_path / "tests" / "fixtures" / "probes").mkdir(parents=True)
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "x.py").write_text("X = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "packages" / "x.py").write_text(
        'import re\nX = 1\nFOOTER = re.compile(r"^\\s*(?:HO-\\d+|홀드아웃용).*$")\n# HO-01 설명 주석은 센다 아니다\n', encoding="utf-8")
    result = hard.scan("HEAD", tmp_path)
    kinds = {(item["kind"], item["token"]) for item in result["hard"]}
    assert ("eval_marker", "HO-\\d") in kinds and ("eval_marker", "홀드아웃용") in kinds


def test_explanatory_mention_of_a_document_id_is_not_flagged(tmp_path):
    (tmp_path / "tests" / "fixtures" / "holdout").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "holdout" / "HO-01.pdf").write_bytes(b"%PDF")
    (tmp_path / "tests" / "fixtures" / "probes").mkdir(parents=True)
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "x.py").write_text("X = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "packages" / "x.py").write_text('X = 1\nNOTE = "HO-01에서 확인한 회귀를 막는다"\n', encoding="utf-8")
    assert hard.scan("HEAD", tmp_path)["hard"] == []


def test_run_pytest_reads_the_summary_even_when_the_repo_config_adds_quiet(tmp_path):
    """저장소 pytest.ini의 `addopts = -q`와 게이트의 `-q`가 겹치면 요약 줄이 사라져 개수를 못 읽었다(평가 측 점검에서 발견)."""
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_a():\n    assert True\n\ndef test_b():\n    assert True\n", encoding="utf-8")
    failed, errored, counts, rc = gate.run_pytest(tmp_path)
    assert counts.get("passed") == 2 and rc == 0 and not failed and not errored


# ------------------------------------------------- 기준 쪽 캐시·현재 성적표 재사용(2026-10-04) ---
def test_probe_cache_key_changes_with_base_tool_env_and_spec(tmp_path, monkeypatch):
    spec = tmp_path / "s.json"
    spec.write_text('{"checks": [], "input": "missing.pdf"}', encoding="utf-8")
    k = gate.probe_cache_key("a" * 40, spec, False, "tool", "env")
    assert k == gate.probe_cache_key("a" * 40, spec, False, "tool", "env")
    assert k != gate.probe_cache_key("b" * 40, spec, False, "tool", "env")
    assert k != gate.probe_cache_key("a" * 40, spec, True, "tool", "env")
    assert k != gate.probe_cache_key("a" * 40, spec, False, "tool2", "env")
    assert k != gate.probe_cache_key("a" * 40, spec, False, "tool", "env2")
    spec.write_text('{"checks": [1], "input": "missing.pdf"}', encoding="utf-8")
    assert k != gate.probe_cache_key("a" * 40, spec, False, "tool", "env")


def test_cache_roundtrip_and_missing_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "CACHE_DIR", tmp_path / "cache")
    assert gate.cache_get("nope") is None
    gate.cache_put("k1", {"rows": {"a": True}, "errors": []}, "label")
    assert gate.cache_get("k1") == {"rows": {"a": True}, "errors": []}


def test_tool_fingerprint_tracks_measurement_scripts():
    assert gate.tool_fingerprint() == gate.tool_fingerprint()
    assert len(gate.env_fingerprint()) == 64


def test_scorecard_load_reads_the_same_shape_as_a_fresh_run(tmp_path):
    card = tmp_path / "scorecard.json"
    card.write_text('{"sets": {"dev": {"per_document": {"TC-01": 0.5, "TC-02": null}}}}', encoding="utf-8")
    assert gate.scorecard_load(card) == {"dev": {"TC-01": 0.5}}
