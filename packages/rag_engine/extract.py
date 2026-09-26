"""Isolated reference extraction. PDF text only; unread/scanned pages are disclosed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from packages.adversarial_engine import AdversarialScanner
from packages.common.enums import MetaMessageType, Severity
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.document_engine.registry import parse_document

MAX_CHARS = 3_000_000
MAX_PAGES = 1500
EXTRACTOR_VERSION = "drive-text-v2"


def extract(path, filename, mime):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if mime == "application/pdf" or path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("ENCRYPTED_REFERENCE")
        doc = NormalizedDocument("reference", filename, mime, digest)
        doc.metadata = dict(reader.metadata or {})
        doc.raw_layers["metadata_text"] = str(doc.metadata)
        total, count = len(reader.pages), 0
        for number, page in enumerate(reader.pages[:MAX_PAGES], 1):
            text = page.extract_text() or ""
            count += len(text)
            if count > MAX_CHARS:
                break
            doc.pages.append(Page(number, blocks=[Block(f"p{number}", text, number)]))
    else:
        doc = parse_document(str(path), document_id="reference", filename=filename,
                             mime_type=mime, sha256=digest)
        total = len(doc.pages)
        if doc.structure.get("parse_error") or doc.structure.get("unsupported_format"):
            raise ValueError("REFERENCE_PARSE_FAILED")
        if len(doc.visible_text) > MAX_CHARS or total > MAX_PAGES:
            raise ValueError("REFERENCE_TEXT_LIMIT")
    scan = AdversarialScanner().scan(doc)
    if any(f.severity in (Severity.HIGH, Severity.CRITICAL)
           and f.meta_message_type == MetaMessageType.MM1_MACHINE_INSTRUCTION for f in scan.findings):
        return {"chunks": [], "sha256": digest, "reason": "REFERENCE_QUARANTINED", "partial": True}
    chunks, read_pages = [], 0
    for page in doc.pages:
        text = "\n".join(b.text for b in page.blocks if b.visible and b.source_layer == "visible_text")
        if not text.strip():
            continue
        read_pages += 1
        for start in range(0, len(text), 1040):
            chunk = text[start:start + 1200]
            if chunk.strip():
                chunks.append({"page": page.page_number, "start": start, "text": chunk})
    coverage_missing = any(p.get("status") in ("UNVERIFIED", "OCR_LOW_QUALITY")
                           for p in doc.structure.get("page_coverage", []))
    partial = read_pages < total or coverage_missing or bool(doc.parse_warnings)
    return {"chunks": chunks, "sha256": digest, "partial": partial,
            "page_numbers_reliable": doc.structure.get("page_numbers_reliable", path.suffix.lower() not in (".hwp", ".hwpx")),
            "body_extraction_scope": doc.structure.get("body_extraction_scope", "TEXT_EXTRACTION"),
            "pages": total, "read_pages": read_pages,
            "reason": "REFERENCE_PARTIALLY_READ" if partial else ""}


def main():
    source, output, filename, mime = sys.argv[1:]
    try:
        if sys.platform == "linux":
            import resource
            # Keep a compressed or malformed reference from exhausting the API/worker container.
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        result = extract(source, filename, mime)
    except Exception:
        result = {"chunks": [], "partial": True, "reason": "REFERENCE_PARSE_FAILED"}
    Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
