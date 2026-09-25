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
from .line_tables import rebuild_line_tables
from .ocr import get_ocr_adapter, page_quality
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


def _relative_luminance(rgb: Tuple[float, float, float]) -> float:
    """WCAG 상대 휘도(0~1)."""
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(max(0.0, min(1.0, v))) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: Tuple[float, float, float], second: Tuple[float, float, float]) -> float:
    """WCAG 명도 대비비(1~21). 1.5 미만이면 사람이 사실상 읽을 수 없다."""
    a, b = _relative_luminance(first), _relative_luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


MIN_READABLE_CONTRAST = 1.5
TRANSPARENT_ALPHA = 0.1


def _is_dark(color: Any) -> bool:
    rgb = _color_to_rgb(color)
    if rgb is None:
        return False
    return all(v <= 0.2 for v in rgb)


_SIGNATURE_RE = re.compile(r"\s+")


def _text_signature(text: str) -> str:
    """공백을 지운 비교용 문자열. 줄바꿈 위치 차이를 무시한다."""
    return _SIGNATURE_RE.sub("", text or "")


def _covered_by(line_signature: str, rows: List[List[str]]) -> bool:
    """표의 셀 내용이 이미 줄 텍스트에 모두 들어 있는지 본다.

    한 셀이라도 줄 텍스트에 없으면 진짜 표로 보고 남긴다.
    """
    cells = [_text_signature(c) for row in rows for c in row]
    meaningful = [c for c in cells if len(c) >= 2]
    if not meaningful:
        return True
    return all(c in line_signature for c in meaningful)


def _cells_run_together(blocks, table_bbox, rows: List[List[str]]) -> bool:
    """표 영역의 줄 글자에서 이웃한 칸이 공백 없이 붙어 있는지("진단서2023. 2. 30.").

    붙어 있으면 줄 블록으로는 칸 경계를 알 수 없으므로 진짜 여러 칸 표로 보고 칸 단위로 읽어야 한다.
    문단을 표로 잘못 잡은 경우에는 칸 경계가 어절 사이(공백)에 놓이므로 붙지 않는다.
    """
    texts = [b.text for b in blocks if _inside(b.bbox, table_bbox)]
    multi = [[c.strip() for c in row if c and c.strip()] for row in rows]
    multi = [row for row in multi if len(row) >= 2]
    if not multi or not texts:
        return False
    joined = [sum(1 for a, b in zip(row, row[1:]) if any((a + b) in t for t in texts)) for row in multi]
    return sum(1 for n in joined if n) * 2 >= len(multi)


def _inside(bbox, area, margin: float = 2.0) -> bool:
    if not bbox or not area:
        return False
    x0, top, x1, bottom = (bbox.as_tuple() if hasattr(bbox, "as_tuple") else bbox)
    ax0, atop, ax1, abottom = area
    return x0 >= ax0 - margin and x1 <= ax1 + margin and top >= atop - margin and bottom <= abottom + margin


def _column_segments(line: List[Dict[str, Any]]) -> List[List[Any]]:
    """글자 사이 간격이 글자 크기의 1.5배를 넘는 곳에서 줄을 칸으로 나눈다. [[x0, x1, text], ...]"""
    segments: List[List[Any]] = []
    previous = None
    for char in line:
        size = float(char.get("size", 10) or 10)
        x0, x1 = float(char.get("x0", 0)), float(char.get("x1", 0))
        if previous is None or x0 - previous > 1.5 * size:
            segments.append([x0, x1, char.get("text", "")])
        else:
            segments[-1][1] = x1
            segments[-1][2] += char.get("text", "")
        previous = x1
    return [[round(a, 1), round(b, 1), t.strip()] for a, b, t in segments if t.strip()]


def _link_lines_to_table(blocks, table_bbox, table_ref) -> List[str]:
    """표 영역 안의 줄 블록에 표 식별자를 붙여, 줄 텍스트와 표 구조를 서로 찾아가게 한다."""
    linked = []
    for block in blocks:
        if _inside(block.bbox, table_bbox):
            block.attributes["table_ref"] = table_ref
            linked.append(block.block_id)
    return linked


def _table_title(blocks, table_bbox) -> Optional[str]:
    """표 바로 위(40pt 이내)의 줄을 표 제목 후보로 둔다."""
    if not table_bbox:
        return None
    best = None
    for block in blocks:
        if not block.bbox or block.attributes.get("table_ref"):
            continue
        x0, top, x1, bottom = block.bbox.as_tuple()
        gap = table_bbox[1] - bottom
        if -3 <= gap <= 40 and (best is None or gap < best[0]):
            best = (gap, block.text.strip())
    return best[1] if best else None


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
        # 표 중복 판정에 쓰는 공백 제거 서명. 줄마다 모아 둔다. 예전에는
        # 페이지마다 그때까지의 본문 전체를 다시 정규화했고, 그 비용은
        # 페이지 수의 제곱에 비례해 늘었다. \s+ 제거는 부분마다 해도
        # 전체에 한 번 해도 결과가 같다.
        signature_parts: List[str] = []

        facts: Dict[str, set] = {"invisible": set(), "covered": set(), "transparent": set(), "image_covered": set(),
                                 "clipped": set()}
        head = raw_bytes[:8_000_000]
        if doc.structure.get("has_invisible_render_mode") or FILLED_SHAPE_RE.search(head) \
                or doc.structure.get("has_filled_shapes") or doc.structure.get("has_clip_paths") \
                or ALPHA_RE.search(head) or b"/Image" in head:
            try:
                facts = _render_facts(path)
            except Exception as exc:  # pragma: no cover - 파서 방어
                doc.parse_warnings.append(f"렌더모드·투명도·가림 확인 실패: {exc}")
        invisible, covered = facts["invisible"], facts["covered"]
        transparent, image_covered = facts["transparent"], facts["image_covered"]
        clipped = facts.get("clipped") or set()
        contrast_checks: List[Tuple[int, Block, List[Dict[str, Any]]]] = []
        # 파서 대체 경로(v4 P8): pdfplumber가 열지 못하면 pypdf 글자 추출로 읽고, 그것도 안 되면 본문 없음으로 둔다.
        try:
            pdfplumber.open(path).close()
            doc.structure["parser_chain"] = ["pdfplumber"]
        except Exception as exc:
            doc.structure["parser_chain"] = [f"pdfplumber:실패({type(exc).__name__})"]
            _parse_with_pypdf(raw_bytes, doc)
            return doc
        page_texts: Dict[int, str] = {}
        with pdfplumber.open(path) as pdf:
            doc.metadata.update({k: str(v) for k, v in (pdf.metadata or {}).items()})
            for index, page in enumerate(pdf.pages, start=1):
                p = Page(page_number=index, width=float(page.width), height=float(page.height))
                chars = page.chars or []
                page_texts[index] = "".join(str(c.get("text") or "") for c in chars)
                lines = self._group_chars_to_lines(chars)
                # 스캔본은 쪽 전체 이미지 위에 Tr 3 OCR 글자층을 얹는 것이 정상이다. 그 쪽의 Tr 3은 숨김이 아니다.
                scan_like = _image_coverage(page) >= 0.5
                # 흰색이 아닌 채움 도형 위의 글자는 글자색이 어두워도 배경과 대비를 봐야 한다(어두운 글자·어두운 상자).
                colored_fills = [(float(r["x0"]), float(r["top"]), float(r["x1"]), float(r["bottom"]))
                                 for r in (page.rects or []) if r.get("fill") and not _is_white(r.get("non_stroking_color"))]
                for line in lines:
                    text = "".join(c["text"] for c in line).strip()
                    if not text:
                        continue
                    bbox = self._line_bbox(line)
                    hidden_reason = self._hidden_reason(line, page)
                    if clipped and (hidden_reason is None or hidden_reason.startswith("TINY_FONT")):
                        # 클리핑 영역 밖(또는 면적 0인 클리핑)에 그린 글자는 크기와 무관하게 보이지 않는다(v5 3-7).
                        # 작은 글자로 함께 숨긴 경우에도 실제 숨김 수단인 클리핑으로 분류한다. 쪽 경계도 클리핑으로 잡히므로
                        # 페이지 밖 좌표(OFF_PAGE) 등 더 구체적인 사유는 그대로 둔다.
                        keys = [(index, round(float(c["x0"]), 1), round(float(c["y0"]), 1))
                                for c in line if c["text"].strip()]
                        if keys and sum(k in clipped for k in keys) >= max(1, 0.8 * len(keys)):
                            hidden_reason = "CLIPPED_OUT"
                    if hidden_reason is None and (invisible or covered or transparent or image_covered):
                        keys = [(index, round(float(c["x0"]), 1), round(float(c["y0"]), 1))
                                for c in line if c["text"].strip()]
                        threshold = max(1, 0.8 * len(keys))
                        if invisible and not scan_like and sum(k in invisible for k in keys) >= threshold:
                            hidden_reason = "INVISIBLE_RENDER_MODE"
                        elif transparent and sum(k in transparent for k in keys) >= threshold:
                            hidden_reason = "TRANSPARENT_FILL"          # 채움 투명도(ExtGState ca)가 0에 가까움
                        elif covered and sum(k in covered for k in keys) >= threshold:
                            hidden_reason = "COVERED_BY_SHAPE"
                        elif image_covered and sum(k in image_covered for k in keys) >= threshold:
                            hidden_reason = "COVERED_BY_IMAGE"
                    attributes = {
                        "font": line[0].get("fontname"),
                        "size": round(float(line[0].get("size", 0)), 2),
                        "hidden_reason": hidden_reason,
                    }
                    segments = _column_segments(line)
                    if len(segments) > 1:
                        # 칸 사이가 크게 벌어진 줄은 괘선 없는 표의 한 줄일 수 있다(표 복원에 쓴다).
                        attributes["segments"] = segments
                    block = Block(
                        block_id=new_id("B"),
                        text=text,
                        page=index,
                        bbox=bbox,
                        source_layer="hidden_text" if hidden_reason else "visible_text",
                        block_type="paragraph",
                        visible=not hidden_reason,
                        attributes=attributes,
                    )
                    p.blocks.append(block)
                    raw_parts.append(text)
                    signature_parts.append(_text_signature(text))
                    if hidden_reason in (None, "WHITE_ON_WHITE") and _needs_contrast_check(line, colored_fills):
                        # 글자색만으로는 알 수 없다. 실제 렌더링한 배경과의 대비비로 판단한다(추가지시 J4·§3-2).
                        contrast_checks.append((index, block, line))
                    if hidden_reason:
                        hidden_parts.append(text)
                    else:
                        rendered_parts.append(text)

                # 표
                #
                # pdfplumber의 표 검출은 글자 정렬만 보므로, 들여쓰기가 규칙적인
                # 법률 서면의 일반 문단도 표로 잡아낸다. 그 결과가 줄 블록과 함께
                # 남으면 같은 문장이 두 벌 생기고, 그중 한 벌은 셀이 " | "로 이어진
                # 파편이 된다. 실제 검증보고서에서 주장 101건 중 16건이 이 파편이었다.
                # 이미 줄 블록으로 읽은 내용과 같은 표는 버린다.
                try:
                    found = page.find_tables() or []
                    tables = [(t.extract() or [], t.bbox) for t in found]
                    # 표가 있는 페이지에서만 서명을 잇는다. 법률 서면은 표가
                    # 드물어 대부분의 페이지가 이 비용을 아예 건너뛴다.
                    line_signature = "".join(signature_parts) if tables else ""
                    for t_index, (table, table_bbox) in enumerate(tables):
                        rows = [[str(c) if c else "" for c in row] for row in table]
                        flat = "\n".join(" | ".join(row) for row in rows)
                        if not flat.strip():
                            continue
                        table_ref = f"p{index}t{t_index}"
                        structure = {"table_ref": table_ref, "page": index, "table_index": t_index,
                                     "bbox": [float(v) for v in table_bbox] if table_bbox else None,
                                     "cells": rows, "header": rows[0] if rows else [],
                                     "title": _table_title(p.blocks, table_bbox),
                                     "row_count": len(rows), "column_count": max((len(r) for r in rows), default=0)}
                        if _covered_by(line_signature, rows) and not _cells_run_together(p.blocks, table_bbox, rows):
                            # 같은 글자는 줄 블록으로 이미 있다. 표 블록을 따로 만들어 중복 표시하지
                            # 않되, 행·열 구조는 버리지 않고 남겨 줄 블록과 연결한다. 첨부 목록처럼
                            # "자료명"과 "첨부 여부"의 대응이 의미를 갖는 표가 있기 때문이다.
                            structure["representation"] = "LINES_WITH_STRUCTURE"
                            structure["line_block_ids"] = _link_lines_to_table(p.blocks, table_bbox, table_ref)
                            doc.structure.setdefault("tables", []).append(structure)
                            doc.parse_warnings.append(
                                f"page {index} table {t_index}: 줄 텍스트와 같은 내용이라 표 블록을 따로 만들지 않고 "
                                "행·열 구조를 보존해 줄 블록과 연결했다"
                            )
                            continue
                        structure["representation"] = "TABLE_BLOCK"
                        # 표 영역 안의 줄 블록은 여러 칸의 글자가 한 줄에 섞여 있다("…선는 재량권 남용…").
                        # 문장 분석·인용 추출은 칸 구조가 살아 있는 표 블록으로 하고, 줄은 표의 줄로 표시한다.
                        structure["line_block_ids"] = _link_lines_to_table(p.blocks, table_bbox, table_ref)
                        for block in p.blocks:
                            if block.block_id in structure["line_block_ids"] and block.visible:
                                block.block_type = "table_line"
                        doc.structure.setdefault("tables", []).append(structure)
                        blk = Block(
                            block_id=new_id("B"),
                            text=flat,
                            page=index,
                            source_layer="visible_text",
                            block_type="table",
                            # 셀 구조를 남겨 두면 검산이 " | " 재파싱에 의존하지 않는다
                            attributes={"table_index": t_index, "cells": rows, "table_ref": table_ref},
                        )
                        p.blocks.append(blk)
                    if not tables:
                        # 괘선 없는 표는 pdfplumber가 찾지 못한다. 줄의 칸 좌표로 복원한다.
                        rebuild_line_tables(doc, p)
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
                # pdfplumber는 페이지마다 파싱 결과를 캐시해 둔다. 긴 문서에서는
                # 그것이 전부 쌓여 메모리를 지배한다. 이 페이지에서 필요한 것은
                # 모두 읽었으므로 놓아준다.
                page.flush_cache()
                chars = []

        if contrast_checks:
            try:
                _apply_contrast(path, contrast_checks, rendered_parts, hidden_parts)
            except Exception as exc:  # pragma: no cover - 파서 방어
                doc.parse_warnings.append(f"글자 대비 확인 실패: {exc}")

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
        # 두 파서의 글자 추출이 크게 다른 쪽(PARSER_DISAGREEMENT). 글자층이 손상·조작된 신호일 수 있다.
        disagreement = parser_disagreement(raw_bytes, page_texts)
        if disagreement:
            doc.structure["parser_disagreement"] = disagreement
            doc.structure["parser_chain"].append("pypdf(대조)")
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
        missing_pages = {p.page_number for p in doc.pages if not any(
            b.visible and b.text.strip() and b.source_layer == "visible_text" for b in p.blocks)}
        coverage = {p.page_number: {"page": p.page_number,
            "status": "UNVERIFIED" if p.page_number in missing_pages else "EXTRACTED",
            "reason": "OCR_REQUIRED" if p.page_number in missing_pages else ""} for p in doc.pages}
        doc.structure["page_coverage"] = list(coverage.values())

        if not adapter.available:
            for number in missing_pages:
                coverage[number]["reason"] = "OCR_UNAVAILABLE"
            if not has_visible_text:
                doc.structure["body_extraction_failed"] = True
                doc.parse_warnings.append(
                    "OCR Adapter를 사용할 수 없어 스캔 PDF 본문을 추출하지 못했다. 본문 검증 항목은 UNVERIFIED로 표시한다. "
                    "스캔 문서를 검증하려면 tesseract-ocr과 한국어 데이터(tesseract-ocr-kor) 설치가 필요하다."
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
        if mode == "off" and not missing_pages:
            return

        body_targets = sorted(missing_pages)[: settings.ocr_max_pages]
        for number in missing_pages - set(body_targets):
            coverage[number]["reason"] = "OCR_PAGE_LIMIT"
        independent_targets = [p.page_number for p in doc.pages if p.page_number not in missing_pages][: settings.independent_ocr_pages] if run_independent else []
        target_pages = sorted(set(body_targets + independent_targets))
        if not target_pages:
            return

        independent_parts: List[str] = []
        recognized_pages = 0
        body_parts = []
        attempted: List[int] = []
        failures: Dict[str, str] = {}
        for raster in render_pages(path, target_pages, dpi=settings.ocr_dpi):
            if raster.page_number in missing_pages:
                attempted.append(raster.page_number)  # 본문 OCR만 센다(독립 OCR은 숨김 글자 대조용 별도 검사)
            lines = adapter.recognize_image(raster.image, page=raster.page_number, scale=raster.scale)
            if not lines and getattr(adapter, "last_error", None) == "TIMEOUT":
                # 부하로 시간이 모자란 경우다. 한도를 두 배로 늘려 한 번 더 읽는다(무응답으로 넘기지 않는다).
                lines = adapter.recognize_image(raster.image, page=raster.page_number, scale=raster.scale,
                                                timeout=2 * max(1.0, settings.ocr_timeout_seconds))
            engine_error = getattr(adapter, "last_error", None) if not lines else None
            quality = page_quality(lines)
            if raster.page_number in missing_pages and (quality["low_quality"] or not lines):
                # 돌려 스캔한 쪽: OSD로 방향을 찾고, 못 찾으면 90·180·270도를 모두 읽어 품질이 가장 좋은 쪽을 쓴다(v4 P8)
                rotated = _reoriented(adapter, raster, quality)
                if rotated is not None:
                    lines, quality, angle = rotated
                    coverage[raster.page_number]["rotation_corrected"] = angle
                    doc.structure.setdefault("ocr_rotation", {})[str(raster.page_number)] = angle
            # 신뢰도 미달 라인은 버린다. 남은 것이 없으면 그 면은 인식 실패로 취급한다.
            kept = [line for line in lines if line.confidence >= settings.ocr_min_confidence]
            if not kept:
                reason = ("OCR_TIMEOUT" if engine_error == "TIMEOUT" else "OCR_ERROR" if engine_error
                          else "OCR_LOW_CONFIDENCE")
                if raster.page_number in missing_pages:
                    failures[str(raster.page_number)] = reason
                    coverage[raster.page_number]["reason"] = reason
                continue
            recognized_pages += 1
            page = next((p for p in doc.pages if p.page_number == raster.page_number), None)
            for line in kept:
                if raster.page_number not in missing_pages:
                    independent_parts.append(line.text)
                if raster.page_number in missing_pages and page is not None:
                    body_parts.append(line.text)
                    coverage[raster.page_number] .update(status="OCR_EXTRACTED", reason="")
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
            if raster.page_number in missing_pages:
                coverage[raster.page_number]["ocr_quality"] = quality
                if quality["low_quality"]:
                    # 읽은 글자로 검사는 계속하되, 이 쪽에서 '결함 없음'을 결론 내리지 못하게 따로 표시한다(G2).
                    coverage[raster.page_number].update(status="OCR_LOW_QUALITY", reason="OCR_LOW_QUALITY")

        # OCR을 시도한 쪽과 실패 사유. 매니페스트가 '실행하지 않음'과 '실행했으나 읽지 못함'을 구분하는 근거다.
        doc.structure["ocr_attempted_pages"] = attempted
        if failures:
            doc.structure["ocr_failures"] = failures
        doc.structure["body_extraction_failed"] = not has_visible_text and not body_parts
        for item in coverage.values():
            if item["status"] == "UNVERIFIED":
                doc.parse_warnings.append(f"{item['page']}면 본문 미검증: {item['reason']}")
        if not recognized_pages:
            return

        joined = "\n".join(independent_parts)
        doc.structure["ocr_pages"] = recognized_pages
        if body_parts:
            doc.raw_layers["ocr_layer"] = "\n".join(body_parts)
            rendered_parts.extend(body_parts)
            doc.structure["scanned_pdf_ocr_applied"] = True
        if independent_parts:
            # 화면 렌더링 결과와 내장 텍스트 레이어를 비교하기 위한 독립 OCR 산출물
            doc.raw_layers["independent_ocr"] = joined
            doc.structure["independent_ocr_pages"] = recognized_pages

    @staticmethod
    def _collect_pdf_structure(raw: bytes, doc: NormalizedDocument) -> None:
        """incremental update, annotation, XMP, 첨부파일, 서명 정보를 수집한다."""
        eof_count = raw.count(b"%%EOF")
        startxref_count = raw.count(b"startxref")
        problems = _structure_problems(raw)
        if problems:
            doc.structure["malformed"] = problems
            doc.parse_warnings.append("PDF 구조 손상(복구 읽기): " + "; ".join(problems))
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
                    # 표준 키로 한정하지 않고 XMP의 모든 값을 문서 속성으로 싣는다(v3 §3-3).
                    for key, value in _xmp_values(doc.structure["xmp"]).items():
                        doc.metadata.setdefault(f"XMP:{key}", value)
            except Exception:
                pass
            # 북마크(Outline) 제목 — 화면 본문에는 없지만 뷰어·추출기가 읽는 글자다.
            try:
                doc.structure["outline"] = _outline_titles(reader.outline)
            except Exception:
                pass
            # 쪽 번호 표시(PageLabels)의 접두 문자열 — 뷰어의 쪽 번호 칸과 추출기가 읽는다(v5 3-7)
            try:
                doc.structure["page_labels"] = _page_label_prefixes(reader)
            except Exception:
                pass
            # 양식 필드 값
            try:
                fields = reader.get_fields() or {}
                doc.structure["form_fields"] = [
                    {"name": str(name), "value": str(field.get("/V") or "")}
                    for name, field in fields.items() if str(field.get("/V") or "").strip()][:200]
            except Exception:
                pass
            # PageLabels (PDF 1.3+) 페이지 레이블 구조
            try:
                catalog = getattr(reader, "trailer", {}).get("/Root") if hasattr(reader, "trailer") else None
                if catalog and hasattr(catalog, "get_object"):
                    catalog = catalog.get_object()
                if catalog and "/PageLabels" in catalog:
                    labels_obj = catalog["/PageLabels"]
                    if hasattr(labels_obj, "get_object"):
                        labels_obj = labels_obj.get_object()
                    doc.structure["page_labels"] = str(labels_obj)[:1000]
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
                    doc.structure["embedded_files"] = _embedded_files(reader)
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
        doc.structure["has_filled_shapes"] = _has_filled_shapes(raw)
        doc.structure["has_clip_paths"] = _has_clip_paths(raw)
        zero_width, strings = _actual_text_zero_width(raw, collect=True)
        if zero_width:
            doc.structure["actual_text_zero_width"] = zero_width
        if strings:
            doc.structure["actual_text_strings"] = strings[:50]


def _structure_problems(raw: bytes) -> List[str]:
    """교차참조표·트레일러 손상. 파서가 복구해 읽더라도 손상 사실은 남긴다(MALFORMED_PDF)."""
    problems: List[str] = []
    tail = raw[-2048:]
    if b"%%EOF" not in tail:
        problems.append("파일 끝 표지(%%EOF)가 없다")
    at = raw.rfind(b"startxref")
    if at < 0:
        problems.append("startxref가 없다")
        return problems
    match = re.match(rb"startxref\s+(\d+)", raw[at:at + 40])
    if not match:
        problems.append("startxref 값이 없다")
        return problems
    offset = int(match.group(1))
    if offset >= len(raw):
        problems.append(f"startxref 위치({offset})가 파일 크기({len(raw)})를 넘는다")
    elif not re.match(rb"\s*(?:xref|\d+\s+\d+\s+obj)", raw[offset:offset + 32]):
        problems.append(f"startxref 위치({offset})에 교차참조표가 없다")
    if b"xref" not in raw and b"/XRef" not in raw:
        problems.append("교차참조표(xref)가 없다")
    return problems


def _parse_with_pypdf(raw: bytes, doc: NormalizedDocument) -> None:
    """pdfplumber가 열지 못한 파일을 pypdf 글자 추출로 읽는다. 글자 위치·색은 없으므로 숨김 판정은 하지 않는다."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw), strict=False)
        parts = []
        for index, page in enumerate(reader.pages, start=1):
            p = Page(page_number=index)
            for line in (page.extract_text() or "").splitlines():
                if line.strip():
                    p.blocks.append(Block(block_id=new_id("B"), text=line.strip(), page=index,
                                          source_layer="visible_text", attributes={"parser": "pypdf"}))
                    parts.append(line.strip())
            doc.pages.append(p)
        doc.raw_layers["rendered_text"] = "\n".join(parts)
        doc.structure["parser_chain"].append("pypdf")
        doc.parse_warnings.append("pdfplumber로 열지 못해 pypdf 글자 추출로 읽었다(글자 색·위치 기반 숨김 검사는 하지 못함)")
    except Exception as exc:
        doc.structure["parser_chain"].append(f"pypdf:실패({type(exc).__name__})")
        doc.structure["parse_error"] = True
        doc.parse_warnings.append(f"PDF를 읽지 못했다: {exc}")


def parser_disagreement(raw: bytes, page_texts: Dict[int, str], *, max_pages: int = 30) -> List[Dict[str, Any]]:
    """pdfplumber와 pypdf가 같은 쪽에서 뽑은 글자가 크게 다른 쪽(글자 구성 겹침 60% 미만)."""
    from collections import Counter

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw), strict=False)
    except Exception:
        return []
    out = []
    for number, text in list(page_texts.items())[:max_pages]:
        mine = Counter(_text_signature(text))
        if sum(mine.values()) < 50 or number > len(reader.pages):
            continue
        try:
            other = Counter(_text_signature(reader.pages[number - 1].extract_text() or ""))
        except Exception:
            continue
        overlap = sum((mine & other).values()) / max(sum(mine.values()), sum(other.values()), 1)
        if overlap < 0.6:
            out.append({"page": number, "overlap": round(overlap, 3), "pdfplumber_chars": sum(mine.values()),
                        "pypdf_chars": sum(other.values())})
    return out


def _quality_key(quality: Dict[str, Any]):
    return (not quality["low_quality"], quality.get("hangul_ratio") or 0.0, quality["confidence"], quality["lines"])


def _reoriented(adapter, raster, quality):
    """방향을 바로잡아 다시 읽은 결과 (lines, quality, 각도). 나아지지 않으면 None. 좌표(bbox)는 돌린 이미지 기준이다."""
    detect = getattr(adapter, "detect_rotation", None)
    angle = detect(raster.image) if detect else None
    candidates = [angle] if angle else [90, 180, 270]
    best = None
    for candidate in candidates:
        # OSD의 rotate는 시계 방향 각도다. PIL rotate는 반시계 방향이므로 음수로 돌린다.
        image = raster.image.rotate(-candidate, expand=True)
        lines = adapter.recognize_image(image, page=raster.page_number, scale=raster.scale)
        found = page_quality(lines)
        if best is None or _quality_key(found) > _quality_key(best[1]):
            best = (lines, found, candidate)
    if best is None or _quality_key(best[1]) <= _quality_key(quality):
        return None
    return best


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
# 채움 도형 연산자(re f, re F, f*). 압축되지 않은 내용 스트림에서만 보이므로 _collect_pdf_structure의
# 압축 해제 결과(has_filled_shapes)와 함께 쓴다.
FILLED_SHAPE_RE = re.compile(rb"\bre\s+[fF]\*?\b")
# 채움 투명도가 1이 아닌 그래픽 상태(ExtGState /ca 0.x)가 있으면 글자별 투명도를 확인한다.
ALPHA_RE = re.compile(rb"/ca\s*(?:0(?:\.\d*)?|\.\d+)\b")


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


def _needs_contrast_check(line: List[Dict[str, Any]], colored_fills=()) -> bool:
    """검은 글자가 아니거나(흰색·회색·색 글자) 색 있는 채움 도형 위에 있으면 실제 배경과의 대비를 본다.
    흰 바탕의 검은 글자는 늘 읽히므로 렌더링하지 않는다."""
    rgb = _line_color(line)
    if rgb is None:
        return False
    if _relative_luminance(rgb) > 0.05:
        return True
    x0, x1 = min(float(c["x0"]) for c in line), max(float(c["x1"]) for c in line)
    top, bottom = min(float(c["top"]) for c in line), max(float(c["bottom"]) for c in line)
    return any(fx0 <= (x0 + x1) / 2 <= fx1 and ft <= (top + bottom) / 2 <= fb for fx0, ft, fx1, fb in colored_fills)


def _line_color(line: List[Dict[str, Any]]) -> Optional[Tuple[float, float, float]]:
    for char in line:
        if char.get("text", "").strip():
            return _color_to_rgb(char.get("non_stroking_color"))
    return None


def _background(image, box, scale: float) -> Optional[Tuple[float, float, float]]:
    """글줄 영역에서 가장 많은 색(글자 획은 소수이므로 배경색)을 0~1 RGB로 돌려준다."""
    from collections import Counter

    x0, top, x1, bottom = (int(round(v * scale)) for v in box)
    x0, top = max(0, x0), max(0, top)
    x1, bottom = min(image.width, max(x0 + 1, x1)), min(image.height, max(top + 1, bottom))
    if x1 <= x0 or bottom <= top:
        return None
    region = image.crop((x0, top, x1, bottom)).convert("RGB")
    counts = Counter((r // 8, g // 8, b // 8) for r, g, b in region.getdata())
    if not counts:
        return None
    (r, g, b), _ = counts.most_common(1)[0]
    return ((r * 8 + 4) / 255.0, (g * 8 + 4) / 255.0, (b * 8 + 4) / 255.0)


def _apply_contrast(path: str, checks, rendered_parts: List[str], hidden_parts: List[str]) -> None:
    """글자색과 실제 렌더링한 배경의 명도 대비비로 보이는지 판단한다(추가지시 J4, v3 §3-2).

    - 대비비가 1.5 미만이면 숨김(흰 글자·흰 배경이면 WHITE_ON_WHITE, 그 밖에는 LOW_CONTRAST).
    - 흰 글자라도 어두운 배경(색 띠 위 제목 등) 위에 있으면 보이는 글자로 되돌린다.
    필요한 쪽만 한 번씩 렌더링한다.
    """
    by_page: Dict[int, List] = {}
    for page_number, block, line in checks:
        by_page.setdefault(page_number, []).append((block, line))
    for raster in render_pages(path, sorted(by_page), dpi=72):
        for block, line in by_page.get(raster.page_number, []):
            text_rgb = _line_color(line)
            box = (min(float(c["x0"]) for c in line), min(float(c["top"]) for c in line),
                   max(float(c["x1"]) for c in line), max(float(c["bottom"]) for c in line))
            background = _background(raster.image, box, raster.scale)
            if text_rgb is None or background is None:
                continue
            ratio = contrast_ratio(text_rgb, background)
            block.attributes["contrast_ratio"] = round(ratio, 2)
            was_hidden = not block.visible
            if ratio < MIN_READABLE_CONTRAST:
                white = _is_white(list(text_rgb)) and all(v >= WHITE_THRESHOLD for v in background)
                reason = "WHITE_ON_WHITE" if white else f"LOW_CONTRAST({ratio:.2f}:1)"
                block.attributes["hidden_reason"] = reason
                block.visible, block.source_layer = False, "hidden_text"
                if not was_hidden:
                    _move(block.text, rendered_parts, hidden_parts)
            elif was_hidden and str(block.attributes.get("hidden_reason")) == "WHITE_ON_WHITE":
                block.attributes["hidden_reason"] = None
                block.visible, block.source_layer = True, "visible_text"
                _move(block.text, hidden_parts, rendered_parts)


def _move(text: str, source: List[str], target: List[str]) -> None:
    if text in source:
        source.remove(text)
    target.append(text)


def _render_facts(path: str) -> Dict[str, set]:
    """글자마다 '보이지 않게 그려졌는지'와 '나중에 그린 흰 도형에 덮였는지'를 구한다.

    반환: {"invisible": 렌더모드 3·7 글자, "covered": 흰 채움 도형에 덮인 글자, "transparent": 채움 투명도
    (ExtGState ca)가 0.1 이하인 글자, "image_covered": 나중에 그린 이미지에 덮인 글자}. 위치는 (쪽, x0, y0) 반올림 값.
    pdfplumber의 글자 정보에는 렌더모드와 그리기 순서가 없다. pdfminer가 글자·도형을 그리는 순서대로
    배치 목록에 넣는 성질을 이용해, 글자보다 뒤에 그린 흰 채움 도형이 글자 중심을 덮으면 가려진 것으로 본다.
    어두운 채움(검은 가림막)은 가림 처리(redaction) 점검이 따로 다룬다.
    """
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    from pdfminer.psparser import literal_name
    from pdfminer.pdftypes import resolve1

    invisible: set = set()
    covered: set = set()
    transparent: set = set()
    image_covered: set = set()
    clipped: set = set()

    class Device(PDFPageAggregator):
        page_number = 0
        mode = 0
        alpha = 1.0
        clip: Optional[Tuple[float, float, float, float]] = None  # 현재 클리핑 영역(장치 좌표 경계 상자)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.chars: List[Tuple[int, Any]] = []
            self.shapes: List[Tuple[int, Tuple[float, float, float, float]]] = []
            self.images: List[Tuple[int, Tuple[float, float, float, float]]] = []
            # 그리기 순서. 이미지는 도형 묶음(figure) 안에 들어가므로 쪽 목록의 길이로는 순서를 알 수 없다.
            self.seq = 0

        def render_string(self, textstate, seq, ncs, graphicstate):
            self.mode = getattr(textstate, "render", 0) or 0
            return super().render_string(textstate, seq, ncs, graphicstate)

        def render_char(self, *args, **kwargs):
            advance = super().render_char(*args, **kwargs)
            item = self.cur_item._objs[-1]
            key = (self.page_number, round(item.x0, 1), round(item.y0, 1))
            if self.clip is not None:
                cx, cy = (item.x0 + item.x1) / 2, (item.y0 + item.y1) / 2
                x0, y0, x1, y1 = self.clip
                if (x1 - x0) * (y1 - y0) < CLIP_MIN_AREA or not (x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5):
                    clipped.add(key)
            if self.mode in (3, 7):
                invisible.add(key)
            elif self.mode in (0, 2, 4, 6) and self.alpha <= TRANSPARENT_ALPHA:
                transparent.add(key)   # 채우는 글자인데 채움 투명도가 0에 가깝다
            self.seq += 1
            self.chars.append((self.seq, item))
            return advance

        def render_image(self, name, stream):
            super().render_image(name, stream)
            items = self.cur_item._objs
            if items:
                obj = items[-1]
                self.seq += 1
                self.images.append((self.seq, (obj.x0, obj.y0, obj.x1, obj.y1)))

        def paint_path(self, gstate, stroke, fill, evenodd, path):
            before = len(self.cur_item._objs)
            super().paint_path(gstate, stroke, fill, evenodd, path)
            if fill and _is_white(getattr(gstate, "ncolor", None)):
                for obj in self.cur_item._objs[before:]:
                    self.seq += 1
                    self.shapes.append((self.seq, (obj.x0, obj.y0, obj.x1, obj.y1)))

    class Interpreter(PDFPageInterpreter):
        """채움 투명도(ExtGState ca)를 그래픽 상태 저장(q)·복원(Q)과 함께 추적한다. pdfminer는 gs를 처리하지 않는다."""

        def init_state(self, ctm):
            super().init_state(ctm)
            self._alpha_stack: List[float] = []
            self._clip_stack: List[Any] = []
            self.device.clip = None

        def do_q(self):
            self._alpha_stack.append(self.device.alpha)
            self._clip_stack.append(self.device.clip)
            super().do_q()

        def do_Q(self):
            if self._alpha_stack:
                self.device.alpha = self._alpha_stack.pop()
            if self._clip_stack:
                self.device.clip = self._clip_stack.pop()
            super().do_Q()

        def _clip_to_path(self):
            """현재 경로의 경계 상자로 클리핑 영역을 좁힌다(W·W*). 경계 상자는 CTM으로 장치 좌표에 옮긴다."""
            from pdfminer.utils import apply_matrix_pt

            points = []
            for segment in getattr(self, "curpath", []) or []:
                values = [v for v in segment[1:] if isinstance(v, (int, float))]
                if segment[0] == "re" and len(values) == 4:
                    x, y, w, h = values
                    values = [x, y, x + w, y + h]
                points += [apply_matrix_pt(self.ctm, (values[i], values[i + 1])) for i in range(0, len(values) - 1, 2)]
            if not points:
                return
            box = (min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points))
            if self.device.clip is not None:
                c = self.device.clip
                box = (max(box[0], c[0]), max(box[1], c[1]), min(box[2], c[2]), min(box[3], c[3]))
                box = (box[0], box[1], max(box[0], box[2]), max(box[1], box[3]))
            self.device.clip = box

        def do_W(self):
            self._clip_to_path()
            super().do_W()

        def do_W_a(self):
            self._clip_to_path()
            super().do_W_a()

        def do_gs(self, name):
            try:
                states = resolve1((self.resources or {}).get("ExtGState")) or {}
                state = resolve1(states.get(literal_name(name))) if isinstance(states, dict) else None
                if isinstance(state, dict) and "ca" in state:
                    self.device.alpha = float(resolve1(state["ca"]))
            except Exception:  # pragma: no cover - 손상된 자원 사전
                pass

    manager = PDFResourceManager()
    device = Device(manager, laparams=LAParams())
    interpreter = Interpreter(manager, device)
    with open(path, "rb") as handle:
        for number, page in enumerate(PDFPage.get_pages(handle), start=1):
            device.page_number, device.chars, device.shapes, device.images, device.seq = number, [], [], [], 0
            device.alpha = 1.0
            interpreter.process_page(page)
            for order, item in device.chars:
                cx, cy = (item.x0 + item.x1) / 2, (item.y0 + item.y1) / 2
                key = (number, round(item.x0, 1), round(item.y0, 1))
                if any(o > order and x0 <= cx <= x1 and y0 <= cy <= y1 for o, (x0, y0, x1, y1) in device.shapes):
                    covered.add(key)
                elif any(o > order and x0 <= cx <= x1 and y0 <= cy <= y1 for o, (x0, y0, x1, y1) in device.images):
                    image_covered.add(key)   # 글자보다 나중에 그린 이미지가 글자를 덮었다
    return {"invisible": invisible, "covered": covered, "transparent": transparent, "image_covered": image_covered,
            "clipped": clipped}


def _image_coverage(page: Any) -> float:
    area = float(page.width) * float(page.height) or 1.0
    covered = sum(max(0.0, float(i["x1"]) - float(i["x0"])) * max(0.0, float(i["bottom"]) - float(i["top"]))
                  for i in (page.images or []))
    return min(1.0, covered / area)


MAX_EMBEDDED_FILES = 20
MAX_EMBEDDED_BYTES = 2_000_000
MAX_EMBEDDED_TEXT = 20_000


def _embedded_files(reader: Any) -> List[Dict[str, Any]]:
    """첨부파일의 이름·크기·해시와, 글자 파일이면 내용 일부를 남긴다. 첨부 안의 지시문도 검사 대상이다."""
    import hashlib

    out: List[Dict[str, Any]] = []
    for name, contents in list((reader.attachments or {}).items())[:MAX_EMBEDDED_FILES]:
        for data in contents[:1]:
            entry: Dict[str, Any] = {"name": str(name), "size": len(data),
                                     "sha256": hashlib.sha256(data).hexdigest(), "is_text": False}
            if len(data) <= MAX_EMBEDDED_BYTES:
                for encoding in ("utf-8", "utf-16", "cp949"):
                    try:
                        text = data.decode(encoding)
                    except UnicodeDecodeError:
                        continue
                    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text[:5000])
                    if text and printable / min(len(text), 5000) >= 0.95:
                        entry.update(is_text=True, encoding=encoding, text=text[:MAX_EMBEDDED_TEXT])
                        break
            out.append(entry)
    return out


ACTUAL_TEXT_RE = re.compile(rb"/ActualText\s*(?:<([0-9A-Fa-f\s]+)>|\(((?:\\.|[^\\)])*)\))")
ZERO_WIDTH_NAMES = {"\u200b": "ZERO WIDTH SPACE", "\u200c": "ZERO WIDTH NON-JOINER", "\u200d": "ZERO WIDTH JOINER",
                    "\u2060": "WORD JOINER", "\ufeff": "ZERO WIDTH NO-BREAK SPACE"}


def _xmp_values(xml: str) -> Dict[str, str]:
    """XMP 패킷의 모든 값(요소 글자·속성). 키는 '접두어:이름'."""
    import xml.etree.ElementTree as ET

    values: Dict[str, str] = {}
    try:
        root = ET.fromstring(xml.strip().split("?>", 1)[-1] if xml.lstrip().startswith("<?xpacket") else xml)
    except ET.ParseError:
        return values

    def name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    for element in root.iter():
        text = (element.text or "").strip()
        tag = name(element.tag)
        if text and tag not in ("li", "Seq", "Bag", "Alt", "Description", "RDF", "xmpmeta"):
            values[tag] = (values.get(tag, "") + " " + text).strip()[:2000]
        elif text and tag == "li":
            parent = "value"
            values[parent] = (values.get(parent, "") + " " + text).strip()[:2000]
        for key, value in element.attrib.items():
            key = name(key)
            if value.strip() and key not in ("about", "lang"):
                values[key] = value.strip()[:2000]
    return values


def _page_label_prefixes(reader) -> List[str]:
    root = reader.trailer["/Root"]
    labels = root.get("/PageLabels") if hasattr(root, "get") else None
    if labels is None:
        return []
    labels = labels.get_object()
    nums = labels.get("/Nums") or []
    out: List[str] = []
    for index in range(1, len(nums), 2):
        entry = nums[index].get_object() if hasattr(nums[index], "get_object") else nums[index]
        prefix = entry.get("/P") if hasattr(entry, "get") else None
        if prefix and str(prefix).strip():
            out.append(str(prefix))
        if len(out) >= 200:
            break
    return out


def _outline_titles(outline, level: int = 0, out: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    out = [] if out is None else out
    for item in outline or []:
        if isinstance(item, list):
            _outline_titles(item, level + 1, out)
        else:
            title = str(getattr(item, "title", "") or (item.get("/Title") if hasattr(item, "get") else "") or "")
            if title.strip():
                out.append({"title": title, "level": level})
        if len(out) >= 500:
            break
    return out


PDF_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _pdf_literal(body: bytes) -> str:
    """PDF 리터럴 문자열(괄호 문자열)의 이스케이프(\\ddd 8진수 등)를 풀고 UTF-16(BOM) 또는 Latin-1로 읽는다."""
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i:i + 1]
        if ch != b"\\" or i + 1 >= len(body):
            out += ch
            i += 1
            continue
        nxt = body[i + 1:i + 2]
        octal = re.match(rb"[0-7]{1,3}", body[i + 1:i + 4])
        if octal:
            out.append(int(octal.group(0), 8) & 0xFF)
            i += 1 + len(octal.group(0))
        elif nxt in (b"\r", b"\n"):  # 줄 이어쓰기
            i += 2 + (1 if body[i + 1:i + 3] == b"\r\n" else 0)
        else:
            out += PDF_ESCAPES.get(nxt, nxt)
            i += 2
    data = bytes(out)
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", "ignore")
    return data.decode("latin-1", "ignore")


def _actual_text_zero_width(raw: bytes, collect: bool = False):
    """표시 글자 대신 쓰일 문자열(ActualText)에 들어 있는 폭 0 문자. 추출기는 이 문자를 버리는 경우가 많다.

    collect=True면 ActualText 문자열 자체도 돌려준다(화면 글자와 다른 문자열을 숨기는 경로이므로 폭 0 문자를 지우고 지시문인지 분류한다).
    """
    counts: Dict[str, int] = {}
    strings: List[str] = []
    body = raw[:8_000_000]
    stream_re = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
    chunks = [stream_re.sub(b"", body)]  # 스트림 밖(구조 트리 등)
    for m in stream_re.finditer(body):
        header = body[max(0, m.start() - 400) : m.start()]
        chunks.append(_decode_stream(m.group(1), header.decode("latin-1", "ignore")))
    for data in chunks:
        for m in ACTUAL_TEXT_RE.finditer(data or b""):
            if m.group(1) is not None:
                hexdigits = re.sub(rb"\s", b"", m.group(1)).decode()
                if hexdigits.upper().startswith("FEFF"):
                    hexdigits = hexdigits[4:]  # UTF-16 바이트 순서 표시(BOM)는 글자가 아니다
                try:
                    text = bytes.fromhex(hexdigits).decode("utf-16-be", "ignore")
                except ValueError:
                    continue
            else:
                text = _pdf_literal(m.group(2))
            found = False
            for ch, name in ZERO_WIDTH_NAMES.items():
                if ch in text:
                    key = f"U+{ord(ch):04X} {name}"
                    counts[key] = counts.get(key, 0) + text.count(ch)
                    found = True
            if collect and (found or len(text.strip()) >= 8):
                strings.append(text[:2000])
    return (counts, strings) if collect else counts


def _has_filled_shapes(raw: bytes) -> bool:
    """내용 스트림에 채움 사각형이 있는지(압축 해제 후). 가림 도형 점검을 할지 정하는 데만 쓴다."""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw[:8_000_000], re.S):
        header = raw[max(0, m.start() - 400) : m.start()]
        if FILLED_SHAPE_RE.search(_decode_stream(m.group(1), header.decode("latin-1", "ignore"))):
            return True
    return False


CLIP_OPERATOR_RE = re.compile(rb"\bW\*?\s+n\b")
CLIP_MIN_AREA = 1.0  # 제곱 포인트. 이보다 작은 클리핑 영역은 아무것도 보이지 않는다


def _has_clip_paths(raw: bytes) -> bool:
    """내용 스트림에 클리핑 경로(W n)가 있는지(압축 해제 후). 클리핑 숨김 점검을 할지 정하는 데만 쓴다."""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw[:8_000_000], re.S):
        header = raw[max(0, m.start() - 400) : m.start()]
        if CLIP_OPERATOR_RE.search(_decode_stream(m.group(1), header.decode("latin-1", "ignore"))):
            return True
    return False


def _has_invisible_render_mode(raw: bytes) -> bool:
    """Tr 3(비표시 렌더모드) 사용 여부. 스캔 PDF의 OCR layer에서 정상적으로 쓰인다."""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw[:8_000_000], re.S):
        header = raw[max(0, m.start() - 400) : m.start()]
        data = _decode_stream(m.group(1), header.decode("latin-1", "ignore"))
        if INVISIBLE_RENDER_MODE_RE.search(data):
            return True
    return False
