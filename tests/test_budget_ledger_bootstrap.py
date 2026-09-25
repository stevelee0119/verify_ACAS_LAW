"""예산 원장이 init_db 없이도 동작하는지(CLI·평가·실연동 테스트 경로).

실연동 CI에서 원장 표(budget_accounts)가 없어 세 모델 호출이 모두 '예산 한도로 호출하지 않음'으로 빠졌다.
원인은 한도가 아니라 표 부재였고, 사유 문구도 한도 초과와 구별되지 않았다.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from packages.llm_router.budget import BudgetExceeded, BudgetLedger
from packages.llm_router.router import describe_failure


def _fresh_ledger(tmp_path, name):
    engine = create_engine(f"sqlite:///{tmp_path / name}", future=True)
    assert "budget_accounts" not in inspect(engine).get_table_names()
    return engine, BudgetLedger(sessionmaker(engine))


def test_reserve_creates_missing_ledger_tables(tmp_path):
    engine, ledger = _fresh_ledger(tmp_path, "a.db")
    reservation = ledger.reserve("run-1", "0.25", monthly_limit="10", run_limit="5")
    assert reservation.amount == Decimal("0.25")
    assert {"budget_accounts", "budget_reservations"} <= set(inspect(engine).get_table_names())


def test_limit_is_still_enforced_on_a_fresh_database(tmp_path):
    _, ledger = _fresh_ledger(tmp_path, "b.db")
    ledger.reserve("run-2", "4", monthly_limit="10", run_limit="5")
    with pytest.raises(BudgetExceeded):
        ledger.reserve("run-2", "2", monthly_limit="10", run_limit="5")


def test_settle_after_bootstrap_records_spend(tmp_path):
    _, ledger = _fresh_ledger(tmp_path, "c.db")
    reservation = ledger.reserve("run-3", "1", monthly_limit="10")
    ledger.dispatch(reservation.id)
    assert ledger.settle(reservation.id, "0.4")
    # 정산 뒤 남은 한도 안에서 다시 예약된다
    assert ledger.reserve("run-3b", "9.5", monthly_limit="10").amount == Decimal("9.5")


@pytest.mark.parametrize("error, label", [
    ("BUDGET_ADMISSION_FAILED: Budget exhausted: month:2026-09", "예산 한도로 호출하지 않음"),
    ("BUDGET_ADMISSION_FAILED: Missing pricing: configure LV_LLM_UNKNOWN_CALL_USD or model prices",
     "모델 단가 미설정으로 호출하지 않음"),
    ("BUDGET_ADMISSION_FAILED: Input exceeds the configured conservative token bound",
     "입력·출력 길이 상한 초과로 호출하지 않음"),
])
def test_admission_failure_labels_name_the_actual_cause(error, label):
    assert describe_failure(error) == label


def test_ledger_errors_are_not_reported_as_budget_limits():
    text = describe_failure("BUDGET_ADMISSION_FAILED: (sqlite3.OperationalError) no such table: budget_accounts")
    assert text.startswith("예산 원장 오류로 호출하지 않음") and "no such table" in text
