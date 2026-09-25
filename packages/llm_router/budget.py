"""Database-wide USD reservations. Unknown provider charges remain reserved."""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING

from sqlalchemy import BigInteger, Column, DateTime, String, select, update

from apps.api.db import Base, JSONType, get_session_factory

UNIT = Decimal("0.000000001")


def money(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Budget amounts must be finite and nonnegative")
    return result


def units(value) -> int:
    result = int((money(value) / UNIT).to_integral_value(rounding=ROUND_CEILING))
    if result > 2**62:
        raise ValueError("Budget amount exceeds ledger capacity")
    return result


class BudgetExceeded(RuntimeError):
    pass


class BudgetAccount(Base):
    __tablename__ = "budget_accounts"
    id = Column(String(120), primary_key=True)
    limit_units = Column(BigInteger, nullable=False, default=0)
    reserved_units = Column(BigInteger, nullable=False, default=0)
    spent_units = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    id = Column(String(64), primary_key=True)
    run_id = Column(String(80), nullable=False, index=True)
    monthly_account = Column(String(120), nullable=False, index=True)
    run_account = Column(String(120), nullable=False)
    state = Column(String(24), nullable=False, default="RESERVED")
    reserved_units = Column(BigInteger, nullable=False)
    charged_units = Column(BigInteger)
    detail = Column(JSONType, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    settled_at = Column(DateTime)


_READY_BINDS = set()


def ensure_ledger_tables(session) -> None:
    """원장 표가 없으면 만든다. API 밖(CLI·평가·실연동 테스트)에서 init_db 없이 돌 때 표가 없어
    모든 모델 호출이 '예산 거절'로 빠지던 문제를 막는다. 운영 DB(Alembic)에는 이미 있어 아무것도 하지 않는다."""
    bind = session.get_bind()
    key = str(bind.url)
    if key in _READY_BINDS:
        return
    Base.metadata.create_all(bind=bind, tables=[BudgetAccount.__table__, BudgetReservation.__table__],
                             checkfirst=True)
    _READY_BINDS.add(key)


@contextmanager
def write_session(factory=None, *, ledger=False):
    """Take SQLite's write lock before reading; PostgreSQL uses row locks.

    ledger=True는 예산 원장 연산에서만 쓴다. 원장 표 확인(스키마 검사)을 작업 관리 같은 다른 쓰기 경로에
    끼우면 그 시간만큼 잠금 구간이 늘어난다."""
    session = (factory or get_session_factory())()
    try:
        if ledger:
            ensure_ledger_tables(session)
        if session.get_bind().dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def insert_missing(session, model, values):
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise RuntimeError("Durable operations require SQLite or PostgreSQL")
    session.execute(insert(model).values(**values).on_conflict_do_nothing())


@dataclass(frozen=True)
class Reservation:
    id: str
    amount: Decimal


class BudgetLedger:
    def __init__(self, factory=None, *, clock=datetime.utcnow):
        self.factory = factory
        self.clock = clock

    def reserve(self, run_id: str, amount, *, monthly_limit=0, run_limit=0,
                budget_run_id=None, reservation_id=None, detail=None) -> Reservation:
        amount_units = units(amount)
        reservation_id = reservation_id or uuid.uuid4().hex
        now = self.clock()
        month = "month:" + now.strftime("%Y-%m")
        run_account = "run:" + (budget_run_id or run_id)
        denied = None
        with write_session(self.factory, ledger=True) as session:
            # The monthly row serializes admission across API and worker processes.
            for account_id, cap in ((month, monthly_limit), (run_account, run_limit)):
                insert_missing(session, BudgetAccount, {
                    "id": account_id, "limit_units": units(cap), "reserved_units": 0,
                    "spent_units": 0, "updated_at": now,
                })
            session.execute(update(BudgetAccount).where(BudgetAccount.id == month)
                            .values(updated_at=now))
            existing = session.get(BudgetReservation, reservation_id)
            if existing is not None:
                if (existing.run_id != run_id or existing.reserved_units != amount_units
                        or existing.run_account != run_account):
                    raise ValueError("Reservation key reused for different inputs")
                if existing.state != "RESERVED":
                    raise ValueError("Reservation has already been dispatched or finalized")
                return Reservation(existing.id, existing.reserved_units * UNIT)
            for account_id, cap in ((month, monthly_limit), (run_account, run_limit)):
                cap_units = units(cap)
                session.execute(update(BudgetAccount).where(BudgetAccount.id == account_id)
                                .values(updated_at=now))
                if cap_units:
                    session.execute(update(BudgetAccount).where(
                        BudgetAccount.id == account_id,
                        (BudgetAccount.limit_units == 0) | (BudgetAccount.limit_units > cap_units),
                    ).values(limit_units=cap_units))
                account = session.get(BudgetAccount, account_id)
                total = account.spent_units + account.reserved_units + amount_units
                if total > (account.limit_units or 2**62):
                    denied = account_id
            if denied is None:
                for account_id in (month, run_account):
                    session.execute(update(BudgetAccount).where(BudgetAccount.id == account_id).values(
                        reserved_units=BudgetAccount.reserved_units + amount_units, updated_at=now))
                session.add(BudgetReservation(
                    id=reservation_id, run_id=run_id, monthly_account=month,
                    run_account=run_account, reserved_units=amount_units, state="RESERVED",
                    detail=detail or {}, created_at=now,
                ))
        # Persist tightened caps even when this request is rejected.
        if denied is not None:
            raise BudgetExceeded("Budget exhausted: " + denied)
        return Reservation(reservation_id, amount_units * UNIT)

    def dispatch(self, reservation_id: str, *, guard=None) -> None:
        with write_session(self.factory, ledger=True) as session:
            if guard:
                guard(session)
            changed = session.execute(update(BudgetReservation).where(
                BudgetReservation.id == reservation_id, BudgetReservation.state == "RESERVED",
            ).values(state="DISPATCHED")).rowcount
            if changed != 1:
                raise ValueError("Reservation is not available for dispatch")

    def release(self, reservation_id: str) -> bool:
        """Only a reservation never dispatched can be safely released automatically."""
        return self._finish(reservation_id, 0, release=True)

    def settle(self, reservation_id: str, actual, *, detail=None) -> bool:
        return self._finish(reservation_id, units(actual), detail=detail)

    def _finish(self, reservation_id, charged, *, release=False, detail=None):
        with write_session(self.factory, ledger=True) as session:
            reservation = session.execute(select(BudgetReservation).where(
                BudgetReservation.id == reservation_id).with_for_update()).scalar_one()
            if reservation.state in {"SETTLED", "RELEASED"}:
                if reservation.charged_units != charged:
                    raise ValueError("Conflicting settlement")
                return False
            if release and reservation.state != "RESERVED":
                raise ValueError("Dispatched reservations require confirmed usage")
            for account_id in (reservation.monthly_account, reservation.run_account):
                session.execute(update(BudgetAccount).where(BudgetAccount.id == account_id).values(
                    reserved_units=BudgetAccount.reserved_units - reservation.reserved_units,
                    spent_units=BudgetAccount.spent_units + charged, updated_at=self.clock(),
                ))
            reservation.charged_units = charged
            reservation.state = "RELEASED" if release else "SETTLED"
            reservation.settled_at = self.clock()
            reservation.detail = {**(reservation.detail or {}), **(detail or {}),
                                  "exceeded_reservation": charged > reservation.reserved_units}
        return True

    def account(self, account_id: str):
        with (self.factory or get_session_factory())() as session:
            # 표가 없는 DB에서 읽기가 실패하면 호출자(budget_exhausted)가 '소진'으로 판단한다. 읽기 전에도 확인한다
            ensure_ledger_tables(session)
            row = session.get(BudgetAccount, account_id)
            return {"limit": row.limit_units * UNIT, "reserved": row.reserved_units * UNIT,
                    "spent": row.spent_units * UNIT} if row else {
                        "limit": Decimal(0), "reserved": Decimal(0), "spent": Decimal(0)}


def budget_settings(settings):
    return {
        "monthly_limit": str(money(os.getenv("LV_MONTHLY_BUDGET_USD", str(settings.monthly_budget_usd)))),
        "run_limit": str(money(os.getenv("LV_RUN_BUDGET_USD", "0"))),
        "max_input_tokens": int(os.getenv("LV_LLM_MAX_INPUT_TOKENS", "131072")),
        "max_output_tokens": int(os.getenv("LV_LLM_MAX_OUTPUT_TOKENS", "4096")),
        "unknown_call_usd": os.getenv("LV_LLM_UNKNOWN_CALL_USD", ""),
    }


def estimate_call(settings, provider, request, limits):
    """Reserve configured input capacity and output cap, never chars/4 guesses."""
    pricing = settings.pricing.get(provider.config.model) or settings.pricing.get(provider.name) or {}
    input_cap = int(limits["max_input_tokens"])
    output_cap = int(limits["max_output_tokens"])
    if input_cap <= 0 or output_cap <= 0 or request.max_tokens <= 0:
        raise ValueError("Model token limits must be positive")
    if request.max_tokens > output_cap:
        raise ValueError("Requested output exceeds the configured token cap")
    # UTF-8 bytes plus protocol overhead is conservative for the supported text APIs.
    if len((request.system + request.user).encode("utf-8")) + 1024 > input_cap:
        raise ValueError("Input exceeds the configured conservative token bound")
    if not all(key in pricing for key in ("input", "output")):
        fallback = limits.get("unknown_call_usd")
        if not fallback or money(fallback) == 0:
            raise ValueError("Missing pricing: configure LV_LLM_UNKNOWN_CALL_USD or model prices")
        return money(fallback), None
    rates = (money(pricing["input"]), money(pricing["output"]))
    if rates == (Decimal(0), Decimal(0)):
        raise ValueError("External provider prices cannot both be zero")
    return (input_cap * rates[0] + request.max_tokens * rates[1]) / Decimal(1000000), rates


def usage_cost(response, rates, reserved):
    # Provider adapters use zero for missing usage. Keep the full estimate in that case.
    if rates is None or response.input_tokens <= 0 or response.output_tokens <= 0:
        return money(reserved), "ESTIMATED"
    return ((money(response.input_tokens) * rates[0] + money(response.output_tokens) * rates[1])
            / Decimal(1000000)), "REPORTED"
