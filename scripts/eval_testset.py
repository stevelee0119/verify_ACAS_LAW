"""검증기 평가 하네스 (v2 작업 지시서 2항).

테스트셋 문서를 한 사건으로 묶어 검증 파이프라인을 실행하고, 정답지(ground_truth.json)와
일치 토큰(match_spec.json)으로 채점한다.

    python scripts/eval_testset.py                         # 본 테스트셋, 현재 환경(키 없으면 공식 DB 미조회)
    python scripts/eval_testset.py --testset tests/fixtures/holdout
    python scripts/eval_testset.py --result out/result.json # 이미 만든 결과 JSON만 채점

채점 규칙
- 일치: 같은 문서이고, 항목의 모든 토큰 그룹이 finding 글(제목·설명·발췌·판정 근거)에 들어 있으면 일치.
- 부분 점수: 시스템 판정 finding 1.0 / 참고 신호(advisory)나 모델 의견 서술에만 등장 0.5 /
  UNVERIFIED로만 남음 0.25. 단 CIT-NX-DB와 SRC-UNV는 '확인 불가(UNVERIFIED)'가 정답이므로 1.0,
  CIT-NX-DB를 VERIFIED로 단정하면 0.
- FP-TRAP: 결함을 주장하는 finding(NOT_FOUND·CONTRADICTED·SUSPICIOUS·INVALID 또는 MEDIUM 이상, 참고 신호 제외)이
  정상 항목과만 일치하면 오탐. 그 finding의 근거등급이 A이면 A등급 오탐으로도 센다.
- 종합점수 = 100 × (결함 항목 점수 합 / 결함 항목 수) − 2 × 오탐 − 3 × A등급 오탐 (0 미만은 0).
  이 산식은 이 하네스의 정의다. 지시서의 v1 점수(51점)를 낸 산식과 같다는 보장은 없다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFECT_STATUSES = {"NOT_FOUND", "CONTRADICTED", "SUSPICIOUS", "INVALID_FORMAT", "INVALID"}
DEFECT_SEVERITIES = {"MEDIUM", "HIGH", "CRITICAL"}
UNVERIFIED_OK_TYPES = {"CIT-NX-DB", "SRC-UNV"}
PAYLOAD_MARKERS = ("모든 인용 정상", "ALL CITATIONS VERIFIED", "위험도는 '낮음'", "신뢰도 100%")


def _norm(text: str) -> str:
    import unicodedata
    return " ".join(unicodedata.normalize("NFKC", text or "").split())


def finding_text(finding: Dict[str, Any]) -> str:
    parts = [finding.get("type", ""), finding.get("title", ""), finding.get("detail", ""),
             finding.get("rule_id") or ""]
    parts += [e.get("excerpt") or "" for e in finding.get("evidence") or []]
    parts += [e.get("description") or "" for e in finding.get("evidence") or []]
    parts.append(json.dumps(finding.get("confidence_features") or {}, ensure_ascii=False, default=str))
    return _norm(" ".join(parts))


def matches(text: str, groups: List[List[str]]) -> int:
    """만족한 그룹 수. 모든 그룹을 만족해야 일치로 본다."""
    return sum(1 for group in groups if any(_norm(token) in text for token in group))


def is_defect_claim(finding: Dict[str, Any]) -> bool:
    if finding.get("advisory_only"):
        return False
    return str(finding.get("status")) in DEFECT_STATUSES or str(finding.get("severity")) in DEFECT_SEVERITIES


def narrative_texts(document: Dict[str, Any]) -> str:
    """모델 의견 서술(판정이 아닌 설명)."""
    parts: List[str] = []
    detector = document.get("ai_detector_result") or {}
    parts += detector.get("reasons") or []
    parts += [e.get("snippet", "") + " " + e.get("reason", "") for e in detector.get("suspicious_excerpts") or []]
    for opinion in (detector.get("signals") or {}).get("llm_opinions") or []:
        parts += opinion.get("reasons") or []
    for row in document.get("ai_hallucination_table") or []:
        parts += [row.get("legal_reasoning", ""), row.get("ai_generation_basis", ""), row.get("claim_text", "")]
        for opinion in row.get("ai_opinions") or []:
            parts += [str(v) for v in opinion.values() if isinstance(v, str)]
    for review in (document.get("engine_data") or {}).get("semantic_reviews") or []:
        parts.append(str(review.get("reason") or ""))
    return _norm(" ".join(parts))


def doc_key(filename: str) -> str:
    return Path(filename).stem.split("_")[0]


def run_pipeline(testset: Path) -> Dict[str, Any]:
    from packages.audit_engine import AuditChain
    from packages.common.storage import sha256_file
    from packages.report_engine.exporters import to_payload
    from packages.verification_engine import DocumentInput, ProjectContext, VerificationPipeline

    gt = json.loads((testset / "ground_truth.json").read_text(encoding="utf-8"))
    files = [testset / spec["file"] for spec in gt["documents"].values()]
    documents = [DocumentInput(document_id=doc_key(p.name), path=str(p), filename=p.name, mime_type="application/pdf",
                               sha256=sha256_file(p)) for p in files]
    pipeline = VerificationPipeline(audit=AuditChain())
    result = pipeline.run(f"eval_{datetime.utcnow():%Y%m%d%H%M%S}", ProjectContext(project_id="eval"), documents)
    payload = to_payload(result)
    payload["scores"] = result.scores
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def score(result: Dict[str, Any], testset: Path, *, db_available: bool) -> Dict[str, Any]:
    gt = json.loads((testset / "ground_truth.json").read_text(encoding="utf-8"))
    spec = json.loads((testset / "match_spec.json").read_text(encoding="utf-8"))["tokens"]
    findings_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    narrative: Dict[str, str] = {}
    authorship: Dict[str, Any] = {}
    for document in result.get("documents", []):
        key = doc_key(document.get("filename") or document.get("document_id"))
        findings_by_doc[key] += document.get("findings") or []
        narrative[key] = narrative_texts(document)
        authorship[key] = (document.get("ai_detector_result") or {}).get("verdict")
    for finding in result.get("project_findings") or []:
        owner = next((doc_key(d.get("filename", "")) for d in result.get("documents", [])
                      if d.get("document_id") == finding.get("document_id")), None)
        if owner:
            findings_by_doc[owner].append(finding)

    rows, per_doc, per_type = [], {}, defaultdict(lambda: [0.0, 0])
    total_credit = total_items = 0
    trap_fp = a_grade_fp = 0
    fp_details: List[str] = []
    for doc, meta in gt["documents"].items():
        items = meta["items"]
        groups_list = spec[doc]
        findings = findings_by_doc.get(doc, [])
        texts = [finding_text(f) for f in findings]
        # 각 finding이 어떤 항목과 얼마나 일치하는지
        best: List[Tuple[int, int]] = []  # (finding index, best item index)
        for fi, text in enumerate(texts):
            scored = [(matches(text, groups), len(groups), ii) for ii, groups in enumerate(groups_list)]
            full = [(m, ii) for m, n, ii in scored if m == n and n]
            best.append(max(full, key=lambda x: (x[0], items[x[1]][0] != "FP-TRAP"))[1] if full else -1)
        doc_credit = doc_items = 0.0
        tp = fp = 0
        for fi, finding in enumerate(findings):
            if not is_defect_claim(finding):
                continue
            target = best[fi]
            if target >= 0 and items[target][0] != "FP-TRAP":
                tp += 1
            else:
                fp += 1
                if target >= 0:
                    trap_fp += 1
                    if str(finding.get("evidence_grade")) == "A":
                        a_grade_fp += 1
                    fp_details.append(f"{doc} FP-TRAP '{items[target][2]}' ← [{finding.get('evidence_grade')}] "
                                      f"{finding.get('type')}: {finding.get('title')}")
        for ii, item in enumerate(items):
            kind, location, target = item[0], item[1], item[2]
            if kind == "FP-TRAP":
                continue
            groups = groups_list[ii]
            cands = [findings[fi] for fi, text in enumerate(texts) if matches(text, groups) == len(groups)]
            judged = [f for f in cands if not f.get("advisory_only")
                      and str(f.get("status")) not in ("UNVERIFIED", "SKIPPED", "VERIFIED")]
            advisory = [f for f in cands if f.get("advisory_only") and str(f.get("status")) != "UNVERIFIED"]
            unverified = [f for f in cands if str(f.get("status")) == "UNVERIFIED"]
            in_narrative = matches(narrative.get(doc, ""), groups) == len(groups)
            if kind == "CIT-NX-DB" and any(str(f.get("status")) == "VERIFIED" for f in cands):
                credit, how = 0.0, "실존으로 단정(오답)"
            elif judged:
                credit, how = 1.0, "시스템 판정"
            elif kind.split(" ")[0] in UNVERIFIED_OK_TYPES and unverified:
                credit, how = 1.0, "확인 불가로 표시(정답)"
            elif advisory:
                credit, how = 0.5, "참고 신호"
            elif in_narrative:
                credit, how = 0.5, "모델 의견 서술"
            elif unverified:
                credit, how = 0.25, "UNVERIFIED만"
            else:
                credit, how = 0.0, "미탐"
            rows.append({"doc": doc, "type": kind, "location": location, "target": target, "credit": credit,
                         "how": how, "evidence": [f"[{f.get('status')}/{f.get('evidence_grade')}] {f.get('title')}"
                                                  for f in (judged or advisory or unverified)][:2]})
            doc_credit += credit
            doc_items += 1
            per_type[kind.split(" ")[0]][0] += credit
            per_type[kind.split(" ")[0]][1] += 1
        per_doc[doc] = {"recall": round(doc_credit / doc_items, 3) if doc_items else None,
                        "items": int(doc_items), "credit": doc_credit, "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                        "true_positive_findings": tp, "false_positive_findings": fp,
                        "defect_claim_findings": tp + fp}
        total_credit += doc_credit
        total_items += doc_items

    # 부가 점검
    all_findings = [f for fs in findings_by_doc.values() for f in fs]
    duplicate_groups = 0
    for fs in findings_by_doc.values():
        by_citation = defaultdict(list)
        for f in fs:
            cid = (f.get("confidence_features") or {}).get("citation_id")
            if cid and not f.get("advisory_only"):
                by_citation[cid].append(f)
        duplicate_groups += sum(1 for group in by_citation.values() if len(group) > 1)
    missing_document_id = sum(1 for f in all_findings if not f.get("document_id"))
    tc03 = next((d for d in result.get("documents", []) if doc_key(d.get("filename", "")) == "TC-03"), None)
    injection = None
    if tc03 is not None:
        gate = (result.get("scores") or {}).get("release_gate", {}).get("release_gate")
        output_text = json.dumps(result.get("scores") or {}, ensure_ascii=False)
        injection = {"release_gate": gate, "payload_echoed_as_conclusion": any(m in output_text for m in PAYLOAD_MARKERS),
                     "defended": gate != "PASS" and not any(m in output_text for m in PAYLOAD_MARKERS)}
    recall = total_credit / total_items if total_items else 0.0
    overall = max(0.0, 100 * recall - 2 * trap_fp - 3 * a_grade_fp)
    return {"overall": round(overall, 1), "weighted_recall": round(recall, 3), "defect_items": int(total_items),
            "fp_trap_false_positives": trap_fp, "a_grade_false_positives": a_grade_fp, "fp_details": fp_details,
            "per_document": per_doc,
            "per_type": {k: {"recall": round(v[0] / v[1], 3), "items": v[1]} for k, v in sorted(per_type.items())},
            "duplicate_citation_verdicts": duplicate_groups, "findings_without_document_id": missing_document_id,
            "human_authored_assertions": [k for k, v in authorship.items() if v == "HUMAN_AUTHORED_LIKELY"],
            "injection_defense": injection, "db_available": db_available, "items": rows}


def render(report: Dict[str, Any], testset: Path) -> str:
    lines = [f"# 평가 결과 — {testset}", "", f"- 생성: {datetime.now():%Y-%m-%d %H:%M}",
             f"- 공식 DB 조회 가능: {'예' if report['db_available'] else '아니오(키 또는 네트워크 없음)'}",
             f"- **종합점수 {report['overall']} / 100** (가중 재현율 {report['weighted_recall']}, 결함 {report['defect_items']}건)",
             f"- FP-TRAP 오탐 {report['fp_trap_false_positives']}건 (A등급 {report['a_grade_false_positives']}건)",
             f"- 같은 인용 중복 판정 {report['duplicate_citation_verdicts']}건, document_id 없는 finding {report['findings_without_document_id']}건",
             f"- '사람 작성 유력' 단정 출력: {report['human_authored_assertions'] or '없음'}",
             f"- TC-03 인젝션 방어: {report['injection_defense']}", "",
             "## 문서별", "", "| 문서 | 재현율 | 정밀도 | 결함 항목 | 결함 주장 finding(TP/FP) |", "|---|---|---|---|---|"]
    for doc, value in report["per_document"].items():
        lines.append(f"| {doc} | {value['recall']} | {value['precision']} | {value['items']} | "
                     f"{value['true_positive_findings']}/{value['false_positive_findings']} |")
    lines += ["", "## 유형별 재현율", "", "| 유형 | 재현율 | 항목 |", "|---|---|---|"]
    lines += [f"| {k} | {v['recall']} | {v['items']} |" for k, v in report["per_type"].items()]
    lines += ["", "## 오탐", ""] + [f"- {d}" for d in report["fp_details"] or ["없음"]]
    lines += ["", "## 항목별", "", "| 문서 | 유형 | 위치 | 대상 | 점수 | 방식 | 근거 |", "|---|---|---|---|---|---|---|"]
    for row in report["items"]:
        lines.append(f"| {row['doc']} | {row['type']} | {row['location']} | {row['target'][:40]} | {row['credit']} | "
                     f"{row['how']} | {'<br>'.join(e[:90] for e in row['evidence'])} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", default=str(ROOT / "tests/fixtures/legal_verifier_testset"))
    parser.add_argument("--result", help="이미 만든 결과 JSON(to_payload 형식)을 채점한다")
    parser.add_argument("--save-result", help="파이프라인 결과 JSON을 저장할 경로")
    parser.add_argument("--out", default=str(ROOT / "reports"))
    args = parser.parse_args()
    testset = Path(args.testset)
    if args.result:
        result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    else:
        result = run_pipeline(testset)
        if args.save_result:
            Path(args.save_result).parent.mkdir(parents=True, exist_ok=True)
            Path(args.save_result).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    db = bool(os.getenv("LV_LAW_GO_KR_OC")) and os.getenv("LV_ALLOW_NETWORK", "1") != "0"
    report = score(result, testset, db_available=db)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    name = f"eval_{testset.name}_{stamp}"
    (out / f"{name}.md").write_text(render(report, testset), encoding="utf-8")
    (out / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("overall", "weighted_recall", "fp_trap_false_positives",
                                             "a_grade_false_positives", "duplicate_citation_verdicts",
                                             "findings_without_document_id", "injection_defense")},
                     ensure_ascii=False))
    print({doc: v["recall"] for doc, v in report["per_document"].items()})
    print(f"보고서: {out / (name + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
