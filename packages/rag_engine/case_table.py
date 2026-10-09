"""Bounded, row-oriented ingestion for structured precedent tables.

The ordinary spreadsheet parser remains the compatibility path.  This module is
used only when a workbook has the semantic headers of a precedent table.  Each
row is a parent record; chunks never cross a row boundary and carry the case
head so an issue and its holding stay together during retrieval.
"""
from __future__ import annotations

import csv
import hashlib
import re
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from packages.adversarial_engine import AdversarialScanner
from packages.adversarial_engine.classifier import find_pattern_hits_batch
from packages.adversarial_engine.normalize import normalize_for_classification
from packages.common.enums import MetaMessageType, Severity
from packages.common.schemas import Block, NormalizedDocument, Page

CASE_TABLE_VERSION = "case-table-v1"
MAX_HEADER_ROWS = 40
MAX_CELL_CHARS = 200_000
MAX_ROW_CHARS = 1_000_000
MAX_ROWS = 50_000
MAX_SECONDS = 25.0

_ALIASES = {
    "number": ("번호", "일련번호", "no", "number"),
    "title": ("제목", "판례명", "사건명"),
    "case_info": ("판례정보", "사건정보", "사건기본정보", "판결정보"),
    "issue": ("쟁점", "쟁점사항", "법적쟁점"),
    "reason": ("선정이유", "선정사유", "선정근거"),
    "holding": ("판결요지", "결정요지", "판결결론", "요지"),
    "facts": ("사실관계", "사실관계요지", "사실"),
}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s\u3000_\-:/·()\[\]{}]+", "", text).casefold()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value).strip()


def _cell_range(first: int, last: int, width: int) -> str:
    def col(n: int) -> str:
        out = ""
        while n:
            n, rem = divmod(n - 1, 26)
            out = chr(65 + rem) + out
        return out
    return f"{col(first)}{last}:{col(max(first, width))}{last}"


def _case_numbers(value: str) -> list[str]:
    # Generic Korean court case-number shape.  It deliberately accepts only
    # normalized number tokens; no actual case number is embedded in code.
    pattern = re.compile(
        r"(?<![\w-])(?P<year>\d{2,4})\s*(?P<kind>[가-힣A-Za-z]{1,8})\s*"
        r"(?P<number>\d{1,8})(?P<merged>(?:\s*[,·/]\s*\d{1,8})*)(?![\w-])"
    )
    result: list[str] = []
    for match in pattern.finditer(value):
        prefix = f"{match.group('year')}{match.group('kind')}{match.group('number')}"
        result.append(prefix)
        for suffix in re.findall(r"\d{1,8}", match.group("merged") or ""):
            result.append(f"{match.group('year')}{match.group('kind')}{suffix}")
    return list(dict.fromkeys(result))


def _date_value(value: str) -> str | None:
    m = re.search(r"(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", value)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _court_value(value: str) -> str | None:
    m = re.search(r"([가-힣A-Za-z]{2,20}(?:법원|재판소|위원회|원))", value)
    return m.group(1) if m else None


def _header_map(values: list[Any]) -> dict[str, int] | None:
    normalized = [_norm(v) for v in values]
    result: dict[str, int] = {}
    for key, aliases in _ALIASES.items():
        for index, value in enumerate(normalized):
            if value and any(value == _norm(alias) or _norm(alias) in value for alias in aliases):
                result[key] = index
                break
    required = {"case_info", "reason", "holding"}
    if not required.issubset(result) or not ("issue" in result or "facts" in result) \
            or not ("title" in result or "number" in result):
        return None
    return result


def _iter_rows(path: Path) -> Iterable[tuple[str, int, list[Any], list[str], bool, str]]:
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for number, row in enumerate(csv.reader(stream), 1):
                yield "CSV", number, row, [""] * len(row), True, ""
        return
    if suffix != ".xlsx":
        return
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=False)
    links_by_sheet = _xlsx_hyperlinks(path)
    hidden_by_sheet = _xlsx_hidden_rows(path)
    try:
        for sheet in workbook.worksheets:
            sheet_hidden = sheet.sheet_state != "visible"
            for number, cells in enumerate(sheet.iter_rows(), 1):
                values, links = [], []
                white_row = False
                for cell in cells:
                    values.append(cell.value)
                    coordinate = getattr(cell, "coordinate", "")
                    links.append(links_by_sheet.get(sheet.title, {}).get(coordinate, ""))
                    color = getattr(getattr(cell, "font", None), "color", None)
                    if color is not None and getattr(color, "type", None) == "rgb":
                        rgb = str(getattr(color, "rgb", ""))[-6:].upper()
                        white_row |= rgb == "FFFFFF"
                visible = number not in hidden_by_sheet.get(sheet.title, set()) and not white_row and not sheet_hidden
                hidden_reason = ("HIDDEN_SHEET" if sheet_hidden else
                                 "HIDDEN_ROW" if number in hidden_by_sheet.get(sheet.title, set()) else
                                 "WHITE_ON_WHITE" if white_row else "")
                yield sheet.title, number, values, links, visible, hidden_reason
    finally:
        workbook.close()


def _xlsx_hyperlinks(path: Path) -> dict[str, dict[str, str]]:
    """Read hyperlink targets from the small XLSX XML relationship parts.

    Read-only openpyxl cells intentionally omit hyperlink objects.  Parsing
    just relationship and hyperlink elements preserves targets without loading
    the workbook's full cell graph into memory.
    """
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    try:
        with zipfile.ZipFile(path) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            workbook_rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            rel_targets = {rel.attrib["Id"]: rel.attrib["Target"]
                           for rel in workbook_rels.findall("r:Relationship", rel_ns)}
            result = {}
            for sheet in workbook.findall("m:sheets/m:sheet", ns):
                title = sheet.attrib.get("name", "")
                target = rel_targets.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"), "")
                if not target:
                    continue
                cleaned_target = target.lstrip("/")
                sheet_path = cleaned_target if cleaned_target.startswith("xl/") else "xl/" + cleaned_target
                rel_path = str(Path(sheet_path).parent / ("_rels/" + Path(sheet_path).name + ".rels"))
                try:
                    rel_root = ET.fromstring(archive.read(rel_path))
                    targets = {rel.attrib["Id"]: rel.attrib.get("Target", "") for rel in rel_root.findall("r:Relationship", rel_ns)}
                    sheet_root = ET.fromstring(archive.read(sheet_path))
                    links = {}
                    for hyperlink in sheet_root.findall("m:hyperlinks/m:hyperlink", ns):
                        ref = hyperlink.attrib.get("ref")
                        target_url = targets.get(hyperlink.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"))
                        if ref and target_url:
                            links[ref] = target_url
                    if links:
                        result[title] = links
                except (KeyError, ET.ParseError):
                    continue
            return result
    except (KeyError, OSError, ET.ParseError, zipfile.BadZipFile):
        return {}


def _xlsx_hidden_rows(path: Path) -> dict[str, set[int]]:
    """Return row numbers marked hidden in worksheet XML without loading cells."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    try:
        with zipfile.ZipFile(path) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("r:Relationship", rel_ns)}
            result = {}
            for sheet in workbook.findall("m:sheets/m:sheet", ns):
                title = sheet.attrib.get("name", "")
                target = targets.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"), "")
                cleaned = target.lstrip("/")
                sheet_path = cleaned if cleaned.startswith("xl/") else "xl/" + cleaned
                root = ET.fromstring(archive.read(sheet_path))
                hidden = {int(row.attrib["r"]) for row in root.findall("m:sheetData/m:row", ns)
                          if row.attrib.get("hidden", "0").casefold() in {"1", "true"}}
                if hidden:
                    result[title] = hidden
            return result
    except (KeyError, OSError, ET.ParseError, ValueError, zipfile.BadZipFile):
        return {}


def _row_scan(sheet: str, number: int, text: str, scanner: AdversarialScanner | None = None) -> list[dict[str, Any]]:
    doc = NormalizedDocument("reference-row", f"{sheet}:{number}", "text", "")
    doc.pages.append(Page(number, blocks=[Block(f"{sheet}:{number}", text, number)]))
    result = (scanner or AdversarialScanner()).scan(doc)
    return [
        {"type": str(getattr(f.type, "value", f.type)),
         "severity": str(getattr(f.severity, "value", f.severity)),
         "page": number,
         "path": (f.confidence_features or {}).get("injection_path"),
         "excerpt": " ".join(str((f.confidence_features or {}).get("observed_text", "")).split())[:100]}
        for f in result.findings
        if f.severity in (Severity.HIGH, Severity.CRITICAL)
        and f.meta_message_type == MetaMessageType.MM1_MACHINE_INSTRUCTION
    ]


def _chunks(record: dict[str, Any], target: int = 1040, max_size: int = 1200) -> list[dict[str, Any]]:
    text = record["indexed_text"]
    if len(text) <= max_size:
        parts = [text]
    else:
        parts = [text[pos:pos + max_size] for pos in range(0, len(text), max_size)]
    output = []
    for index, part in enumerate(parts):
        output.append({
            "page": record["row"], "start": index * max_size, "text": part,
            "case_record_id": record["record_id"], "case_head": record["case_head"],
            "sheet": record["sheet"], "row": record["row"],
            "source_cell_range": record["source_cell_range"],
            "structured_case_table": True,
        })
    return output


def extract_case_table(path: str | Path, *, file_id: str = "", revision: str = "",
                       max_seconds: float = MAX_SECONDS, max_excluded_rows: int | None = None) -> dict[str, Any] | None:
    """Return a structured extraction, or ``None`` for an ordinary workbook."""
    path = Path(path)
    started = time.monotonic()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    headers: dict[str, dict[str, int]] = {}
    records: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    stats = {"discovered": 0, "indexed": 0, "quarantined": 0, "errors": 0, "pending": 0}
    scanner = AdversarialScanner()
    pending_rows: list[dict[str, Any]] = []
    for sheet, number, values, links, visible, hidden_reason in _iter_rows(path):
        if time.monotonic() - started > max_seconds:
            stats["pending"] = max(0, stats["discovered"] - stats["indexed"] - stats["quarantined"] - stats["errors"])
            stats["status_total"] = stats["indexed"] + stats["quarantined"] + stats["errors"] + stats["pending"]
            return {"chunks": chunks, "case_records": records, "sha256": digest,
                    "structured_case_table": True, "partial": True,
                    "reason": "REFERENCE_PARSE_TIMEOUT", "stats": stats,
                    "elapsed_ms": round((time.monotonic() - started) * 1000)}
        header = headers.get(sheet)
        if header is None and number <= MAX_HEADER_ROWS:
            header = _header_map(values)
            if header:
                headers[sheet] = header
                continue
        if not header:
            continue
        populated = [(i, _text(v), links[i] if i < len(links) else "") for i, v in enumerate(values)
                     if _text(v) or (i < len(links) and links[i])]
        if not populated:
            continue
        stats["discovered"] += 1
        if len(pending_rows) >= MAX_ROWS:
            stats["pending"] += 1
            continue
        row_values = {key: _text(values[index]) if index < len(values) else ""
                      for key, index in header.items()}
        raw_cells = {str(index + 1): value for index, value, _link in populated}
        raw_text = " | ".join(value for _index, value, _link in populated)
        if len(raw_text) > MAX_ROW_CHARS or any(len(value) > MAX_CELL_CHARS for _i, value, _l in populated):
            stats["errors"] += 1
            continue
        case_info = row_values.get("case_info", "")
        target_numbers = _case_numbers(case_info)
        referenced_numbers = _case_numbers(" ".join(filter(None, [row_values.get("issue"), row_values.get("facts"),
                                                                    row_values.get("reason"), row_values.get("holding")])) )
        numbers = list(dict.fromkeys(target_numbers + referenced_numbers))
        head_values = [f"[{sheet}]", row_values.get("court") or _court_value(case_info),
                       _date_value(case_info) or "", ", ".join(target_numbers), row_values.get("title") or ""]
        case_head = " ".join(value for value in head_values if value).strip()[:500]
        indexed_text = " | ".join(filter(None, [case_head, row_values.get("issue"), row_values.get("facts"),
                                                  row_values.get("reason"), row_values.get("holding")]))
        record = {
            "record_id": f"{file_id or digest}:{sheet}:{number}", "file_id": file_id,
            "revision": revision, "sheet": sheet, "row": number,
            "source_cell_range": _cell_range(1, number, max((i for i, _v, _l in populated), default=0) + 1),
            "original_number": row_values.get("number", ""), "title": row_values.get("title", ""),
            "case_info": case_info, "court": _court_value(case_info),
            "decision_date": _date_value(case_info), "case_numbers": numbers,
            "target_case_numbers": target_numbers, "referenced_case_numbers": referenced_numbers,
            "issue": row_values.get("issue", ""), "facts": row_values.get("facts", ""),
            "reason": row_values.get("reason", ""), "holding": row_values.get("holding", ""),
            "hyperlinks": [link for _i, _v, link in populated if link],
            "raw_cells": raw_cells, "quality_warnings": [], "case_head": case_head,
            "indexed_text": indexed_text,
            "raw_text": raw_text, "visible": visible, "hidden_reason": hidden_reason,
        }
        if hidden_reason:
            record["quality_warnings"].append(hidden_reason)
        if any(str(v).startswith("=") for _i, v, _l in populated):
            record["quality_warnings"].append("FORMULA_CELL")
        pending_rows.append(record)
    # Scanning one document with one block per row preserves row-level finding
    # locations while avoiding scanner setup and full-text work thousands of
    # times.  Hidden/white rows remain in the scan and count toward exclusion.
    scan_doc = NormalizedDocument("reference-case-table", path.name, "text", digest)
    normalized_rows = [normalize_for_classification(row["raw_text"])[0] for row in pending_rows]
    pattern_hits = find_pattern_hits_batch(normalized_rows)
    for row, hits in zip(pending_rows, pattern_hits):
        scan_doc.pages.append(Page(row["row"], blocks=[Block(
            row["record_id"], row["raw_text"], row["row"], visible=row["visible"],
            block_type="table",
            attributes={**({"hidden_reason": row["hidden_reason"]} if row["hidden_reason"] else {}),
                        "_pattern_hits": hits})]))
    scan = scanner.scan(scan_doc)
    findings_by_row: dict[str, list[dict[str, Any]]] = {}
    for finding in scan.findings:
        if finding.severity not in (Severity.HIGH, Severity.CRITICAL) \
                or finding.meta_message_type != MetaMessageType.MM1_MACHINE_INSTRUCTION:
            continue
        block_ids = (finding.confidence_features or {}).get("block_ids") or []
        if not block_ids and finding.block_id:
            block_ids = [finding.block_id]
        evidence = {"type": str(getattr(finding.type, "value", finding.type)),
                    "severity": str(getattr(finding.severity, "value", finding.severity)),
                    "page": finding.page,
                    "path": (finding.confidence_features or {}).get("injection_path"),
                    "excerpt": " ".join(str((finding.confidence_features or {}).get("observed_text", "")).split())[:100]}
        for block_id in block_ids:
            findings_by_row.setdefault(block_id, []).append(evidence)
    excluded_limit = max_excluded_rows
    if excluded_limit is None:
        import os
        excluded_limit = int(os.getenv("LV_CASE_TABLE_MAX_EXCLUDED_ROWS", "32"))
    file_scan_findings: list[dict[str, Any]] = []
    for row in pending_rows:
        warnings = findings_by_row.get(row["record_id"], [])
        if warnings:
            row["quality_warnings"].append("SECURITY_QUARANTINE")
            row["scan_findings"] = warnings[:3]
            file_scan_findings.extend(warnings)
        if warnings or not row["visible"]:
            stats["quarantined"] += 1
            continue
        records.append({key: value for key, value in row.items()
                        if key not in {"raw_text", "visible", "hidden_reason"}})
        chunks.extend(_chunks(records[-1]))
        stats["indexed"] += 1
    if stats["quarantined"] > max(0, excluded_limit):
        stats["status_total"] = stats["indexed"] + stats["quarantined"] + stats["errors"] + stats["pending"]
        return {"chunks": [], "case_records": [], "sha256": digest,
                "structured_case_table": True, "partial": True,
                "reason": "REFERENCE_QUARANTINED", "stats": stats,
                "scan_findings": file_scan_findings[:3],
                "elapsed_ms": round((time.monotonic() - started) * 1000)}
    if not headers:
        return None
    stats["status_total"] = stats["indexed"] + stats["quarantined"] + stats["errors"] + stats["pending"]
    partial = bool(stats["quarantined"] or stats["errors"] or stats["pending"])
    return {"chunks": chunks, "case_records": records, "sha256": digest,
            "structured_case_table": True, "partial": partial,
            "reason": "REFERENCE_CASE_TABLE_PARTIAL" if partial else "",
            "stats": stats, "scan_findings": file_scan_findings[:3],
            "table_version": CASE_TABLE_VERSION,
            "elapsed_ms": round((time.monotonic() - started) * 1000)}


def lookup_records(records: Iterable[dict[str, Any]], case_number: str, *, court: str | None = None,
                   decision_date: str | None = None) -> dict[str, Any]:
    target = re.sub(r"\s+", "", str(case_number or "").strip())
    matches = [r for r in records if target and target in (r.get("target_case_numbers") or r.get("case_numbers") or [])]
    if not matches:
        return {"status": "NOT_IN_REFERENCE", "case_number": target}
    if len(matches) > 1:
        same_event = len({(_norm(r.get("court")), r.get("decision_date")) for r in matches}) == 1
        return {"status": "MATCH" if same_event else "AMBIGUOUS", "case_number": target,
                "record_ids": [r.get("record_id") for r in matches],
                "record_id": matches[0].get("record_id") if same_event else None,
                "file_id": matches[0].get("file_id") if same_event else None,
                "sheet": matches[0].get("sheet") if same_event else None,
                "row": matches[0].get("row") if same_event else None,
                "source_cell_range": matches[0].get("source_cell_range") if same_event else None}
    record = matches[0]
    mismatches = {}
    if court and record.get("court") and _norm(court) != _norm(record["court"]):
        mismatches["court"] = {"document": court, "reference": record.get("court")}
    if decision_date and record.get("decision_date") and _date_value(str(decision_date)) != record.get("decision_date"):
        mismatches["decision_date"] = {"document": decision_date, "reference": record.get("decision_date")}
    return {"status": "METADATA_MISMATCH" if mismatches else "MATCH", "case_number": target,
            "record_id": record.get("record_id"), "file_id": record.get("file_id"),
            "sheet": record.get("sheet"), "row": record.get("row"),
            "source_cell_range": record.get("source_cell_range"), "court": record.get("court"),
            "decision_date": record.get("decision_date"), "mismatches": mismatches}
