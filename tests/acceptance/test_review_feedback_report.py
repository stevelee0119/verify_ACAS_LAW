"""사람 판정 집계(scripts/review_feedback_report.py)의 시험(평가 에이전트 소관, 보호 경로)."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("review_feedback_report", ROOT / "scripts" / "review_feedback_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("review_feedback_report", module)
    spec.loader.exec_module(module)
    return module


rf = _load()


def _db(tmp_path, rows):
    path = tmp_path / "app.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE findings (id TEXT PRIMARY KEY, engine TEXT, type TEXT, data TEXT, title TEXT, detail TEXT)")
    con.execute("CREATE TABLE finding_workflows (finding_id TEXT PRIMARY KEY, decision TEXT)")
    for i, (engine, ftype, rule, decision) in enumerate(rows):
        con.execute("INSERT INTO findings VALUES (?,?,?,?,?,?)",
                    (f"F{i}", engine, ftype, json.dumps({"confidence_features": {"rule_id": rule}}) if rule else "{}",
                     "비밀 제목 홍길동", "비밀 본문"))
        if decision:
            con.execute("INSERT INTO finding_workflows VALUES (?,?)", (f"F{i}", decision))
    con.commit()
    con.close()
    return f"sqlite:///{path}"


def test_aggregates_by_engine_type_rule_and_ranks_by_false_positive_rate(tmp_path):
    rows = ([("adversarial_engine", "UNICODE_SMUGGLING", "r1", "FALSE_POSITIVE")] * 4
            + [("adversarial_engine", "UNICODE_SMUGGLING", "r1", "AGREED")]
            + [("legal_engine", "CASE_NOT_FOUND", "", "AGREED")] * 5
            + [("rag_engine", "RAG_ADVISORY", "", "FALSE_POSITIVE")] * 2            # 표본 부족
            + [("legal_engine", "CASE_NOT_FOUND", "", None)] * 3)                     # 판정 없음
    groups = rf.aggregate(rf.fetch(_db(tmp_path, rows)), min_decided=5)
    top = groups[0]
    assert (top["engine"], top["type"], top["rule_id"]) == ("adversarial_engine", "UNICODE_SMUGGLING", "r1")
    assert top["decided"] == 5 and top["false_positive"] == 4 and top["false_positive_rate"] == 0.8
    case = next(g for g in groups if g["type"] == "CASE_NOT_FOUND")
    assert case["total"] == 8 and case["decided"] == 5 and case["undecided"] == 3 and case["false_positive_rate"] == 0.0
    rag = next(g for g in groups if g["type"] == "RAG_ADVISORY")
    assert rag["false_positive_rate"] is None and rag["sample"] == "표본 부족"
    assert groups[-1]["type"] == "RAG_ADVISORY"         # 표본 부족은 맨 뒤


def test_partly_agreed_is_not_counted_as_false_positive():
    rows = [{"engine": "e", "type": "T", "data": "{}", "decision": d}
            for d in ("PARTLY_AGREED", "PARTLY_AGREED", "AGREED", "FALSE_POSITIVE", "AGREED")]
    (group,) = rf.aggregate(rows, min_decided=5)
    assert group["false_positive"] == 1 and group["partly_agreed"] == 2 and group["false_positive_rate"] == 0.2


def test_unknown_decision_is_counted_as_undecided():
    (group,) = rf.aggregate([{"engine": "e", "type": "T", "data": None, "decision": "WEIRD"}], min_decided=1)
    assert group["undecided"] == 1 and group["decided"] == 0


def test_report_never_prints_finding_content(tmp_path, capsys):
    url = _db(tmp_path, [("e", "T", "", "AGREED")] * 5)
    out = tmp_path / "out.json"
    assert rf.main(["--db-url", url, "--json", str(out)]) == 0
    printed = capsys.readouterr().out + out.read_text(encoding="utf-8")
    assert "비밀" not in printed and "홍길동" not in printed
    assert "| e | T |" in printed
