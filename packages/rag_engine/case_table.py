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
from packages.common.enums import MetaMessageType, Severity
from packages.common.schemas import Block, NormalizedDocument, Page

CASE_TABLE_VERSION = "case-table-v2-resumable"
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


_NORMALIZED_ALIASES = {key: tuple(_norm(alias) for alias in aliases) for key, aliases in _ALIASES.items()}


_HEADER_EXACT = {alias: key for key, aliases in _NORMALIZED_ALIASES.items() for alias in aliases}


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
    if all(not value or value in _HEADER_EXACT for value in normalized):
        for index, value in enumerate(normalized):
            if value:
                result.setdefault(_HEADER_EXACT[value], index)
    else:
        for key, aliases in _NORMALIZED_ALIASES.items():
            for index, value in enumerate(normalized):
                if value and any(value == alias or alias in value for alias in aliases):
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
        properties = [f"{key}: {getattr(workbook.properties, key)}"
                      for key in ("creator", "lastModifiedBy", "title", "subject", "keywords", "description", "company")
                      if getattr(workbook.properties, key, None)]
        properties.extend(f"{name}: {value}" for name, value in workbook.defined_names.items())
        if properties:
            yield "Workbook metadata", 0, properties, [""] * len(properties), False, "METADATA"
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


def _row_scan(sheet: str, number: int, text: str, scanner: AdversarialScanner | None = None, *,
              visible: bool = True, hidden_reason: str = "") -> list[dict[str, Any]]:
    doc = NormalizedDocument("reference-row", f"{sheet}:{number}", "text", "")
    doc.pages.append(Page(number, blocks=[Block(f"{sheet}:{number}", text, number, visible=visible,
                                                    attributes={"hidden_reason": hidden_reason} if hidden_reason else {})]))
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
    head = record["case_head"][:500]
    body = text[len(head):].lstrip(" |") if text.startswith(head) else text
    width = max(1, max_size - len(head) - 3)
    parts = [head + (" | " + body[pos:pos + width] if body else "")
             for pos in range(0, max(1, len(body)), width)]
    output = []
    for index, part in enumerate(parts):
        output.append({
            "page": record["row"], "start": index * width, "text": part,
            "case_record_id": record["record_id"], "case_head": record["case_head"],
            "sheet": record["sheet"], "row": record["row"],
            "source_cell_range": record["source_cell_range"],
            "structured_case_table": True,
        })
    return output


def _record(sheet, number, populated, values, header, *, file_id, revision, digest):
    row_values = {key: _text(values[index]) if index < len(values) else ""
                  for key, index in header.items()}
    case_info = row_values.get("case_info", "")
    target_numbers = _case_numbers(case_info)
    referenced_numbers = _case_numbers(" ".join(filter(None, [row_values.get("issue"), row_values.get("facts"),
                                                              row_values.get("reason"), row_values.get("holding")])))
    case_head = " ".join(filter(None, [f"[{sheet}]", _court_value(case_info), _date_value(case_info),
                                      ", ".join(target_numbers), row_values.get("title")]))[:500]
    indexed_text = " | ".join(filter(None, [case_head, row_values.get("issue"), row_values.get("facts"),
                                           row_values.get("reason"), row_values.get("holding")]))
    return {
        "record_id": f"{file_id or digest}:{sheet}:{number}", "file_id": file_id,
        "revision": revision, "sheet": sheet, "row": number,
        "source_cell_range": _cell_range(1, number, max(i for i, _v, _l in populated) + 1),
        "original_number": row_values.get("number", ""), "title": row_values.get("title", ""),
        "case_info": case_info, "court": _court_value(case_info), "decision_date": _date_value(case_info),
        "case_numbers": list(dict.fromkeys(target_numbers + referenced_numbers)),
        "target_case_numbers": target_numbers, "referenced_case_numbers": referenced_numbers,
        "issue": row_values.get("issue", ""), "facts": row_values.get("facts", ""),
        "reason": row_values.get("reason", ""), "holding": row_values.get("holding", ""),
        "hyperlinks": [link for _i, _v, link in populated if link],
        "raw_cells": {str(i + 1): value for i, value, _link in populated},
        "quality_warnings": (["MISSING_SUMMARY"] if not row_values.get("holding") else []) +
                            (["FORMULA_CELL"] if any(v.startswith("=") for _i, v, _l in populated) else []),
        "case_head": case_head, "indexed_text": indexed_text,
    }


def extract_case_table(path: str | Path, *, file_id: str = "", revision: str = "",
                       max_seconds: float = MAX_SECONDS, max_excluded_rows: int | None = None,
                       continuation: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Scan independent rows with the unchanged scanner, resuming a bounded batch.

    A checkpoint only advances after the row's full security scan.  Batches
    contain newly scanned rows; their caller atomically appends them to the
    same revision.  Unscanned rows are counted as pending and never indexed.
    """
    import os
    path = Path(path)
    started = time.monotonic()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    previous = continuation or {}
    resumed = (previous.get("sha256") == digest and previous.get("table_version") == CASE_TABLE_VERSION
               and previous.get("revision", "") == revision)
    state = previous if resumed else {}
    cursor = dict(state.get("cursor") or {})
    resume_position = int(cursor.get("position", 0))
    stats = {key: int((state.get("stats") or {}).get(key, 0))
             for key in ("indexed", "quarantined", "errors")}
    stats.update(discovered=0, pending=0)
    file_findings = list(state.get("scan_findings") or [])[:3]
    excluded_rows = list(state.get("excluded_rows") or [])
    ranges = [dict(value) for value in state.get("read_ranges") or []]
    excluded_limit = max(0, int(max_excluded_rows if max_excluded_rows is not None else
                              os.getenv("LV_CASE_TABLE_MAX_EXCLUDED_ROWS", "32")))
    headers: dict[str, dict[str, int]] = {}
    records, chunks = [], []
    scanner = AdversarialScanner()
    stopped = False
    row_limit = False
    auxiliary_quarantine = False
    scanned_chars, scan_seconds = 0, 0.0
    for position, (sheet, number, values, links, visible, hidden_reason) in enumerate(_iter_rows(path), 1):
        header = headers.get(sheet)
        header_row = False
        if header is None and number <= MAX_HEADER_ROWS:
            header = _header_map(values)
            if header:
                headers[sheet] = header
                header_row = True
        populated = [(i, _text(v), links[i] if i < len(links) else "") for i, v in enumerate(values)
                     if _text(v) or (i < len(links) and links[i])]
        is_data = bool(header and not header_row and populated)
        if is_data:
            stats["discovered"] += 1
        if position <= resume_position or stopped:
            continue
        raw_text = " | ".join(value for _i, value, _link in populated)
        # Reserve time for reading the remaining cheap rows and writing the
        # result, using measured scalar scan throughput for the next row.
        predicted = max(0.05, len(raw_text) * scan_seconds / max(1, scanned_chars) * 3)
        if time.monotonic() - started + predicted >= max_seconds:
            stopped = True
            continue
        if is_data and stats["indexed"] + stats["quarantined"] + stats["errors"] >= MAX_ROWS:
            row_limit = True
            stopped = True
            continue
        if len(raw_text) > MAX_ROW_CHARS or any(len(value) > MAX_CELL_CHARS for _i, value, _l in populated):
            if is_data:
                stats["errors"] += 1
            else:
                auxiliary_quarantine = True
        elif raw_text:
            mark = time.monotonic()
            warnings = _row_scan(sheet, number, raw_text, scanner, visible=visible, hidden_reason=hidden_reason)
            # Hyperlinks are untrusted metadata, too; do not follow them.
            for _i, _value, link in populated:
                if link:
                    warnings.extend(_row_scan(sheet, number, link, scanner, visible=False,
                                              hidden_reason="HYPERLINK"))
            scan_seconds += time.monotonic() - mark
            scanned_chars += len(raw_text)
            file_findings.extend({**warning, "sheet": sheet, "row": number} for warning in warnings)
            file_findings = file_findings[:3]
            if warnings or not visible:
                if is_data:
                    stats["quarantined"] += 1
                    if len(excluded_rows) <= excluded_limit:
                        excluded_rows.append({"sheet": sheet, "row": number,
                                              "reason": hidden_reason or "SECURITY_QUARANTINE"})
                elif warnings:
                    auxiliary_quarantine = True
            elif is_data:
                record = _record(sheet, number, populated, values, header,
                                 file_id=file_id, revision=revision, digest=digest)
                records.append(record)
                chunks.extend(_chunks(record))
                stats["indexed"] += 1
        cursor = {"position": position, "sheet": sheet, "row": number}
        if ranges and ranges[-1]["sheet"] == sheet:
            ranges[-1]["last_row"] = number
        else:
            ranges.append({"sheet": sheet, "first_row": number, "last_row": number})
        # Check again after each full scalar scan.  No unbounded batch scan
        # remains after the row loop.
        if time.monotonic() - started >= max_seconds:
            stopped = True
    if not headers:
        return None
    stats["pending"] = max(0, stats["discovered"] - stats["indexed"] - stats["quarantined"] - stats["errors"])
    stats["status_total"] = sum(stats[key] for key in ("indexed", "quarantined", "errors", "pending"))
    quarantined = stats["quarantined"] > excluded_limit or auxiliary_quarantine
    no_progress = stopped and int(cursor.get("position", 0)) <= resume_position
    reason = ("REFERENCE_QUARANTINED" if quarantined else "REFERENCE_TEXT_LIMIT" if row_limit else "REFERENCE_PARSE_TIMEOUT" if no_progress else "REFERENCE_PARTIALLY_READ" if stopped else
              "REFERENCE_CASE_TABLE_PARTIAL" if stats["quarantined"] or stats["errors"] else "")
    checkpoint = {"sha256": digest, "table_version": CASE_TABLE_VERSION, "revision": revision,
                  "cursor": cursor, "stats": stats, "scan_findings": file_findings,
                  "excluded_rows": excluded_rows, "read_ranges": ranges}
    return {"chunks": [] if quarantined else chunks, "case_records": [] if quarantined else records,
            "sha256": digest, "structured_case_table": True, "partial": bool(reason), "reason": reason,
            "stats": stats, "scan_findings": file_findings, "excluded_rows": excluded_rows,
            "read_ranges": ranges, "continuation": checkpoint if stopped and not quarantined and not no_progress and not row_limit else None,
            "resumed": resumed, "table_version": CASE_TABLE_VERSION,
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
