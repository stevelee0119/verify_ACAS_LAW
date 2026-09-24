"""사람이 읽는 보고서(PDF·Word·Excel)의 분량 기준.

전체 기술 기록(실행 당시의 모든 필드)을 PDF에 그대로 실으면 인용이 많은 사건에서 2천 쪽을
넘었다(측정: 241개 finding 사건 2,234쪽 중 2,195쪽이 기술 기록). 사람이 검토에 쓰는 내용은
앞의 40쪽 남짓이다.

요약본(SUMMARY)은 판단에 필요한 것을 모두 싣되 원자료 나열을 줄인다.
  - 판정·미확인 항목·인용별 단계는 그대로 싣는다.
  - 출처 조회 기록은 출처·상태별 건수와 실패한 조회만, 사람 검토 기록은 진행된 항목만 싣는다.
  - 전체 기술 기록은 함께 생성하는 '검증 상세(JSON)'와 고정본 스냅샷(해시로 고정)에 보존한다.
전체본(FULL)은 종전처럼 전체 기술 기록을 보고서에 싣는다.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

SUMMARY = "SUMMARY"
FULL = "FULL"
PROBLEM_SOURCE_LIMIT = 50
OK_STATUSES = {"READY", "OK", "VERIFIED"}


def detail_level(run_result: Any) -> str:
    """보고서 분량. 분량 기록이 없는 예전 고정본은 발행 당시와 같게 전체본으로 다시 만든다."""
    metadata = getattr(run_result, "report_metadata", None)
    if metadata:
        return metadata.get("detail_level") or FULL
    return SUMMARY


def _collect_stages(value: Any, path: str, out: List[Dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "unavailable_stages" and item:
                for stage in (item if isinstance(item, list) else [item]):
                    out.append({"path": path, "stage": stage})
            else:
                _collect_stages(item, f"{path}.{key}" if path else key, out)
    elif isinstance(value, list):
        for item in value:
            _collect_stages(item, path, out)


def evidence_summary(run_result: Any) -> Dict[str, Any]:
    """요약본에 싣는 검증 근거. 수행하지 못한 단계와 실패한 조회는 빠짐없이 싣는다."""
    stages: List[Dict[str, Any]] = []
    source_counts: Counter = Counter()
    problems: List[Dict[str, Any]] = []
    coverage: Counter = Counter()
    coverage_problems: List[str] = []
    for document in run_result.documents:
        engine_data = getattr(document, "engine_data", {}) or {}
        _collect_stages(engine_data, document.filename, stages)
        for page in engine_data.get("page_coverage", []) or []:
            status = str((page or {}).get("status", "unknown")) if isinstance(page, dict) else str(page)
            coverage[status] += 1
            if status.lower() not in ("ok", "verified", "text", "complete", "visible_text"):
                coverage_problems.append(f"{document.filename} {page.get('page', '?') if isinstance(page, dict) else ''}쪽: {status}")
        for record in getattr(document, "source_records", []) or []:
            source = record.to_dict() if hasattr(record, "to_dict") else dict(record)
            status = str(source.get("status", "UNKNOWN"))
            source_counts[(str(source.get("adapter", "-")), status)] += 1
            if status.upper() not in OK_STATUSES:
                problems.append({key: source.get(key) for key in (
                    "adapter", "status", "query", "url", "note", "retrieved_at", "response_hash")})
    executions = Counter()
    for execution in getattr(run_result, "model_executions", []) or []:
        item = execution if isinstance(execution, dict) else getattr(execution, "__dict__", {})
        executions[(str(item.get("provider", "-")), str(item.get("status", item.get("outcome", "-"))))] += 1
    return {
        "unavailable_stages": stages,
        "source_counts": [{"adapter": a, "status": s, "count": n} for (a, s), n in sorted(source_counts.items())],
        "problem_sources": problems[:PROBLEM_SOURCE_LIMIT],
        "problem_sources_omitted": max(0, len(problems) - PROBLEM_SOURCE_LIMIT),
        "page_coverage": dict(coverage),
        "page_coverage_problems": coverage_problems,
        "model_executions": [{"provider": p, "status": s, "count": n} for (p, s), n in sorted(executions.items())],
    }


def reviewed_workflow(rows: List[Dict[str, Any]]) -> tuple:
    """사람 검토 기록 중 진행·의견·메모가 있는 것만 남기고, 나머지는 건수로 센다."""
    active = [r for r in rows if r.get("workflow_state") not in (None, "NOT_STARTED")
              or r.get("decision") not in (None, "UNDECIDED") or r.get("note")]
    return active, len(rows) - len(active)


def assessed_claims(rows: List[Dict[str, Any]]) -> tuple:
    """주장·증거 검토표 중 사람이 입장·증거를 적은 주장만 남기고, 나머지는 건수로 센다."""
    active = [r for r in rows if (r.get("assessment") or {}).get("position", "UNASSESSED") != "UNASSESSED"
              or r.get("review_status") not in (None, "UNASSESSED")]
    return active, len(rows) - len(active)


_GROUPS = [("확인", {"CONFIRMED", "TEXT_AVAILABLE"}), ("일부", {"PARTIAL"}),
           ("불일치", {"MISMATCH", "INVALID_FORMAT"}),
           ("미발견", {"NOT_FOUND_IN_SEARCHED_SCOPE", "NOT_FOUND_IN_SELECTED_VERSION", "DELETED"}),
           ("미확인", {"UNVERIFIED", "NOT_RUN"}), ("사람 검토", {"REVIEW_NEEDED"})]


def component_line(components: List[Dict[str, Any]]) -> str:
    """인용 한 건의 단계별 결과를 한 줄로 줄인다. 예: '확인: 법령 존재·조문 존재 / 미확인: 시간적 적용'."""
    parts = []
    for name, statuses in _GROUPS:
        labels = [c["label"] for c in components if c.get("status") in statuses]
        if labels:
            parts.append(f"{name}: {'·'.join(labels)}")
    return ("\n" + " / ".join(parts)) if parts else ""


def _citation_key(citation: Dict[str, Any]) -> tuple:
    identity = tuple(citation.get(k) for k in ("type", "canonical_case_number", "case_number", "law_name",
                                                 "article", "paragraph", "item", "title", "doi"))
    identity += ((citation.get("attributes") or {}).get("rule_number"),)
    if not any(identity[1:]):  # 구조화 필드가 없으면 원문 표기로 묶는다
        identity += (" ".join(str(citation.get("raw_text") or "").split()),)
    return identity


def grouped_citations(documents: List[Any]) -> List[Dict[str, Any]]:
    """같은 문서에서 같은 인용(같은 판정)이 여러 번 나오면 한 줄로 묶고 면과 횟수를 적는다."""
    rows: Dict[tuple, Dict[str, Any]] = {}
    for document in documents:
        verdicts = {v["citation_id"]: v for v in (document.engine_data.get("legal_verdicts") or [])}
        for citation in document.citations:
            verdict = verdicts.get(citation["citation_id"], {})
            key = (document.filename, _citation_key(citation), verdict.get("status", "UNVERIFIED"))
            row = rows.setdefault(key, {"filename": document.filename, "citation": citation, "verdict": verdict,
                                        "pages": [], "count": 0})
            row["count"] += 1
            if citation.get("page") and citation["page"] not in row["pages"]:
                row["pages"].append(citation["page"])
    return list(rows.values())


def grouped_unverified(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """같은 대상·같은 사유의 미확인 항목을 한 줄로 묶는다(건수 보존)."""
    rows: Dict[tuple, Dict[str, Any]] = {}
    for item in items:
        if item.get("kind") == "applicability":
            continue  # 확인 완료 인용(v3 D4)은 미확인 목록에 넣지 않는다
        target = " ".join(str(item.get("raw_text") or item.get("document_id") or "-").split())
        key = (item.get("kind", "-"), target, item.get("reason") or "-")
        rows.setdefault(key, {"kind": key[0], "target": target, "reason": key[2], "count": 0})["count"] += 1
    return list(rows.values())


FULL_RECORD_NOTE = (
    "요약본에는 전체 기술 기록(실행 당시의 모든 필드)을 싣지 않았습니다. 전체 기록은 함께 생성된 "
    "'검증 상세(JSON)' 산출물과 위 고정본 스냅샷 해시로 고정된 기록에 빠짐없이 보존되며, 산출물의 "
    "SHA-256은 보고서 목록과 무결성 기록에서 확인할 수 있습니다. 보고서에 전체 기록이 필요하면 "
    "'전체 기술 기록 포함'으로 다시 생성하십시오."
)
