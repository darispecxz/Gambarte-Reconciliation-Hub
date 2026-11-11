from app.domain.reconciliation import decimal_amount
from app.integrations.source import map_status


def test_decimal_prevents_float():
    try:
        decimal_amount(0.1)
        assert False
    except TypeError:
        pass


def test_unknown_state_not_assumed_paid():
    assert map_status("CHILE", 999) == "UNKNOWN"


def test_missing_state_not_paid():
    assert map_status("BOLIVIA", None) == "UNKNOWN"
