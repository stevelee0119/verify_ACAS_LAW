"""OCR Adapter (제3.2장 교체 가능한 OCR Adapter).

한글·레이아웃·bbox 보존이 필수이므로 인터페이스에 bbox를 강제한다.
엔진이 설치되지 않은 환경에서는 NullOCRAdapter가 UNVERIFIED를 유도한다.
"""
from __future__ import annotations

import re
import shutil
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, List, Optional

from packages.common.config import get_settings
from packages.common.schemas import BBox


# 의미 있는 문자(한글·영숫자)가 2자 미만인 라인은 인식 노이즈로 본다.
MEANINGFUL_RE = re.compile(r"[0-9A-Za-z가-힣]")
MIN_MEANINGFUL_CHARS = 2


def is_noise(text: str) -> bool:
    return len(MEANINGFUL_RE.findall(text)) < MIN_MEANINGFUL_CHARS


@dataclass
class OCRLine:
    text: str
    page: int
    bbox: Optional[BBox] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "page": self.page,
            "bbox": self.bbox.as_tuple() if self.bbox else None,
            "confidence": round(self.confidence, 3),
        }


class OCRAdapter(ABC):
    name = "base"
    available = False

    @abstractmethod
    def recognize(self, path: str, page_numbers: Optional[List[int]] = None) -> List[OCRLine]:
        """파일 경로에서 텍스트를 인식한다."""

    def recognize_image(self, image: Any, *, page: int = 1, scale: float = 1.0) -> List[OCRLine]:
        """PIL Image에서 인식한다. scale은 이미지 좌표를 canonical 좌표로 되돌리는 비율이다."""
        raise NotImplementedError


class NullOCRAdapter(OCRAdapter):
    """OCR 엔진 미설치 환경. 실패시키지 않고 빈 결과를 반환한다(제10장 원칙)."""

    name = "null"
    available = False

    def recognize(self, path: str, page_numbers: Optional[List[int]] = None) -> List[OCRLine]:
        return []

    def recognize_image(self, image: Any, *, page: int = 1, scale: float = 1.0) -> List[OCRLine]:
        return []


class TesseractOCRAdapter(OCRAdapter):
    """Tesseract 기반 구현. 단어가 아니라 라인 단위로 묶어 bbox를 보존한다."""

    name = "tesseract"

    def __init__(self, lang: Optional[str] = None, psm: Optional[int] = None) -> None:
        settings = get_settings()
        self.lang = lang or settings.ocr_lang
        self.psm = psm if psm is not None else settings.ocr_psm
        self.available = False
        self.version = ""
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401

            if shutil.which("tesseract") is None:
                return
            self.version = str(pytesseract.get_tesseract_version())
            self.available = True
        except Exception:
            self.available = False

    @property
    def config(self) -> str:
        return f"--psm {self.psm}"

    def recognize(self, path: str, page_numbers: Optional[List[int]] = None) -> List[OCRLine]:
        if not self.available:
            return []
        from PIL import Image

        try:
            with Image.open(path) as image:
                return self.recognize_image(image.convert("RGB"), page=1)
        except Exception:
            return []

    def recognize_image(self, image: Any, *, page: int = 1, scale: float = 1.0) -> List[OCRLine]:
        """라인 단위로 그룹핑해 텍스트·bbox·평균 신뢰도를 만든다."""
        if not self.available:
            return []
        import pytesseract

        try:
            data = pytesseract.image_to_data(
                image, lang=self.lang, config=self.config, output_type=pytesseract.Output.DICT
            )
        except Exception:
            return []

        grouped: dict = defaultdict(list)
        for index, text in enumerate(data.get("text", [])):
            if not str(text).strip():
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            grouped[key].append(index)

        lines: List[OCRLine] = []
        for indices in grouped.values():
            text = " ".join(str(data["text"][i]).strip() for i in indices).strip()
            if not text or is_noise(text):
                continue
            confidences = [float(data["conf"][i]) for i in indices if str(data["conf"][i]) not in ("-1",)]
            lines.append(
                OCRLine(
                    text=text,
                    page=page,
                    bbox=BBox(
                        x0=min(float(data["left"][i]) for i in indices) / scale,
                        y0=min(float(data["top"][i]) for i in indices) / scale,
                        x1=max(float(data["left"][i] + data["width"][i]) for i in indices) / scale,
                        y1=max(float(data["top"][i] + data["height"][i]) for i in indices) / scale,
                    ),
                    confidence=(sum(confidences) / len(confidences) / 100.0) if confidences else 0.0,
                )
            )
        lines.sort(key=lambda line: (line.bbox.y0 if line.bbox else 0, line.bbox.x0 if line.bbox else 0))
        return lines


_adapter: Optional[OCRAdapter] = None


def get_ocr_adapter() -> OCRAdapter:
    global _adapter
    if _adapter is None:
        candidate = TesseractOCRAdapter()
        _adapter = candidate if candidate.available else NullOCRAdapter()
    return _adapter


def set_ocr_adapter(adapter: OCRAdapter) -> None:
    global _adapter
    _adapter = adapter


def reset_ocr_adapter() -> None:
    global _adapter
    _adapter = None
