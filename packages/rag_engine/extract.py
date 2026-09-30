"""Isolated reference extraction. PDF text only; unread/scanned pages are disclosed."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
from pathlib import Path
import re
import sys

from packages.adversarial_engine import AdversarialScanner
from packages.common.enums import MetaMessageType, Severity
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.document_engine.registry import parse_document

MAX_CHARS = 3_000_000
MAX_PAGES = 1500
EXTRACTOR_VERSION = "drive-text-v3"
EXCLUDE_MIN_TOTAL = 10       # 이보다 짧은 파일은 쪽 단위로 빼지 않고 전체를 격리한다
EXCLUDE_MAX_SHARE = 0.02     # 전체 쪽수의 2%까지(최소 1쪽)
EXCLUDE_MAX_PAGES = 3        # 그리고 3쪽까지만 해당 쪽을 빼고 색인한다


def chunk_page_text(text: str, page_number: int, target_size: int = 1040, max_size: int = 1200, overlap: int = 160) -> list[dict]:
    """페이지 텍스트를 문맥·문장 경계를 보존하며 고품질 청크로 분할한다.

    1. PDF 줄바꿈으로 인해 단어나 수치 중간이 쪼개진 현상을 정돈.
    2. 단순 글자 수 슬라이싱 대신 문장 마침표·개행 경계에서 분할하여 키워드 분실 방지.
    """
    if not text or not text.strip():
        return []

    # 단어 중간의 부자연스러운 PDF 줄바꿈 결합
    normalized = re.sub(r'([가-힣a-zA-Z0-9,])\n([가-힣a-zA-Z0-9])', r'\1 \2', text)
    normalized = re.sub(r'[ \t]+', ' ', normalized).strip()
    if not normalized:
        return []

    if len(normalized) <= max_size:
        return [{"page": page_number, "start": 0, "text": normalized}]

    chunks = []
    start = 0
    total_len = len(normalized)

    while start < total_len:
        end = min(start + max_size, total_len)
        if end < total_len:
            # target_size 주변에서 자연스러운 문장 마침표 탐색
            search_start = max(start + target_size - 120, start + 200)
            for marker in ("\n\n", ".\n", ". ", "다. ", "함. ", "임. ", "\n", "; "):
                idx = normalized.rfind(marker, search_start, end)
                if idx != -1:
                    end = idx + len(marker)
                    break

        chunk_str = normalized[start:end].strip()
        if chunk_str:
            chunks.append({"page": page_number, "start": start, "text": chunk_str})

        if end >= total_len:
            break
        start = max(start + 1, end - overlap)

    return chunks


def excludable_pages(total):
    if not total or total < EXCLUDE_MIN_TOTAL:
        return 0
    return min(EXCLUDE_MAX_PAGES, max(1, int(total * EXCLUDE_MAX_SHARE)))


def scan_evidence(finding):
    """격리·제외 근거를 실행 JSON에 남긴다(무엇이 왜 걸렸는지 사람이 되짚을 수 있게)."""
    features = finding.confidence_features or {}
    observed = str(features.get("observed_text") or "")
    return {"type": str(getattr(finding.type, "value", finding.type)),
            "severity": str(getattr(finding.severity, "value", finding.severity)),
            "page": finding.page, "path": features.get("injection_path") or features.get("layer"),
            "intents": [t for t in (finding.tags or [])][:3], "excerpt": " ".join(observed.split())[:60]}


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
        native, fallback_pages = None, []
        try:
            import pypdfium2 as pdfium
            native = pdfium.PdfDocument(path)
        except Exception:
            pass  # Retain the existing parser if the native engine cannot open this PDF.
        try:
            for number in range(1, min(total, MAX_PAGES) + 1):
                text = None
                if native is not None:
                    try:
                        with closing(native[number - 1]) as page, closing(page.get_textpage()) as textpage:
                            text = textpage.get_text_range()
                    except Exception:
                        text = None
                if text is None or not text.strip():
                    fallback_pages.append(number)
                    text = reader.pages[number - 1].extract_text() or ""
                count += len(text)
                if count > MAX_CHARS:
                    break
                doc.pages.append(Page(number, blocks=[Block(f"p{number}", text, number)]))
        finally:
            if native is not None:
                native.close()
        doc.structure.update(text_parser="pypdfium2" if native is not None else "pypdf",
                             fallback_pages=fallback_pages)
    else:
        doc = parse_document(str(path), document_id="reference", filename=filename,
                             mime_type=mime, sha256=digest)
        total = len(doc.pages)
        if doc.structure.get("parse_error") or doc.structure.get("unsupported_format"):
            raise ValueError("REFERENCE_PARSE_FAILED")
        if len(doc.visible_text) > MAX_CHARS or total > MAX_PAGES:
            raise ValueError("REFERENCE_TEXT_LIMIT")
    scan = AdversarialScanner().scan(doc)
    flagged = [f for f in scan.findings if f.severity in (Severity.HIGH, Severity.CRITICAL)
               and f.meta_message_type == MetaMessageType.MM1_MACHINE_INSTRUCTION]
    evidence = [scan_evidence(f) for f in flagged[:5]]
    # 지시형 문자열이 특정 쪽에만 있으면 그 쪽만 빼고 나머지를 색인한다(수백 쪽 판례집 전체를 버리지 않는다).
    # 쪽을 특정할 수 없는 신호(메타데이터·숨은 층·인코딩)나 여러 쪽에 퍼진 경우에는 종전처럼 파일 전체를 격리한다.
    pages_hit = {f.page for f in flagged if f.page and f.block_id}
    whole_file = any(not (f.page and f.block_id) for f in flagged) or len(pages_hit) > excludable_pages(total)
    if flagged and whole_file:
        return {"chunks": [], "sha256": digest, "reason": "REFERENCE_QUARANTINED", "partial": True,
                "scan_findings": evidence, "pages": total}
    chunks, read_pages, no_text_pages = [], 0, []
    for page in doc.pages:
        if page.page_number in pages_hit:
            continue
        text = "\n".join(b.text for b in page.blocks if b.visible and b.source_layer == "visible_text")
        if not text.strip():
            no_text_pages.append(page.page_number)
            continue
        read_pages += 1
        page_chunks = chunk_page_text(text, page.page_number)
        chunks.extend(page_chunks)
    coverage_missing = any(p.get("status") in ("UNVERIFIED", "OCR_LOW_QUALITY")
                           for p in doc.structure.get("page_coverage", []))
    partial = read_pages < total or coverage_missing or bool(doc.parse_warnings)
    reason = ("REFERENCE_INSTRUCTION_PAGES_EXCLUDED" if pages_hit else
              "REFERENCE_PARTIALLY_READ" if partial else "")
    return {"chunks": chunks, "sha256": digest, "partial": partial,
            "excluded_pages": sorted(pages_hit), "scan_findings": evidence,
            "no_text_pages": no_text_pages,
            "text_parser": doc.structure.get("text_parser", doc.parser_name),
            "fallback_pages": doc.structure.get("fallback_pages", []),
            "unprocessed_pages": list(range(len(doc.pages) + 1, total + 1)),
            "coverage_note": ("텍스트 미추출 쪽은 빈 쪽 또는 스캔 쪽일 수 있으며 전문 확인으로 간주하지 않음"
                              if no_text_pages else ""),
            "page_numbers_reliable": doc.structure.get("page_numbers_reliable", path.suffix.lower() not in (".hwp", ".hwpx")),
            "body_extraction_scope": doc.structure.get("body_extraction_scope", "TEXT_EXTRACTION"),
            "pages": total, "read_pages": read_pages,
            "reason": reason}


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
