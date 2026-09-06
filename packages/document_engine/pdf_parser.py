"""PDF / Scanned PDF Parser.

- 화면 표시 텍스트와 PDF Text Object를 구분해 보존한다(제7.3장 Cross-Layer Comparison).
- 흰색·초소형·페이지 밖 텍스트를 hidden_text 레이어로 분류한다(제7.2장).
- incremental update, annotation, XMP는 structure에 담아 포렌식 엔진에 전달한다(제7-A.2장).
"""
from __future__ import annotations

import io
import re
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from packages.common.schemas import BBox, Block, NormalizedDocument, Page, new_id

from packages.common.config import get_settings

from .base import DocumentParser, ParserError
from .ocr import get_ocr_adapter
from .rasterize import render_pages

HIDDEN_MIN_FONT_SIZE = 3.5
WHITE_THRESHOLD = 0.92


def _color_to_rgb(color: Any) -> Optional[Tuple[float, float, float]]:
    if color is None:
        return None
    if isinstance(color, (int, float)):
        g = float(color)
        return (g, g, g)
    if isinstance(color, (list, tuple)):
        vals = [float(c) for c in color if isinstance(c, (int, float))]
        if len(vals) == 1:
            return (vals[0], vals[0], vals[0])
        if len(vals) == 3:
            return (vals[0], vals[1], vals[2])
        if len(vals) == 4:  # CMYK
            c, m, y, k = vals
            return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _is_white(color: Any) -> bool:
    rgb = _color_to_rgb(color)
    if rgb is None:
        return False
    return all(v >= WHITE_THRESHOLD for v in rgb)


def _is_dark(color: Any) -> bool:
    rgb = _color_to_rgb(color)
    if rgb is None:
        return False
    return all(v <= 0.2 for v in rgb)


class PdfParser(DocumentParser):
    name = "PdfParser"
    extensions = [".pdf"]
    mime_types = ["application/pdf"]

    def parse(self, path: str, *, document_id: str, filename: str, mime_type: str, sha256: str) -> NormalizedDocument:
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover
            raise ParserError(f"pdfplumber 미설치: {exc}") from exc

        doc = NormalizedDocument(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type or "application/pdf",
            sha256=sha256,
            parser_name=self.name,
        )
        raw_bytes = Path(path).read_bytes()
        doc.structure["file_size"] = len(raw_bytes)
        self._collect_pdf_structure(raw_bytes, doc)

        rendered_parts: List[str] = []
        raw_parts: List[str] = []
        hidden_parts: List[str] = []

        with pdfplumber.open(path) as pdf:
            doc.metadata.update({k: str(v) for k, v in (pdf.metadata or {}).items()})
            for index, page in enumerate(pdf.pages, start=1):
                p = Page(page_number=index, width=float(page.width), height=float(page.height))
                chars = page.chars or []
                lines = self._group_chars_to_lines(chars)
                for line in lines:
                    text = "".join(c["text"] for c in line).strip()
                    if not text:
                        continue
                    bbox = self._line_bbox(line)
                    hidden_reason = self._hidden_reason(line, page)
                    block = Block(
                        block_id=new_id("B"),
                        text=text,
                        page=index,
                        bbox=bbox,
                        source_layer="hidden_text" if hidden_reason else "visible_text",
                        block_type="paragraph",
                        visible=not hidden_reason,
                        attributes={
                            "font": line[0].get("fontname"),
                            "size": round(float(line[0].get("size", 0)), 2),
                            "hidden_reason": hidden_reason,
                        },
                    )
                    p.blocks.append(block)
                    raw_parts.append(text)
                    if hidden_reason:
                        hidden_parts.append(text)
                    else:
                        rendered_parts.append(text)

                # 표
                try:
                    for t_index, table in enumerate(page.extract_tables() or []):
                        flat = "\n".join(" | ".join(str(c) if c else "" for c in row) for row in table)
                        if flat.strip():
                            blk = Block(
                                block_id=new_id("B"),
                                text=flat,
                                page=index,
                                source_layer="visible_text",
                                block_type="table",
                                attributes={"table_index": t_index},
                            )
                            p.blocks.append(blk)
                except Exception as exc:  # pragma: no cover - 파서 방어
                    doc.parse_warnings.append(f"page {index} table extraction failed: {exc}")

                p.attributes["rect_count"] = len(page.rects or [])
                p.attributes["image_count"] = len(page.images or [])
                p.attributes["filled_dark_rects"] = [
                    {
                        "bbox": (float(r["x0"]), float(r["top"]), float(r["x1"]), float(r["bottom"])),
                        "fill": _color_to_rgb(r.get("non_stroking_color")),
                    }
                    for r in (page.rects or [])
                    if r.get("fill") and _is_dark(r.get("non_stroking_color"))
                ]
                fonts = {c.get("fontname") for c in chars if c.get("fontname")}
                p.attributes["fonts"] = sorted(f for f in fonts if f)
                doc.pages.append(p)

        # annotation 텍스트를 별도 레이어 Block으로 추가
        for ann in doc.structure.get("annotations", []):
            if ann.get("contents"):
                page_no = ann.get("page", 1)
                target = next((pg for pg in doc.pages if pg.page_number == page_no), None)
                if target is None:
                    continue
                target.blocks.append(
                    Block(
                        block_id=new_id("B"),
                        text=str(ann["contents"]),
                        page=page_no,
                        source_layer="annotation",
                        block_type="comment",
                        visible=False,
                        attributes={"subtype": ann.get("subtype")},
                    )
                )

        # 스캔 PDF 본문 OCR 및 독립 OCR 교차검증 (제6장, 제7.3장)
        self._apply_ocr(doc, path, rendered_parts)

        doc.raw_layers["rendered_text"] = "\n".join(rendered_parts)
        doc.raw_layers["raw_text"] = "\n".join(raw_parts)
        doc.raw_layers["hidden_text"] = "\n".join(hidden_parts)
        doc.raw_layers["metadata_text"] = "\n".join(f"{k}: {v}" for k, v in doc.metadata.items())
        if doc.structure.get("xmp"):
            doc.raw_layers["xml"] = doc.structure["xmp"]
        ann_text = "\n".join(str(a.get("contents", "")) for a in doc.structure.get("annotations", []))
        if ann_text.strip():
            doc.raw_layers["annotation_text"] = ann_text

        if doc.structure.get("scanned_pdf_ocr_applied"):
            doc.structure["scanned_pdf"] = True
            doc.parse_warnings.append(
                f"표시 텍스트가 없어 스캔 PDF로 판단되어 OCR을 적용했다"
                f"(엔진 {doc.structure.get('ocr_engine')}, {doc.structure.get('ocr_pages')}면). "
                "OCR 결과는 원문과 다를 수 있으므로 인용문 대조는 원본 확인이 필요하다."
            )
        elif not doc.raw_layers["rendered_text"].strip():
            doc.parse_warnings.append(
                "표시 텍스트가 없어 스캔 PDF로 판단된다. OCR Adapter 결과가 없으면 본문 검증은 UNVERIFIED로 처리한다."
            )
            doc.structure["scanned_pdf"] = True
        return doc

    # -- 내부 유틸 --------------------------------------------------------
    @staticmethod
    def _group_chars_to_lines(chars: List[Dict[str, Any]], tolerance: float = 2.5) -> List[List[Dict[str, Any]]]:
        lines: List[List[Dict[str, Any]]] = []
        for ch in sorted(chars, key=lambda c: (round(float(c.get("top", 0)), 1), float(c.get("x0", 0)))):
            if lines and abs(float(ch.get("top", 0)) - float(lines[-1][-1].get("top", 0))) <= tolerance:
                lines[-1].append(ch)
            else:
                lines.append([ch])
        return lines

    @staticmethod
    def _line_bbox(line: List[Dict[str, Any]]) -> BBox:
        return BBox(
            x0=min(float(c["x0"]) for c in line),
            y0=min(float(c["top"]) for c in line),
            x1=max(float(c["x1"]) for c in line),
            y1=max(float(c["bottom"]) for c in line),
        )

    @staticmethod
    def _hidden_reason(line: List[Dict[str, Any]], page: Any) -> Optional[str]:
        first = line[0]
        size = float(first.get("size", 10) or 10)
        if size < HIDDEN_MIN_FONT_SIZE:
            return f"TINY_FONT({size:.2f}pt)"
        if all(_is_white(c.get("non_stroking_color")) for c in line):
            return "WHITE_ON_WHITE"
        bbox = PdfParser._line_bbox(line)
        if bbox.x1 < 0 or bbox.y1 < 0 or bbox.x0 > float(page.width) or bbox.y0 > float(page.height):
            return "OFF_PAGE"
        return None

    # -- OCR ---------------------------------------------------------------
    def _apply_ocr(self, doc: NormalizedDocument, path: str, rendered_parts: List[str]) -> None:
        """스캔 PDF는 본문을 OCR하고, 위험 신호가 있으면 독립 OCR로 텍스트 레이어를 대조한다."""
        settings = get_settings()
        adapter = get_ocr_adapter()
        has_visible_text = bool("".join(rendered_parts).strip())
        doc.structure["ocr_engine"] = adapter.name

        if not adapter.available:
            if not has_visible_text:
                doc.parse_warnings.append(
                    "OCR Adapter를 사용할 수 없어 스캔 PDF 본문을 추출하지 못했다. 본문 검증 항목은 UNVERIFIED로 표시한다."
                )
            return

        scanned = not has_visible_text
        risky = bool(
            doc.structure.get("has_invisible_render_mode")
            or doc.raw_layers.get("hidden_text", "").strip()
            or any(not block.visible for block in doc.blocks)
        )
        mode = settings.independent_ocr_mode.lower()
        run_independent = mode == "always" or (mode == "auto" and (risky or scanned))
        if mode == "off" and not scanned:
            return

        target_pages = [p.page_number for p in doc.pages]
        if scanned:
            target_pages = target_pages[: settings.ocr_max_pages]
        elif run_independent:
            target_pages = target_pages[: settings.independent_ocr_pages]
        else:
            return

        independent_parts: List[str] = []
        recognized_pages = 0
        for raster in render_pages(path, target_pages, dpi=settings.ocr_dpi):
            lines = adapter.recognize_image(raster.image, page=raster.page_number, scale=raster.scale)
            # 신뢰도 미달 라인은 버린다. 남은 것이 없으면 그 면은 인식 실패로 취급한다.
            kept = [line for line in lines if line.confidence >= settings.ocr_min_confidence]
            if not kept:
                continue
            recognized_pages += 1
            page = next((p for p in doc.pages if p.page_number == raster.page_number), None)
            for line in kept:
                independent_parts.append(line.text)
                if scanned and page is not None:
                    page.blocks.append(
                        Block(
                            block_id=new_id("B"),
                            text=line.text,
                            page=raster.page_number,
                            bbox=line.bbox,
                            source_layer="ocr_layer",
                            attributes={"ocr_confidence": round(line.confidence, 3), "ocr_engine": adapter.name},
                        )
                    )

        if not recognized_pages:
            return

        joined = "\n".join(independent_parts)
        doc.structure["ocr_pages"] = recognized_pages
        if scanned:
            doc.raw_layers["ocr_layer"] = joined
            rendered_parts.extend(independent_parts)
            doc.structure["scanned_pdf_ocr_applied"] = True
        else:
            # 화면 렌더링 결과와 내장 텍스트 레이어를 비교하기 위한 독립 OCR 산출물
            doc.raw_layers["independent_ocr"] = joined
            doc.structure["independent_ocr_pages"] = recognized_pages

    @staticmethod
    def _collect_pdf_structure(raw: bytes, doc: NormalizedDocument) -> None:
        """incremental update, annotation, XMP, 첨부파일, 서명 정보를 수집한다."""
        eof_count = raw.count(b"%%EOF")
        startxref_count = raw.count(b"startxref")
        doc.structure["eof_markers"] = eof_count
        doc.structure["startxref_count"] = startxref_count
        doc.structure["incremental_updates"] = max(0, eof_count - 1)

        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            doc.structure["page_count"] = len(reader.pages)
            doc.structure["encrypted"] = bool(reader.is_encrypted)
            info = reader.metadata or {}
            for k, v in dict(info).items():
                doc.metadata[str(k).lstrip("/")] = str(v)
            try:
                xmp = reader.xmp_metadata
                if xmp is not None and getattr(xmp, "stream", None) is not None:
                    doc.structure["xmp"] = xmp.stream.get_data().decode("utf-8", "replace")
            except Exception:
                pass

            annotations: List[Dict[str, Any]] = []
            has_signature = False
            for pno, page in enumerate(reader.pages, start=1):
                for annot_ref in page.get("/Annots") or []:
                    try:
                        annot = annot_ref.get_object()
                    except Exception:
                        continue
                    subtype = str(annot.get("/Subtype", ""))
                    entry: Dict[str, Any] = {
                        "page": pno,
                        "subtype": subtype,
                        "contents": str(annot.get("/Contents", "") or ""),
                    }
                    rect = annot.get("/Rect")
                    if rect is not None:
                        try:
                            entry["rect"] = [float(x) for x in rect]
                        except Exception:
                            pass
                    if subtype == "/Widget" and annot.get("/FT") == "/Sig":
                        has_signature = True
                    if annot.get("/FT") is not None:
                        entry["field_name"] = str(annot.get("/T", ""))
                        entry["field_value"] = str(annot.get("/V", ""))
                    if str(annot.get("/A", {}).get("/URI", "")) if isinstance(annot.get("/A"), dict) else False:
                        entry["uri"] = str(annot["/A"]["/URI"])
                    annotations.append(entry)
            doc.structure["annotations"] = annotations
            doc.structure["has_signature_field"] = has_signature

            # 첨부파일
            try:
                names = reader.trailer["/Root"].get("/Names", {})
                if names and "/EmbeddedFiles" in names:
                    doc.structure["has_embedded_files"] = True
            except Exception:
                pass

            # OCG(비표시 레이어)
            try:
                ocp = reader.trailer["/Root"].get("/OCProperties")
                if ocp:
                    d = ocp.get("/D", {})
                    off = d.get("/OFF") or []
                    doc.structure["ocg_off_count"] = len(off)
                    doc.structure["has_optional_content"] = True
            except Exception:
                pass

            # AcroForm
            try:
                if reader.trailer["/Root"].get("/AcroForm"):
                    doc.structure["has_acroform"] = True
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover
            doc.parse_warnings.append(f"pypdf 구조 분석 실패: {exc}")

        doc.structure["embedded_stream_text"] = _extract_stream_text(raw)
        doc.structure["has_invisible_render_mode"] = _has_invisible_render_mode(raw)


def _decode_stream(chunk: bytes, filters: str) -> bytes:
    """선언된 filter에 따라 안전 디코드한다. 외부 실행 없이 표준 라이브러리만 사용한다."""
    import base64

    data = chunk
    order = []
    if "ASCII85Decode" in filters or "A85" in filters:
        order.append("a85")
    if "ASCIIHexDecode" in filters or "AHx" in filters:
        order.append("ahx")
    if "FlateDecode" in filters or "Fl" in filters:
        order.append("flate")
    if not order:
        order = ["flate"]
    for step in order:
        try:
            if step == "a85":
                payload = data.strip()
                if payload.startswith(b"<~"):
                    payload = payload[2:]
                idx = payload.find(b"~>")
                if idx >= 0:
                    payload = payload[:idx]
                data = base64.a85decode(payload, adobe=False)
            elif step == "ahx":
                hex_only = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
                if len(hex_only) % 2:
                    hex_only += b"0"
                data = bytes.fromhex(hex_only.decode("ascii"))
            elif step == "flate":
                data = zlib.decompress(data)
        except Exception:
            return data
    return data


INVISIBLE_RENDER_MODE_RE = re.compile(rb"\b3\s+Tr\b")


def _extract_stream_text(raw: bytes, limit: int = 200000) -> str:
    """content stream을 안전 디코드해 PDF Text Object의 문자열만 뽑는다.

    외부 실행 없이 표준 디코더만 사용하며 실패는 무시한다.
    제7.3장 Cross-Layer Comparison의 'PDF Text Objects' 입력이다.
    """
    out: List[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw[:8_000_000], re.S):
        header = raw[max(0, m.start() - 400) : m.start()]
        filters = header.decode("latin-1", "ignore")
        data = _decode_stream(m.group(1), filters)
        text = data.decode("latin-1", "ignore")
        for tm in re.finditer(r"\((?:\\.|[^\\()])*\)\s*Tj|\[(?:[^\]]*)\]\s*TJ", text):
            segment = tm.group(0)
            for sm in re.finditer(r"\((?:\\.|[^\\()])*\)", segment):
                s = sm.group(0)[1:-1]
                s = s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
                if s.strip():
                    out.append(s)
        if sum(len(s) for s in out) > limit:
            break
    return "".join(out)


def _has_invisible_render_mode(raw: bytes) -> bool:
    """Tr 3(비표시 렌더모드) 사용 여부. 스캔 PDF의 OCR layer에서 정상적으로 쓰인다."""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw[:8_000_000], re.S):
        header = raw[max(0, m.start() - 400) : m.start()]
        data = _decode_stream(m.group(1), header.decode("latin-1", "ignore"))
        if INVISIBLE_RENDER_MODE_RE.search(data):
            return True
    return False
