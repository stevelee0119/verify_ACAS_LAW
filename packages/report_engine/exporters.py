"""제20.2장 출력 파일: JSON / CSV / XLSX / Chain of Custody Manifest."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, List

from packages.common.enums import MM4_ADVISORY_TYPES

FINDING_COLUMNS = [
    "finding_id", "type", "status", "severity", "evidence_grade", "confidence",
    "document_id", "page", "block_id", "title", "detail", "engine",
    "meta_message_type", "advisory_only", "review_status", "sources", "has_sealed_content",
]


def findings_to_rows(findings: List[Any], *, reveal_sealed: bool = False) -> List[Dict[str, Any]]:
    rows = []
    for finding in findings:
        data = finding.to_dict(reveal_sealed=reveal_sealed)
        row = {key: data.get(key) for key in FINDING_COLUMNS}
        row["sources"] = ";".join(data.get("sources") or [])
        rows.append(row)
    return rows


def to_json(run_result: Any, *, reveal_sealed: bool = False) -> bytes:
    """제20.2장 JSON 전체 검증결과."""
    payload = {
        "run_id": run_result.run_id,
        "project_id": run_result.project_id,
        "state": str(run_result.state),
        "verification_key": run_result.verification_key,
        "started_at": run_result.started_at.isoformat(),
        "finished_at": run_result.finished_at.isoformat() if run_result.finished_at else None,
        "scores": run_result.scores,
        "timeline": run_result.timeline,
        "unavailable_sources": run_result.unavailable_sources,
        "unverified_items": run_result.unverified_items,
        "errors": run_result.errors,
        "documents": [
            {
                "document_id": d.document_id,
                "filename": d.filename,
                "sha256": d.normalized.sha256 if d.normalized else None,
                "parser": d.normalized.parser_name if d.normalized else None,
                "quarantined": d.quarantined,
                "rag_indexable": d.rag_indexable,
                "warnings": d.warnings,
                "authorship": d.authorship,
                "masked_preview": d.masked_preview,
                "citations": d.citations,
                "claims": d.claims,
                "entities": d.entities,
                "events": d.events,
                "engine_data": d.engine_data,
                "findings": [f.to_dict(reveal_sealed=reveal_sealed) for f in d.findings],
            }
            for d in run_result.documents
        ],
        "project_findings": [f.to_dict(reveal_sealed=reveal_sealed) for f in run_result.project_findings],
        "notice": (
            "봉인된 원문(sealed)은 사용자 명시적 열람 요청이 있는 경우에만 포함된다. "
            "본 결과는 검증 보조자료이며 최종 법적 평가는 사용자에게 있다."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def to_csv(findings: List[Any], *, reveal_sealed: bool = False) -> bytes:
    """제20.2장 CSV Findings."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FINDING_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in findings_to_rows(findings, reveal_sealed=reveal_sealed):
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")  # Excel 한글 호환


def to_xlsx(run_result: Any, *, reveal_sealed: bool = False) -> bytes:
    """제20.2장 XLSX 오류표."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = openpyxl.Workbook()

    # 1) 요약
    summary = workbook.active
    summary.title = "검증개요"
    summary.append(["항목", "값"])
    summary.append(["Run ID", run_result.run_id])
    summary.append(["Project ID", run_result.project_id])
    summary.append(["상태", str(run_result.state)])
    summary.append(["Verification Key", run_result.verification_key])
    summary.append(["생성시각", datetime.utcnow().isoformat()])
    summary.append(["문서 수", len(run_result.documents)])
    summary.append(["Finding 수", len(run_result.all_findings)])
    for axis, value in (run_result.scores.get("axes") or {}).items():
        summary.append([axis, json.dumps(value, ensure_ascii=False)])
    summary.append(["사용 불가 Source", ", ".join(s["name"] for s in run_result.unavailable_sources)])

    # 2) Findings
    sheet = workbook.create_sheet("Findings")
    sheet.append(FINDING_COLUMNS)
    severity_fill = {
        "CRITICAL": PatternFill("solid", fgColor="FFC7CE"),
        "HIGH": PatternFill("solid", fgColor="FFD9B3"),
        "MEDIUM": PatternFill("solid", fgColor="FFF2CC"),
    }
    main = [f for f in run_result.all_findings if not f.advisory_only]
    for finding in sorted(main, key=lambda f: -f.severity.rank):
        row = findings_to_rows([finding], reveal_sealed=reveal_sealed)[0]
        sheet.append([row.get(c) for c in FINDING_COLUMNS])
        fill = severity_fill.get(str(finding.severity))
        if fill:
            for cell in sheet[sheet.max_row]:
                cell.fill = fill

    # 3) 참고 신호 (MM-4) — 본문과 분리 (제7-A.4장)
    advisory_sheet = workbook.create_sheet("참고신호(MM-4)")
    advisory_sheet.append(FINDING_COLUMNS)
    for finding in run_result.all_findings:
        if finding.advisory_only or finding.type in MM4_ADVISORY_TYPES:
            row = findings_to_rows([finding], reveal_sealed=reveal_sealed)[0]
            advisory_sheet.append([row.get(c) for c in FINDING_COLUMNS])

    # 4) 미검증 항목
    unverified = workbook.create_sheet("미검증항목")
    unverified.append(["kind", "document_id", "citation_id", "type", "raw_text", "reason"])
    for item in run_result.unverified_items:
        unverified.append([item.get(k) for k in ("kind", "document_id", "citation_id", "type", "raw_text", "reason")])

    for worksheet in workbook.worksheets:
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(vertical="center")
        for column in worksheet.columns:
            width = max((len(str(c.value)) for c in column if c.value), default=10)
            worksheet.column_dimensions[column[0].column_letter].width = min(60, max(12, width + 2))

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def to_manifest(audit_chain: Any, project_id: str, run_result: Any) -> bytes:
    """제20.2장 Chain of Custody Manifest JSON."""
    manifest = audit_chain.manifest(project_id=project_id)
    manifest["run"] = {
        "run_id": run_result.run_id,
        "verification_key": run_result.verification_key,
        "state": str(run_result.state),
        "documents": [
            {
                "document_id": d.document_id,
                "filename": d.filename,
                "sha256": d.normalized.sha256 if d.normalized else None,
            }
            for d in run_result.documents
        ],
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
