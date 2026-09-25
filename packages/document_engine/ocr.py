"""OCR Adapter (제3.2장 교체 가능한 OCR Adapter).

한글·레이아웃·bbox 보존이 필수이므로 인터페이스에 bbox를 강제한다.
엔진이 설치되지 않은 환경에서는 NullOCRAdapter가 UNVERIFIED를 유도한다.
"""
from __future__ import annotations

import re
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


SINGLE_SYLLABLE_RE = re.compile(r"^[가-힣]$")


def normalize_ocr_spacing(text: str) -> str:
    """한글 OCR이 음절마다 띄어 읽은 부분을 붙인다('헌 법 재판소' → '헌법 재판소', '2020 헌 마 1127' → '2020 헌마 1127').

    한 글자짜리 한글 어절이 둘 이상 이어지면 한 어절로 합친다. 두 글자 이상 어절 사이의 띄어쓰기는 그대로 둔다.
    OCR 층에만 쓴다(원래 띄어 쓴 한 글자 어절이 붙을 수 있으나, 인용·날짜 추출이 깨지는 것보다 낫다).
    """
    tokens = text.split(" ")
    out: List[str] = []
    run: List[str] = []
    for token in tokens + [""]:
        if SINGLE_SYLLABLE_RE.match(token):
            run.append(token)
            continue
        if run:
            out.append("".join(run) if len(run) >= 2 else run[0])
            run = []
        if token:
            out.append(token)
    return " ".join(out)


HANGUL_RE = re.compile(r"[가-힣]")
LATIN_RE = re.compile(r"[A-Za-z]")
MIN_LETTERS_FOR_RATIO = 20


def page_quality(lines, *, lang: Optional[str] = None, min_confidence: Optional[float] = None,
                 min_hangul_ratio: Optional[float] = None) -> dict:
    """한 쪽의 OCR 품질(추가지시 G2).

    - confidence: 인식한 라인의 평균 신뢰도(0~1).
    - hangul_ratio: 글자(한글+로마자) 가운데 한글 비율. 한국어 모델로 읽었는데 한글이 거의 없으면
      "의 xj ot AOO"처럼 한글이 깨져 로마자로 읽힌 것이다. 글자가 적으면 비율을 판단하지 않는다.
    둘 중 하나라도 기준에 못 미치면 low_quality=True. 그 쪽에서 '결함 없음'을 결론 내리지 않는다.
    """
    settings = get_settings()
    lang = lang or settings.ocr_lang
    min_confidence = settings.ocr_quality_min_confidence if min_confidence is None else min_confidence
    min_hangul_ratio = settings.ocr_min_hangul_ratio if min_hangul_ratio is None else min_hangul_ratio
    texts = [line for line in lines if (line.text or "").strip() and not is_noise(line.text)]
    joined = " ".join(line.text for line in texts)
    hangul, latin = len(HANGUL_RE.findall(joined)), len(LATIN_RE.findall(joined))
    confidence = sum(line.confidence for line in texts) / len(texts) if texts else 0.0
    ratio = hangul / (hangul + latin) if hangul + latin else None
    reasons = []
    if texts and confidence < min_confidence:
        reasons.append(f"평균 신뢰도 {confidence:.2f} < {min_confidence:.2f}")
    if "kor" in lang and ratio is not None and hangul + latin >= MIN_LETTERS_FOR_RATIO and ratio < min_hangul_ratio:
        reasons.append(f"한글 비율 {ratio:.2f} < {min_hangul_ratio:.2f}")
    return {"lines": len(texts), "confidence": round(confidence, 3),
            "hangul_ratio": None if ratio is None else round(ratio, 3),
            "low_quality": bool(reasons), "reasons": reasons}


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

    def __init__(self, diagnostics=None):
        self.diagnostics = diagnostics

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
        from .ocr_readiness import probe_tesseract
        self.diagnostics = probe_tesseract(self.lang)
        self.available = self.diagnostics["available"]
        self.version = self.diagnostics["version"]

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

    def detect_rotation(self, image: Any) -> Optional[int]:
        """Tesseract OSD로 바로 세우는 데 필요한 회전 각도(시계 방향, 0·90·180·270). 판단하지 못하면 None."""
        if not self.available:
            return None
        import pytesseract

        try:
            osd = pytesseract.image_to_osd(image, config="--psm 0", output_type=pytesseract.Output.DICT,
                                           timeout=max(1, get_settings().ocr_timeout_seconds))
        except Exception:
            return None
        rotate = int(osd.get("rotate") or 0) % 360
        return rotate if float(osd.get("orientation_conf") or 0) >= 1.0 else None

    last_error: Optional[str] = None

    def recognize_image(self, image: Any, *, page: int = 1, scale: float = 1.0,
                        timeout: Optional[float] = None) -> List[OCRLine]:
        """라인 단위로 그룹핑해 텍스트·bbox·평균 신뢰도를 만든다.

        인식 실패는 빈 목록을 돌려주되 사유를 last_error에 남긴다('TIMEOUT' 또는 예외 이름). 빈 결과만으로는
        '글자가 없는 쪽'과 '시간 초과로 읽지 못한 쪽'을 구분할 수 없어, 시간 초과가 신뢰도 미달로 기록됐다."""
        self.last_error = None
        if not self.available:
            return []
        import pytesseract

        try:
            data = pytesseract.image_to_data(
                image, lang=self.lang, config=self.config, output_type=pytesseract.Output.DICT,
                timeout=max(1, timeout or get_settings().ocr_timeout_seconds),
            )
        except Exception as exc:
            # pytesseract는 시간 초과를 RuntimeError('Tesseract process timeout')로 알린다
            self.last_error = "TIMEOUT" if "timeout" in str(exc).lower() else type(exc).__name__
            return []

        grouped: dict = defaultdict(list)
        for index, text in enumerate(data.get("text", [])):
            if not str(text).strip():
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            grouped[key].append(index)

        lines: List[OCRLine] = []
        for indices in grouped.values():
            text = normalize_ocr_spacing(" ".join(str(data["text"][i]).strip() for i in indices).strip())
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
        _adapter = candidate if candidate.available else NullOCRAdapter(candidate.diagnostics)
    return _adapter


def set_ocr_adapter(adapter: OCRAdapter) -> None:
    global _adapter
    _adapter = adapter


def reset_ocr_adapter() -> None:
    global _adapter
    _adapter = None
