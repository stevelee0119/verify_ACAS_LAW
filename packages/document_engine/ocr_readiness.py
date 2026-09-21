"""Bounded OCR capability checks and a synthetic Korean scanned-PDF smoke test."""
from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time


PROBE_TIMEOUT_SECONDS = 5
_smoke_lock = threading.Lock()
_smoke_cache = {}


def probe_tesseract(lang: str) -> dict:
    required = list(dict.fromkeys(part for part in lang.split("+") if part))
    binary = shutil.which("tesseract") or ""
    result = {"engine": "tesseract" if binary else "null", "available": False,
              "binary_available": bool(binary), "binary_path": binary, "version": "",
              "languages": [], "languages_checked": False, "required_languages": required,
              "missing_languages": None, "status": "NOT_INSTALLED"}
    if not binary:
        return result
    try:
        importlib.import_module("pytesseract")
        importlib.import_module("PIL.Image")
    except ImportError:
        result["status"] = "PYTHON_DEPENDENCY_MISSING"
        return result
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=PROBE_TIMEOUT_SECONDS, check=True)
        result["version"] = version.stdout.splitlines()[0][:160]
    except (OSError, subprocess.SubprocessError, IndexError):
        result["status"] = "ENGINE_FAILED"
        return result
    try:
        output = subprocess.run([binary, "--list-langs"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=PROBE_TIMEOUT_SECONDS, check=True)
        languages = sorted({line.strip() for line in output.stdout.splitlines()
                            if re.fullmatch(r"[A-Za-z0-9_/-]+", line.strip())})
    except (OSError, subprocess.SubprocessError):
        result["status"] = "LANGUAGES_UNAVAILABLE"
        return result
    result.update(languages=languages, languages_checked=True,
                  missing_languages=[item for item in required if item not in languages])
    result["available"] = bool(required) and not result["missing_languages"]
    result["status"] = "READY" if result["available"] else "LANGUAGES_MISSING"
    return result


def korean_font_path() -> Path | None:
    candidates = ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "C:/Windows/Fonts/malgun.ttf")
    return next((Path(path) for path in candidates if Path(path).is_file()), None)


def run_ocr_smoke() -> dict:
    """No user files, network, database, model calls, or retained output are involved."""
    font_path = korean_font_path()
    if font_path is None:
        return {"status": "FAILED", "reason": "KOREAN_TEST_FONT_MISSING"}
    try:
        from PIL import Image, ImageDraw, ImageFont
        from reportlab.pdfgen import canvas
        from .registry import parse_document

        with tempfile.TemporaryDirectory(prefix="acas-ocr-check-") as directory:
            root = Path(directory)
            image = Image.new("RGB", (1800, 360), "white")
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype(str(font_path), 72)
            draw.text((60, 35), "법률 문서 검증", font=font, fill="black")
            draw.text((60, 175), "ACAS 12345", font=font, fill="black")
            image.save(root / "sample.png")
            image.close()
            path = root / "sample.pdf"
            pdf = canvas.Canvas(str(path), pagesize=(720, 144))
            pdf.drawImage(str(root / "sample.png"), 0, 0, width=720, height=144)
            pdf.save()
            doc = parse_document(str(path), document_id="ocr-self-test", filename="sample.pdf",
                                 mime_type="application/pdf", sha256="synthetic-ocr-self-test")
            blocks = [block for block in doc.body_blocks() if block.source_layer == "ocr_layer"]
            text = re.sub(r"\s+", "", "".join(block.text for block in blocks))
            valid_boxes = bool(blocks) and all(block.page == 1 and block.bbox is not None and
                                              block.bbox.x1 > block.bbox.x0 for block in blocks)
            if "법률문서검증" not in text or "12345" not in text or not valid_boxes:
                return {"status": "FAILED", "reason": "SCANNED_PDF_RECOGNITION_FAILED"}
            return {"status": "PASSED", "check": "KOREAN_SCANNED_PDF", "body_blocks": len(blocks),
                    "page_and_bbox_verified": True}
    except Exception:
        # Exception text can contain paths; diagnostics only expose a stable failure code.
        return {"status": "FAILED", "reason": "SCANNED_PDF_CHECK_FAILED"}


def ocr_readiness(*, refresh: bool = False) -> dict:
    from .ocr import get_ocr_adapter
    from packages.common.config import get_settings

    adapter = get_ocr_adapter()
    state = deepcopy(getattr(adapter, "diagnostics", None) or {
        "engine": adapter.name, "available": False, "version": "", "binary_path": "",
        "binary_available": False, "languages": [], "languages_checked": False,
        "required_languages": get_settings().ocr_lang.split("+"), "missing_languages": None,
        "status": "NOT_INSTALLED"})
    state["available"] = bool(adapter.available)
    state["self_test"] = {"status": "NOT_RUN", "reason": state["status"]}
    state["ready"] = False
    if not adapter.available:
        return state
    key = (id(adapter), get_settings().ocr_lang, get_settings().ocr_min_confidence)
    with _smoke_lock:
        now = time.monotonic()
        cached = _smoke_cache.get(key)
        if refresh or cached is None or now - cached[0] >= 60:
            _smoke_cache.clear()
            cached = (now, run_ocr_smoke())
            _smoke_cache[key] = cached
        state["self_test"] = deepcopy(cached[1])
    state["ready"] = state["self_test"]["status"] == "PASSED"
    return state


def require_ocr_ready() -> None:
    if not ocr_readiness(refresh=True)["ready"]:
        raise RuntimeError("OCR_READINESS_FAILED: check Tesseract, kor/eng data and Korean scanned-PDF recognition")
