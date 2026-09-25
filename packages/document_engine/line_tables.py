"""괘선 없는 표를 줄의 칸 좌표로 복원한다.

증거설명서·첨부목록처럼 괘선 없이 칸을 맞춘 표는 pdfplumber가 표로 잡지 못한다. 그러면 호증 번호·작성일·
작성자·입증취지가 한 줄 문자열로만 남아 칸별 대조(작성일 검사, 결번, 인적사항)를 할 수 없다.

머리행(짧은 칸이 셋 이상인 줄)의 칸 시작 좌표를 열 경계로 삼고, 아래 줄의 칸을 가장 가까운 열에 넣는다.
첫 열에 글자가 있으면 새 행, 없으면 바로 위 행의 이어지는 줄로 본다. 열 경계 둘 이상을 가로지르는 긴 칸
(일반 문단)이나 줄 간격이 크게 벌어지면 표가 끝난 것으로 본다. pdfplumber가 표를 찾지 못한 쪽에서만 쓴다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from packages.common.schemas import BBox, Block, NormalizedDocument, Page, new_id

from .reading_text import join_separator

TABLE_LINE = "table_line"
MIN_COLUMNS = 3
MAX_HEADER_CELL = 12   # 머리행 칸 글자 수 상한
ROW_GAP_FACTOR = 2.6   # 줄 높이의 이 배수보다 크게 벌어지면 표가 끝난 것으로 본다


def _segments(block: Block) -> List[List[Any]]:
    segments = (block.attributes or {}).get("segments")
    if segments:
        return segments
    return [[block.bbox.x0, block.bbox.x1, block.text.strip()]] if block.bbox is not None else []


def _column_of(x0: float, starts: List[float], tolerance: float) -> int:
    column = 0
    for index, start in enumerate(starts):
        if x0 + tolerance >= start:
            column = index
    return column


def _is_header(block: Block) -> bool:
    segments = (block.attributes or {}).get("segments") or []
    return len(segments) >= MIN_COLUMNS and all(len(s[2]) <= MAX_HEADER_CELL for s in segments)


def _crosses_columns(segment: List[Any], starts: List[float], tolerance: float) -> bool:
    return len([s for s in starts if segment[0] + tolerance < s < segment[1] - tolerance]) >= 2


def rebuild_line_tables(doc: NormalizedDocument, page: Page) -> List[Dict[str, Any]]:
    lines = sorted((b for b in page.blocks if b.visible and b.block_type == "paragraph" and b.bbox is not None
                    and (b.text or "").strip()), key=lambda b: (b.bbox.y0, b.bbox.x0))
    built: List[Dict[str, Any]] = []
    index = 0
    while index < len(lines):
        header = lines[index]
        if not _is_header(header):
            index += 1
            continue
        header_segments = header.attributes["segments"]
        starts = [s[0] for s in header_segments]
        height = max(header.bbox.y1 - header.bbox.y0, 1.0)
        tolerance = height * 0.8
        rows: List[List[List[str]]] = []
        members = [header]
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            if line.bbox.y0 - members[-1].bbox.y1 > ROW_GAP_FACTOR * height:
                break
            segments = _segments(line)
            if not segments or segments[0][0] < starts[0] - tolerance \
                    or any(_crosses_columns(s, starts, tolerance) for s in segments):
                break
            cells: Dict[int, str] = {}
            for x0, _x1, text in segments:
                column = _column_of(x0, starts, tolerance)
                cells[column] = f"{cells[column]} {text}" if column in cells else text
            if 0 in cells or not rows:
                rows.append([[cells[c]] if cells.get(c) else [] for c in range(len(starts))])
            else:
                for column, text in cells.items():
                    rows[-1][column].append(text)
            members.append(line)
            cursor += 1
        if len(rows) < 2:
            index += 1
            continue
        table_rows = [[s[2] for s in header_segments]]
        for row in rows:
            joined = []
            for pieces in row:
                text = ""
                for piece in pieces:
                    text = (text + join_separator(text, piece) + piece) if text else piece
                joined.append(text)
            table_rows.append(joined)
        ref = f"p{page.page_number}L{len(built)}"
        bbox = BBox(min(b.bbox.x0 for b in members), min(b.bbox.y0 for b in members),
                    max(b.bbox.x1 for b in members), max(b.bbox.y1 for b in members))
        for member in members:
            member.block_type = TABLE_LINE
            member.attributes["table_ref"] = ref
        structure = {"table_ref": ref, "page": page.page_number, "table_index": len(built),
                     "bbox": list(bbox.as_tuple()), "cells": table_rows, "header": table_rows[0], "title": None,
                     "row_count": len(table_rows), "column_count": len(starts),
                     "representation": "RECONSTRUCTED_FROM_LINES", "line_block_ids": [m.block_id for m in members],
                     # 열 경계: 열 시작 x좌표로 나누고 마지막 열은 표 오른쪽 끝까지(연속 표 엔진이 열 너비 비율을 비교한다)
                     "column_bounds": [[float(starts[i]), float(starts[i + 1] if i + 1 < len(starts) else bbox.x1)]
                                       for i in range(len(starts))],
                     "page_height": float(getattr(page, "height", 0) or 0)}
        doc.structure.setdefault("tables", []).append(structure)
        page.blocks.append(Block(
            block_id=new_id("B"), text="\n".join(" | ".join(r) for r in table_rows), page=page.page_number,
            bbox=bbox, source_layer="visible_text", block_type="table",
            attributes={"table_index": structure["table_index"], "cells": table_rows, "table_ref": ref,
                        "reconstructed": True}))
        built.append(structure)
        index = cursor
    return built
