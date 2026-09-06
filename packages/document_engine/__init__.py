from .base import DocumentParser, ParserError
from .ocr import OCRAdapter, OCRLine, NullOCRAdapter, get_ocr_adapter, set_ocr_adapter
from .registry import ALLOWED_EXTENSIONS, PARSERS, guess_mime, parse_document, select_parser

__all__ = [
    "DocumentParser",
    "ParserError",
    "OCRAdapter",
    "OCRLine",
    "NullOCRAdapter",
    "get_ocr_adapter",
    "set_ocr_adapter",
    "parse_document",
    "select_parser",
    "guess_mime",
    "PARSERS",
    "ALLOWED_EXTENSIONS",
]
