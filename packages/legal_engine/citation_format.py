"""인용 서지 형식 검사(v2 Phase 2). 공식 DB 조회 전에, DB와 무관하게 성립할 수 없는 표기를 확정한다.

보수성 원칙: DB에 없다는 이유만으로 '부존재'라고 하지 않는다. 대신 형식상 존재할 수 없는 표기는 DB와
무관하게 INVALID_FORMAT(A)으로 확정한다. 여기서 보는 것은 달력·연도 산술처럼 누구나 확인할 수 있는 사실과,
공식 재판예규로 확인한 사건부호표(config/legal_rules/case_codes.json)에 적힌 것뿐이다. 표에 없거나 근거가
불확실한 조합은 판단하지 않는다(unknown).
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.common.enums import CitationType

from .normalize import split_case_number

CASE_CODES_PATH = Path(__file__).resolve().parents[2] / "config" / "legal_rules" / "case_codes.yaml"
DATED_TYPES = (CitationType.CASE, CitationType.CONSTITUTIONAL, CitationType.INTERPRETATION,
               CitationType.ADMIN_APPEAL, CitationType.ADMIN_RULE)


@lru_cache(maxsize=1)
def case_code_table() -> Dict[str, Any]:
    """공식 재판예규 별표에서 옮긴 사건부호표(scripts/build_case_codes.py). 파일이 없으면 빈 표(판단하지 않음)."""
    try:
        import yaml

        return yaml.safe_load(CASE_CODES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return {}


LEVEL_FAMILY = {"SUPREME": "대법원", "FIRST": "하급법원", "APPELLATE": "하급법원"}


def court_family(court: str) -> Optional[str]:
    """문서에 적힌 법원 → 대법원 / 헌법재판소 / 하급법원. 알 수 없으면 None."""
    name = (court or "").replace(" ", "")
    if not name:
        return None
    if "대법원" in name:
        return "대법원"
    if "헌법재판소" in name:
        return "헌법재판소"
    if name.endswith("법원") or "법원" in name or name.endswith("지원"):
        return "하급법원"
    return None


def code_court_family(code: str) -> Optional[str]:
    """사건부호가 가리키는 법원 종류. 표에 없거나 여러 법원에 쓰이는 부호는 None(unknown)."""
    table = case_code_table()
    if code in (table.get("constitutional_codes") or {}):
        return "헌법재판소"
    entry = (table.get("codes") or {}).get(code)
    return LEVEL_FAMILY.get((entry or {}).get("level")) if entry else None


def _court_code_violations(citation: Any, code: str, year: int,
                           official_record: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table = case_code_table()
    source = table.get("source") or {}
    written = court_family(citation.court or "")
    inferred = code_court_family(code)
    constitutional = table.get("constitutional_codes") or {}
    if written == "헌법재판소" and constitutional and code not in constitutional:
        # 헌법재판소 사건은 「헌법재판소 사건의 접수에 관한 규칙」 제8조 제3항의 부호(헌가·헌나·…)만 쓴다. 민사·형사 일반 부호가
        # 사건부호표에 없더라도(unknown) 헌법재판소 표시와 '헌' 부호가 아닌 조합은 이 규칙만으로 성립할 수 없다.
        basis = table.get("constitutional_source") or {}
        return [_with_actual_court({
            "rule_id": "FMT.COURT_CODE_MISMATCH", "field": "court", "value": f"{citation.court} {code}",
            "kind": "COURT_CODE", "inferred_court": inferred or "법원(헌법재판소 외)",
            "reason": (f"헌법재판소 사건부호는 {'·'.join(constitutional)}뿐이다(근거: {basis.get('title', '헌법재판소 사건부호표')}). "
                       f"'{code}'는 헌법재판소 사건부호가 아니므로 문서의 '{citation.court}' 표시와 맞지 않는다"),
            "source_url": basis.get("url")}, official_record, lambda actual: court_family(actual) != "헌법재판소")]
    entry = (table.get("codes") or {}).get(code) or {}
    exclusive = entry.get("exclusive_court")
    if exclusive and written == "하급법원" and exclusive not in (citation.court or "").replace(" ", ""):
        # 전속 관할 부호(예: 특허1심 '허' → 특허법원): 하급법원끼리라도 다른 법원 표시와는 맞지 않는다
        basis = (table.get("exclusive_court_basis") or {}).get(exclusive) or {}
        return [_with_actual_court({
            "rule_id": "FMT.COURT_CODE_MISMATCH", "field": "court", "value": f"{citation.court} {code}",
            "kind": "COURT_CODE", "inferred_court": exclusive,
            "reason": (f"사건부호 '{code}'는 {entry.get('case_type', '')} 부호로 {exclusive} 사건에만 붙는다"
                       f"(근거: {basis.get('title', exclusive + ' 관할')}). 문서는 {citation.court}로 적었다"),
            "source_url": basis.get("url")}, official_record, lambda actual: exclusive in str(actual).replace(" ", ""))]
    if not written or not inferred or written == inferred:
        return []
    meaning = entry.get("case_type") or (table.get("constitutional_codes") or {}).get(code) or ""
    until = entry.get("supreme_court_until_year")
    if until and written == "대법원":
        if year <= int(until) or year <= int(entry.get("supreme_court_unknown_until_year") or until):
            return []  # 그 시기 대법원도 이 부호를 썼거나, 경계 연도라 판단하지 않는다
        return [{"rule_id": "FMT.CODE_OUT_OF_PERIOD", "field": "case_number", "value": f"{year}{code}",
                 "kind": "COURT_CODE", "inferred_court": inferred,
                 "reason": f"대법원 사건부호로 '{code}'는 {until}년까지 접수된 사건에만 쓰였다"
                           f"(현행 예규상 '{code}'는 {meaning})", "source_url": source.get("url")}]
    if entry.get("source") == "SUPPLEMENT":
        # 현행 별표 제공 파일에 없어 연혁본 별표에서 보충한 부호: 근거로 그 연혁본 버전을 적는다
        source = table.get("supplement_source") or source
    basis = source.get("title", "사건부호표") + (f", {source['version']}" if source.get("version") else "")
    reason = (f"사건부호 '{code}'는 {meaning or inferred + ' 사건'} 부호로 {inferred} 사건에 붙는다. "
              f"문서는 {citation.court}로 적었다(근거: {basis})")
    violation = {"rule_id": "FMT.COURT_CODE_MISMATCH", "field": "court", "value": f"{citation.court} {code}",
                 "kind": "COURT_CODE", "inferred_court": inferred, "reason": reason,
                 "source_url": source.get("url")}
    return [_with_actual_court(violation, official_record, lambda actual: court_family(actual) == inferred)]


def _with_actual_court(violation: Dict[str, Any], official_record: Optional[Dict[str, Any]], matches) -> Dict[str, Any]:
    """부호가 가리키는 법원의 DB로 다시 찾은 기록이 있으면 '법원 표시 오류(실제: ○○ 판결)'로 알린다."""
    actual = (official_record or {}).get("court")
    if actual and matches(actual):
        kind = (official_record or {}).get("case_kind") or "판결"
        violation["actual_court"] = actual
        violation["reason"] += f". 법원 표시 오류(실제: {actual} {kind.replace('전원합의체 ', '')})"
    return violation


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
        out.append({"rule_id": "FMT.DATE_NOT_ON_CALENDAR", "kind": "DATE", "field": "date", "value": written,
                    "reason": f"'{written}'은(는) 달력에 없는 날짜다"})
    elif decided and decided > today and not confirmed:
        out.append({"rule_id": "FMT.FUTURE_DATE", "kind": "DATE", "field": "date", "value": written,
                    "reason": f"'{written}'은(는) 아직 오지 않은 날짜다"})
    if citation.type not in (CitationType.CASE, CitationType.CONSTITUTIONAL):
        return out
    parts = split_case_number(citation.canonical_case_number or citation.case_number or "")
    if not parts:
        return out
    year, code, _serial = parts
    full_year = int(year) if len(year) == 4 else 1900 + int(year)
    if full_year > today.year and not confirmed:
        out.append({"rule_id": "FMT.FUTURE_CASE_YEAR", "kind": "YEAR", "field": "case_number", "value": year,
                    "reason": f"사건번호의 접수연도({full_year})가 아직 오지 않았다"})
    if decided and decided.year < full_year and not confirmed:
        out.append({"rule_id": "FMT.DECIDED_BEFORE_FILED", "kind": "YEAR", "field": "date", "value": written,
                    "reason": f"선고연도({decided.year})가 사건번호의 접수연도({full_year})보다 앞선다"})
    out += _court_code_violations(citation, code, full_year, official_record)
    return out
