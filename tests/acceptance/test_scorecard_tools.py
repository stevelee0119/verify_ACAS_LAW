"""성적표·점수 게이트 도구의 시험(평가 에이전트 소관, 보호 경로)."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "scorecards" / "baseline.json"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


gate = _load("score_gate")


@pytest.fixture()
def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_baseline_file_is_complete(baseline):
    assert baseline["schema"] == 1
    assert set(baseline["sets"]) >= {"dev", "holdout"}
    assert baseline["environment"]["network"] is False
    for row in baseline["sets"].values():
        assert row["false_positives"] == 0 and row["a_grade_fp"] == 0
        assert row["injection_defended"] is True
        assert row["per_document"]


def test_gate_passes_identical_scorecard(baseline):
    failures, warnings, improvements = gate.compare(copy.deepcopy(baseline), baseline)
    assert (failures, warnings, improvements) == ([], [], [])


@pytest.mark.parametrize("mutate, expected", [
    (lambda c: c["sets"]["dev"].update(overall=c["sets"]["dev"]["overall"] - 0.6), "종합"),
    (lambda c: c["sets"]["holdout"].update(false_positives=1), "false_positives"),
    (lambda c: c["sets"]["holdout"].update(a_grade_fp=1), "a_grade_fp"),
    (lambda c: c["sets"]["dev"].update(duplicate_citation_verdicts=2), "duplicate_citation_verdicts"),
    (lambda c: c["sets"]["dev"].update(injection_defended=False), "인젝션"),
    (lambda c: c["sets"]["dev"]["per_document"].update({"TC-03": 0.9}), "TC-03"),   # 한 항목 상실(1.0 → 0.909급)
    (lambda c: c["sets"].pop("holdout"), "성적표에 없음"),
])
def test_gate_fails_on_regression(baseline, mutate, expected):
    current = copy.deepcopy(baseline)
    mutate(current)
    failures, _, _ = gate.compare(current, baseline)
    assert failures and any(expected in line for line in failures), failures


def test_gate_tolerates_small_noise_and_reports_improvement(baseline):
    current = copy.deepcopy(baseline)
    current["sets"]["dev"]["overall"] -= 0.4
    assert gate.compare(current, baseline)[0] == []
    better = copy.deepcopy(baseline)
    better["sets"]["holdout"]["overall"] += 2.0
    failures, _, improvements = gate.compare(better, baseline)
    assert failures == [] and improvements


def test_gate_flags_environment_mismatch(baseline):
    current = copy.deepcopy(baseline)
    current["environment"]["tesseract"] = None
    _, warnings, _ = gate.compare(current, baseline)
    assert any("OCR" in w for w in warnings)


def test_baseline_can_only_be_raised(baseline):
    lower = copy.deepcopy(baseline)
    lower["sets"]["dev"]["overall"] -= 0.2
    assert gate.can_raise_baseline(lower, baseline)
    higher = copy.deepcopy(baseline)
    higher["sets"]["dev"]["overall"] += 1.0
    assert gate.can_raise_baseline(higher, baseline) == []


def _run_scorecard(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "scorecard.py"), *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)


def test_sealed_set_reports_aggregates_only(tmp_path):
    sealed = tmp_path / "sealed"
    shutil.copytree(ROOT / "tests" / "fixtures" / "holdout", sealed)   # 봉인 세트와 같은 형식의 임시 폴더
    out = tmp_path / "card.json"
    proc = _run_scorecard("--sets", "dev", "--sealed-dir", str(sealed), "--out", str(out))
    assert proc.returncode == 0, proc.stderr[-400:]
    card = json.loads(out.read_text(encoding="utf-8"))
    assert "per_document" not in card["sets"]["sealed"] and card["sets"]["sealed"]["documents"] == 6
    assert "HO-0" not in proc.stdout and "HO-0" not in out.read_text(encoding="utf-8")
    details = list((sealed / ".sealed_out").glob("scorecard_*.json"))
    assert len(details) == 1 and "per_document" in json.loads(details[0].read_text(encoding="utf-8"))


def test_sealed_set_must_live_outside_repository():
    proc = _run_scorecard("--sealed-dir", str(ROOT / "tests" / "fixtures" / "holdout"))
    assert proc.returncode == 2 and "저장소 밖" in proc.stderr


def test_sealed_set_requires_answer_files(tmp_path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF-1.4")
    proc = _run_scorecard("--sealed-dir", str(tmp_path))
    assert proc.returncode == 2 and "ground_truth.json" in proc.stderr


def test_current_tree_passes_score_gate(baseline, tmp_path):
    """현재 트리가 기준선을 지키는지. 측정 조건(OCR 유무)이 기준선과 다르면 건너뛴다."""
    tesseract = shutil.which("tesseract")
    if not tesseract or not baseline["environment"]["tesseract"]:
        pytest.skip("기준선은 한국어 OCR이 있는 조건에서 만들었다")
    out = tmp_path / "card.json"
    assert _run_scorecard("--out", str(out)).returncode == 0
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_gate.py"), "--current", str(out)],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
