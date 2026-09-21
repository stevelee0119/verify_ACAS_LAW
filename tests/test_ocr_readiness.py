"""OCR availability must distinguish missing, unknown, and tested capabilities."""
import subprocess
from types import SimpleNamespace

import pytest

from packages.document_engine import ocr, ocr_readiness as module


def install_probe(monkeypatch, languages="eng\nkor\n", failure=None):
    calls = []
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/tesseract")
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if failure and args[-1] == failure[0]:
            raise failure[1]
        output = "tesseract 5.5.0\n" if args[-1] == "--version" else "List of available languages (2):\n" + languages
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")
    monkeypatch.setattr(module.subprocess, "run", run)
    return calls


def test_missing_binary_reports_unknown_languages_not_empty_success(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    state = module.probe_tesseract("kor+eng")
    assert state["status"] == "NOT_INSTALLED"
    assert not state["available"] and not state["languages_checked"]
    assert state["missing_languages"] is None
    assert state["required_languages"] == ["kor", "eng"]


@pytest.mark.parametrize("languages,missing", [("eng\n", ["kor"]), ("", ["kor", "eng"]), ("eng\nkor\n", [])])
def test_language_probe_preserves_known_missing_and_ready(monkeypatch, languages, missing):
    calls = install_probe(monkeypatch, languages)
    state = module.probe_tesseract("kor+eng")
    assert state["languages_checked"]
    assert state["missing_languages"] == missing
    assert state["available"] == (not missing)
    assert all(call[1]["timeout"] == 5 and call[1]["check"] for call in calls)
    assert all(isinstance(call[0], list) and not call[1].get("shell") for call in calls)


@pytest.mark.parametrize("command,status", [("--version", "ENGINE_FAILED"), ("--list-langs", "LANGUAGES_UNAVAILABLE")])
def test_probe_failure_is_bounded_and_does_not_expose_exception_text(monkeypatch, command, status):
    install_probe(monkeypatch, failure=(command, subprocess.TimeoutExpired("SECRET_PATH", 5)))
    state = module.probe_tesseract("kor+eng")
    assert state["status"] == status
    assert state["missing_languages"] is None
    assert not state["available"] and "SECRET_PATH" not in str(state)


def test_missing_python_dependency_is_not_called_ready(monkeypatch):
    install_probe(monkeypatch)
    def missing(name):
        raise ImportError("SECRET_IMPORT_PATH")
    monkeypatch.setattr(module.importlib, "import_module", missing)
    state = module.probe_tesseract("kor+eng")
    assert state["status"] == "PYTHON_DEPENDENCY_MISSING"
    assert not state["available"] and "SECRET_IMPORT_PATH" not in str(state)


def test_missing_korean_data_disables_adapter_and_preserves_reason(monkeypatch):
    install_probe(monkeypatch, "eng\n")
    monkeypatch.setattr(ocr, "_adapter", None)
    adapter = ocr.get_ocr_adapter()
    assert isinstance(adapter, ocr.NullOCRAdapter)
    assert adapter.diagnostics["status"] == "LANGUAGES_MISSING"
    assert adapter.diagnostics["missing_languages"] == ["kor"]
    assert module.ocr_readiness()["self_test"]["status"] == "NOT_RUN"


def test_ocr_subprocess_has_a_whole_recognition_timeout(monkeypatch):
    import pytesseract
    from PIL import Image
    install_probe(monkeypatch)
    adapter = ocr.TesseractOCRAdapter()
    calls = []
    monkeypatch.setattr(pytesseract, "image_to_data", lambda image, **kwargs: calls.append(kwargs) or {})
    assert adapter.recognize_image(Image.new("RGB", (10, 10))) == []
    assert 0 < calls[0]["timeout"] <= 30


def test_readiness_requires_smoke_test_and_caches_only_for_one_minute(monkeypatch):
    install_probe(monkeypatch)
    adapter = ocr.TesseractOCRAdapter()
    monkeypatch.setattr(ocr, "get_ocr_adapter", lambda: adapter)
    monkeypatch.setattr(module, "_smoke_cache", {})
    now, calls = [1.0], []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    def smoke():
        calls.append(True)
        return {"status": "PASSED" if len(calls) > 1 else "FAILED"}
    monkeypatch.setattr(module, "run_ocr_smoke", smoke)
    assert not module.ocr_readiness()["ready"]
    assert not module.ocr_readiness()["ready"] and len(calls) == 1
    now[0] += 61
    assert module.ocr_readiness()["ready"] and len(calls) == 2
    assert module.ocr_readiness(refresh=True)["ready"] and len(calls) == 3


def test_smoke_test_missing_font_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(module, "korean_font_path", lambda: None)
    assert module.run_ocr_smoke() == {"status": "FAILED", "reason": "KOREAN_TEST_FONT_MISSING"}


def test_smoke_uses_image_only_pdf_and_requires_korean_text_and_positions(monkeypatch):
    from packages.document_engine import registry
    from packages.common.schemas import BBox
    import pypdf
    if module.korean_font_path() is None:
        pytest.skip("Synthetic rendering requires a Korean font; Docker CI requires this check without skips")
    texts = ["법률 문서 검증 ACAS 12345", "ACAS 12345", "법률 문서 검증 ACAS 12345"]
    def parse(path, **kwargs):
        assert not pypdf.PdfReader(path).pages[0].extract_text().strip()
        text = texts.pop(0)
        block = SimpleNamespace(text=text, page=1, source_layer="ocr_layer",
                                bbox=BBox(0, 0, 100, 30) if texts else None)
        return SimpleNamespace(body_blocks=lambda: [block])
    monkeypatch.setattr(registry, "parse_document", parse)
    assert module.run_ocr_smoke()["status"] == "PASSED"
    assert module.run_ocr_smoke()["status"] == "FAILED"
    assert module.run_ocr_smoke()["status"] == "FAILED"


def test_mandatory_ocr_check_fails_closed(monkeypatch):
    monkeypatch.setattr(module, "ocr_readiness", lambda **kwargs: {"ready": False})
    with pytest.raises(RuntimeError, match="OCR_READINESS_FAILED"):
        module.require_ocr_ready()


def test_ci_check_returns_failure_instead_of_skipping(monkeypatch, capsys):
    from scripts import check_ocr_runtime
    monkeypatch.setattr(check_ocr_runtime, "ocr_readiness", lambda **kwargs: {"ready": False})
    assert check_ocr_runtime.main() == 1
    assert '"ready": false' in capsys.readouterr().out
