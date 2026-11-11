"""Read-only preflight validation without touching any source DB."""
from datetime import datetime
import pytest
from scripts.preflight_source import inspect_page, key_for, run


def chile_row(code, destination):
    return {
        "operation_type": 3, "code": code, "cursor_destination": destination,
        "source_pk": 1, "status_code": 1, "amount": None,
        "currency_id": "BOB", "occurred_at": datetime(2026, 11, 1),
    }


def test_chile_primary_key_order_and_uniqueness():
    rows = [chile_row(100, 1), chile_row(100, 2), chile_row(101, 1)]
    assert key_for("CHILE", "remittance", rows[0]) == (3, 100, 1)
    assert inspect_page("CHILE", "remittance", rows)["PAID"] == 3


def test_invalid_source_order_blocks_preview():
    with pytest.raises(RuntimeError, match="Non-unique or unordered"):
        inspect_page("CHILE", "remittance", [chile_row(101, 1), chile_row(100, 1)])
    with pytest.raises(RuntimeError, match="Non-unique or unordered"):
        inspect_page("CHILE", "remittance", [chile_row(100, 1), chile_row(100, 1)])


@pytest.mark.parametrize("days,limit", [(0, 50), (91, 50), (60, 0), (60, 101)])
def test_safety_limit_before_connection(days, limit):
    with pytest.raises(ValueError, match="Safety limits"):
        run("CHILE", "remittance", days, limit)


def test_other_dataset_key_is_not_chile_composite():
    assert key_for("BOLIVIA", "remittance", {
        "source_pk": 10, "operation_type": 16
    }) == (10, 16)
