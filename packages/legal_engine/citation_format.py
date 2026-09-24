"""인용 서지 형식 검사(v2 Phase 2). 공식 DB 조회 전에, DB와 무관하게 성립할 수 없는 표기를 확정한다.

보수성 원칙: DB에 없다는 이유만으로 '부존재'라고 하지 않는다. 대신 형식상 존재할 수 없는 표기는 DB와
무관하게 INVALID_FORMAT(A)으로 확정한다. 여기서 보는 것은 달력·연도 산술처럼 누구나 확인할 수 있는 사실과,
공식 재판예규로 확인한 사건부호표(data/legal_rules/case_codes.json)에 적힌 것뿐이다. 표에 없거나 근거가
불확실한 조합은 판단하지 않는다(unknown).
"""
from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.common.enums import CitationType

from .normalize import split_case_number

CASE_CODES_PATH = Path(__file__).resolve().parents[2] / "data" / "legal_rules" / "case_codes.json"
DATED_TYPES = (CitationType.CASE, CitationType.CONSTITUTIONAL, CitationType.INTERPRETATION,
               CitationType.ADMIN_APPEAL, CitationType.ADMIN_RULE)


@lru_cache(maxsize=1)
def case_code_table() -> Dict[str, Any]:
    """공식 재판예규에서 옮긴 사건부호표. 파일이 없으면 빈 표(법원–부호 호환은 판단하지 않는다)."""
    try:
        return json.loads(CASE_CODES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _decision(citation: Any) -> tuple:
    """추출한 선고·결정·회신일 → (date 또는 None, 문서 표기, 달력에 없는지)."""
    value = citation.decision_date or ""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return None, None, False
    y, mo, d = (int(g) for g in m.groups())
    written = f"{y}. {mo}. {d}."
    try:
        return date(y, mo, d), written, False
    except ValueError:
        return None, written, True


def format_violations(citation: Any, *, today: Optional[date] = None,
                      official_record: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """형식상 성립할 수 없는 사유 목록. 비어 있으면 형식 위반 없음(존재 확인과는 별개).

    official_record: 공식 기록이 이 사건번호를 확인한 경우, 시계·연도 산술 규칙(미래 날짜, 선고연도<접수연도)은
    적용하지 않고 공식 기록과의 대조에 맡긴다. 달력에 없는 날짜는 어떤 기록으로도 성립하지 않으므로 그대로 본다.
    """
    today = today or date.today()
    out: List[Dict[str, Any]] = []
    # 공식 기록이 이 사건번호를 확인했으면 시계에 기댄 규칙(미래 날짜·연도, 선고연도<접수연도)은 쓰지 않는다.
    # 날짜 차이는 공식 기록과의 메타데이터 대조가 따로 보고한다.
    confirmed = bool(official_record)
    if citation.type not in DATED_TYPES:
        return out
    decided, written, impossible = _decision(citation)
    if impossible:
        out.append({"rule_id": "FMT.DATE_NOT_ON_CALENDAR", "field": "date", "value": written,
                    "reason": f"'{written}'은(는) 달력에 없는 날짜다"})
    elif decided and decided > today and not confirmed:
        out.append({"rule_id": "FMT.FUTURE_DATE", "field": "date", "value": written,
                    "reason": f"'{written}'은(는) 아직 오지 않은 날짜다"})
    if citation.type not in (CitationType.CASE, CitationType.CONSTITUTIONAL):
        return out
    parts = split_case_number(citation.canonical_case_number or citation.case_number or "")
    if not parts:
        return out
    year, code, _serial = parts
    full_year = int(year) if len(year) == 4 else 1900 + int(year)
    if full_year > today.year and not confirmed:
        out.append({"rule_id": "FMT.FUTURE_CASE_YEAR", "field": "case_number", "value": year,
                    "reason": f"사건번호의 접수연도({full_year})가 아직 오지 않았다"})
    if decided and decided.year < full_year and not confirmed:
        out.append({"rule_id": "FMT.DECIDED_BEFORE_FILED", "field": "date", "value": written,
                    "reason": f"선고연도({decided.year})가 사건번호의 접수연도({full_year})보다 앞선다"})
    table = case_code_table()
    entry = (table.get("codes") or {}).get(code)
    court = (citation.court or "").replace(" ", "")
    if entry and court:
        levels = entry.get("courts") or []
        allowed = any(level in court for level in levels)
        if levels and not allowed and _court_level_known(court, table):
            out.append({"rule_id": "FMT.COURT_CODE_MISMATCH", "field": "court", "value": f"{court} {code}",
                        "reason": f"사건부호 '{code}'({entry.get('meaning')})는 {', '.join(levels)} 사건에 붙는다"
                                  f"(근거: {table.get('source', {}).get('title')})",
                        "source_url": table.get("source", {}).get("url")})
        until = entry.get("supreme_court_until_year")
        if until and "대법원" in court and full_year > int(until):
            out.append({"rule_id": "FMT.CODE_OUT_OF_PERIOD", "field": "case_number", "value": f"{year}{code}",
                        "reason": f"대법원 사건부호 '{code}'는 {until}년까지 접수된 사건에만 쓰였다"})
    return out


def _court_level_known(court: str, table: Dict[str, Any]) -> bool:
    """법원 명칭이 표가 아는 법원 종류인지. 모르는 법원명(군사법원 등 표에 없는 것)은 판단하지 않는다."""
    return any(name in court for name in table.get("court_names") or [])
