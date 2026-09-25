"""v5 2-1·2-2: 실행 환경 점검·환경 지문과 평가 도구의 신뢰성(대조군 오탐, 유형 대응표, 모델 의견 조건, 오탐 후보).

정답지·결과 JSON은 모두 시험용으로 새로 지었다(테스트셋·블라인드 내용을 쓰지 않는다).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.verification_engine import environment as env_mod

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluator = _load("eval_testset")
fdiff = _load("findings_diff")
ecompare = _load("eval_compare")


# --- 2-1 환경 점검·지문 --------------------------------------------------------------------------
def _settings(model="m-1"):
    def provider(name):
        return SimpleNamespace(name=name, enabled=True, has_key=True, model=model)
    return SimpleNamespace(providers={n: provider(n) for n in env_mod.AI_PROVIDERS}, ocr_lang="kor+eng")


class _Registry:
    def __init__(self, law="READY"):
        self.law = law

    def states(self):
        return [SimpleNamespace(name="law_go_kr", status=self.law), SimpleNamespace(name="kci", status="READY")]


class _Router:
    def __init__(self, names=env_mod.AI_PROVIDERS):
        self.names = list(names)

    def available_providers(self):
        return self.names


@pytest.fixture
def ocr_ready(monkeypatch):
    monkeypatch.setenv("LV_ALLOW_NETWORK", "1")  # 시험 기본값은 네트워크 차단이다. 지문 시험은 연결된 환경을 가정한다
    monkeypatch.setattr(env_mod, "_ocr_state", lambda lang: {"status": "READY", "version": "tesseract 5.3.4",
                                                             "kor": True, "osd": True})


def test_complete_environment_has_no_incomparable_area(monkeypatch, ocr_ready):
    monkeypatch.setenv("LV_LAW_GO_KR_OC", "secret-value-1")
    monkeypatch.setenv("LV_ALLOW_NETWORK", "1")
    got = env_mod.preflight(_settings(), _Registry(), _Router())
    assert got["complete"] and got["missing_required"] == [] and got["incomparable_areas"] == []
    assert "secret-value-1" not in json.dumps(got)  # 비밀값은 기록하지 않는다


def test_missing_law_key_ai_and_korean_ocr_are_each_reported_with_their_areas(monkeypatch):
    monkeypatch.delenv("LV_LAW_GO_KR_OC", raising=False)
    monkeypatch.setattr(env_mod, "_ocr_state", lambda lang: {"status": "LANGUAGES_MISSING", "version": "", "kor": False,
                                                             "osd": False})
    got = env_mod.preflight(_settings(), _Registry(law="MISSING_KEY"), _Router(names=["anthropic"]))
    assert set(got["missing_required"]) == {"law_db", "ai_models", "korean_ocr"}
    assert any("공식 DB" in a for a in got["incomparable_areas"])
    assert any("semantic_review" in a for a in got["incomparable_areas"])
    assert any("스캔" in a for a in got["incomparable_areas"])
    assert env_mod.incomplete_banner(got).startswith("불완전 환경")


def test_fingerprint_ignores_secret_values_but_tracks_models_and_resources(monkeypatch, ocr_ready):
    monkeypatch.setenv("LV_LAW_GO_KR_OC", "one")
    a = env_mod.preflight(_settings(), _Registry(), _Router())
    monkeypatch.setenv("LV_LAW_GO_KR_OC", "two")
    b = env_mod.preflight(_settings(), _Registry(), _Router())
    c = env_mod.preflight(_settings(model="m-2"), _Registry(), _Router())
    monkeypatch.delenv("LV_LAW_GO_KR_OC")
    d = env_mod.preflight(_settings(), _Registry(law="MISSING_KEY"), _Router())
    assert a["fingerprint"] == b["fingerprint"]
    assert len({a["fingerprint"], c["fingerprint"], d["fingerprint"]}) == 3


def test_comparability_lists_areas_only_when_fingerprints_differ(monkeypatch, ocr_ready):
    monkeypatch.setenv("LV_LAW_GO_KR_OC", "k")
    full = env_mod.preflight(_settings(), _Registry(), _Router())
    monkeypatch.delenv("LV_LAW_GO_KR_OC")
    partial = env_mod.preflight(_settings(), _Registry(law="MISSING_KEY"), _Router())
    assert env_mod.comparability(full, full) == {"same_environment": True,
                                                 "fingerprints": [full["fingerprint"]] * 2, "incomparable_areas": []}
    other = env_mod.comparability(full, partial)
    assert not other["same_environment"] and any("law_db" in a for a in other["incomparable_areas"])
    assert not env_mod.comparability(None, full)["same_environment"]


# --- 2-2 채점 --------------------------------------------------------------------------------------
def _finding(doc, kind, status, grade, title, advisory=False):
    return {"document_id": doc, "type": kind, "status": status, "evidence_grade": grade, "title": title,
            "detail": "", "advisory_only": advisory, "evidence": [], "confidence_features": {}}


def _testset(tmp_path, documents, tokens):
    root = tmp_path / "set"
    root.mkdir()
    (root / "ground_truth.json").write_text(json.dumps({"documents": documents}, ensure_ascii=False), encoding="utf-8")
    (root / "match_spec.json").write_text(json.dumps({"tokens": tokens}, ensure_ascii=False), encoding="utf-8")
    return root


def _result(docs, executions=()):
    return {"documents": [{"document_id": d, "filename": f"{d}.pdf", "findings": fs,
                           "ai_detector_result": {"reasons": ["규칙 판별기의 이유: 가공 인용문"], "signals": {}}}
                          for d, fs in docs.items()],
            "model_executions": list(executions), "run_manifest": {"environment": {"fingerprint": "f1"}}}


def test_control_document_defect_claims_count_as_false_positives_even_without_a_trap(tmp_path):
    root = _testset(tmp_path, {"P-01": {"file": "P-01.pdf", "expected": "PASS",
                                        "items": [["FP-TRAP", "1", "2024. 2. 29.", "윤년", None]]},
                               "F-01": {"file": "F-01.pdf", "expected": "FAIL",
                                        "items": [["EVI-NUM", "갑 제2호증", "결번", "", None]]}},
                    {"P-01": [[["2024. 2. 29."]]], "F-01": [[["제2호증"], ["결번"]]]})
    result = _result({"P-01": [_finding("P-01", "EVIDENCE_NUMBERING_GAP", "CONTRADICTED", "B", "갑 제9호증 결번"),
                               _finding("P-01", "HIDDEN_INSTRUCTION", "SUSPICIOUS", "A", "숨은 지시문"),
                               _finding("P-01", "STYLE_SHIFT", "SUSPICIOUS", "C", "문체 변화"),
                               _finding("P-01", "SPECIMEN_DOCUMENT_DECLARED", "SUSPICIOUS", "A", "예시 문서")],
                      "F-01": [_finding("F-01", "EVIDENCE_NUMBERING_GAP", "CONTRADICTED", "B", "갑 제2호증 결번")]})
    report = evaluator.score(result, root, db_available=False)
    assert report["control_false_positives"] == 2 and report["a_grade_false_positives"] == 1
    assert report["overall"] == pytest.approx(100 - 2 * 2 - 3 * 1)
    assert len(report["not_evaluated_findings"]) == 1  # 바닥글 가상 문서 표시는 따로 적는다


def test_token_match_with_an_unrelated_finding_type_earns_no_credit(tmp_path):
    root = _testset(tmp_path, {"F-02": {"file": "F-02.pdf", "expected": "FAIL",
                                        "items": [["CIT-FAB-Q", "2", "가공 인용문", "", None],
                                                  ["LAW-MIS", "3", "제5조 60일", "", None]]}},
                    {"F-02": [[["가공 인용문"]], [["제5조"], ["60일"]]]})
    result = _result({"F-02": [_finding("F-02", "UNCERTAINTY_NOT_DISCLOSED", "SUSPICIOUS", "C", "가공 인용문 단정"),
                               _finding("F-02", "LAW_CITATION_ERROR", "CONTRADICTED", "A", "가상법 제5조 60일 ≠ 90일")]})
    report = evaluator.score(result, root, db_available=False)
    credit = {row["type"]: row["credit"] for row in report["items"]}
    assert credit == {"CIT-FAB-Q": 0.0, "LAW-MIS": 1.0}
    assert any("UNCERTAINTY_NOT_DISCLOSED" in r for r in report["rejected_by_type_map"])


def test_model_opinion_credit_requires_an_actual_model_call(tmp_path):
    root = _testset(tmp_path, {"F-03": {"file": "F-03.pdf", "expected": "FAIL",
                                        "items": [["AIGEN", "1", "지식 기준일", "", None]]}},
                    {"F-03": [[["지식 기준일"]]]})
    opinion = {"llm_opinions": [{"provider": "anthropic", "reasons": ["'지식 기준일' 표현은 모델 잔재"]}]}
    no_call = _result({"F-03": []})
    no_call["documents"][0]["ai_detector_result"]["signals"] = opinion
    called = json.loads(json.dumps(no_call))
    called["model_executions"] = [{"provider": "anthropic", "error": None}]
    assert evaluator.score(no_call, root, db_available=False)["items"][0]["credit"] == 0.0
    assert evaluator.score(called, root, db_available=False)["items"][0]["how"] == "모델 의견 서술"


def test_every_ground_truth_defect_type_has_an_allowed_finding_type_map():
    for name in ("legal_verifier_testset", "holdout"):
        gt = json.loads((ROOT / "tests/fixtures" / name / "ground_truth.json").read_text(encoding="utf-8"))
        for doc in gt["documents"].values():
            for item in doc["items"]:
                if item[0] != "FP-TRAP":
                    assert evaluator.allowed_types(item[0])


# --- 2-2 블라인드 비교: 오탐 후보 --------------------------------------------------------------
def _payload(findings, fingerprint="f1"):
    return {"documents": [{"filename": "X-01_doc.pdf", "findings": findings}],
            "run_manifest": {"environment": {"fingerprint": fingerprint, "resources": {}}}}


def test_new_contradicted_and_ab_grade_findings_are_listed_as_false_positive_candidates():
    before = _payload([])
    after = _payload([_finding("X-01", "EVIDENCE_NUMBERING_GAP", "CONTRADICTED", "B", "갑 제4호증 결번"),
                      _finding("X-01", "LEGAL_ARGUMENT_INVALID", "SUSPICIOUS", "B", "헌법 조항 위헌 주장"),
                      _finding("X-01", "STYLE_SHIFT", "SUSPICIOUS", "C", "문체 변화"),
                      _finding("X-01", "DRAFT_ARTIFACT", "SUSPICIOUS", "A", "참고 신호", advisory=True)])
    d = fdiff.diff(before, after)
    assert {r["type"] for r in d["false_positive_candidates"]} == {"EVIDENCE_NUMBERING_GAP", "LEGAL_ARGUMENT_INVALID"}
    assert "오탐 후보" in fdiff.render("t", d)


def test_regression_zero_is_not_concluded_across_different_environments():
    same = fdiff.diff(_payload([]), _payload([]))
    other = fdiff.diff(_payload([], "f1"), _payload([], "f2"))
    assert same["environment"]["same_environment"] and "결론 내리지 않는다" not in fdiff.render("t", same)
    assert not other["environment"]["same_environment"] and "결론 내리지 않는다" in fdiff.render("t", other)


def test_eval_compare_refuses_zero_regression_across_scoring_versions():
    base = {"items": [], "environment": {"fingerprint": "f1"}}
    d = ecompare.compare({**base, "scoring_version": 1}, {**base, "scoring_version": 2})
    assert not d["environment"]["same_environment"] and "채점 방식이 다름" in d["environment"]["incomparable_areas"][0]
    assert ecompare.compare({**base, "scoring_version": 2}, {**base, "scoring_version": 2})["environment"]["same_environment"]
