"""Synthetic HWP records only; never commit private case documents."""
import io
import struct
import zlib

import olefile
import pytest

from packages.document_engine import hwp_parser as hwp
from packages.document_engine.base import ParserError


def record(text, *, tag=0x43, extended=False):
    data = text if isinstance(text, bytes) else text.encode("utf-16-le")
    size = 0xFFF if extended else len(data)
    return struct.pack("<I", tag | (size << 20)) + (struct.pack("<I", len(data)) if extended else b"") + data


def raw_deflate(data):
    encoder = zlib.compressobj(wbits=-15)
    return encoder.compress(data) + encoder.flush()


def mock_ole(monkeypatch, streams, *, flags=1):
    header = b"HWP Document File".ljust(32, b"\0") + struct.pack("<II", 0x05000300, flags) + bytes(216)
    streams = {"FileHeader": header, **streams}
    class Ole:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def exists(self, name):
            return name in streams
        def get_size(self, name):
            return len(streams["/".join(name) if isinstance(name, list) else name])
        def openstream(self, name):
            return io.BytesIO(streams["/".join(name) if isinstance(name, list) else name])
        def listdir(self, **kwargs):
            return [name.split("/") for name in streams]
    monkeypatch.setattr(olefile, "OleFileIO", Ole)


@pytest.mark.parametrize("compressed", [False, True])
def test_reads_only_paragraph_records_in_numeric_section_order(monkeypatch, compressed):
    encode = raw_deflate if compressed else lambda data: data
    mock_ole(monkeypatch, {
        "BodyText/Section10": encode(record("세 번째")),
        "BodyText/Section2": encode(record("둘째")),
        "BodyText/Section0": encode(record("본문") + record("본문") + record("읽지 않을 서식", tag=0x44)),
        "PrvText": "미리보기만으로 검증하면 안 됨".encode("utf-16-le"),
        "BinData/data": zlib.compress(record("관련 없는 첨부자료")),
    }, flags=int(compressed))
    assert hwp._extract_hwp_text(b"synthetic") == ["본문", "본문", "둘째", "세 번째"]


def test_control_payload_is_not_misread_as_body_and_unicode_is_preserved():
    extended = struct.pack("<H", 2) + b"SHOULDNOTSEE" + struct.pack("<H", 2)
    tab = struct.pack("<H", 9) + bytes(12) + struct.pack("<H", 9)
    data = extended + "첫째".encode("utf-16-le") + tab + "둘째\n③항".encode("utf-16-le")
    assert hwp._section_text(record(data)) == ["첫째\t둘째\n③항"]
    assert hwp._section_text(record("가" * 3000, extended=True)) == ["가" * 3000]


@pytest.mark.parametrize("flags", [2, 4, 16, 256, 1024])
def test_encrypted_distributed_and_drm_documents_are_not_guessed(monkeypatch, flags):
    mock_ole(monkeypatch, {"PrvText": b"preview"}, flags=flags)
    with pytest.raises(ParserError, match="변환"):
        hwp._extract_hwp_text(b"synthetic")


@pytest.mark.parametrize("data", [b"x", struct.pack("<I", 0xFFF00043), record("valid")[:-1], record(b"\x01\x00")])
def test_truncated_records_fail_instead_of_silently_skipping(data):
    with pytest.raises(ParserError):
        hwp._section_text(data)


def test_decompression_is_bounded(monkeypatch):
    monkeypatch.setattr(hwp, "MAX_HWP_SECTION_BYTES", 128)
    mock_ole(monkeypatch, {"BodyText/Section0": raw_deflate(record("A" * 2000))})
    with pytest.raises(ParserError, match="한도"):
        hwp._extract_hwp_text(b"synthetic")


def test_failed_hwp_is_explicitly_body_unverified(tmp_path):
    path = tmp_path / "damaged.hwp"
    path.write_bytes(b"not-a-compound-file")
    doc = hwp.HwpParser().parse(str(path), document_id="d", filename=path.name, mime_type="", sha256="test")
    assert doc.structure["body_extraction_failed"] and doc.structure["unsupported_body"]
    assert not doc.body_blocks()


def test_trailing_bytes_after_complete_stream_are_reported_not_fatal(monkeypatch):
    # 일부 HWP 작성기는 완결된 DEFLATE 스트림 뒤에 채움 바이트를 남긴다. 본문은 완결됐으므로 읽되, 사실을 알린다.
    mock_ole(monkeypatch, {"BodyText/Section0": raw_deflate(record("본문")) + b"\x00" * 7})
    notes = []
    assert hwp._extract_hwp_text(b"synthetic", notes) == ["본문"]
    assert notes and "7" in notes[0]


def test_truncated_compressed_stream_still_fails_with_diagnostics(monkeypatch):
    mock_ole(monkeypatch, {"BodyText/Section0": raw_deflate(record("본문" * 50))[:-6]})
    with pytest.raises(ParserError, match="Section0"):
        hwp._extract_hwp_text(b"synthetic")
