"""법률 실무 표의 복합 산식(산식 그래프) 검산.

합계 행 검산(세로 합)만으로는 한 행 안의 관계(공급가액 + 부가가치세 = 합계금액)나 뺄셈이 든 관계(원금 + 이자 −
기변제액 = 잔존채권액, 지급총액 − 공제총액 = 실지급액)를 보지 못한다. 여기서는 표의 열(또는 행) 이름을 '역할'로
읽고, 역할 사이의 표준 산식을 데이터(FORMULAS)로 정의해 검산한다.

오탐 방지 원칙
- 역할 이름은 열·행 이름 '전체'가 일치해야 한다(부분 일치 금지: '이자율'은 이자가 아니다).
- 표의 금액 열(행) 가운데 산식의 역할로 설명되지 않는 것이 하나라도 있으면 그 산식을 적용하지 않는다. 모르는
  구성 요소(예: '비용', '가산금')가 결과에 섞여 있을 수 있기 때문이다.
- 목표 역할은 표에 하나만 있어야 하고, 필수 항이 모두 있어야 한다. 값을 읽지 못한 칸이 있는 행은 건너뛴다.
- 세로 방향(행 이름이 역할)의 덧셈뿐인 산식은 기존 합계 검산과 겹치므로 뺄셈이 든 산식만 적용한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packages.common.confidence import score as confidence_score
from packages.common.enums import EvidenceGrade, FindingType, Severity, VerificationStatus
from packages.common.schemas import Evidence, Finding, NormalizedDocument

ENGINE_NAME = "claim_engine.calculation"

# 역할 이름(공백·괄호를 뺀 이름 전체가 일치해야 한다)
ROLES: Dict[str, "re.Pattern[str]"] = {
    "SUPPLY": re.compile(r"^공급가(?:액)?$"),
    "VAT": re.compile(r"^(?:부가가치세(?:액)?|부가세(?:액)?|세액|vat)$", re.IGNORECASE),
    "TAXED_TOTAL": re.compile(r"^(?:합계(?:금액)?|총액|총금액|공급대가|청구금액)$"),
    "PRINCIPAL": re.compile(r"^(?:대여|차용|채권|미수)?원금(?:액)?$|^대여금(?:액)?$"),
    "INTEREST": re.compile(r"^(?:약정|법정|연체)?이자(?:액|금)?$|^지연(?:손해금|이자)(?:액)?$"),
    "REPAID": re.compile(r"^(?:기)?변제(?:액|금|금액)$|^기지급(?:액|금)$|^회수(?:액|금)$|^변제충당(?:액|금)?$"),
    "BALANCE": re.compile(r"^(?:잔존)?(?:채권|원리금)?잔액$|^잔존(?:채권|원리금)(?:액)?$|^미(?:변제|지급|수)(?:금|액)$"),
    "GROSS": re.compile(r"^(?:지급총액|지급합계|총지급액|급여총액|지급계)$"),
    "DEDUCTION": re.compile(r"^(?:공제총액|공제합계|공제계|총공제액)$"),
    "NET": re.compile(r"^(?:실지급액|차인지급액|실수령액|차감지급액)$"),
}


@dataclass(frozen=True)
class Formula:
    """target = Σ(+항) − Σ(−항). optional 역할은 없으면 0으로 본다(있으면 모두 더하거나 뺀다)."""
    name: str
    label: str
    target: str
    plus: Tuple[str, ...]
    minus: Tuple[str, ...] = ()
    optional: Tuple[str, ...] = ()
    basis: str = ""
    # 세로 방향(행 이름이 역할) 표에도 적용할지. 실지급액은 기존 급여표 검산(_verify_cell_tables)이 맡는다.
    column_wise: bool = True


FORMULAS: Tuple[Formula, ...] = (
    Formula("VAT_TOTAL", "공급가액 + 부가가치세 = 합계금액", "TAXED_TOTAL", ("SUPPLY", "VAT"),
            basis="세금계산서의 공급대가는 공급가액과 부가가치세액의 합이다"),
    Formula("DEBT_BALANCE", "원금 + 이자 − 기변제액 = 잔존채권액", "BALANCE", ("PRINCIPAL", "INTEREST"), ("REPAID",),
            optional=("INTEREST",), basis="잔존 원리금은 원금·이자 합계에서 변제액을 뺀 금액이다(충당 순서와 무관한 총액 관계)"),
    Formula("NET_PAY", "지급총액 − 공제총액 = 실지급액", "NET", ("GROSS",), ("DEDUCTION",),
            basis="실지급액은 지급총액에서 공제총액을 뺀 금액이다", column_wise=False),
)


def role_of(label: Any) -> Optional[str]:
    """열·행 이름 → 역할. 단위 표기('(원)', '(₩)')와 공백·괄호는 무시하고 이름 전체로 맞춘다."""
    text = re.sub(r"[(（\[]\s*(?:원|₩|￦|KRW|천원|만원)\s*[)）\]]", "", str(label or ""))
    compact = re.sub(r"[\s()（）\[\]:：·ㆍ]", "", text)
    for role, pattern in ROLES.items():
        if pattern.match(compact):
            return role
    return None


def _amount(cell: Any) -> Optional[Decimal]:
    from .calculation import parse_cell_amount

    parsed = parse_cell_amount(str(cell or ""))
    return abs(parsed.value) if parsed is not None else None


def _applicable(formula: Formula, roles: Dict[int, Optional[str]], amount_slots: Sequence[int]) -> bool:
    """이 산식을 이 표(열·행 배치)에 적용해도 되는가."""
    used = set(formula.plus) | set(formula.minus) | {formula.target}
    present = [roles[i] for i in amount_slots]
    if any(role not in used for role in present):
        return False  # 산식으로 설명되지 않는 금액 열(행)이 있다
    if present.count(formula.target) != 1:
        return False
    required = (set(formula.plus) | set(formula.minus)) - set(formula.optional)
    return all(role in present for role in required)


def _compute(formula: Formula, values: Dict[str, List[Decimal]]) -> Optional[Decimal]:
    for role in (set(formula.plus) | set(formula.minus)) - set(formula.optional):
        if not values.get(role):
            return None
    return (sum((v for r in formula.plus for v in values.get(r, [])), Decimal(0))
            - sum((v for r in formula.minus for v in values.get(r, [])), Decimal(0)))


def _finding(doc: NormalizedDocument, formula: Formula, stated: Decimal, computed: Decimal, table: Dict[str, Any],
             slot: str, excerpt: str, parts: str) -> Finding:
    difference = stated - computed
    features = {"arithmetic_proof": True, "deterministic_rule": True, "kind": "FORMULA",
                "rule_id": f"CALC.FORMULA_GRAPH.{formula.name}", "formula": formula.label, "stated": str(stated),
                "computed": str(computed), "difference": str(difference),
                "table_ref": table.get("table_ref"), "table_column": f"formula:{formula.name}:{slot}"}
    return Finding.create(
        type=FindingType.ARITHMETIC_MISMATCH, status=VerificationStatus.CONTRADICTED, severity=Severity.HIGH,
        evidence_grade=EvidenceGrade.A,
        title=f"표 산식({formula.label})이 맞지 않는다 (차이 {difference:,}원)",
        detail=(f"{parts} = {computed:,}원이나 표에는 {stated:,}원으로 적혀 있다. 근거 관계: {formula.basis}. "
                "표의 모든 금액 열이 이 산식의 항으로 설명될 때만 적용한 결정론적 검산이다."),
        confidence=confidence_score(features), confidence_features=features, document_id=doc.document_id,
        page=table.get("page"), engine=ENGINE_NAME, tags=["CALCULATION", "FORMULA_GRAPH"],
        evidence=[Evidence.create(description="산식이 성립하지 않는 표의 행·열", grade=EvidenceGrade.A,
                                  document_id=doc.document_id, page=table.get("page"), excerpt=excerpt[:300])])


def _row_wise(doc: NormalizedDocument, table: Dict[str, Any], cells: List[List[str]]) -> List[Finding]:
    """열 이름이 역할인 표: 데이터 행마다 산식을 검산한다(세금계산서·채권목록·개인별 임금대장)."""
    from .calculation import TOLERANCE

    header = cells[0]
    roles = {i: role_of(name) for i, name in enumerate(header)}
    amount_cols = [i for i in range(len(header)) if i > 0 and sum(1 for r in cells[1:] if i < len(r) and _amount(r[i]) is not None)]
    out: List[Finding] = []
    for formula in FORMULAS:
        if not _applicable(formula, roles, amount_cols):
            continue
        target_col = next(i for i in amount_cols if roles[i] == formula.target)
        for row_index, row in enumerate(cells[1:], start=1):
            stated = _amount(row[target_col]) if target_col < len(row) else None
            values: Dict[str, List[Decimal]] = {}
            unreadable = False
            for i in amount_cols:
                if i == target_col:
                    continue
                value = _amount(row[i]) if i < len(row) else None
                if value is None:
                    unreadable = unreadable or bool(str(row[i] if i < len(row) else "").strip())
                    continue
                values.setdefault(roles[i], []).append(value)
            computed = _compute(formula, values)
            if stated is None or computed is None or unreadable or abs(stated - computed) <= TOLERANCE:
                continue
            parts = " ".join(f"{'−' if roles[i] in formula.minus else '+'} {header[i]} {_amount(row[i]):,}"
                             for i in amount_cols if i != target_col and i < len(row) and _amount(row[i]) is not None)
            out.append(_finding(doc, formula, stated, computed, table, f"row{row_index}",
                                " | ".join(header) + "\n" + " | ".join(row), parts.lstrip("+ ")))
    return out


def _column_wise(doc: NormalizedDocument, table: Dict[str, Any], cells: List[List[str]]) -> List[Finding]:
    """행 이름이 역할인 표: 금액 열마다 산식을 검산한다. 덧셈뿐인 산식은 합계 행 검산과 겹치므로 뺀다."""
    from .calculation import TOLERANCE

    rows = cells[1:]
    roles = {i: role_of(r[0] if r else "") for i, r in enumerate(rows)}
    out: List[Finding] = []
    for col in range(1, len(cells[0])):
        amount_rows = [i for i, r in enumerate(rows) if col < len(r) and _amount(r[col]) is not None]
        for formula in FORMULAS:
            if not formula.minus or not formula.column_wise or not _applicable(formula, roles, amount_rows):
                continue
            target_row = next(i for i in amount_rows if roles[i] == formula.target)
            values: Dict[str, List[Decimal]] = {}
            for i in amount_rows:
                if i != target_row:
                    values.setdefault(roles[i], []).append(_amount(rows[i][col]))
            stated, computed = _amount(rows[target_row][col]), _compute(formula, values)
            if computed is None or stated is None or abs(stated - computed) <= TOLERANCE:
                continue
            parts = " ".join(f"{'−' if roles[i] in formula.minus else '+'} {rows[i][0]} {_amount(rows[i][col]):,}"
                             for i in amount_rows if i != target_row)
            out.append(_finding(doc, formula, stated, computed, table, f"col{col}",
                                "\n".join(" | ".join(r) for r in cells), parts.lstrip("+ ")))
    return out


def formula_graph_findings(doc: NormalizedDocument) -> List[Finding]:
    out: List[Finding] = []
    for index, raw in enumerate(doc.structure.get("tables") or []):
        table = dict(raw, table_ref=raw.get("table_ref") or f"table-{index}")
        cells = [[str(c or "").strip() for c in row] for row in raw.get("cells") or []]
        if len(cells) < 2 or len(cells[0]) < 2:
            continue
        out += _row_wise(doc, table, cells)
        # 세로 방향 표(첫 열이 항목 이름)는 3행 이상일 때만
        if len(cells) >= 3:
            out += _column_wise(doc, table, cells)
    return out
