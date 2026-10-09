"""온라인 보고서 채점 도구(scripts/score_report.py)의 시험(평가 에이전트 소관, 보호 경로).

실제 보고서 JSON은 크고 서면 본문을 담고 있어 저장소에 두지 않는다. 같은 구조의 작은 합성 보고서로 도구를 시험한다.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC_ONLINE = ROOT / "tests" / "fixtures" / "probes" / "case7_suspension_online.json"


def _load():
    spec = importlib.util.spec_from_file_location("score_report", ROOT / "scripts" / "score_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("score_report", module)
    spec.loader.exec_module(module)
    return module


sr = _load()


def _finding(ftype, severity="MEDIUM", status="SUSPICIOUS", title=""):
    return {"type": ftype, "severity": severity, "status": status, "title": title}


def _report(findings=(), kinds=None, verdict="UNCERTAIN", models=(), rag=()):
    return {
        "run_id": "run_x", "started_at": "2026-09-30T00:00:00",
        "run_manifest": {"implementation": {"git_commit": "abcdef1234567890"}, "versions": {"program": "0.9.13"},
                         "environment": {"network": True}},
        "scores": {"axes": {"ai_authorship": {"documents": [{"verdict": verdict}]}}},
        "project_findings": [],
        "documents": [{
            "findings": list(findings), "masked_preview": {"kinds": kinds or {}},
            "ai_detector_result": {"model_opinions": list(models)},
            "engine_data": {"rag": {"observations": list(rag)}},
        }],
    }


def _write(tmp_path, report):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def test_online_spec_is_valid():
    spec = sr.load_spec(SPEC_ONLINE)
    assert len(spec["checks"]) == 20
    assert {c["kind"] for c in spec["checks"]} <= sr.KINDS


def test_empty_report_fails_positive_checks_and_passes_negative_ones(tmp_path):
    result = sr.score(_write(tmp_path, _report()), SPEC_ONLINE)
    by_id = {r["id"]: r["passed"] for r in result["rows"]}
    assert by_id["FA-1"] is True                      # 오탐 없음 항목은 finding이 없으면 통과
    assert not any(by_id[k] for k in ("AI-1", "AI-2", "EX-1", "EX-2", "TMP-1", "LEG-1", "INJ-1", "RAG-1", "PII-K1"))
    assert result["commit"] == "abcdef123456" and result["network"] is True


def test_full_marks_report(tmp_path):
    models = [{"provider": p, "score": s, "verdict": "AI_FULL_GENERATION_LIKELY"} for p, s in (("a", 0.9), ("b", 0.95))]
    findings = [
        _finding("AI_AUTHORSHIP_LIKELY", "INFO", "UNVERIFIED", "다각적인 관점에"),
        _finding("CASE_NOT_FOUND", "CRITICAL", "NOT_FOUND", "대법원 2022두49182 판결"),
        _finding("LAW_CITATION_ERROR", "MEDIUM", "NOT_FOUND", "군인사법 제57조의3"),
        _finding("TEMPORAL_LAW_MISMATCH", "HIGH", "SUSPICIOUS", "군인징계령 2025"),
        _finding("LEGAL_ARGUMENT_INVALID", "MEDIUM", "SUSPICIOUS", "민법 제734조 사무관리"),
        _finding("OVERCLAIM", "MEDIUM", "SUSPICIOUS", "형법 제20조 정당행위"),
        _finding("HIDDEN_INSTRUCTION", "HIGH", "SUSPICIOUS", "ADMINISTRATIVE_AUDIT_PROTOCOL"),
    ]
    kinds = {k: 1 for k in ("PERSON", "AFFILIATION", "DOB", "ADDRESS", "EMAIL", "MILITARY_ID", "PHONE", "ACCOUNT",
                            "DRIVER_LICENSE")}
    rag = [{"relationship": "CONTRADICTS", "claim_quote": "훈령 제15조 제3항에 의하면"}]
    result = sr.score(_write(tmp_path, _report(findings, kinds, "AI_FULL_GENERATION_LIKELY", models, rag)), SPEC_ONLINE)
    assert result["failed"] == [] and result["passed"] == result["total"] == 20


def test_severity_and_status_conditions_are_enforced(tmp_path):
    findings = [_finding("CASE_NOT_FOUND", "MEDIUM", "NOT_FOUND", "대법원 2022두49182 판결"),      # HIGH 미만
                _finding("LAW_CITATION_ERROR", "MEDIUM", "UNVERIFIED", "군인사법 제57조의3"),       # 상태 불일치
                _finding("UNICODE_SMUGGLING", "MEDIUM", "SUSPICIOUS", "ZWSP")]                     # 오탐 항목 위반
    by_id = {r["id"]: r["passed"] for r in sr.score(_write(tmp_path, _report(findings)), SPEC_ONLINE)["rows"]}
    assert by_id["EX-1"] is False and by_id["EX-2"] is False and by_id["FA-1"] is False


def test_ai_models_needs_enough_high_scoring_ai_opinions(tmp_path):
    one = [{"provider": "a", "score": 0.95, "verdict": "AI_FULL_GENERATION_LIKELY"},
           {"provider": "b", "score": 0.60, "verdict": "AI_PARTIAL_GENERATION"},
           {"provider": "c", "score": 0.99, "verdict": "HUMAN_AUTHORED_LIKELY"}]
    by_id = {r["id"]: r["passed"] for r in sr.score(_write(tmp_path, _report(models=one)), SPEC_ONLINE)["rows"]}
    assert by_id["AI-2"] is False           # 0.85 이상이면서 AI 쪽인 의견이 1개뿐


def test_spec_rejects_unknown_kind_and_duplicate_ids(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x", "checks": [{"id": "A", "kind": "nope"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        sr.load_spec(bad)
    dup = tmp_path / "dup.json"
    dup.write_text(json.dumps({"name": "x", "checks": [{"id": "A", "kind": "finding"}, {"id": "A", "kind": "finding"}]}),
                   encoding="utf-8")
    with pytest.raises(ValueError):
        sr.load_spec(dup)


def test_record_appends_one_line_with_provenance(tmp_path):
    report = _write(tmp_path, _report())
    result = sr.score(report, SPEC_ONLINE)
    log = tmp_path / "log.jsonl"
    sr.record(result, "시험", log)
    entry = json.loads(log.read_text(encoding="utf-8"))
    assert entry["input"] == "online_report" and entry["measured_commit"] == "abcdef123456"
    assert entry["report_sha256"] == result["report_sha256"] and entry["note"] == "시험"
    assert "online" in entry["condition"]


def _rag_spec(tmp_path, scope=None, rule_version=None):
    check = {"id": "R", "kind": "rag_relationship", "relationship": "CONTRADICTS", "text": "제7조"}
    if scope:
        check["scope"] = scope
    spec = {"name": "synthetic_rag", "checks": [check]}
    if rule_version:
        spec["rule_version"] = rule_version
    path = tmp_path / "rag_spec.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


def _report_with_claim(claim_text, quote, relationship="CONTRADICTS", claim_id="CLM_a"):
    """합성: 인용 주장 원문에는 조항 번호가 있고, 모델이 고른 claim_quote에는 인용문만 있는 경우."""
    report = _report(rag=[{"relationship": relationship, "claim_id": claim_id, "claim_quote": quote}])
    report["documents"][0]["claims"] = [{"claim_id": "CLM_a", "text": claim_text}]
    return report


def test_rag_claim_scope_uses_claim_text_by_claim_id(tmp_path):
    report = _write(tmp_path, _report_with_claim("「가상 규정」 제7조에 따르면 \"전부 면제한다\"고 정한다", "전부 면제한다"))
    assert sr.score(report, _rag_spec(tmp_path))["failed"] == ["R"]                  # 1판(인용 범위만)
    assert sr.score(report, _rag_spec(tmp_path, scope="claim"))["failed"] == []      # 2판(주장 원문 포함)


def test_rag_claim_scope_still_needs_relationship_and_matching_claim(tmp_path):
    spec = _rag_spec(tmp_path, scope="claim")
    other_relation = _report_with_claim("「가상 규정」 제7조에 따르면", "따르면", relationship="CONTEXT")
    assert sr.score(_write(tmp_path, other_relation), spec)["failed"] == ["R"]
    other_claim = _report_with_claim("「가상 규정」 제7조에 따르면", "따르면", claim_id="CLM_b")
    assert sr.score(_write(tmp_path, other_claim), spec)["failed"] == ["R"]


def test_spec_rejects_unknown_scope_and_records_rule_version(tmp_path):
    with pytest.raises(ValueError):
        sr.load_spec(_rag_spec(tmp_path, scope="anything"))
    result = sr.score(_write(tmp_path, _report()), _rag_spec(tmp_path, rule_version="2"))
    log = tmp_path / "log.jsonl"
    sr.record(result, "시험", log)
    assert json.loads(log.read_text(encoding="utf-8"))["rule_version"] == "2"
    assert sr.score(_write(tmp_path, _report()), SPEC_ONLINE)["rule_version"] == "1"


def test_case9_online_spec_rag1_uses_claim_scope():
    spec = sr.load_spec(ROOT / "tests" / "fixtures" / "probes" / "case9_state_compensation_online.json")
    assert spec["rule_version"] == "2"
    assert {c["id"]: c.get("scope") for c in spec["checks"]}["RAG-1"] == "claim"


def test_no_rag_relationship_is_the_negation_with_claim_scope(tmp_path):
    spec = tmp_path / "neg.json"
    spec.write_text(json.dumps({"name": "neg", "checks": [
        {"id": "C", "kind": "no_rag_relationship", "relationship": "CONTRADICTS", "text": "제7조", "scope": "claim"}]},
        ensure_ascii=False), encoding="utf-8")
    hit = _report_with_claim("「가상 규정」 제7조에 따르면", "따르면")
    assert sr.score(_write(tmp_path, hit), spec)["failed"] == ["C"]          # 모순 의견이 있으면 대조군 실패
    context = _report_with_claim("「가상 규정」 제7조에 따르면", "따르면", relationship="CONTEXT")
    assert sr.score(_write(tmp_path, context), spec)["failed"] == []          # 다른 관계는 통과
    assert sr.score(_write(tmp_path, _report()), spec)["failed"] == []        # 의견이 없으면 통과
