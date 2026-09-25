"""v4 P8: 손상 PDF 신호·파서 대체 경로·파서 불일치·회전 스캔 방향 보정·공통 JSON 직렬화."""
from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from packages.common.schemas import NormalizedDocument
from packages.document_engine.pdf_parser import _parse_with_pypdf, _structure_problems, parser_disagreement
from packages.report_engine.serialize import ERROR_KEY, dumps, jsonable_payload, to_jsonable, write_json
from packages.verification_engine.pipeline import parser_integrity_findings


def _pdf(tmp_path, lines, name="a.pdf"):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    path = tmp_path / name
    c = canvas.Canvas(str(path), pagesize=A4)
    for i, line in enumerate(lines):
        c.drawString(60, 780 - i * 16, line)
    c.save()
    return path


def _damage(data: bytes) -> bytes:
    at = data.rfind(b"startxref")
    return data[:at] + b"startxref\n999999999\n%%EOF\n"


# --- 구조 손상 -------------------------------------------------------------------------------
def test_intact_pdf_has_no_structure_problem(tmp_path):
    assert _structure_problems(_pdf(tmp_path, ["Civil brief"]).read_bytes()) == []


@pytest.mark.parametrize("mutate, expected", [
    (_damage, "파일 크기"),                                               # startxref가 파일 밖
    (lambda d: d.replace(b"%%EOF", b""), "%%EOF"),                       # 끝 표지 삭제
    (lambda d: d[:d.rfind(b"startxref")], "startxref가 없다"),          # 트레일러 잘림
])
def test_structure_problems_are_named(tmp_path, mutate, expected):
    problems = _structure_problems(mutate(_pdf(tmp_path, ["Administrative ruling"]).read_bytes()))
    assert any(expected in p for p in problems)


def test_malformed_pdf_finding_carries_defect_code_and_parser_chain():
    doc = NormalizedDocument(document_id="d", filename="손상.pdf", mime_type="application/pdf", sha256="0")
    doc.structure.update(malformed=["startxref 위치(999)가 파일 크기(10)를 넘는다"], parser_chain=["pdfplumber"])
    [finding] = parser_integrity_findings(doc)
    assert finding.confidence_features["defect_code"] == "MALFORMED_PDF" and "pdfplumber" in finding.detail


# --- 파서 대체 경로·불일치 -----------------------------------------------------------------
def test_pypdf_fallback_reads_text(tmp_path):
    doc = NormalizedDocument(document_id="d", filename="a.pdf", mime_type="application/pdf", sha256="0")
    doc.structure["parser_chain"] = ["pdfplumber:실패(PDFSyntaxError)"]
    _parse_with_pypdf(_pdf(tmp_path, ["Criminal defense brief", "Family petition"]).read_bytes(), doc)
    assert doc.structure["parser_chain"][-1] == "pypdf"
    assert "Criminal defense brief" in doc.raw_layers["rendered_text"]


def test_parser_disagreement_only_when_texts_differ(tmp_path):
    raw = _pdf(tmp_path, ["The plaintiff seeks damages of 30,000,000 won for the injury on 2023-03-15."] * 3).read_bytes()
    same = "The plaintiff seeks damages of 30,000,000 won for the injury on 2023-03-15." * 3
    assert parser_disagreement(raw, {1: same}) == []
    [item] = parser_disagreement(raw, {1: "완전히 다른 글자층이 들어 있는 쪽입니다" * 5})
    assert item["page"] == 1 and item["overlap"] < 0.6


# --- 회전 스캔 --------------------------------------------------------------------------------
def test_rotated_scan_is_reoriented_before_judgement():
    from types import SimpleNamespace

    from PIL import Image

    from packages.document_engine.ocr import OCRLine
    from packages.document_engine.pdf_parser import _reoriented

    class Adapter:
        def detect_rotation(self, image):
            return None                    # OSD가 판단하지 못한 경우: 세 방향을 모두 읽는다

        def recognize_image(self, image, page=1, scale=1.0):
            upright = image.size == (100, 200)
            return [OCRLine("대법원 판결 참조" if upright else "xq zz", page, confidence=0.95 if upright else 0.3)]

    raster = SimpleNamespace(image=Image.new("RGB", (200, 100)), page_number=4, scale=1.0)
    lines, quality, angle = _reoriented(Adapter(), raster, {"low_quality": True, "hangul_ratio": 0.0,
                                                            "confidence": 0.3, "lines": 1})
    assert angle in (90, 270) and lines[0].text == "대법원 판결 참조" and not quality["low_quality"]


# --- 공통 직렬화 ------------------------------------------------------------------------------
class Color(enum.Enum):
    RED = "red"


@dataclass
class Item:
    name: str
    amount: Decimal


class Broken:
    def to_dict(self):
        raise RuntimeError("boom")


def test_to_jsonable_handles_common_types_and_matches_legacy_roundtrip():
    value = {"when": datetime(2026, 9, 25, tzinfo=timezone.utc), "amount": Decimal("12.50"), "tags": {"b", "a"},
             "item": Item("영수증", Decimal("1200000")), "color": Color.RED, "blob": b"abc"}
    out = to_jsonable(value)
    assert out["when"] == str(value["when"]) and out["amount"] == "12.50" and out["tags"] == ["a", "b"]
    assert out["item"] == {"name": "영수증", "amount": "1200000"}
    assert out["blob"] == {"$bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    simple = {"a": [1, 2, (3, 4)], "b": Decimal("1.5"), "c": datetime(2026, 1, 1)}
    assert to_jsonable(simple) == json.loads(json.dumps(simple, default=str))


def test_one_broken_field_does_not_drop_the_report():
    payload = jsonable_payload({"ok": 1, "bad": Broken(), "nested": {"also_bad": Broken()}})
    assert payload["ok"] == 1 and payload["bad"] == {ERROR_KEY: "RuntimeError"}
    assert [e["path"] for e in payload["serialization_errors"]] == ["$.bad", "$.nested.also_bad"]
    json.loads(dumps({"bad": Broken()}))


def test_write_json_streams_and_reports_hash(tmp_path):
    info = write_json(tmp_path / "out.json", {"rows": list(range(1000))}, limit=100)
    data = (tmp_path / "out.json").read_bytes()
    assert info["bytes"] == len(data) and info["sha256"] == hashlib.sha256(data).hexdigest() and info["over_limit"]
