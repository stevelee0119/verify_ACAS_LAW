"""쪽을 넘어 이어지는 표(연속 표)의 결정론적 식별.

임금대장·채권목록처럼 두세 쪽에 걸친 표는 PDF 파서가 쪽마다 다른 표로 읽는다. 열 수가 같다는 것만으로 묶으면
서로 무관한 표를 합산하는 오탐이 생기고(열 수가 같은 표는 흔하다), 묶지 않으면 마지막 쪽의 '합계'가 그 쪽 행만의
합계로 검산되어 오탐이 생기거나 쪽을 넘는 합산 오류를 놓친다.

여기서는 아래 요건을 모두 갖춘 경우에만 두 표를 '연속'으로 본다(하나라도 없으면 독립 표로 둔다).
  (1) 위치·형태: 앞 표가 그 쪽의 마지막 표, 뒤 표가 다음 쪽의 첫 표이고, 열 경계(x좌표)로 계산한 열 너비 비율과
      표의 좌우 끝이 일치한다. 열 경계를 모르면 판단하지 않는다.
  (2) 헤더 상태: 뒤 표의 첫 행이 앞 표의 헤더를 그대로 반복하거나, 헤더 없이 바로 데이터 행으로 시작한다. 그리고
      앞 표가 아직 최종 합계(합계·총계·총액) 행으로 닫히지 않았다(쪽 소계·이월 행은 허용).
  (3) 이어짐 표지: '(계속)'·'다음 쪽에 계속'·'이어서' 같은 분할 표지, 이월 행('전면 이월'), 또는 순번 열의 연속
      (앞 표 마지막 순번 n → 뒤 표 첫 순번 n+1) 중 하나 이상.
결합 결과는 원래 표들의 table_ref를 그대로 남긴 '가상 결합 표'이며, 계산 엔진의 검산 범위(_calculation_scope)에서는
가상 표의 table_ref로 독립된 범위를 갖는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

# 열 너비 비율·표 좌우 끝의 허용 오차(표 너비 대비). 인쇄 여백·선 굵기 차이 정도만 허용한다.
WIDTH_RATIO_TOLERANCE = 0.02
EDGE_TOLERANCE = 0.03
# 앞 표는 쪽의 아래쪽에서 끝나고 뒤 표는 쪽의 위쪽에서 시작해야 한다(쪽 높이 대비).
LOWER_PART, UPPER_PART = 0.5, 0.5
# 표 바깥 분할 표지를 찾을 거리(pt). 표 바로 아래·바로 위의 짧은 줄만 본다.
MARKER_DISTANCE = 60.0

# 분할 표지: 셀·제목·표 바깥 줄의 글자 전체가 표지여야 한다('계속근로기간' 같은 낱말 안의 '계속'은 표지가 아니다).
_MARKER_CORE = (r"(?:계속|이어서|이어짐|다음(?:쪽|면|페이지|장)(?:에|으로)?(?:계속|이어짐)|"
                r"(?:앞|전|이전)(?:쪽|면|페이지|장)(?:에서|에)?(?:계속|이어짐)|continued|cont'?d)")
MARKER_RE = re.compile(rf"^[\-–~\s(（\[<]*{_MARKER_CORE}[\-–~\s)）\]>.]*$", re.IGNORECASE)
TITLE_MARKER_RE = re.compile(rf"[(（\[]\s*{_MARKER_CORE}\s*[)）\]]\s*$", re.IGNORECASE)
# 이월 행: 앞쪽에서 넘어온 금액(전면 이월) 또는 다음 쪽으로 넘기는 금액(차면 이월). 합산 항목에서 빼야 이중 합산이 없다.
CARRY_RE = re.compile(r"^(?:(?:전|앞|이전)(?:면|쪽|페이지|장)?(?:에서)?이월(?:액|금액|분)?|"
                      r"(?:차|다음)(?:면|쪽|페이지|장)?(?:으로|에)?이월(?:액|금액|분)?|이월(?:액|금액|분)?)$")
# 최종 합계(표를 닫는 행). 쪽 소계('소계')는 표를 닫지 않는다.
GRAND_TOTAL_RE = re.compile(r"^(?:총?합계|합계액|총계|총액|총합|계)$")
SERIAL_HEADER_RE = re.compile(r"^(?:순번|번호|연번|일련번호|no\.?|num)$", re.IGNORECASE)
NUMBER_RE = re.compile(r"^\d{1,4}$")
AMOUNT_LIKE_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+\s*원")


def _compact(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _cells(table: Dict[str, Any]) -> List[List[str]]:
    return [[str(c or "").strip() for c in row] for row in table.get("cells") or []]


def _label(row: Sequence[str]) -> str:
    """행 이름: 첫 번째로 비어 있지 않은 칸(순번 열이 앞에 있으면 그 다음 칸)."""
    values = [_compact(c) for c in row if _compact(c)]
    if values and NUMBER_RE.match(values[0]) and len(values) > 1:
        return values[1]
    return values[0] if values else ""


def is_carry_row(row: Sequence[str]) -> bool:
    return bool(CARRY_RE.match(_label(row)))


def is_grand_total_row(row: Sequence[str]) -> bool:
    return bool(GRAND_TOTAL_RE.match(_label(row)))


def _is_marker(text: str) -> bool:
    value = str(text or "").strip()
    return bool(value) and (bool(MARKER_RE.match(value)) or bool(TITLE_MARKER_RE.search(value)))


def _widths(bounds: Optional[Sequence[Sequence[float]]]) -> Optional[List[float]]:
    if not bounds:
        return None
    widths = [float(b[1]) - float(b[0]) for b in bounds]
    total = sum(widths)
    if total <= 0 or any(w <= 0 for w in widths):
        return None
    return [w / total for w in widths]


def _geometry_matches(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[str]:
    """요건 (1): 열 너비 비율과 표 좌우 끝이 같은가. 같으면 설명 문자열, 아니면 None."""
    wa, wb = _widths(a.get("column_bounds")), _widths(b.get("column_bounds"))
    if not wa or not wb or len(wa) != len(wb):
        return None
    if any(abs(x - y) > WIDTH_RATIO_TOLERANCE for x, y in zip(wa, wb)):
        return None
    ba, bb = a.get("column_bounds"), b.get("column_bounds")
    left_a, right_a, left_b, right_b = ba[0][0], ba[-1][1], bb[0][0], bb[-1][1]
    span = max(right_a - left_a, right_b - left_b, 1.0)
    if abs(left_a - left_b) > EDGE_TOLERANCE * span or abs(right_a - right_b) > EDGE_TOLERANCE * span:
        return None
    return f"열 {len(wa)}개의 너비 비율·표 좌우 끝 일치"


def _vertical_position_ok(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """앞 표는 쪽 아래쪽에서 끝나고 뒤 표는 쪽 위쪽에서 시작한다. 좌표를 모르면 이 조건으로 거르지 않는다."""
    box_a, box_b = a.get("bbox"), b.get("bbox")
    height_a, height_b = float(a.get("page_height") or 0), float(b.get("page_height") or 0)
    if not (box_a and box_b and height_a and height_b):
        return True
    return float(box_a[3]) >= LOWER_PART * height_a and float(box_b[1]) <= UPPER_PART * height_b


def _data_start(cells: List[List[str]], header: List[str]) -> Optional[str]:
    """요건 (2)의 뒤 표 첫 행 상태: 'HEADER_REPEATED' / 'DATA' / None(다른 헤더 등)."""
    if not cells:
        return None
    first = cells[0]
    if [_compact(c) for c in first] == [_compact(c) for c in header]:
        return "HEADER_REPEATED"
    joined = " ".join(first)
    if is_carry_row(first) or AMOUNT_LIKE_RE.search(joined) or (first and NUMBER_RE.match(_compact(first[0]))):
        return "DATA"
    return None


def _serial_column(header: List[str], rows: List[List[str]]) -> Optional[int]:
    """순번 열: 헤더가 순번·번호이거나, 첫 열 값이 1씩 늘어나는 정수인 열."""
    for index, name in enumerate(header):
        if SERIAL_HEADER_RE.match(_compact(name)):
            return index
    values = [_compact(r[0]) for r in rows if r and NUMBER_RE.match(_compact(r[0]))]
    if len(values) >= 2 and all(int(y) - int(x) == 1 for x, y in zip(values, values[1:])):
        return 0
    return None


def _serials(rows: List[List[str]], column: int) -> List[int]:
    return [int(_compact(r[column])) for r in rows if column < len(r) and NUMBER_RE.match(_compact(r[column]))]


def _nearby_markers(doc: Any, table: Dict[str, Any], below: bool) -> List[str]:
    """표 바로 아래(below=True) 또는 바로 위의 짧은 줄에서 분할 표지를 찾는다."""
    box, page_no = table.get("bbox"), table.get("page")
    if doc is None or not box or page_no is None:
        return []
    found: List[str] = []
    for page in getattr(doc, "pages", []) or []:
        if page.page_number != page_no:
            continue
        for block in page.blocks:
            if not block.bbox or block.attributes.get("table_ref") or not block.visible:
                continue
            x0, top, x1, bottom = block.bbox.as_tuple()
            gap = (top - float(box[3])) if below else (float(box[1]) - bottom)
            if 0 <= gap <= MARKER_DISTANCE and _is_marker(block.text):
                found.append(block.text.strip())
    return found


def continuation_evidence(doc: Any, a: Dict[str, Any], b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """두 표가 연속 표인지 판단한다. 요건 (1)~(3)을 모두 갖추면 근거 dict, 아니면 None."""
    if a.get("page") is None or b.get("page") is None or int(b["page"]) != int(a["page"]) + 1:
        return None
    ca, cb = _cells(a), _cells(b)
    if len(ca) < 2 or not cb:
        return None
    header = ca[0]
    if len(header) < 2 or any(len(r) != len(header) for r in cb[:1]):
        return None
    # (1) 위치·형태
    geometry = _geometry_matches(a, b)
    if not geometry or not _vertical_position_ok(a, b):
        return None
    # (2) 헤더 상태와 앞 표가 아직 닫히지 않았는지
    start = _data_start(cb, header)
    if start is None or any(is_grand_total_row(r) for r in ca[1:]):
        return None
    body_b = cb[1:] if start == "HEADER_REPEATED" else cb
    if not body_b:
        return None
    # (3) 이어짐 표지(분할 표지, 이월 행, 순번 연속) 중 하나 이상
    markers: List[str] = []
    for text in [a.get("title") or "", b.get("title") or ""] + list(ca[-1]) + list(body_b[0]):
        if _is_marker(text):
            markers.append(str(text).strip())
    markers += _nearby_markers(doc, a, below=True) + _nearby_markers(doc, b, below=False)
    if is_carry_row(ca[-1]) or is_carry_row(body_b[0]):
        markers.append("이월 행")
    serial = None
    column = _serial_column(header, [r for r in ca[1:] if not is_carry_row(r)])
    if column is not None:
        before, after = _serials(ca[1:], column), _serials(body_b, column)
        if len(before) >= 2 and after and before[-1] - before[-2] == 1 and after[0] == before[-1] + 1:
            serial = f"순번 {before[-1]} → {after[0]}"
    # (3)이 없으면 연속 여부를 알 수 없다(confirmed=False). 결합하지 않되, 뒤 표의 합계 판정은 확정하지 않는다.
    return {"geometry": geometry, "header": "헤더 반복" if start == "HEADER_REPEATED" else "헤더 없이 데이터로 시작",
            "markers": markers, "serial": serial, "confirmed": bool(markers or serial)}


def find_continuations(tables: List[Dict[str, Any]], doc: Any = None) -> List[Dict[str, Any]]:
    """연속 표 묶음. 각 묶음은 원래 표들을 그대로 두고 가상 결합 표 하나를 만든다.

    반환: [{"table_ref": "p1t0+p2t0", "members": [...], "page": 첫 쪽, "pages": [...], "cells": 결합 셀,
            "evidence": [각 이음매의 근거]}]
    """
    indexed = [dict(t, table_ref=t.get("table_ref") or f"table-{i}") for i, t in enumerate(tables)]
    by_page: Dict[Any, List[Dict[str, Any]]] = {}
    for table in indexed:
        by_page.setdefault(table.get("page"), []).append(table)

    def last_on_page(table: Dict[str, Any]) -> bool:
        return by_page.get(table.get("page"), [])[-1] is table

    def first_on_page(table: Dict[str, Any]) -> bool:
        return by_page.get(table.get("page"), [None])[0] is table

    chains: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for a, b in zip(indexed, indexed[1:]):
        evidence = (continuation_evidence(doc, a, b)
                    if last_on_page(a) and first_on_page(b) else None)
        if evidence is None or not evidence["confirmed"]:
            current = None
            continue
        cells_b = _cells(b)
        header = _cells(a)[0] if current is None else current["cells"][0]
        body_b = cells_b[1:] if evidence["header"] == "헤더 반복" else cells_b
        if current is None:
            current = {"members": [a["table_ref"]], "pages": [a.get("page")], "page": a.get("page"),
                       "cells": _cells(a), "evidence": []}
            chains.append(current)
        current["members"].append(b["table_ref"])
        current["pages"].append(b.get("page"))
        current["cells"] = current["cells"] + body_b
        current["evidence"].append({"from": a["table_ref"], "to": b["table_ref"], **evidence})
        current["table_ref"] = "+".join(current["members"])
    for chain in chains:
        # 이월 행은 앞 행들의 합을 다시 적은 것이므로 결합 표의 합산 항목에서 뺀다(이중 합산 방지)
        header, body = chain["cells"][0], chain["cells"][1:]
        chain["cells"] = [header] + [r for r in body if not is_carry_row(r)]
    return chains


def possible_continuations(tables: List[Dict[str, Any]], doc: Any = None) -> Dict[str, Dict[str, Any]]:
    """요건 (1)·(2)는 갖췄으나 이어짐 표지 (3)이 없는 뒤 표 {table_ref: 근거}.

    이런 표는 앞 쪽 표의 연속일 수도, 새 표일 수도 있다. 결합하지 않고, 그 표만으로 계산한 최종 합계 불일치는
    확정하지 않는다(앞 쪽 행이 합계에 들어 있을 수 있으므로).
    """
    indexed = [dict(t, table_ref=t.get("table_ref") or f"table-{i}") for i, t in enumerate(tables)]
    by_page: Dict[Any, List[Dict[str, Any]]] = {}
    for table in indexed:
        by_page.setdefault(table.get("page"), []).append(table)
    out: Dict[str, Dict[str, Any]] = {}
    for a, b in zip(indexed, indexed[1:]):
        if by_page[a.get("page")][-1] is not a or by_page[b.get("page")][0] is not b:
            continue
        evidence = continuation_evidence(doc, a, b)
        if evidence is not None and not evidence["confirmed"]:
            out[b["table_ref"]] = {"from": a["table_ref"], **evidence}
    return out
