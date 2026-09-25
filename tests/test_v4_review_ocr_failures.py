"""OCR 실패 사유 구분(v4 검토 중 발견). 시간 초과는 신뢰도 미달·OCR 미수행과 다르게 기록한다.

CPU가 포화된 러너에서 스캔 쪽 OCR이 시간 초과로 빈 결과를 돌려주자, 그 쪽은 'OCR_LOW_CONFIDENCE'로,
매니페스트는 'OCR을 수행하지 못함(실행 0회)'으로 잘못 기록됐다. 시간 초과는 한도를 늘려 한 번 더 읽고,
그래도 실패하면 'OCR_TIMEOUT'으로 미검증 처리하며 매니페스트에는 '실행했으나 실패'로 남긴다.
"""
from __future__ import annotations

from packages.common.schemas import BBox
from packages.document_engine import parse_document
from packages.document_engine.ocr import OCRAdapter, OCRLine, get_ocr_adapter, set_ocr_adapter
from tests.test_ocr import _scanned_pdf


class TimeoutAdapter(OCRAdapter):
    """처음 n번은 시간 초과, 그다음은 정상 인식."""

    name = "timeout-stub"
    available = True

    def __init__(self, fail_times, text):
        self.fail_times, self.text, self.calls, self.last_error = fail_times, text, [], None

    def recognize(self, path, page_numbers=None):
        return []

    def recognize_image(self, image, *, page=1, scale=1.0, timeout=None):
        self.calls.append(timeout)
        if len(self.calls) <= self.fail_times:
            self.last_error = "TIMEOUT"
            return []
        self.last_error = None
        return [OCRLine(text=self.text, page=page, bbox=BBox(60, 700, 400, 718), confidence=0.93)]

    def detect_rotation(self, image):
        return None


def _parse(tmp_path, adapter, text):
    original = get_ocr_adapter()
    set_ocr_adapter(adapter)
    try:
        path = _scanned_pdf(tmp_path, [text])
        return parse_document(str(path), document_id="D", filename="s.pdf", mime_type="application/pdf", sha256="x")
    finally:
        set_ocr_adapter(original)


def test_timeout_is_retried_with_a_longer_limit_and_then_read(tmp_path):
    """형사: 공판조서 스캔. 첫 시도 시간 초과 → 한도를 늘린 재시도에서 읽는다."""
    adapter = TimeoutAdapter(1, "피고인은 공소사실을 모두 인정하였다")
    doc = _parse(tmp_path, adapter, "피고인은 공소사실을 모두 인정하였다")
    assert adapter.calls[0] is None and adapter.calls[1] and adapter.calls[1] >= 2
    assert doc.structure.get("scanned_pdf_ocr_applied") and not doc.structure.get("ocr_failures")
    assert doc.structure["ocr_attempted_pages"] == [1]


def test_repeated_timeout_is_recorded_as_timeout_not_low_confidence(tmp_path):
    """민사: 영수증 스캔. 재시도도 시간 초과면 그 쪽은 OCR_TIMEOUT(미검증)이다."""
    doc = _parse(tmp_path, TimeoutAdapter(99, "영수증"), "영수증 금 일백만 원")
    page = doc.structure["page_coverage"][0]
    assert page["status"] == "UNVERIFIED" and page["reason"] == "OCR_TIMEOUT"
    assert doc.structure["ocr_failures"] == {"1": "OCR_TIMEOUT"}
    assert any("OCR_TIMEOUT" in warning for warning in doc.parse_warnings)


def test_empty_result_without_engine_error_stays_low_confidence(tmp_path):
    """가사: 흐린 가족관계증명서 스캔. 엔진 오류 없이 읽은 글자가 없으면 신뢰도 미달로 둔다."""
    class Blank(TimeoutAdapter):
        def recognize_image(self, image, *, page=1, scale=1.0, timeout=None):
            self.calls.append(timeout)
            self.last_error = None
            return []

    adapter = Blank(0, "")
    doc = _parse(tmp_path, adapter, "가족관계증명서")
    assert doc.structure["page_coverage"][0]["reason"] == "OCR_LOW_CONFIDENCE"
    assert adapter.calls and all(t is None for t in adapter.calls)  # 한도를 늘린 재시도는 시간 초과에만 한다


def test_manifest_counts_a_failed_ocr_as_executed_with_error(tmp_path, monkeypatch):
    """행정: 처분서 스캔. 매니페스트는 '실행 0회'가 아니라 '실행 1회 + 실패 사유'를 기록한다."""
    from packages.pii_engine import PseudonymStore
    from packages.verification_engine import pipeline as module
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext, VerificationPipeline

    monkeypatch.setattr(module, "PseudonymStore", lambda project_id: PseudonymStore(project_id, root=tmp_path / "vault"))
    original = get_ocr_adapter()
    set_ocr_adapter(TimeoutAdapter(99, "처분서"))
    try:
        path = _scanned_pdf(tmp_path, ["처분서 정직 3월"])
        result = VerificationPipeline().run("r", ProjectContext("p"), [DocumentInput("d1", str(path), "s.pdf", "application/pdf", "x")])
    finally:
        set_ocr_adapter(original)
    ocr = result.run_manifest["engines"]["ocr"]
    assert ocr["runs"] == 1 and ocr["inputs"] == 1
    assert ocr["errors"] and "OCR_TIMEOUT" in ocr["errors"][0]
