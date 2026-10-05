"""scripts/check_test_edits.py 자체 시험: 기존 시험 삭제·skip/xfail 추가를 잡고, 새 시험 추가와 평가 측 커밋은 통과시킨다."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_test_edits.py"

BASE_TESTS = '''import pytest


def test_keeps_asserting():
    assert 1 == 1
    assert 2 == 2


def test_will_be_removed():
    assert True
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: Path, tests: str, agent: str, msg: str = "c") -> None:
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_x.py").write_text(tests, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"{msg}\n\nAgent: {agent}")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, BASE_TESTS, "implementer", "base")
    return tmp_path


def _run(repo: Path, base: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--base", base], cwd=repo, capture_output=True, text=True)


def test_removed_test_fails(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, BASE_TESTS.replace("def test_will_be_removed():\n    assert True\n", ""), "implementer")
    r = _run(repo, base)
    assert r.returncode == 1 and "test_will_be_removed" in r.stdout


def test_newly_xfailed_test_fails(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, BASE_TESTS.replace("def test_keeps_asserting", "@pytest.mark.xfail\ndef test_keeps_asserting"), "implementer")
    r = _run(repo, base)
    assert r.returncode == 1 and "xfail" in r.stdout


def test_added_tests_and_weakened_assert_only_warn(repo):
    base = _git(repo, "rev-parse", "HEAD")
    changed = BASE_TESTS.replace("    assert 2 == 2\n", "") + "\n\ndef test_new():\n    assert True\n"
    _commit(repo, changed, "implementer")
    r = _run(repo, base)
    assert r.returncode == 0 and "경고" in r.stdout


def test_evaluator_only_range_is_skipped(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, BASE_TESTS.replace("def test_will_be_removed():\n    assert True\n", ""), "evaluator")
    r = _run(repo, base)
    assert r.returncode == 0 and "건너뜀" in r.stdout


def _write_approvals(repo: Path, agent: str) -> None:
    (repo / "docs" / "scorecards").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "scorecards" / "approved_test_marks.json").write_text(
        '{"approved": [{"test": "tests/test_x.py::test_keeps_asserting", "mark": "xfail"}]}', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"approvals\n\nAgent: {agent}")


def test_evaluator_approved_mark_passes(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _write_approvals(repo, "evaluator")
    _commit(repo, BASE_TESTS.replace("def test_keeps_asserting", "@pytest.mark.xfail\ndef test_keeps_asserting"), "implementer")
    r = _run(repo, base)
    assert r.returncode == 0 and "승인" in r.stdout


def test_approval_list_written_by_implementer_is_ignored(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _write_approvals(repo, "implementer")
    _commit(repo, BASE_TESTS.replace("def test_keeps_asserting", "@pytest.mark.xfail\ndef test_keeps_asserting"), "implementer")
    r = _run(repo, base)
    assert r.returncode == 1 and "xfail" in r.stdout


def test_approval_covers_only_listed_test(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _write_approvals(repo, "evaluator")
    _commit(repo, BASE_TESTS.replace("def test_will_be_removed", "@pytest.mark.xfail\ndef test_will_be_removed"), "implementer")
    r = _run(repo, base)
    assert r.returncode == 1 and "test_will_be_removed" in r.stdout


def _write_delete_approval(repo: Path, agent: str) -> None:
    (repo / "docs" / "scorecards").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "scorecards" / "approved_test_marks.json").write_text(
        '{"approved": [{"test": "tests/test_x.py::test_will_be_removed", "mark": "delete"}]}', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"approvals\n\nAgent: {agent}")


def test_evaluator_approved_deletion_passes_and_only_for_listed_test(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _write_delete_approval(repo, "evaluator")
    _commit(repo, BASE_TESTS.replace("def test_will_be_removed():\n    assert True\n", ""), "implementer")
    r = _run(repo, base)
    assert r.returncode == 0 and "(삭제)" in r.stdout
    base2 = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "import pytest\n", "implementer")
    r2 = _run(repo, base2)
    assert r2.returncode == 1 and "test_keeps_asserting" in r2.stdout


def test_deletion_approval_written_by_implementer_is_ignored(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _write_delete_approval(repo, "implementer")
    _commit(repo, BASE_TESTS.replace("def test_will_be_removed():\n    assert True\n", ""), "implementer")
    r = _run(repo, base)
    assert r.returncode == 1 and "test_will_be_removed" in r.stdout


def test_pure_rename_is_reported_not_failed(repo):
    """본문·표시가 같고 이름만 바뀐 시험은 삭제가 아니다(2026-10-05 PR #17 push 비교 거짓 실패)."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, BASE_TESTS.replace("def test_will_be_removed():", "def test_renamed():"), "implementer")
    r = _run(repo, base)
    assert r.returncode == 0 and "이름 변경" in r.stdout and "test_will_be_removed → test_renamed" in r.stdout


def test_rename_with_weaker_body_still_fails(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, BASE_TESTS.replace("def test_keeps_asserting():\n    assert 1 == 1\n    assert 2 == 2\n",
                                     "def test_other_name():\n    assert 1 == 1\n"), "implementer")
    r = _run(repo, base)
    assert r.returncode == 1 and "test_keeps_asserting" in r.stdout


def test_rename_that_adds_xfail_still_fails(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, BASE_TESTS.replace("def test_will_be_removed():", "@pytest.mark.xfail\ndef test_renamed():"), "implementer")
    r = _run(repo, base)
    assert r.returncode == 1 and "test_will_be_removed" in r.stdout
