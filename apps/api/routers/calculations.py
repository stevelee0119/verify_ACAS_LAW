"""Explicit-assumption, deterministic interest worksheet."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.claim_engine.segmented_interest import (
    AllocatedPayment, InterestAssumptions, RatePeriod, calculate_segmented_interest,
)

router = APIRouter(tags=["calculations"])


class InterestRequest(BaseModel):
    principal: Decimal = Field(ge=0, le=10**15, max_digits=18, decimal_places=2)
    rate: Decimal = Field(ge=0, le=100, max_digits=6, decimal_places=3)
    start: date
    end: date
    inclusive: bool = False


@router.post("/calculations/interest")
def calculate_interest(payload: InterestRequest):
    if payload.end < payload.start:
        raise HTTPException(422, "종료일은 기산일보다 빠를 수 없습니다")
    days = (payload.end - payload.start).days + int(payload.inclusive)
    interest = (payload.principal * payload.rate * days / Decimal(36500)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return {"principal": str(payload.principal), "annual_rate_percent": str(payload.rate),
            "days": days, "day_basis": 365, "rounding": "ROUND_HALF_UP_TO_WON",
            "start_inclusive": payload.inclusive, "end_inclusive": True,
            "interest": str(interest), "total": str(payload.principal + interest),
            "formula": f"{payload.principal} × {payload.rate} / 100 × {days} / 365; 원 단위 사사오입"}


class SegmentedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_float_money(cls, value, info):
        if info.field_name in {"principal", "interest", "amount", "annual_rate_percent", "rounding_quantum"}:
            if isinstance(value, (float, bool)):
                raise ValueError("Send monetary values and rates as decimal strings")
        return value


class RatePeriodRequest(SegmentedInput):
    start_date: date
    end_date: date
    annual_rate_percent: Decimal = Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)
    source: str = Field(min_length=1, max_length=2000)


class AllocatedPaymentRequest(SegmentedInput):
    payment_id: str = Field(min_length=1, max_length=200)
    paid_on: date
    amount: Decimal = Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)
    principal: Decimal = Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)
    interest: Decimal = Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)
    source: str = Field(min_length=1, max_length=2000)


class InterestAssumptionsRequest(SegmentedInput):
    day_count_convention: Literal["ACT/365F", "ACT/360", "ACT/ACT"]
    include_start: bool = Field(strict=True)
    include_end: bool = Field(strict=True)
    rounding: Literal["ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_DOWN", "ROUND_UP"]
    rounding_quantum: Decimal = Field(gt=0, max_digits=28, decimal_places=12, allow_inf_nan=False)
    rounding_stage: Literal["SEGMENT", "FINAL"]
    payment_timing: Literal["START_OF_DAY", "END_OF_DAY"]
    allocation_policy: Literal["EXPLICIT"]
    principal_source: str = Field(min_length=1, max_length=2000)
    period_source: str = Field(min_length=1, max_length=2000)
    convention_source: str = Field(min_length=1, max_length=2000)
    confirmed_by: str = Field(min_length=1, max_length=200)
    user_confirmed: bool = Field(default=False, strict=True)


class SegmentedInterestRequest(SegmentedInput):
    principal: Decimal = Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)
    start_date: date
    end_date: date
    rate_periods: list[RatePeriodRequest] = Field(max_length=1000)
    payments: list[AllocatedPaymentRequest] = Field(max_length=1000)
    assumptions: InterestAssumptionsRequest


@router.post("/calculations/interest/segmented")
def calculate_segmented_interest_endpoint(payload: SegmentedInterestRequest):
    try:
        return calculate_segmented_interest(
            principal=payload.principal, start_date=payload.start_date, end_date=payload.end_date,
            rate_periods=[RatePeriod(**period.model_dump()) for period in payload.rate_periods],
            payments=[AllocatedPayment(**payment.model_dump()) for payment in payload.payments],
            assumptions=InterestAssumptions(**payload.assumptions.model_dump()),
        ).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --- 제6장 베스팅·지분 검산 ---------------------------------------------------
class SourcedValue(BaseModel):
    """계산 입력 하나. 출처를 함께 받는다(제6장 '입력값마다 source span')."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    source_span: str = Field(default="", max_length=500)
    support: Literal["EXPLICIT", "INFERRED"] = "EXPLICIT"


class DatedValue(SourcedValue):
    value: date


class VestingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_shares: Decimal = Field(gt=0, le=10**15, max_digits=18, decimal_places=0)
    total_shares_source: str = Field(default="", max_length=500)
    start: DatedValue
    vesting_months: int = Field(gt=0, le=1200)
    vesting_months_source: str = Field(default="", max_length=500)
    cliff_months: int | None = Field(default=None, ge=0, le=1200)
    rounding_rule: Literal["FLOOR", "CEILING", "TRUNCATE", "HALF_UP", "HALF_EVEN"] = "FLOOR"
    as_of_candidates: list[DatedValue] = Field(min_length=1, max_length=12)
    stated_vested_shares: Decimal | None = Field(
        default=None, ge=0, le=10**15, max_digits=18, decimal_places=0)


@router.post("/calculations/vesting")
def calculate_vesting(payload: VestingRequest):
    """베스팅 주식수를 전제별로 계산한다.

    기준일 전제가 갈리면 결과를 나란히 돌려준다. 어느 전제가 옳은지는
    이 API가 정하지 않는다(제6장).
    """
    from packages.claim_engine.deterministic import (
        CalculationError, Input, verify_stated, vesting, vesting_sensitivity,
    )

    total = Input(name="총주식수", value=payload.total_shares, unit="주",
                  source_span=payload.total_shares_source or None)
    start = Input(name=payload.start.name, value=payload.start.value,
                  source_span=payload.start.source_span or None, support=payload.start.support)
    months = Input(name="베스팅기간", value=payload.vesting_months,
                   source_span=payload.vesting_months_source or None)
    cliff = (Input(name="cliff", value=payload.cliff_months)
             if payload.cliff_months is not None else None)
    candidates = [Input(name=c.name, value=c.value, source_span=c.source_span or None,
                        support=c.support) for c in payload.as_of_candidates]

    try:
        primary = vesting(total_shares=total, start=start, as_of=candidates[0],
                          vesting_months=months, cliff_months=cliff,
                          rounding_rule=payload.rounding_rule)
        sensitivity = vesting_sensitivity(
            total_shares=total, start=start, as_of_candidates=candidates,
            vesting_months=months, cliff_months=cliff, rounding_rule=payload.rounding_rule)
    except CalculationError as e:
        raise HTTPException(422, str(e))

    body = {"calculation": primary.to_dict(), "sensitivity": sensitivity.to_dict()}
    if payload.stated_vested_shares is not None:
        body["stated_comparison"] = verify_stated(
            primary, "vested_shares", payload.stated_vested_shares)
    return body
