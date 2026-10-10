"""평가 측 도구(티켓 지표·고정 벤치마크) 시험. 입력은 지어낸 합성 값이다."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ticket_metrics_counts_regression_and_open(tmp_path, monkeypatch):
    tm = _load("ticket_metrics")
    tickets = [
        {"id": "TK-1", "found_on": "2026-10-05", "kind_auto": "regression", "title": "a", "file": "x"},
        {"id": "TK-2", "found_on": "2026-10-06", "kind_auto": "existing", "title": "b", "file": "y"},
        {"id": "TK-3", "found_on": "2026-10-12", "kind_auto": "existing", "title": "c", "file": "z"},
    ]
    reg = {"TK-1": {"status": "deployed", "deployed_on": "2026-10-12"},
           "TK-2": {"status": "open", "kind": "regression"}}
    m = tm.build(tickets, reg)
    assert m["regression_total"] == 2            # 등록부 kind가 자동 분류를 덮어쓴다
    assert [r["id"] for r in m["open"]] == ["TK-2", "TK-3"]
    assert m["unregistered"] == ["TK-3"]
    assert m["weekly"]["2026-W41"] == {"found": 2, "regression": 2, "recurrence": 0}
    assert m["weekly"]["2026-W42"]["deployed"] == 1


def test_ticket_registry_covers_every_ticket():
    tm = _load("ticket_metrics")
    assert tm.main(["--check"]) == 0


def test_fixed_benchmark_fingerprint_and_combine(tmp_path):
    fb = _load("fixed_benchmark")
    for name in ("set01", "set02"):
        d = tmp_path / name
        d.mkdir()
        (d / "ground_truth.json").write_text("{}", encoding="utf-8")
        (d / "match_spec.json").write_text("{}", encoding="utf-8")
        (d / "SD-01.pdf").write_bytes(name.encode())
        (d / "notes.txt").write_text("무시", encoding="utf-8")
    first = fb.fingerprint(tmp_path)
    (tmp_path / "set01" / "notes.txt").write_text("바꿔도 지문 같음", encoding="utf-8")
    assert fb.fingerprint(tmp_path) == first
    (tmp_path / "set02" / "SD-01.pdf").write_bytes(b"changed")
    assert fb.fingerprint(tmp_path) != first
    row = lambda items, rec, ov, fp, inj: {"documents": 8, "defect_items": items, "weighted_recall": rec, "overall": ov,
                                           "false_positives": fp, "fp_trap": 0, "control_fp": fp, "a_grade_fp": fp,
                                           "injection_defended": inj}
    c = fb.combine([row(53, 0.302, 15.2, 3, True), row(46, 0.19, 19.0, 0, True)])
    assert c["weighted_recall"] == 0.25 and c["overall"] == 17.0 and c["false_positives"] == 3
    assert c["injection_defended"] is True
    assert fb.combine([row(10, 0.5, 50, 0, True), row(10, 0.5, 50, 0, False)])["injection_defended"] is False


def test_fixed_benchmark_refuses_folder_inside_repo():
    fb = _load("fixed_benchmark")
    assert fb.main(["--bench-dir", str(ROOT / "tests" / "fixtures" / "retired_sealed" / "sealed_20261010")]) == 2
