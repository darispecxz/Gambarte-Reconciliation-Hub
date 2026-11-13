"""Pure offline safety and date contract tests for bounded historical backfill."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from scripts.pilot_backfill_2026 import (
    historical_sql, month_window, source_plan_guard, validate_request,
)


def settings(**updates):
    data = {
        "db_host": "pilot-db", "db_name": "gambarte_reconciliation_pilot",
        "enable_source_etl": False, "source_mapping_verified": False,
    }
    data.update(updates)
    return SimpleNamespace(**data)


@pytest.mark.parametrize("dataset", [
    ("BOLIVIA", "remittance"), ("BOLIVIA", "payment"),
    ("CHILE", "remittance"), ("CHILE", "payment"),
])
def test_historical_query_reuses_current_source_projection(dataset):
    sql = historical_sql(*dataset)
    assert ":from_date" in sql and ":to_date" in sql
    assert ":cutoff" not in sql
    assert "ORDER BY" in sql and "LIMIT :lim" in sql
    assert ":last_op" in sql


def test_month_half_open_bounds():
    assert month_window("2026-01", date(2026, 11, 12)) == (
        datetime(2026, 1, 1), datetime(2026, 2, 1))
    assert month_window("2026-12", date(2026, 12, 20)) == (
        datetime(2026, 12, 1), datetime(2027, 1, 1))


@pytest.mark.parametrize("month", [
    "2025-12", "2027-01", "2026-00", "2026-13",
    "2026-1", "2026-11-02", "2026-12",
])
def test_refuses_out_of_range_and_future_month(month):
    with pytest.raises(ValueError):
        month_window(month, date(2026, 11, 12))


@pytest.mark.parametrize("bad", [
    {"db_host": "mariadb"}, {"db_name": "gambarte_reconciliation"},
    {"enable_source_etl": True}, {"source_mapping_verified": True},
])
def test_rejects_unsafe_configuration(bad):
    with pytest.raises(RuntimeError):
        validate_request(settings(**bad), "BOLIVIA", "payment",
                         "2026-09", 50, 1, False, False)


def test_cap_and_explicit_permission():
    with pytest.raises(ValueError):
        validate_request(settings(), "BOLIVIA", "payment",
                         "2026-09", 51, 1, False, False)
    with pytest.raises(ValueError):
        validate_request(settings(), "BOLIVIA", "payment",
                         "2026-09", 50, 3, False, False)
    with pytest.raises(ValueError, match="acknowledge"):
        validate_request(settings(), "BOLIVIA", "payment",
                         "2026-09", 50, 1, True, False)
    validate_request(settings(), "BOLIVIA", "payment",
                     "2026-09", 50, 2, True, True)


def test_rejects_expensive_or_unindexed_plans():
    with pytest.raises(RuntimeError):
        source_plan_guard([{"type": "ALL", "key": None, "rows": 100}])
    with pytest.raises(RuntimeError):
        source_plan_guard([{"type": "range", "key": "PRIMARY",
                           "rows": 200_000, "Extra": "Using filesort"}])
    with pytest.raises(RuntimeError):
        source_plan_guard([{"type": "range", "key": "PRIMARY", "rows": 500_001}])
    source_plan_guard([{"type": "range", "key": "PRIMARY",
                        "rows": 400_000, "Extra": "Using where"}])
