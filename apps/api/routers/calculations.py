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
