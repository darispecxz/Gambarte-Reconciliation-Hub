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

from scripts.preflight_source import next_cursor_params


def test_two_page_cursor_uses_real_primary():
    base = {"last_id": 0, "last_op": 0, "last_code": 0, "last_dest": 0}
    chile = next_cursor_params("CHILE", "remittance", chile_row(100, 2), base)
    assert (chile["last_op"], chile["last_code"], chile["last_dest"]) == (3, 100, 2)
    assert chile["last_id"] == 0
    bolivia = next_cursor_params("BOLIVIA", "payment", {
        "source_pk": 31, "operation_type": 7
    }, base)
    assert (bolivia["last_id"], bolivia["last_op"]) == (31, 7)
