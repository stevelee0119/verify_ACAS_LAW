"""OCR Adapter (제3.2장 교체 가능한 OCR Adapter).

한글·레이아웃·bbox 보존이 필수이므로 인터페이스에 bbox를 강제한다.
엔진이 설치되지 않은 환경에서는 NullOCRAdapter가 UNVERIFIED를 유도한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from packages.common.schemas import BBox


@dataclass
class OCRLine:
    text: str
    page: int
    bbox: Optional[BBox] = None
    confidence: float = 0.0


class OCRAdapter(ABC):
    name = "base"
    available = False

    @abstractmethod
    def recognize(self, path: str, page_numbers: Optional[List[int]] = None) -> List[OCRLine]: ...


class NullOCRAdapter(OCRAdapter):
    """OCR 엔진 미설치 환경. 실패시키지 않고 빈 결과 + 경고를 반환한다(제10장 원칙)."""

    name = "null"
    available = False

    def recognize(self, path: str, page_numbers: Optional[List[int]] = None) -> List[OCRLine]:
        return []


class TesseractOCRAdapter(OCRAdapter):  # pragma: no cover - 선택적 의존성
    name = "tesseract"

    def __init__(self, lang: str = "kor+eng") -> None:
        self.lang = lang
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401

            self.available = True
        except Exception:
            self.available = False

    def recognize(self, path: str, page_numbers: Optional[List[int]] = None) -> List[OCRLine]:
        if not self.available:
            return []
        import pytesseract
        from PIL import Image

        data = pytesseract.image_to_data(Image.open(path), lang=self.lang, output_type=pytesseract.Output.DICT)
        lines: List[OCRLine] = []
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            lines.append(
                OCRLine(
                    text=text,
                    page=1,
                    bbox=BBox(
                        float(data["left"][i]),
                        float(data["top"][i]),
                        float(data["left"][i] + data["width"][i]),
                        float(data["top"][i] + data["height"][i]),
                    ),
                    confidence=float(data["conf"][i]) / 100.0 if data["conf"][i] not in ("-1", -1) else 0.0,
                )
            )
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
