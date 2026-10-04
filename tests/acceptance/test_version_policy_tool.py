"""버전 정책 점검 도구 시험(평가 에이전트 소관, 보호 경로). 정책: docs/scorecards/VERSION_POLICY.md

핵심: 판정서 없는 상향(커밋마다 올리기)은 실패하고, 한 번에 한 단계만 오르며, 판정서의 등급과 실제 상향 자리가 같아야 한다.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location("check_version_policy_tool", ROOT / "scripts" / "check_version_policy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_version_policy_tool", module)
    spec.loader.exec_module(module)
    return module


tool = _tool()


def verdict(version, frm, level, **extra):
    base = {"version": version, "from": frm, "level": level, "measured_commit": "abc1234", "conditions": "offline linux py3.11 ocr",
            "evidence": ["dev +1.2"], "decided_by": "evaluator", "decided_at": "2026-10-02"}
    base.update(extra)
    return base


@pytest.mark.parametrize("old, new, expected", [
    ((0, 9, 13), (0, 9, 13), None),
    ((0, 9, 13), (0, 9, 14), "patch"),
    ((0, 9, 13), (0, 10, 0), "minor"),
    ((0, 9, 13), (1, 0, 0), "major"),
    ((0, 9, 13), (0, 10, 1), "invalid"),     # 아래 자리를 0으로 되돌리지 않음
    ((0, 9, 13), (0, 9, 15), "invalid"),     # 한 단계 건너뜀
    ((0, 9, 13), (0, 9, 12), "invalid"),     # 내려감
    ((0, 9, 13), (2, 0, 0), "invalid"),      # 정수를 두 단계 올림
])
def test_bump_level(old, new, expected):
    assert tool.bump_level(old, new) == expected


def test_version_regex_reads_the_settings_line():
    assert tool.parse_version('class S:\n    version: str = "0.9.13"\n') == (0, 9, 13)
    assert tool.parse_version("nothing") is None


def test_bump_without_verdict_fails():
    problems = tool.check_bump((0, 9, 13), (0, 9, 14), [], set())
    assert problems and "판정서가 없다" in problems[0]


def test_bump_with_matching_verdict_passes():
    assert tool.check_bump((0, 9, 13), (0, 9, 14), [verdict("0.9.14", "0.9.13", "patch")], set()) == []
    assert tool.check_bump((0, 9, 13), (0, 10, 0), [verdict("0.10.0", "0.9.13", "minor")], set()) == []


def test_level_and_from_must_match_the_actual_bump():
    wrong_level = tool.check_bump((0, 9, 13), (0, 10, 0), [verdict("0.10.0", "0.9.13", "patch")], set())
    assert any("등급" in p for p in wrong_level)
    wrong_from = tool.check_bump((0, 9, 13), (0, 9, 14), [verdict("0.9.14", "0.9.12", "patch")], set())
    assert any("from" in p for p in wrong_from)


def test_verdict_must_carry_evidence_and_conditions():
    incomplete = verdict("0.9.14", "0.9.13", "patch", evidence=[], conditions="")
    problems = tool.check_bump((0, 9, 13), (0, 9, 14), [incomplete], set())
    assert any("빠진 항목" in p for p in problems)


def test_major_needs_user_approval():
    unapproved = tool.check_bump((0, 9, 13), (1, 0, 0), [verdict("1.0.0", "0.9.13", "major")], set())
    assert any("사용자 승인" in p for p in unapproved)
    approved = tool.check_bump((0, 9, 13), (1, 0, 0), [verdict("1.0.0", "0.9.13", "major", user_approved=True)], set())
    assert approved == []


def test_skipping_or_decreasing_is_rejected_even_with_a_verdict():
    problems = tool.check_bump((0, 9, 13), (0, 9, 15), [verdict("0.9.15", "0.9.13", "patch")], set())
    assert problems and "한 단계" in problems[0]


# ------------------------------------------------------------------------------ 종단: 커밋 범위 ---
def _fake_git(monkeypatch, versions):
    """versions: {rev: 'X.Y.Z' 또는 None}. rev-list는 base..head 사이 커밋을 versions의 키 순서로 돌려준다."""
    revs = [r for r in versions if r not in ("BASE",)]

    def fake(*args):
        if args[0] == "rev-list":
            return "\n".join(revs) + "\n"
        if args[0] == "show":
            rev = args[1].split(":")[0]
            version = versions.get(rev)
            return None if version is None else f'    version: str = "{version}"\n'
        return None
    monkeypatch.setattr(tool, "git", fake)


def test_range_without_version_change_passes(monkeypatch, capsys):
    _fake_git(monkeypatch, {"BASE": "0.9.13", "c1": "0.9.13", "c2": "0.9.13"})
    monkeypatch.setattr(tool, "load_verdicts", lambda: [])
    assert tool.main(["--base", "BASE"]) == 0


def test_per_commit_bumping_is_a_violation(monkeypatch, capsys):
    _fake_git(monkeypatch, {"BASE": "0.9.13", "c1": "0.9.14", "c2": "0.9.15"})
    monkeypatch.setattr(tool, "load_verdicts", lambda: [])
    assert tool.main(["--base", "BASE"]) == 1
    assert "판정서가 없다" in capsys.readouterr().out


def test_bump_with_verdict_passes_once(monkeypatch):
    _fake_git(monkeypatch, {"BASE": "0.9.13", "c1": "0.9.13", "c2": "0.10.0"})
    monkeypatch.setattr(tool, "load_verdicts", lambda: [verdict("0.10.0", "0.9.13", "minor")])
    assert tool.main(["--base", "BASE"]) == 0


def test_unreadable_base_is_unmeasured(monkeypatch):
    _fake_git(monkeypatch, {"BASE": None, "c1": "0.9.13"})
    monkeypatch.setattr(tool, "load_verdicts", lambda: [])
    assert tool.main(["--base", "BASE"]) == 2


def test_committed_verdict_file_is_valid_json_list():
    path = ROOT / "docs" / "scorecards" / "version_verdicts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    for item in data:
        assert set(tool.REQUIRED) <= set(item), item.get("version")
