"""문서 점검 도구(scripts/probe_document.py)와 서면6 명세의 시험(평가 에이전트 소관, 보호 경로)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "probe_document.py"
SPEC = ROOT / "tests" / "fixtures" / "probes" / "case6_military_secret.json"
PRE_FIX_COMMIT = "aa93276"     # 서면6을 받았을 때의 코드(수정 전)


def _load():
    spec = importlib.util.spec_from_file_location("probe_document", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("probe_document", module)
    spec.loader.exec_module(module)
    return module


probe = _load()


def _run(*args, timeout=600):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def test_case6_spec_is_valid():
    spec = probe.load_spec(SPEC)
    assert len(spec["checks"]) == 20
    assert {c["kind"] for c in spec["checks"]} <= probe.KINDS
    for key in ("input", "text_input"):
        assert (ROOT / spec[key]).is_file()


@pytest.mark.parametrize("flags", [[], ["--text"]])
def test_case6_probe_full_score_on_current_tree(flags):
    proc = _run("run", "--spec", str(SPEC), "--json", *flags)
    assert proc.returncode == 0, proc.stderr[-400:]
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["failed"] == [] and result["passed"] == result["total"] == 20, result["failed"]


def test_every_check_kind_is_evaluated(tmp_path):
    document = tmp_path / "doc.txt"
    document.write_text("피고인 김철수는 서울특별시 마포구 월드컵로 10에 거주하고 연락처는 010-1234-5678이다. "
                        "형법 제20조에 해당한다고 주장한다.\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"name": "synthetic", "input": str(document), "text_input": str(document), "checks": [
        {"id": "T-1", "kind": "text_contains", "value": "010-1234-5678"},
        {"id": "T-2", "kind": "text_contains", "value": "없는문구"},
        {"id": "M-1", "kind": "masked", "value": "010-1234-5678"},
        {"id": "M-2", "kind": "masked", "value": "주장한다"},          # 개인정보가 아니므로 마스킹되지 않는다 → 실패
        {"id": "C-1", "kind": "citation", "law_contains": "형법", "article": "20"},
        {"id": "C-2", "kind": "citation", "law_contains": "형법", "article": "21"},
        {"id": "F-1", "kind": "finding", "types": ["NO_SUCH_TYPE"]},
        {"id": "N-1", "kind": "no_finding", "types": ["NO_SUCH_TYPE"]},
    ]}), encoding="utf-8")
    proc = _run("run", "--spec", str(spec), "--json", "--text")
    assert proc.returncode == 0, proc.stderr[-400:]
    by_id = {r["id"]: r["passed"] for r in json.loads(proc.stdout.strip().splitlines()[-1])["rows"]}
    assert by_id == {"T-1": True, "T-2": False, "M-1": True, "M-2": False, "C-1": True, "C-2": False,
                     "F-1": False, "N-1": True}


def test_spec_rejects_unknown_kind_and_duplicate_ids(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x", "checks": [{"id": "A", "kind": "nope"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        probe.load_spec(bad)
    dup = tmp_path / "dup.json"
    dup.write_text(json.dumps({"name": "x", "checks": [{"id": "A", "kind": "masked", "value": "a"},
                                                       {"id": "A", "kind": "masked", "value": "b"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        probe.load_spec(dup)


def test_record_appends_one_line(tmp_path):
    log = tmp_path / "first_touch.jsonl"
    proc = _run("record", "--spec", str(SPEC), "--text", "--allow-dirty", "--log", str(log), "--note", "시험")
    assert proc.returncode == 0, proc.stderr[-400:]
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["spec"] == "case6_military_secret" and entry["input"] == "text"
    assert entry["passed"] == entry["total"] == 20 and entry["backfilled"] is False and entry["note"] == "시험"


def _commit_available(sha: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT, capture_output=True).returncode == 0


@pytest.mark.skipif(not _commit_available(PRE_FIX_COMMIT), reason="얕은 복제라 과거 커밋이 없다")
def test_backfill_measures_the_old_commit_not_the_current_tree(tmp_path):
    log = tmp_path / "first_touch.jsonl"
    proc = _run("record", "--spec", str(SPEC), "--sha", PRE_FIX_COMMIT, "--log", str(log), "--note", "소급", timeout=900)
    assert proc.returncode == 0, proc.stderr[-400:]
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert entry["backfilled"] is True and entry["measured_commit"].startswith(PRE_FIX_COMMIT[:7])
    assert entry["passed"] < entry["total"]      # 수정 전 코드는 이 서면의 항목 일부를 놓친다
    assert "TEXT-1" in entry["failed"]           # PDF 글자 순서 결함(수정 전)
