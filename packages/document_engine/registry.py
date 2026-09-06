"""Parser 선택 및 정규화 진입점 (제6장)."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import List, Optional

from packages.common.schemas import NormalizedDocument, Page

from .base import DocumentParser, ParserError
from .docx_parser import DocxParser
from .hwp_parser import HwpParser, HwpxParser
from .pdf_parser import PdfParser
from .simple_parsers import ImageParser, SpreadsheetParser, TextParser

PARSERS: List[DocumentParser] = [
    PdfParser(),
    DocxParser(),
    HwpxParser(),
    HwpParser(),
    SpreadsheetParser(),
    ImageParser(),
    TextParser(),
]

ALLOWED_EXTENSIONS = sorted({ext for p in PARSERS for ext in p.extensions})


def guess_mime(filename: str, provided: Optional[str] = None) -> str:
    if provided and provided != "application/octet-stream":
        return provided
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    suffix = Path(filename).suffix.lower()
    return {
        ".hwpx": "application/hwp+zip",
        ".hwp": "application/x-hwp",
    }.get(suffix, "application/octet-stream")


def select_parser(mime_type: str, filename: str) -> Optional[DocumentParser]:
    for parser in PARSERS:
        if parser.supports(mime_type, filename):
            return parser
    return None


def parse_document(path: str, *, document_id: str, filename: str, mime_type: str, sha256: str) -> NormalizedDocument:
    """파서를 선택해 NormalizedDocument를 만든다.

    지원하지 않는 형식이거나 파싱에 실패해도 예외를 밖으로 던지지 않고
    경고를 포함한 빈 문서를 돌려주어 Job 전체가 실패하지 않게 한다.
    """
    mime = guess_mime(filename, mime_type)
    parser = select_parser(mime, filename)
    if parser is None:
        doc = NormalizedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime,
            sha256=sha256,
            parser_name="none",
        )
        doc.pages.append(Page(page_number=1))
        doc.parse_warnings.append(f"지원하지 않는 형식이다: {mime or Path(filename).suffix}")
        doc.structure["unsupported_format"] = True
        return doc
    try:
        return parser.parse(path, document_id=document_id, filename=filename, mime_type=mime, sha256=sha256)
    except Exception as exc:
        doc = NormalizedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime,
            sha256=sha256,
            parser_name=parser.name,
        )
        doc.pages.append(Page(page_number=1))
        doc.parse_warnings.append(f"{parser.name} 파싱 실패: {exc}")
        doc.structure["parse_error"] = str(exc)
        return doc
