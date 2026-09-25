"""eval_v4 정답지 채점기 v2 (SCORER_VERSION).

이전 채점기(scripts/evaluate_eval_v4.py, 0.9.0 시점, 이하 v1)의 문제와 v2의 기준
  v1: 사건번호·날짜·금액 하나만 finding 글에 들어 있어도 +4점으로 적중(HIT) 처리 → 유형이 다르거나 '확인됨(VERIFIED)'·
      '확인 불가(UNVERIFIED)'인 결과도 적중. 한 finding을 여러 정답에 재사용. 프로젝트 finding을 모든 문서에 붙임.
      대조군(D-05)이 결과에 없으면 finding 0건 → 오탐 0 → 보너스 15점. 오탐은 대조군에서만 셈.
  v2: 한 정답 항목이 '확정 적중'이려면 아래를 모두 만족해야 한다.
      (1) 문서: finding이 그 정답 문서의 finding이다(프로젝트 finding은 그 문서를 명시할 때만).
      (2) 유형: 결함 태그별 허용 finding 유형(TAG_TYPE_MAP)에 든다. 대응표에 없는 태그는 채점 불가로 드러낸다.
      (3) 근거: 정답 대상의 식별자(사건번호·날짜·금액·조문)가 finding 근거 글에 있다. 식별자가 없는 대상은 대상
          낱말 2개 이상이 있어야 한다. 정답 위치에 쪽 번호가 있고 finding에도 쪽이 있으면 같아야 한다.
      (4) 판정 방향: 태그별 허용 상태(CONTRADICTED 등)이고 참고 신호(advisory_only)가 아니다. VERIFIED는 어떤 경우도
          적중이 아니다. UNVERIFIED·참고 신호로만 맞은 항목은 '참고 신호 적중'으로 따로 센다.
      (5) 일대일: finding 하나는 정답 하나에만 쓴다. finding이 여러 결함을 명시적으로 나열한 경우(merged_findings·
          missing_items·differences 등)에만 나열 항목마다 하나씩 대응한다(최대 이분 매칭).
      대조군(결함 항목이 없는 문서)이 결과에 없거나, 추출 실패·격리되면 '평가 불완전'이다(오탐 0으로 보지 않는다).
      오탐은 전체 문서에서 센다. 합산 종합점수는 내지 않고 지표를 나눠 보고한다.
v1과 v2의 수치는 정의가 달라 증감으로 비교하지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.eval_testset import (_INJECTION, _norm, finding_text, is_control_false_positive,  # noqa: E402
                                  is_defect_claim, models_called)

SCORER_VERSION = "eval_v4-scorer-2"

# 결함 태그 → 적중으로 인정하는 finding 유형
TAG_TYPE_MAP: Dict[str, Set[str]] = {
    "CIT-DATE": {"CASE_CITATION_ERROR", "CASE_METADATA_MISMATCH"},
    "CIT-NX": {"CASE_NOT_FOUND", "CASE_CITATION_ERROR", "AI_HALLUCINATED_CONTENT"},
    "CIT-MIS": {"CASE_HOLDING_DISTORTION", "CASE_QUOTE_MISMATCH", "CASE_RELEVANCE_WEAK", "SELECTIVE_QUOTATION_SIGNAL"},
    "QUOTE-MOD": {"CASE_QUOTE_MISMATCH", "QUOTE_MISMATCH", "STATUTE_TEXT_MISMATCH", "CASE_HOLDING_DISTORTION"},
    "OVR": {"OVERCLAIM", "UNSUPPORTED_GENERALIZATION", "LEGAL_ARGUMENT_INVALID", "REASONING_GAP",
            "LEGAL_REQUIREMENT_OMITTED", "UNCERTAINTY_NOT_DISCLOSED", "AUTHORITY_RANK_ERROR"},
    "LOGIC": {"LEGAL_ARGUMENT_INVALID", "REASONING_GAP", "FACT_CONTRADICTION", "LEGAL_REQUIREMENT_OMITTED"},
    "LAW-MIS": {"LAW_CITATION_ERROR", "STATUTE_TEXT_MISMATCH", "TEMPORAL_LAW_MISMATCH"},
    "LAW-NX": {"STATUTE_NONEXISTENT", "LAW_CITATION_ERROR"},
    "TEMPORAL": {"TEMPORAL_LAW_MISMATCH", "TIMELINE_CONTRADICTION"},
    "ARITH": {"ARITHMETIC_MISMATCH", "CALCULATION_INVARIANT_VIOLATION"},
    "ARITH-SUM": {"ARITHMETIC_MISMATCH", "CALCULATION_INVARIANT_VIOLATION"},
    "AMOUNT-WORDS": {"ARITHMETIC_MISMATCH"},
    "DATE-WEEKDAY": {"TIMELINE_CONTRADICTION", "EVIDENCE_DATE_INVALID"},
    "DAYS": {"TIMELINE_CONTRADICTION", "ARITHMETIC_MISMATCH"},
    "DATE-INVALID": {"TIMELINE_CONTRADICTION", "EVIDENCE_DATE_INVALID", "CASE_CITATION_ERROR"},
    "DATE-INVERSION": {"TIMELINE_CONTRADICTION", "EVIDENCE_TIMELINE_INVERSION"},
    "XDOC": {"CROSS_DOCUMENT_CONTRADICTION", "FACT_CONTRADICTION"},
    "COUNT": {"FACT_CONTRADICTION", "ARITHMETIC_MISMATCH"},
    "EVID-MISSING": {"EVIDENCE_NOT_PROVIDED", "EVIDENCE_REFERENCE_MISSING"},
    "EVID-NUM-GAP": {"EVIDENCE_NUMBERING_GAP", "EVIDENCE_LIST_MISMATCH"},
    "AI-META": {"AI_AUTHORSHIP_LIKELY", "MODEL_ATTRIBUTION_SIGNAL", "AUTHORSHIP_METADATA_LEAK", "METADATA_ANOMALY"},
    "AI-RESIDUE": {"DRAFT_ARTIFACT", "TEMPLATE_RESIDUE", "AI_AUTHORSHIP_LIKELY"},
    "OCR-REQ": {"OCR_LOW_QUALITY", "OCR_LAYER_MISMATCH", "UNSUPPORTED_FORMAT", "PARSE_ERROR"},
}
# 판정 방향: 태그별로 '결함 확정'으로 인정하는 상태. 기본은 CONTRADICTED.
CONFIRMED_STATUSES: Dict[str, Set[str]] = {
    "CIT-NX": {"CONTRADICTED", "NOT_FOUND"},
    "LAW-NX": {"CONTRADICTED", "NOT_FOUND"},
}
SUSPICION_TAG_PREFIXES = ("INJ-", "AI-", "OVR", "LOGIC", "CIT-MIS", "QUOTE-MOD", "EVID-", "XDOC")
# '확인 불가'가 정답인 태그(OCR 필요 쪽을 판독하지 못했다고 밝히는 것이 올바른 결과)
UNVERIFIED_IS_CORRECT = {"OCR-REQ"}
MULTI_DEFECT_KEYS = ("merged_findings", "missing_items", "differences", "violations", "defects")
NOT_EVALUATED_TYPES = {"SPECIMEN_DOCUMENT_DECLARED"}

IDENT_RE = re.compile(
    r"(?:19|20)\d{2}\s*[가-힣]{1,3}\s*\d{1,7}"                           # 사건번호
    r"|(?:19|20)\d{2}\s*[.년]\s*\d{1,2}\s*[.월]\s*\d{1,2}"                 # 날짜
    r"|\d{1,3}(?:,\d{3})+"                                                # 금액
    r"|제\s*\d+\s*조(?:\s*의\s*\d+)?"                                    # 조문
    r"|(?:갑|을|병|정)\s*(?:가|나)?\s*제?\s*\d+\s*호증(?:의\s*\d+)?")          # 호증
PAGE_RE = re.compile(r"(?:\bp\.?\s*(\d+)|(\d+)\s*(?:쪽|페이지|면)\b)", re.IGNORECASE)
STOPWORDS = {"및", "등", "the", "에서", "으로", "관련", "기재", "문서", "내용", "부분", "항목"}


# --- 정답지 읽기 ------------------------------------------------------------------------------------
def base_tag(tag: str) -> str:
    """'INJ-TINY (회귀)' → 'INJ-TINY'."""
    return re.sub(r"\s*\(.*?\)\s*$", "", str(tag or "")).strip()


def tag_parts(tag: str) -> List[str]:
    return [p.strip() for p in base_tag(tag).split("/") if p.strip()]


def allowed_types(tag: str) -> Optional[Set[str]]:
    """태그가 허용하는 finding 유형. 대응표에 없는 부분이 있으면 None(채점 불가)."""
    out: Set[str] = set()
    for part in tag_parts(tag):
        if part.startswith("INJ-"):
            out |= _INJECTION
        elif part in TAG_TYPE_MAP:
            out |= TAG_TYPE_MAP[part]
        else:
            return None
    return out


def confirmed_statuses(tag: str) -> Set[str]:
    out = {"CONTRADICTED"}
    for part in tag_parts(tag):
        out |= CONFIRMED_STATUSES.get(part, set())
        if part.startswith(SUSPICION_TAG_PREFIXES):
            out.add("SUSPICIOUS")
    return out


def gt_items(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for item in doc.get("items") or []:
        if isinstance(item, dict):
            out.append({"tag": str(item.get("tag") or item.get("type") or ""),
                        "loc": str(item.get("loc") or item.get("location") or ""),
                        "target": str(item.get("target") or ""),
                        "desc": str(item.get("desc") or item.get("description") or "")})
        else:
            values = list(item) + ["", "", "", ""]
            out.append({"tag": str(values[0]), "loc": str(values[1]), "target": str(values[2]),
                        "desc": str(values[3])})
    return out


# --- 결과(report) 읽기 --------------------------------------------------------------------------------
def _stem(name: str) -> str:
    return Path(str(name or "")).stem


def doc_matches(gt_doc: Dict[str, Any], report_doc: Dict[str, Any]) -> bool:
    """정답 문서 ↔ 결과 문서. id가 같거나, 파일명이 같거나, 파일명·id가 정답 id로 시작(구분자 뒤)하면 같은 문서."""
    gid, gfile = str(gt_doc.get("id") or ""), str(gt_doc.get("file") or "")
    rid, rfile = str(report_doc.get("document_id") or ""), str(report_doc.get("filename") or "")
    if gid and gid in (rid, _stem(rfile)):
        return True
    if gfile and (gfile == rfile or _stem(gfile) == _stem(rfile)):
        return True
    return bool(gid) and any(re.match(rf"^{re.escape(gid)}[_\-.\s]", value) for value in (rid, _stem(rfile)) if value)


def _entries(finding: Dict[str, Any]) -> List[str]:
    """finding이 명시적으로 나열한 개별 결함(일대일 대응의 슬롯). 없으면 finding 전체가 슬롯 하나."""
    features = finding.get("confidence_features") or {}
    for key in MULTI_DEFECT_KEYS:
        value = features.get(key)
        if isinstance(value, list) and len(value) > 1:
            return [_norm(json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v)
                    for v in value]
    return [finding_text(finding)]


def anchors(target: str) -> Tuple[List[str], List[str]]:
    """(식별자 목록, 대상 낱말 목록). 식별자는 공백을 없애 비교한다."""
    idents = [re.sub(r"\s+", "", m.group(0)) for m in IDENT_RE.finditer(target)]
    words = [w for w in re.findall(r"[가-힣A-Za-z0-9_]{2,}", target) if w not in STOPWORDS]
    return idents, words


def _date_forms(ident: str) -> List[str]:
    m = re.fullmatch(r"((?:19|20)\d{2})[.년](\d{1,2})[.월](\d{1,2})", ident)
    if not m:
        return [ident]
    y, mo, d = m.groups()
    return [ident, f"{y}.{int(mo)}.{int(d)}", f"{y}-{int(mo):02d}-{int(d):02d}", f"{y}년{int(mo)}월{int(d)}일"]


def anchor_ok(target: str, loc: str, text: str, finding: Dict[str, Any]) -> bool:
    compact = re.sub(r"\s+", "", text)
    idents, words = anchors(target)
    if idents:
        if not any(form in compact for ident in idents for form in _date_forms(ident)):
            return False
    else:
        if len({w for w in words if w.lower() in text.lower()}) < 2:
            return False
    page = PAGE_RE.search(loc or "")
    if page and finding.get("page") not in (None, ""):
        return int(page.group(1) or page.group(2)) == int(finding["page"])
    return True


# --- 이분 매칭 ----------------------------------------------------------------------------------------
def _max_matching(edges: Dict[int, List[Tuple[str, int]]]) -> Dict[int, Tuple[str, int]]:
    """정답 항목 → (finding_id, 슬롯) 최대 매칭(증가 경로)."""
    owner: Dict[Tuple[str, int], int] = {}

    def augment(item: int, seen: Set[Tuple[str, int]]) -> bool:
        for slot in edges.get(item, []):
            if slot in seen:
                continue
            seen.add(slot)
            if slot not in owner or augment(owner[slot], seen):
                owner[slot] = item
                return True
        return False

    for item in edges:
        augment(item, set())
    return {item: slot for slot, item in owner.items()}


# --- 채점 --------------------------------------------------------------------------------------------
def score(answer_key: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    report_docs = report.get("documents") or []
    project = report.get("project_findings") or []
    doc_results: List[Dict[str, Any]] = []
    all_items: List[Dict[str, Any]] = []
    evaluated_findings: Dict[str, Dict[str, Any]] = {}
    unmapped_tags: Set[str] = set()
    incomplete_reasons: List[str] = []

    for gt_doc in answer_key.get("documents") or []:
        gid = str(gt_doc.get("id") or gt_doc.get("file") or "")
        items = gt_items(gt_doc)
        defects = [i for i in items if base_tag(i["tag"]) != "FP-TRAP"]
        traps = [i for i in items if base_tag(i["tag"]) == "FP-TRAP"]
        is_control = not defects or str(gt_doc.get("expected") or "").upper() == "PASS"
        matched_docs = [d for d in report_docs if doc_matches(gt_doc, d)]
        doc_ids = {str(d.get("document_id")) for d in matched_docs}
        filenames = {str(d.get("filename")) for d in matched_docs}
        findings = [f for d in matched_docs for f in d.get("findings") or []]
        # 프로젝트 finding은 이 문서를 명시할 때만(모든 문서에 붙이지 않는다)
        for f in project:
            listed = set(map(str, (f.get("confidence_features") or {}).get("documents") or []))
            if str(f.get("document_id")) in doc_ids or listed & (doc_ids | filenames):
                findings.append(f)
        findings = [f for f in findings if str(f.get("type")) not in NOT_EVALUATED_TYPES]
        for f in findings:
            evaluated_findings[str(f.get("finding_id"))] = f

        coverage = "EVALUATED"
        if not matched_docs:
            coverage = "MISSING_FROM_REPORT"
        elif any(d.get("quarantined") for d in matched_docs):
            coverage = "QUARANTINED"
        elif any(p.get("status") not in ("EXTRACTED", "OCR_EXTRACTED", "OCR")
                 for d in matched_docs for p in d.get("page_coverage") or []) \
                or any(str(f.get("type")) in ("PARSE_ERROR", "UNSUPPORTED_FORMAT") for f in findings):
            coverage = "EXTRACTION_INCOMPLETE"
        if coverage != "EVALUATED":
            incomplete_reasons.append(f"{gid}: {coverage}")

        control_fp = [f for f in findings if is_control_false_positive(f)] if is_control else []
        doc_results.append({"doc": gid, "control": is_control, "coverage": coverage, "defect_items": len(defects),
                            "control_status": (None if not is_control else
                                               "INCOMPLETE" if coverage != "EVALUATED" else
                                               "PASS" if not control_fp else "FAIL"),
                            "control_false_positives": [_brief(f) for f in control_fp],
                            "_findings": findings, "_traps": traps})
        for item in defects:
            all_items.append({**item, "doc": gid, "_findings": findings, "_coverage": coverage})

    # 확정 적중 후보(간선)와 참고 신호 적중
    edges: Dict[int, List[Tuple[str, int]]] = {}
    reference: Dict[int, List[str]] = defaultdict(list)
    for index, item in enumerate(all_items):
        allowed = allowed_types(item["tag"])
        if allowed is None:
            unmapped_tags.add(base_tag(item["tag"]))
            item["result"] = "NOT_SCORABLE_UNMAPPED_TAG"
            continue
        statuses = confirmed_statuses(item["tag"])
        for f in item["_findings"]:
            if str(f.get("type")) not in allowed or str(f.get("status")) == "VERIFIED":
                continue
            fid = str(f.get("finding_id"))
            confirmed = (str(f.get("status")) in statuses and not f.get("advisory_only"))
            if base_tag(item["tag"]) in UNVERIFIED_IS_CORRECT and str(f.get("status")) == "UNVERIFIED":
                confirmed = True
            for slot, text in enumerate(_entries(f)):
                if not anchor_ok(item["target"], item["loc"], text, f):
                    continue
                if confirmed:
                    edges.setdefault(index, []).append((fid, slot))
                elif str(f.get("status")) in ("UNVERIFIED", "SUSPICIOUS", "CONTRADICTED", "NOT_FOUND"):
                    reference[index].append(fid)
    assignment = _max_matching(edges)
    used_findings = {fid for fid, _ in assignment.values()}
    for index, item in enumerate(all_items):
        if item.get("result"):
            continue
        if index in assignment:
            item["result"], item["finding"] = "CONFIRMED_HIT", assignment[index][0]
        elif reference.get(index):
            item["result"], item["finding"] = "REFERENCE_ONLY", reference[index][0]
        else:
            item["result"], item["finding"] = "MISS", None

    # 오탐: 전체 문서의 결함 주장 finding 중 어느 정답에도 쓰이지 않은 것(정답지 밖 주장) + FP-TRAP·대조군
    defect_claims = [f for f in evaluated_findings.values() if is_defect_claim(f)]
    unmatched_claims = [f for f in defect_claims if str(f.get("finding_id")) not in used_findings]
    trap_fps = []
    for doc in doc_results:
        for trap in doc["_traps"]:
            for f in doc["_findings"]:
                if is_defect_claim(f) and anchor_ok(trap["target"], trap["loc"], finding_text(f), f):
                    trap_fps.append({"doc": doc["doc"], "trap": trap["target"], "finding": _brief(f)})

    scorable = [i for i in all_items if i["result"] != "NOT_SCORABLE_UNMAPPED_TAG"]
    hits = [i for i in scorable if i["result"] == "CONFIRMED_HIT"]
    ref_only = [i for i in scorable if i["result"] == "REFERENCE_ONLY"]
    all_eval = list(evaluated_findings.values())
    manifest = report.get("run_manifest") or {}
    environment = manifest.get("environment") or {}
    if unmapped_tags:
        incomplete_reasons.append("대응표에 없는 결함 태그: " + ", ".join(sorted(unmapped_tags)))
    controls = [d for d in doc_results if d["control"]]
    if not controls:
        incomplete_reasons.append("정답지에 대조군 문서가 없다")

    return {
        "scorer_version": SCORER_VERSION,
        "criteria": __doc__.strip().splitlines()[2:18],
        "evaluation_status": "INCOMPLETE" if incomplete_reasons else "COMPLETE",
        "incomplete_reasons": incomplete_reasons,
        "composite_score": None,
        "composite_note": "정의가 다른 항목을 더한 종합점수는 내지 않는다. 아래 지표를 따로 읽는다.",
        "metrics": {
            "defect_items_scorable": len(scorable),
            "confirmed_hits": len(hits),
            "recall_confirmed": _ratio(len(hits), len(scorable)),
            "reference_only_items": len(ref_only),
            "reference_only_ratio": _ratio(len(ref_only), len(scorable)),
            "defect_claim_findings": len(defect_claims),
            "defect_claims_used_for_hits": len({i["finding"] for i in hits}),
            "precision_lower_bound": _ratio(len({i["finding"] for i in hits}), len(defect_claims)),
            "unmatched_defect_claims": len(unmatched_claims),
            "fp_trap_false_positives": len(trap_fps),
            "control_false_positives": sum(len(d["control_false_positives"]) for d in controls),
            "unverified_findings": sum(1 for f in all_eval if str(f.get("status")) == "UNVERIFIED"),
            "unverified_ratio": _ratio(sum(1 for f in all_eval if str(f.get("status")) == "UNVERIFIED"), len(all_eval)),
            "unverified_items_reported": len(report.get("unverified_items") or []),
        },
        "coverage": {
            "documents_in_answer_key": len(doc_results),
            "documents_evaluated": sum(1 for d in doc_results if d["coverage"] == "EVALUATED"),
            "per_document": [{k: v for k, v in d.items() if not k.startswith("_")} for d in doc_results],
            "engines_not_executed": manifest.get("not_executed") or [],
            "missing_resources": manifest.get("missing_resources") or environment.get("missing_required") or [],
            "environment_complete": environment.get("complete"),
            "environment_fingerprint": environment.get("fingerprint"),
            "regression_comparable": manifest.get("regression_comparable"),
            "models_called": models_called(report),
        },
        "items": [{k: v for k, v in i.items() if not k.startswith("_")} for i in all_items],
        "fp_trap_details": trap_fps,
        "unmatched_defect_claims": [_brief(f) for f in unmatched_claims][:200],
    }


def _ratio(a: int, b: int) -> Optional[float]:
    return round(a / b, 4) if b else None


def _brief(f: Dict[str, Any]) -> Dict[str, Any]:
    return {"finding_id": f.get("finding_id"), "document_id": f.get("document_id"), "type": f.get("type"),
            "status": f.get("status"), "grade": f.get("evidence_grade"), "advisory_only": bool(f.get("advisory_only")),
            "title": str(f.get("title") or "")[:120]}


def write_new(path: Path, data: Dict[str, Any]) -> Path:
    """기존 산출물을 덮어쓰지 않는다(같은 이름이 있으면 실패)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return path


def iter_markdown(result: Dict[str, Any]) -> Iterable[str]:
    m, c = result["metrics"], result["coverage"]
    yield f"# eval_v4 채점 결과 ({result['scorer_version']})"
    yield f"- 평가 상태: **{result['evaluation_status']}** " + ("; ".join(result["incomplete_reasons"]) or "")
    yield f"- 환경 완전: {c['environment_complete']} · 지문 {c['environment_fingerprint']} · 비교 가능: {c['regression_comparable']}" \
          f" · 모델 호출: {c['models_called']} · 미실행 엔진: {', '.join(c['engines_not_executed']) or '없음'}"
    yield f"- 확정 적중 {m['confirmed_hits']}/{m['defect_items_scorable']} (재현율 {m['recall_confirmed']})," \
          f" 참고 신호로만 맞음 {m['reference_only_items']}"
    yield f"- 결함 주장 finding {m['defect_claim_findings']}건 중 정답에 쓰인 것 {m['defect_claims_used_for_hits']}" \
          f" (정밀도 하한 {m['precision_lower_bound']}), 정답지 밖 주장 {m['unmatched_defect_claims']}"
    yield f"- FP-TRAP 오탐 {m['fp_trap_false_positives']} · 대조군 오탐 {m['control_false_positives']}" \
          f" · UNVERIFIED 비율 {m['unverified_ratio']}"
    yield "- 종합점수: 내지 않음(" + result["composite_note"] + ")"
