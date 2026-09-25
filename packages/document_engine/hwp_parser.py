"""HWPX / HWP Parser.

HWPX는 OWPML(ZIP+XML) 구조를 직접 읽는다.
Binary HWP는 native parse를 시도하고 실패 시 UNSUPPORTED로 표시하여
전체 Job을 실패시키지 않는다(제14.2장, 제10장 Graceful Degradation).
"""
from __future__ import annotations

import io
import re
import struct
import zlib
from pathlib import Path
from typing import List, Optional

from packages.common.schemas import Block, NormalizedDocument, Page, new_id

from .base import DocumentParser, ParserError
from .ooxml_common import local_name, parse_xml, read_entries, safe_open_zip


class HwpxParser(DocumentParser):
    name = "HwpxParser"
    extensions = [".hwpx"]
    mime_types = ["application/hwp+zip", "application/vnd.hancom.hwpx"]

    def parse(self, path: str, *, document_id: str, filename: str, mime_type: str, sha256: str) -> NormalizedDocument:
        doc = NormalizedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type or self.mime_types[0],
            sha256=sha256,
            parser_name=self.name,
        )
        try:
            zf = safe_open_zip(path)
        except Exception as exc:
            raise ParserError(f"HWPX ZIP 처리 실패: {exc}") from exc

        visible: List[str] = []
        hidden: List[str] = []
        xml_parts: List[str] = []
        page = Page(page_number=1)

        with zf:
            doc.structure["zip_entries"] = [i.filename for i in zf.infolist()]
            entries = read_entries(zf, lambda n: n.endswith(".xml"))
            sections = {k: v for k, v in entries.items() if "section" in k.lower()}
            for name in sorted(sections):
                data = sections[name]
                xml_parts.append(data.decode("utf-8", "replace"))
                try:
                    root = parse_xml(data)
                except Exception as exc:
                    doc.parse_warnings.append(f"{name} 파싱 실패: {exc}")
                    continue
                for para in root.iter():
                    if local_name(para.tag) != "p":
                        continue
                    text = "".join(t.text or "" for t in para.iter() if local_name(t.tag) == "t")
                    text = text.strip()
                    if not text:
                        continue
                    page.blocks.append(
                        Block(block_id=new_id("B"), text=text, page=1, source_layer="visible_text")
                    )
                    visible.append(text)

            # 메모/주석/설정
            for name, data in entries.items():
                low = name.lower()
                if any(k in low for k in ("memo", "comment", "annotation")):
                    xml_parts.append(data.decode("utf-8", "replace"))
                    try:
                        root = parse_xml(data)
                    except Exception:
                        continue
                    texts = [t.text.strip() for t in root.iter() if local_name(t.tag) == "t" and t.text and t.text.strip()]
                    for t in texts:
                        page.blocks.append(
                            Block(
                                block_id=new_id("B"),
                                text=t,
                                page=1,
                                source_layer="xml",
                                block_type="comment",
                                visible=False,
                                attributes={"part": name},
                            )
                        )
                        hidden.append(t)
                if "content.hpf" in low or "meta" in low or "version" in low:
                    xml_parts.append(data.decode("utf-8", "replace"))

            meta = entries.get("Contents/content.hpf") or entries.get("META-INF/container.xml")
            if meta:
                try:
                    root = parse_xml(meta)
                    for el in root.iter():
                        tag = local_name(el.tag)
                        if el.text and el.text.strip() and tag in ("title", "creator", "date", "publisher", "subject"):
                            doc.metadata[tag] = el.text.strip()
                except Exception:
                    pass

        doc.pages.append(page)
        doc.raw_layers["rendered_text"] = "\n".join(visible)
        doc.raw_layers["raw_text"] = "\n".join(visible + hidden)
        doc.raw_layers["hidden_text"] = "\n".join(hidden)
        doc.raw_layers["xml"] = "\n".join(xml_parts)
        doc.raw_layers["metadata_text"] = "\n".join(f"{k}: {v}" for k, v in doc.metadata.items())
        return doc


class HwpParser(DocumentParser):
    """Binary HWP 5.x. CFB 컨테이너의 BodyText 스트림을 zlib 해제해 텍스트만 추출한다."""

    name = "HwpParser"
    extensions = [".hwp"]
    mime_types = ["application/x-hwp", "application/haansofthwp"]

    def parse(self, path: str, *, document_id: str, filename: str, mime_type: str, sha256: str) -> NormalizedDocument:
        doc = NormalizedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type or self.mime_types[0],
            sha256=sha256,
            parser_name=self.name,
        )
        raw = Path(path).read_bytes()
        if not raw.startswith(b"\xd0\xcf\x11\xe0"):
            doc.parse_warnings.append("HWP CFB 시그니처가 아니다. 형식 확인 필요.")
        texts: List[str] = []
        try:
            texts = _extract_hwp_text(raw, doc.parse_warnings)
        except Exception as exc:
            doc.parse_warnings.append(f"HWP native parse 실패: {exc}")

        if not texts:
            doc.parse_warnings.append(
                "Binary HWP 본문 추출에 실패했다. isolated conversion fallback(HWPX/PDF 변환) 후 재업로드가 필요하며, "
                "현재 문서의 본문 검증 항목은 UNVERIFIED로 처리한다."
            )
            doc.structure["unsupported_body"] = True
            doc.structure["body_extraction_failed"] = True
        else:
            doc.structure["body_extraction_scope"] = "HWP_PARAGRAPH_RECORDS"
            doc.structure["page_numbers_reliable"] = False
            doc.parse_warnings.append("HWP 본문 텍스트를 추출했습니다. 원본 쪽 번호와 시각적 배치·서식은 확인되지 않습니다.")

        page = Page(page_number=1)
        for t in texts:
            page.blocks.append(Block(block_id=new_id("B"), text=t, page=1, source_layer="visible_text"))
        doc.pages.append(page)
        joined = "\n".join(texts)
        doc.raw_layers["rendered_text"] = joined
        doc.raw_layers["raw_text"] = joined
        return doc


MAX_HWP_SECTION_BYTES = 16 * 1024 * 1024
MAX_HWP_BODY_BYTES = 32 * 1024 * 1024
MAX_HWP_SECTIONS = 512
MAX_HWP_RECORDS = 200_000


def _paragraph_text(data: bytes) -> str:
    if len(data) % 2:
        raise ParserError("HWP 문단 텍스트 길이가 잘못되었습니다")
    output = bytearray()
    cursor = 0
    while cursor < len(data):
        code = struct.unpack_from("<H", data, cursor)[0]
        if code >= 32:
            output.extend(data[cursor:cursor + 2])
            cursor += 2
            continue
        # Inline/extended controls occupy eight UTF-16 code units, not one.
        width = 16 if code in {*range(1, 10), 11, 12, *range(14, 24)} else 2
        if cursor + width > len(data):
            raise ParserError("HWP 문단 제어문자가 잘렸습니다")
        replacement = {9: "\t", 10: "\n", 13: "\n", 24: "-", 30: " ", 31: " "}.get(code, "")
        output.extend(replacement.encode("utf-16-le"))
        cursor += width
    return output.decode("utf-16-le").strip()


def _section_text(data: bytes) -> List[str]:
    texts = []
    cursor = count = 0
    while cursor < len(data):
        count += 1
        if count > MAX_HWP_RECORDS or len(data) - cursor < 4:
            raise ParserError("HWP 레코드 수 초과 또는 잘린 헤더")
        header = struct.unpack_from("<I", data, cursor)[0]
        tag, size = header & 0x3FF, header >> 20
        cursor += 4
        if size == 0xFFF:
            if len(data) - cursor < 4:
                raise ParserError("HWP 확장 길이 헤더가 잘렸습니다")
            size = struct.unpack_from("<I", data, cursor)[0]
            cursor += 4
        if size > len(data) - cursor:
            raise ParserError("HWP 레코드 본문이 잘렸습니다")
        if tag == 0x43:  # HWPTAG_PARA_TEXT, including table-cell paragraphs.
            text = _paragraph_text(data[cursor:cursor + size])
            if text:
                texts.append(text)
        cursor += size
    return texts


def _extract_hwp_text(raw: bytes, notes: Optional[List[str]] = None) -> List[str]:
    """Read CFB streams and raw DEFLATE records per the Hancom HWP 5.0 spec.

    https://tech.hancom.com/python-hwp-parsing-2/
    Preview text and embedded binary data are not substitutes for the body.
    """
    results: List[str] = []
    for data in _section_streams(raw, notes):
        results.extend(_section_text(data))
    return results


def _extract_hwp_tables(raw: bytes, notes: Optional[List[str]] = None) -> List[List[List[str]]]:
    """표를 셀 단위로 복원한다(행 목록, 각 행은 열 순서의 셀 글자). 셀 글자를 이어 붙이지 않는다."""
    tables: List[List[List[str]]] = []
    for data in _section_streams(raw, notes):
        tables.extend(_section_tables(data))
    return tables


def _records(data: bytes):
    cursor = count = 0
    while cursor < len(data):
        count += 1
        if count > MAX_HWP_RECORDS or len(data) - cursor < 4:
            raise ParserError("HWP 레코드 수 초과 또는 잘린 헤더")
        header = struct.unpack_from("<I", data, cursor)[0]
        tag, level, size = header & 0x3FF, (header >> 10) & 0x3FF, header >> 20
        cursor += 4
        if size == 0xFFF:
            if len(data) - cursor < 4:
                raise ParserError("HWP 확장 길이 헤더가 잘렸습니다")
            size = struct.unpack_from("<I", data, cursor)[0]
            cursor += 4
        if size > len(data) - cursor:
            raise ParserError("HWP 레코드 본문이 잘렸습니다")
        yield tag, level, data[cursor:cursor + size]
        cursor += size


HWPTAG_TABLE, HWPTAG_LIST_HEADER, HWPTAG_PARA_TEXT = 0x4D, 0x48, 0x43


def _section_tables(data: bytes) -> List[List[List[str]]]:
    """HWPTAG_TABLE(행·열 수) 뒤의 셀 머리(HWPTAG_LIST_HEADER: 열·행 주소)마다 그 아래 문단 글자를 모은다."""
    tables: List[List[List[str]]] = []
    grid: Optional[List[List[str]]] = None
    table_level = cell_level = -1
    cell = None
    for tag, level, body in _records(data):
        if grid is not None and level < table_level:  # 표 제어보다 바깥 수준의 레코드가 나오면 표가 끝났다
            tables.append(grid)
            grid, cell = None, None
        if tag == HWPTAG_TABLE and len(body) >= 8 and grid is None:
            rows, cols = struct.unpack_from("<HH", body, 4)
            if 0 < rows <= 2000 and 0 < cols <= 100:
                grid = [["" for _ in range(cols)] for _ in range(rows)]
                table_level = level
        elif tag == HWPTAG_LIST_HEADER and grid is not None and len(body) >= 12 and level in (table_level, table_level + 1):
            col, row = struct.unpack_from("<HH", body, 8)
            cell = (row, col) if row < len(grid) and col < len(grid[0]) else None
            cell_level = level
        elif tag == HWPTAG_PARA_TEXT and grid is not None and cell is not None and level > cell_level:
            text = _paragraph_text(body)
            if text:
                row, col = cell
                grid[row][col] = f"{grid[row][col]} {text}".strip() if grid[row][col] else text
    if grid is not None:
        tables.append(grid)
    return tables


def _section_streams(raw: bytes, notes: Optional[List[str]] = None) -> List[bytes]:
    import olefile

    with olefile.OleFileIO(io.BytesIO(raw)) as ole:
        if not ole.exists("FileHeader") or ole.get_size("FileHeader") != 256:
            raise ParserError("HWP FileHeader가 없거나 길이가 잘못되었습니다")
        header = ole.openstream("FileHeader").read()
        if header[:32].rstrip(b"\0") != b"HWP Document File" or header[35] != 5:
            raise ParserError("지원하지 않는 HWP 형식입니다")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & ((1 << 1) | (1 << 2) | (1 << 4) | (1 << 8) | (1 << 10)):
            raise ParserError("암호화·배포용·DRM HWP는 HWPX 또는 PDF 변환 후 검증해야 합니다")
        sections = [path for path in ole.listdir(streams=True, storages=False)
                    if len(path) == 2 and path[0] == "BodyText" and re.fullmatch(r"Section\d+", path[1])]
        sections.sort(key=lambda path: int(path[1][7:]))
        if not sections or len(sections) > MAX_HWP_SECTIONS:
            raise ParserError("HWP 본문 구역이 없거나 구역 수 한도를 초과했습니다")
        streams, body_size = [], 0
        for section in sections:
            if ole.get_size(section) > MAX_HWP_SECTION_BYTES:
                raise ParserError("HWP 본문 스트림 크기 한도 초과")
            data = ole.openstream(section).read()
            if flags & 1:
                decoder = zlib.decompressobj(-15)
                data = decoder.decompress(data, MAX_HWP_SECTION_BYTES + 1)
                if len(data) > MAX_HWP_SECTION_BYTES or not decoder.eof:
                    raise ParserError(f"HWP 압축 본문 한도 초과 또는 손상({section[1]}: 스트림 완결={decoder.eof}, "
                                      f"해제 {len(data)}바이트)")
                # 완결된 DEFLATE 스트림 뒤의 바이트는 본문이 아니다(작성기 채움 바이트). 읽지 않고 알린다.
                if decoder.unused_data and notes is not None:
                    notes.append(f"HWP {section[1]} 압축 스트림 뒤 {len(decoder.unused_data)}바이트는 본문으로 읽지 않았다")
            body_size += len(data)
            if body_size > MAX_HWP_BODY_BYTES:
                raise ParserError("HWP 전체 본문 크기 한도 초과")
            streams.append(data)
        return streams
