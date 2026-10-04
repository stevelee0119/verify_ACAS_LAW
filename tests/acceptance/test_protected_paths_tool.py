"""[평가 에이전트 소관] scripts/check_protected_paths.py 자체 시험 — 평가 측이 아닌 커밋의 보호 경로 변경을 잡고,
평가 측 커밋·평가 측 승인·평가 측 브랜치 병합은 통과시킨다. 병합 해결로 보호 경로를 바꾼 경우도 잡는다."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_protected_paths.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo,
                          capture_output=True, text=True, check=True).stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, files: dict, agent: str, msg: str = "c") -> str:
    for rel, text in files.items():
        _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"{msg}\n\nAgent: {agent}")
    return _git(repo, "rev-parse", "HEAD")


def _check(repo: Path, base: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--base", base], cwd=repo, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, {"tests/acceptance/test_a.py": "def test_a():\n    assert True\n",
                       "packages/x.py": "X = 1\n", "docs/scorecards/baseline.json": "{}\n"}, "evaluator", "base")
    return tmp_path


def test_product_only_change_passes(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"packages/x.py": "X = 2\n"}, "implementer")
    r = _check(repo, base)
    assert r.returncode == 0, r.stdout
    assert "바뀐 보호 경로 없음" in r.stdout


def test_implementer_change_to_protected_path_fails(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"tests/acceptance/test_a.py": "def test_a():\n    pass\n"}, "implementer")
    r = _check(repo, base)
    assert r.returncode == 1
    assert "[보호 경로 변경] tests/acceptance/test_a.py" in r.stdout


def test_ci_workflow_change_by_implementer_fails(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {".github/workflows/ci.yml": "name: CI\n"}, "implementer")
    assert _check(repo, base).returncode == 1


def test_evaluator_commit_passes(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"docs/scorecards/baseline.json": "{\"a\": 1}\n"}, "evaluator")
    r = _check(repo, base)
    assert r.returncode == 0, r.stdout
    assert "[평가 측]" in r.stdout


def test_merging_an_evaluator_branch_passes(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "evaluator")
    _commit(repo, {"tests/acceptance/test_b.py": "def test_b():\n    assert True\n"}, "evaluator")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, {"packages/x.py": "X = 3\n"}, "implementer")
    _git(repo, "merge", "-q", "--no-ff", "evaluator", "-m", "merge\n\nAgent: implementer")
    r = _check(repo, base)
    assert r.returncode == 0, r.stdout


def test_protected_change_made_in_a_merge_resolution_fails(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "evaluator")
    _commit(repo, {"tests/acceptance/test_a.py": "def test_a():\n    assert 1\n"}, "evaluator")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, {"packages/x.py": "X = 4\n"}, "implementer")
    _git(repo, "merge", "-q", "--no-ff", "--no-commit", "evaluator")
    _write(repo, "tests/acceptance/test_a.py", "def test_a():\n    pass\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "merge\n\nAgent: implementer")
    r = _check(repo, base)
    assert r.returncode == 1, r.stdout


def test_evaluator_approval_list_allows_the_listed_change_only(repo):
    base = _git(repo, "rev-parse", "HEAD")
    sha = _commit(repo, {".github/workflows/ci.yml": "name: CI\n", "tests/fixtures/f.json": "{}\n"}, "implementer")
    approvals = {"approved": [{"path": ".github/workflows/ci.yml", "commit": sha[:10]}]}
    _commit(repo, {"docs/scorecards/approved_protected_changes.json": json.dumps(approvals)}, "evaluator")
    r = _check(repo, base)
    assert "[승인] .github/workflows/ci.yml" in r.stdout
    assert "[보호 경로 변경] tests/fixtures/f.json" in r.stdout
    assert r.returncode == 1


def test_approval_list_written_by_implementer_is_ignored(repo):
    base = _git(repo, "rev-parse", "HEAD")
    sha = _commit(repo, {".github/workflows/ci.yml": "name: CI\n"}, "implementer")
    approvals = {"approved": [{"path": ".github/workflows/ci.yml", "commit": sha}]}
    _commit(repo, {"docs/scorecards/approved_protected_changes.json": json.dumps(approvals)}, "implementer")
    r = _check(repo, base)
    assert r.returncode == 1
    assert "[승인]" not in r.stdout


def test_unknown_base_is_unmeasured(repo):
    assert _check(repo, "0" * 40).returncode == 2
