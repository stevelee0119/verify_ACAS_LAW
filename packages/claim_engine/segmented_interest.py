"""User-confirmed simple interest arithmetic; no jurisdictional defaults.

Rate periods are [start_date, end_date). Endpoint flags describe the dates on
which interest accrues. Payments take effect at the selected start/end of day.
Only explicitly allocated principal and interest payments are supported; costs,
capitalization, statutory rates and legal allocation priorities are not inferred.
"""
from __future__ import annotations

from calendar import isleap
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, timedelta
from decimal import Context, Decimal, localcontext
from typing import Any


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _decimal(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite, nonnegative Decimal")
    if len(value.as_tuple().digits) > 28 or value.adjusted() > 27 or not -12 <= value.as_tuple().exponent <= 24:
        raise ValueError(f"{name} exceeds supported precision (28 digits, scale <= 12)")


def _source(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must identify the input source or confirmed assumption")


@dataclass(frozen=True)
class RatePeriod:
    start_date: date
    end_date: date
    annual_rate_percent: Decimal
    source: str


@dataclass(frozen=True)
class AllocatedPayment:
    payment_id: str
    paid_on: date
    amount: Decimal
    principal: Decimal
    interest: Decimal
    source: str


@dataclass(frozen=True)
class InterestAssumptions:
    day_count_convention: str  # ACT/365F | ACT/360 | ACT/ACT
    include_start: bool
    include_end: bool
    rounding: str  # ROUND_HALF_UP | ROUND_HALF_EVEN | ROUND_DOWN | ROUND_UP
    rounding_quantum: Decimal  # power of ten, e.g. Decimal('1') or Decimal('0.01')
    rounding_stage: str  # SEGMENT | FINAL (interest allocations use raw accrual for FINAL)
    payment_timing: str  # START_OF_DAY | END_OF_DAY
    allocation_policy: str  # EXPLICIT
    principal_source: str
    period_source: str
    convention_source: str
    confirmed_by: str
    user_confirmed: bool = False


@dataclass(frozen=True)
class InterestScheduleRow:
    kind: str
    start_date: date
    end_date: date
    days: int
    principal_before: Decimal
    principal_after: Decimal
    interest_balance: Decimal
    annual_rate_percent: Decimal | None = None
    year_denominator: int | None = None
    raw_interest: Decimal = Decimal(0)
    posted_interest: Decimal = Decimal(0)
    principal_paid: Decimal = Decimal(0)
    interest_paid: Decimal = Decimal(0)
    payment_id: str | None = None
    source: str = ""


@dataclass(frozen=True)
class SegmentedInterestResult:
    principal: Decimal
    start_date: date
    end_date: date
    accrual_start: date
    accrual_end_exclusive: date
    days: int
    raw_interest: Decimal
    accrued_interest: Decimal
    principal_paid: Decimal
    interest_paid: Decimal
    remaining_principal: Decimal
    remaining_interest: Decimal
    total_due: Decimal
    rounding_adjustment: Decimal
    assumptions: InterestAssumptions
    rate_periods: list[RatePeriod]
    payments: list[AllocatedPayment]
    schedule: list[InterestScheduleRow]
    arithmetic_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


def calculate_segmented_interest(
    *, principal: Decimal, start_date: date, end_date: date,
    rate_periods: list[RatePeriod], payments: list[AllocatedPayment],
    assumptions: InterestAssumptions,
) -> SegmentedInterestResult:
    """Calculate confirmed inputs or raise ValueError, without changing inputs.

    ACT/ACT splits each calendar year and uses its actual 365/366 denominator.
    FINAL rounds once after the complete accrual. SEGMENT rounds each interval
    split by a rate, payment, or ACT/ACT year boundary. This choice affects totals.
    Zero-day periods accrue nothing but can apply payments on their boundary.
    No interest is capitalized. A returned result does not verify any legal input.
    """
    _decimal(principal, "principal")
    if type(start_date) is not date or type(end_date) is not date or end_date < start_date:
        raise ValueError("start_date/end_date must be dates in ascending order")
    a = assumptions
    if a.user_confirmed is not True:
        raise ValueError("All inputs and assumptions must be user-confirmed")
    for name in ("principal_source", "period_source", "convention_source", "confirmed_by"):
        _source(getattr(a, name), name)
    if type(a.include_start) is not bool or type(a.include_end) is not bool:
        raise ValueError("Endpoint conventions must be explicit booleans")
    if a.day_count_convention not in {"ACT/365F", "ACT/360", "ACT/ACT"}:
        raise ValueError("Unsupported day_count_convention")
    if a.rounding not in {"ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_DOWN", "ROUND_UP"}:
        raise ValueError("Unsupported rounding mode")
    _decimal(a.rounding_quantum, "rounding_quantum")
    digits = a.rounding_quantum.as_tuple().digits
    if a.rounding_quantum == 0 or digits[0] != 1 or any(digits[1:]):
        raise ValueError("rounding_quantum must be a positive power of ten")
    if a.rounding_stage not in {"SEGMENT", "FINAL"}:
        raise ValueError("Unsupported rounding_stage")
    if a.payment_timing not in {"START_OF_DAY", "END_OF_DAY"} or a.allocation_policy != "EXPLICIT":
        raise ValueError("Explicit allocation and start/end-of-day timing are required")
    try:
        first = start_date + timedelta(days=not a.include_start)
        stop = end_date + timedelta(days=a.include_end)
    except OverflowError as exc:
        raise ValueError("Endpoint convention exceeds supported date range") from exc
    stop = max(first, stop)
    if any(type(r.start_date) is not date or type(r.end_date) is not date for r in rate_periods):
        raise ValueError("Rate endpoints must be dates")
    rates = sorted(rate_periods, key=lambda r: r.start_date)
    for index, rate in enumerate(rates):
        _decimal(rate.annual_rate_percent, "annual_rate_percent")
        _source(rate.source, "rate source")
        if type(rate.start_date) is not date or type(rate.end_date) is not date or rate.start_date >= rate.end_date:
            raise ValueError("Rate periods must be nonempty half-open date intervals")
        if index and rates[index - 1].end_date > rate.start_date:
            raise ValueError("Rate periods overlap")
    covered_until = first
    for rate in rates:
        if rate.end_date <= first or rate.start_date >= stop:
            continue
        if rate.start_date > covered_until:
            raise ValueError("Rate periods leave an accrual coverage gap")
        covered_until = min(stop, rate.end_date)
    if covered_until < stop:
        raise ValueError("Rate periods do not cover every accrual day")

    payment_dates: dict[date, list[AllocatedPayment]] = {}
    seen_ids: set[str] = set()
    for payment in payments:
        _source(payment.payment_id, "payment_id")
        _source(payment.source, "payment source")
        if payment.payment_id in seen_ids:
            raise ValueError("Duplicate payment_id")
        seen_ids.add(payment.payment_id)
        for name in ("amount", "principal", "interest"):
            _decimal(getattr(payment, name), f"payment {name}")
        with localcontext(Context(prec=80)):
            if payment.amount != payment.principal + payment.interest:
                raise ValueError("Payment amount must equal explicit principal + interest allocation")
        if type(payment.paid_on) is not date or not start_date <= payment.paid_on <= end_date:
            raise ValueError("Payment date is outside the calculation period")
        try:
            effective = payment.paid_on + timedelta(days=a.payment_timing == "END_OF_DAY")
        except OverflowError as exc:
            raise ValueError("Payment timing exceeds supported date range") from exc
        effective = min(stop, max(first, effective))
        payment_dates.setdefault(effective, []).append(payment)

    boundaries = {first, stop, *payment_dates}
    for rate in rates:
        boundaries.update(d for d in (rate.start_date, rate.end_date) if first < d < stop)
    if a.day_count_convention == "ACT/ACT":
        boundaries.update(date(year, 1, 1) for year in range(first.year + 1, stop.year + 1)
                          if date(year, 1, 1) < stop)
    points = sorted(boundaries)
    rows: list[InterestScheduleRow] = []
    balance = principal
    raw_total = accrued = paid_principal = paid_interest = Decimal(0)
    # Isolate arithmetic from callers' global Decimal context and precision.
    with localcontext(Context(prec=80, rounding=a.rounding)):

        def rounded(value: Decimal) -> Decimal:
            return value.quantize(a.rounding_quantum.normalize(), rounding=a.rounding)

        for index, point in enumerate(points):
            for payment in payment_dates.get(point, []):
                if payment.principal > balance:
                    raise ValueError(f"Payment {payment.payment_id} exceeds remaining principal")
                if payment.interest > accrued - paid_interest:
                    raise ValueError(f"Payment {payment.payment_id} exceeds accrued unpaid interest")
                before = balance
                balance -= payment.principal
                paid_principal += payment.principal
                paid_interest += payment.interest
                rows.append(InterestScheduleRow(
                    kind="PAYMENT", start_date=point, end_date=point, days=0,
                    principal_before=before, principal_after=balance,
                    interest_balance=accrued - paid_interest, principal_paid=payment.principal,
                    interest_paid=payment.interest, payment_id=payment.payment_id, source=payment.source,
                ))
            if index == len(points) - 1:
                continue
            next_point = points[index + 1]
            rate = next(r for r in rates if r.start_date <= point < r.end_date)
            days = (next_point - point).days
            denominator = (366 if isleap(point.year) else 365) if a.day_count_convention == "ACT/ACT" else (
                360 if a.day_count_convention == "ACT/360" else 365)
            raw = balance * rate.annual_rate_percent * Decimal(days) / Decimal(100 * denominator)
            posted = rounded(raw) if a.rounding_stage == "SEGMENT" else raw
            raw_total += raw
            accrued += posted
            rows.append(InterestScheduleRow(
                kind="ACCRUAL", start_date=point, end_date=next_point, days=days,
                principal_before=balance, principal_after=balance, interest_balance=accrued - paid_interest,
                annual_rate_percent=rate.annual_rate_percent, year_denominator=denominator,
                raw_interest=raw, posted_interest=posted, source=rate.source,
            ))
        final_interest = rounded(accrued) if a.rounding_stage == "FINAL" else accrued
        remaining_interest = final_interest - paid_interest
        if remaining_interest < 0:
            raise ValueError("Rounding would reduce accrued interest below interest already paid")
        if final_interest != accrued:
            rows.append(InterestScheduleRow(
                kind="ROUNDING", start_date=stop, end_date=stop, days=0,
                principal_before=balance, principal_after=balance,
                interest_balance=remaining_interest, posted_interest=final_interest - accrued,
                source=a.convention_source,
            ))
        return SegmentedInterestResult(
            principal=principal, start_date=start_date, end_date=end_date,
            accrual_start=first, accrual_end_exclusive=stop, days=(stop - first).days,
            raw_interest=raw_total, accrued_interest=final_interest,
            principal_paid=paid_principal, interest_paid=paid_interest,
            remaining_principal=balance, remaining_interest=remaining_interest,
            total_due=balance + remaining_interest, rounding_adjustment=final_interest - raw_total,
            assumptions=a, rate_periods=list(rates), payments=list(payments), schedule=rows,
        )
