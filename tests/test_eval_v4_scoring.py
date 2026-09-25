"""eval_v4 채점기 v2 회귀시험. 정답지·결과는 모두 합성이다(블라인드 정답지를 쓰지 않는다)."""
from __future__ import annotations

import json

import pytest

from scripts.eval_v4_scoring import SCORER_VERSION, allowed_types, score, write_new


def _f(fid, ftype, status, title, *, doc="D-01", adv=False, grade="A", page=1, features=None):
    return {"finding_id": fid, "type": ftype, "status": status, "severity": "HIGH", "evidence_grade": grade,
            "title": title, "detail": "", "advisory_only": adv, "tags": [], "evidence": [{"excerpt": title}],
            "confidence_features": features or {}, "document_id": doc, "page": page}


def _doc(doc_id, findings, *, pages=("EXTRACTED",), quarantined=False):
    return {"document_id": doc_id, "filename": f"{doc_id}_합성.pdf", "quarantined": quarantined,
            "page_coverage": [{"page": i + 1, "status": s} for i, s in enumerate(pages)], "findings": findings}


GT = {"version": "synthetic", "documents": [
    {"id": "D-01", "file": "D-01_합성.pdf", "items": [
        ["CIT-NX", "p.1", "대법원 2020다123456 판결", "존재하지 않는 판례"],
        ["ARITH", "p.2", "합계 12,500,000원", "합계 오류"],
        ["LAW-NX", "p.1", "근로기준법 제250조", "부존재 조문"],
        ["FP-TRAP", "p.1", "대법원 2019다55555 판결", "실존 판례(정상)"]]},
    {"id": "D-05", "file": "D-05_합성.pdf", "items": []}]}


def _report(d01, d05=None):
    docs = [_doc("D-01", d01)] + ([_doc("D-05", d05)] if d05 is not None else [])
    return {"documents": docs, "project_findings": [], "run_manifest": {}}


def test_legacy_counterexample_verified_and_unverified_with_matching_numbers_and_no_control_is_blocked():
    """v1은 이 입력에 100점을 줬다(사건번호 일치만으로 적중 + D-05 누락을 오탐 0으로 처리)."""
    report = _report([
        _f("f1", "CASE_CITATION_ERROR", "VERIFIED", "대법원 2020다123456 판결 확인됨"),
        _f("f2", "CASE_NOT_FOUND", "UNVERIFIED", "대법원 2020다123456 판결 조회 실패", adv=True, grade="C"),
        _f("f3", "ARITHMETIC_MISMATCH", "VERIFIED", "합계 12,500,000원 검산 일치", page=2),
        _f("f4", "LAW_CITATION_ERROR", "VERIFIED", "근로기준법 제250조 확인")])
    result = score(GT, report)
    assert result["scorer_version"] == SCORER_VERSION
    assert result["evaluation_status"] == "INCOMPLETE"
    assert any("D-05" in reason and "MISSING" in reason for reason in result["incomplete_reasons"])
    assert result["metrics"]["confirmed_hits"] == 0
    assert result["metrics"]["reference_only_items"] == 1      # UNVERIFIED는 참고 신호로 따로 센다
    assert result["composite_score"] is None
    control = next(d for d in result["coverage"]["per_document"] if d["doc"] == "D-05")
    assert control["control_status"] == "INCOMPLETE"


def test_confirmed_hits_need_type_anchor_and_direction():
    report = _report([
        _f("a", "CASE_NOT_FOUND", "NOT_FOUND", "대법원 2020다123456 판결 부존재"),
        _f("b", "ARITHMETIC_MISMATCH", "CONTRADICTED", "합계 12,500,000원이 세부 합과 다르다", page=2),
        _f("c", "STATUTE_NONEXISTENT", "CONTRADICTED", "근로기준법 제250조 부존재")], d05=[])
    result = score(GT, report)
    assert result["evaluation_status"] == "COMPLETE"
    assert result["metrics"]["confirmed_hits"] == 3 and result["metrics"]["recall_confirmed"] == 1.0
    assert result["metrics"]["precision_lower_bound"] == 1.0


@pytest.mark.parametrize("finding, reason", [
    (_f("x", "EVIDENCE_NUMBERING_GAP", "CONTRADICTED", "대법원 2020다123456 판결"), "유형 불일치"),
    (_f("x", "CASE_NOT_FOUND", "NOT_FOUND", "대법원 2021다999999 판결 부존재"), "근거 식별자 불일치"),
    (_f("x", "CASE_NOT_FOUND", "NOT_FOUND", "대법원 2020다123456 판결 부존재", page=3), "쪽 불일치"),
    (_f("x", "CASE_NOT_FOUND", "VERIFIED", "대법원 2020다123456 판결 확인"), "반대 방향"),
    (_f("x", "CASE_NOT_FOUND", "NOT_FOUND", "대법원 2020다123456 판결", adv=True), "참고 신호"),
])
def test_each_matching_condition_is_required(finding, reason):
    result = score(GT, _report([finding], d05=[]))
    item = next(i for i in result["items"] if i["tag"] == "CIT-NX")
    assert item["result"] != "CONFIRMED_HIT", reason


def test_one_finding_is_not_reused_for_unrelated_items():
    gt = {"documents": [{"id": "D-01", "items": [["ARITH", "", "합계 12,500,000원", ""],
                                                 ["AMOUNT-WORDS", "", "금 12,500,000원", ""]]},
                        {"id": "D-05", "items": []}]}
    one = _f("a", "ARITHMETIC_MISMATCH", "CONTRADICTED", "합계 12,500,000원 불일치")
    result = score(gt, _report([one], d05=[]))
    assert result["metrics"]["confirmed_hits"] == 1


def test_explicitly_listed_multiple_defects_can_cover_multiple_items():
    gt = {"documents": [{"id": "D-01", "items": [["EVID-MISSING", "", "갑 제3호증", ""],
                                                 ["EVID-MISSING", "", "갑 제7호증", ""]]},
                        {"id": "D-05", "items": []}]}
    bundle = _f("m", "EVIDENCE_REFERENCE_MISSING", "CONTRADICTED", "첨부 증거 2건이 없다",
                features={"missing_items": ["갑 제3호증 진술서", "갑 제7호증 사진"]})
    # 호증 번호는 식별자다. 나열 항목(슬롯)마다 다른 호증이 있어야 각각 대응한다
    result = score(gt, _report([bundle], d05=[]))
    assert result["metrics"]["confirmed_hits"] == 2


def test_project_findings_are_not_attached_to_every_document():
    gt = {"documents": [{"id": "D-01", "items": [["XDOC", "", "입사일 2021. 3. 4.", ""]]},
                        {"id": "D-02", "items": [["XDOC", "", "입사일 2021. 3. 4.", ""]]},
                        {"id": "D-05", "items": []}]}
    xdoc = _f("p", "CROSS_DOCUMENT_CONTRADICTION", "CONTRADICTED", "입사일 2021. 3. 4. ↔ 2021. 4. 3.", doc="D-01",
              features={"documents": ["D-01_합성.pdf"]})
    report = {"documents": [_doc("D-01", []), _doc("D-02", []), _doc("D-05", [])], "project_findings": [xdoc],
              "run_manifest": {}}
    result = score(gt, report)
    hits = [i["doc"] for i in result["items"] if i["result"] == "CONFIRMED_HIT"]
    assert hits == ["D-01"]


@pytest.mark.parametrize("control_doc, status", [
    (_doc("D-05", [], pages=("EXTRACTED", "FAILED")), "INCOMPLETE"),
    (_doc("D-05", [], quarantined=True), "INCOMPLETE"),
    (_doc("D-05", [_f("z", "ARITHMETIC_MISMATCH", "CONTRADICTED", "합계 오류", doc="D-05")]), "FAIL"),
    (_doc("D-05", [_f("z", "DRAFT_ARTIFACT", "SUSPICIOUS", "참고", doc="D-05", adv=True)]), "PASS"),
])
def test_control_document_status(control_doc, status):
    report = {"documents": [_doc("D-01", []), control_doc], "project_findings": [], "run_manifest": {}}
    control = next(d for d in score(GT, report)["coverage"]["per_document"] if d["doc"] == "D-05")
    assert control["control_status"] == status


def test_false_positives_are_counted_in_all_documents_not_only_controls():
    report = _report([_f("t", "CASE_NOT_FOUND", "NOT_FOUND", "대법원 2019다55555 판결 부존재"),
                      _f("u", "FACT_CONTRADICTION", "CONTRADICTED", "정답지에 없는 모순 주장")], d05=[])
    metrics = score(GT, report)["metrics"]
    assert metrics["fp_trap_false_positives"] == 1
    assert metrics["unmatched_defect_claims"] == 2 and metrics["precision_lower_bound"] == 0.0


def test_unmapped_tag_is_reported_not_silently_scored():
    gt = {"documents": [{"id": "D-01", "items": [["NEW-TAG", "", "대법원 2020다123456 판결", ""]]},
                        {"id": "D-05", "items": []}]}
    result = score(gt, _report([_f("a", "CASE_NOT_FOUND", "NOT_FOUND", "대법원 2020다123456 판결")], d05=[]))
    assert result["evaluation_status"] == "INCOMPLETE"
    assert result["items"][0]["result"] == "NOT_SCORABLE_UNMAPPED_TAG"
    assert allowed_types("INJ-TINY (회귀)") and allowed_types("CIT-MIS/OVR")


def test_existing_outputs_are_not_overwritten(tmp_path):
    path = tmp_path / "out.json"
    write_new(path, {"a": 1})
    with pytest.raises(FileExistsError):
        write_new(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
