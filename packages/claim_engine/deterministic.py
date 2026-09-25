"""제6장 결정론적 계산 엔진.

LLM은 변수와 수식을 추출할 뿐이고 값은 이 모듈이 계산한다. 계산 결과에는
수식, 입력값과 그 출처, 반올림 규칙, 불변식 검사 결과가 함께 담긴다.
그 세 가지가 없으면 재현할 수 없고, 재현할 수 없는 숫자는 검산이 아니다.

명세 제6장의 요구사항을 그대로 옮긴다.

- 날짜 차이: 달력월, 일수, 영업일, 초일산입 여부를 선택한다
- 지분·비율·베스팅·이자 계산
- 반올림·절사·잔여 처리 규칙을 명시한다
- 전제가 갈리면 민감도 분석으로 나란히 제시한다
- 입력값마다 source span을 요구한다
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence

ENGINE_NAME = "claim_engine.deterministic"

# 반올림 규칙. 이름을 결과에 그대로 싣는다. "반올림했다"는 설명만으로는
# 342,708주가 나온 이유를 확인할 수 없다.
ROUNDING_RULES = {
    "FLOOR": ROUND_FLOOR,
    "CEILING": ROUND_CEILING,
    "TRUNCATE": ROUND_DOWN,
    "HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
}

# 단위 정규화(제6장). 금액과 수량의 배수만 다룬다.
UNIT_MULTIPLIER = {
    "원": Decimal(1), "천원": Decimal(1_000), "만원": Decimal(10_000),
    "백만원": Decimal(1_000_000), "천만원": Decimal(10_000_000), "억원": Decimal(100_000_000),
    "주": Decimal(1), "%": Decimal(1),
}

DAY_COUNT_BASIS = {"ACT/365": Decimal(365), "ACT/360": Decimal(360)}


class CalculationError(ValueError):
    """입력이 계산을 성립시키지 못한다. 추정값으로 메우지 않는다."""


# --- 입력값 ------------------------------------------------------------------
@dataclass
class Input:
    """계산 입력 하나. 출처가 없으면 미확인으로 표시된다."""

    name: str
    value: Any
    unit: str = ""
    source_span: Optional[str] = None
    """예: "DOC_CONTRACT:p3:l12-14". 없으면 기록에서 확인되지 않은 전제다."""
    support: str = "EXPLICIT"
    """EXPLICIT이면 기록에 적힌 값, INFERRED이면 해석으로 도출한 값이다."""
    note: str = ""

    @property
    def sourced(self) -> bool:
        return bool(self.source_span)

    def to_dict(self) -> Dict[str, Any]:
        value = self.value
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, date):
            value = value.isoformat()
        return {"name": self.name, "value": value, "unit": self.unit,
                "source_span": self.source_span, "support": self.support,
                "sourced": self.sourced, "note": self.note}


@dataclass
class InvariantCheck:
    """제6장 invariant. 위반은 계산 자체가 틀렸다는 뜻이다."""

    name: str
    expression: str
    holds: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "expression": self.expression,
                "holds": self.holds, "detail": self.detail}


@dataclass
class Calculation:
    """검산 결과 하나. 이 객체만으로 손으로 재현할 수 있어야 한다."""

    kind: str
    formula: str
    inputs: List[Input] = field(default_factory=list)
    outputs: Dict[str, Decimal] = field(default_factory=dict)
    rounding_rule: str = "NONE"
    invariants: List[InvariantCheck] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    note: str = ""

    @property
    def invariants_hold(self) -> bool:
        return all(i.holds for i in self.invariants)

    @property
    def unsourced_inputs(self) -> List[str]:
        return [i.name for i in self.inputs if not i.sourced]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "formula": self.formula,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": {k: str(v) for k, v in self.outputs.items()},
            "rounding_rule": self.rounding_rule,
            "invariants": [i.to_dict() for i in self.invariants],
            "invariants_hold": self.invariants_hold,
            "assumptions": list(self.assumptions),
            "unsourced_inputs": self.unsourced_inputs,
            "note": self.note,
        }


@dataclass
class Sensitivity:
    """제6장 민감도 분석. 전제별 결과를 나란히 둔다."""

    variable: str
    cases: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""

    @property
    def diverges(self) -> bool:
        seen = {tuple(sorted(c["outputs"].items())) for c in self.cases}
        return len(seen) > 1

    def to_dict(self) -> Dict[str, Any]:
        return {"variable": self.variable, "cases": self.cases,
                "diverges": self.diverges, "note": self.note}


# --- 단위·반올림 --------------------------------------------------------------
def to_base_unit(value: Any, unit: str) -> Decimal:
    """단위가 붙은 값을 기본 단위(원 또는 주)로 바꾼다."""
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not unit:
        return amount
    multiplier = UNIT_MULTIPLIER.get(unit.strip())
    if multiplier is None:
        raise CalculationError(f"알 수 없는 단위다: {unit}")
    return amount * multiplier


def apply_rounding(value: Decimal, rule: str = "FLOOR", *, places: int = 0) -> Decimal:
    """반올림 규칙을 적용한다. 규칙 이름은 결과에 그대로 남는다."""
    mode = ROUNDING_RULES.get(rule.upper())
    if mode is None:
        raise CalculationError(f"알 수 없는 반올림 규칙이다: {rule}")
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=mode)


# --- 날짜 --------------------------------------------------------------------
def days_between(start: date, end: date, *, count_first_day: bool = False,
                 count_last_day: bool = True) -> int:
    """일수를 센다. 초일산입과 말일산입을 각각 선택한다.

    민법 제157조의 초일불산입이 기본값이지만, 계약이 달리 정하는 경우가
    흔하므로 규칙을 고르게 하고 고른 값을 결과에 남긴다.
    """
    if end < start:
        raise CalculationError("종기가 시기보다 앞선다")
    count = (end - start).days
    if count_first_day:
        count += 1
    if not count_last_day:
        count -= 1
    return max(count, 0)


def months_elapsed(start: date, end: date, *, whole_only: bool = True) -> int:
    """달력월 기준 경과개월. 응당일 전날까지는 그 달이 차지 않은 것으로 본다.

    예: 2024-01-31에서 2024-02-29까지는 1개월이다(말일 보정).
    """
    if end < start:
        raise CalculationError("종기가 시기보다 앞선다")
    months = (end.year - start.year) * 12 + (end.month - start.month)
    anniversary_day = min(start.day, calendar.monthrange(end.year, end.month)[1])
    if end.day < anniversary_day:
        months -= 1
    if not whole_only and end.day > anniversary_day:
        pass  # 부분월은 별도 계산이 필요하며 여기서 임의로 올리지 않는다
    return max(months, 0)


# --- 베스팅 -------------------------------------------------------------------
def vesting(*, total_shares: Input, start: Input, as_of: Input,
            vesting_months: Input, cliff_months: Optional[Input] = None,
            rounding_rule: str = "FLOOR") -> Calculation:
    """베스팅 주식수를 계산한다(제6장 예시).

    vested_ratio   = min(elapsed_months / vesting_months, 1)
    vested_shares  = rounding_rule(total_shares * vested_ratio)
    unvested_shares = total_shares - vested_shares
    invariant: vested_shares + unvested_shares == total_shares

    미베스팅 주식수를 따로 반올림하지 않고 총수에서 빼는 것이 핵심이다.
    양쪽을 각각 반올림하면 합이 총수와 어긋난다.
    """
    total = to_base_unit(total_shares.value, total_shares.unit or "주")
    months_total = int(vesting_months.value)
    if months_total <= 0:
        raise CalculationError("베스팅 기간은 1개월 이상이어야 한다")
    elapsed = months_elapsed(start.value, as_of.value)
    cliff = int(cliff_months.value) if cliff_months is not None else 0

    inputs = [total_shares, start, as_of, vesting_months]
    assumptions = [f"경과개월 {elapsed}개월 (달력월, 응당일 기준)"]
    if cliff_months is not None:
        inputs.append(cliff_months)
        assumptions.append(f"cliff {cliff}개월")

    if elapsed < cliff:
        ratio = Decimal(0)
        assumptions.append("cliff 미도래로 베스팅분 없음")
    else:
        ratio = min(Decimal(elapsed) / Decimal(months_total), Decimal(1))

    vested = apply_rounding(total * ratio, rounding_rule)
    unvested = total - vested

    invariant = InvariantCheck(
        name="vested_plus_unvested_equals_total",
        expression="vested_shares + unvested_shares == total_shares",
        holds=(vested + unvested == total),
        detail=f"{vested} + {unvested} == {total}",
    )
    return Calculation(
        kind="vesting",
        formula=("vested_ratio = min(elapsed_months / vesting_months, 1); "
                 "vested_shares = rounding_rule(total_shares * vested_ratio); "
                 "unvested_shares = total_shares - vested_shares"),
        inputs=inputs,
        outputs={"elapsed_months": Decimal(elapsed),
                 "vested_ratio": ratio,
                 "vested_shares": vested,
                 "unvested_shares": unvested},
        rounding_rule=rounding_rule,
        invariants=[invariant],
        assumptions=assumptions,
    )


def vesting_sensitivity(*, total_shares: Input, start: Input,
                        as_of_candidates: Sequence[Input],
                        vesting_months: Input,
                        cliff_months: Optional[Input] = None,
                        rounding_rule: str = "FLOOR") -> Sensitivity:
    """기준일 전제가 갈릴 때 결과를 나란히 낸다(제6장).

    평가 기준일을 어느 날로 잡느냐에 따라 경과개월이 달라진다. 어느 쪽이
    옳은지는 이 프로그램이 정하지 않는다. 다른 결과가 나온다는 사실을
    보이고 판단은 사람에게 남긴다.
    """
    cases: List[Dict[str, Any]] = []
    for candidate in as_of_candidates:
        result = vesting(total_shares=total_shares, start=start, as_of=candidate,
                         vesting_months=vesting_months, cliff_months=cliff_months,
                         rounding_rule=rounding_rule)
        cases.append({
            "assumption": candidate.name,
            "as_of": candidate.value.isoformat(),
            "source_span": candidate.source_span,
            "support": candidate.support,
            "outputs": {k: str(v) for k, v in result.outputs.items()},
        })
    return Sensitivity(
        variable="as_of_date",
        cases=cases,
        note=("기준일 전제에 따라 결과가 달라진다. 어느 전제가 맞는지는 "
              "기록과 계약 해석의 문제이며 담당 변호사가 확정한다."),
    )


# --- 일반 산식 ----------------------------------------------------------------
def multiply(*, quantity: Input, unit_price: Input, rounding_rule: str = "HALF_UP",
             places: int = 0) -> Calculation:
    """수량 x 단가. 미베스팅 주식 매매대금 같은 독립 검산에 쓴다."""
    q = to_base_unit(quantity.value, quantity.unit or "주")
    price = to_base_unit(unit_price.value, unit_price.unit or "원")
    amount = apply_rounding(q * price, rounding_rule, places=places)
    return Calculation(
        kind="multiply",
        formula="amount = quantity * unit_price",
        inputs=[quantity, unit_price],
        outputs={"amount": amount},
        rounding_rule=rounding_rule,
    )


def simple_interest(*, principal: Input, annual_rate: Input, start: Input, end: Input,
                    basis: str = "ACT/365", count_first_day: bool = False,
                    rounding_rule: str = "TRUNCATE") -> Calculation:
    """단리 이자. 기간 산정 방식과 일수 기준을 결과에 남긴다."""
    divisor = DAY_COUNT_BASIS.get(basis.upper())
    if divisor is None:
        raise CalculationError(f"알 수 없는 일수 기준이다: {basis}")
    amount = to_base_unit(principal.value, principal.unit or "원")
    rate = Decimal(str(annual_rate.value))
    if annual_rate.unit == "%":
        rate = rate / Decimal(100)
    days = days_between(start.value, end.value, count_first_day=count_first_day)
    interest = apply_rounding(amount * rate * Decimal(days) / divisor, rounding_rule)
    return Calculation(
        kind="simple_interest",
        formula="interest = principal * annual_rate * days / day_count_basis",
        inputs=[principal, annual_rate, start, end],
        outputs={"days": Decimal(days), "interest": interest,
                 "total": amount + interest},
        rounding_rule=rounding_rule,
        assumptions=[f"일수 기준 {basis.upper()}",
                     "초일산입" if count_first_day else "초일불산입(민법 제157조 본문)"],
    )


def share_ratio(*, held: Input, total: Input, places: int = 4,
                rounding_rule: str = "HALF_UP") -> Calculation:
    """지분율. 소수 자릿수와 반올림 규칙을 명시한다."""
    numerator = to_base_unit(held.value, held.unit or "주")
    denominator = to_base_unit(total.value, total.unit or "주")
    if denominator == 0:
        raise CalculationError("발행주식총수가 0이다")
    ratio = apply_rounding(numerator / denominator * Decimal(100), rounding_rule, places=places)
    return Calculation(
        kind="share_ratio",
        formula="ratio_percent = held_shares / total_shares * 100",
        inputs=[held, total],
        outputs={"ratio_percent": ratio},
        rounding_rule=rounding_rule,
        assumptions=[f"소수점 {places}자리"],
    )


def verify_stated(calculation: Calculation, output_name: str, stated: Any,
                  *, tolerance: Decimal = Decimal("0")) -> Dict[str, Any]:
    """문서가 적은 값과 독립 계산값을 대조한다.

    tolerance를 두더라도 어긋난 크기를 그대로 보고한다. "오차 범위"라는
    말로 차이를 지우면 반올림 규칙이 다른 계산과 진짜 계산 착오를
    구분할 수 없게 된다.
    """
    if output_name not in calculation.outputs:
        raise CalculationError(f"계산에 없는 출력이다: {output_name}")
    computed = calculation.outputs[output_name]
    stated_value = stated if isinstance(stated, Decimal) else Decimal(str(stated))
    delta = stated_value - computed
    return {
        "output": output_name,
        "stated": str(stated_value),
        "computed": str(computed),
        "delta": str(delta),
        "matches": abs(delta) <= tolerance,
        "rounding_rule": calculation.rounding_rule,
        "formula": calculation.formula,
    }
