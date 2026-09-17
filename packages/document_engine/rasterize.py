"""PDF 페이지 래스터화.

독립 OCR(제7.3장)과 스캔 PDF 본문 추출에 사용한다.
원본 파일은 열기만 하며 어떤 경우에도 수정하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, List, Optional

from packages.common.config import get_settings


@dataclass
class RasterPage:
    page_number: int
    image: Any
    scale: float
    """이미지 픽셀 좌표 → PDF pt 좌표 환산 비율 (pixel / pt)."""


def available() -> bool:
    try:
        import pypdfium2  # noqa: F401

        return True
    except Exception:  # pragma: no cover - 선택적 의존성
        return False


def render_pages(path: str, page_numbers: Optional[List[int]] = None, *, dpi: Optional[int] = None) -> Iterator[RasterPage]:
    """지정 페이지를 PIL Image로 렌더링한다."""
    if not available():
        return
    import pypdfium2 as pdfium

    resolution = dpi or get_settings().ocr_dpi
    scale = resolution / 72.0
    document = None
    try:
        document = pdfium.PdfDocument(path)
        total = len(document)
        targets = page_numbers or list(range(1, total + 1))
        for page_number in targets:
            if page_number < 1 or page_number > total:
                continue
            page = document[page_number - 1]
            try:
                image = page.render(scale=scale).to_pil()
            except Exception:
                continue
            yield RasterPage(page_number=page_number, image=image, scale=scale)
    except Exception:
        return
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:
                pass
