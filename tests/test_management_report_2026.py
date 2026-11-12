"""Synthetic management report tests: no connections or real financial data."""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from scripts.management_report_2026 import build_summary, render_html, inside_period


def operation(source, code, operation_type, month=1, day=3, status="PAID"):
    return SimpleNamespace(
        source=source, code=code, operation_type=operation_type, status=status,
        occurred_at=datetime(2026, month, day, 10),
        amount=Decimal("1.00"), currency="USD",
    )


def test_pilot_report_never_certifies_full_year():
    rem = [operation("BOLIVIA", "CASE-A", 16),
           operation("CHILE", "CASE-B", 3, 2, 5)]
    pays = [operation("CHILE", "CASE-A", 3, status="RECORDED"),
            operation("BOLIVIA", "CASE-B", 4, 2, 6, "RECORDED")]
    report = build_summary(rem, pays, 2026, date(2026, 3, 1))
    assert report["certified"] is False
    assert report["coverage"] == "NO VERIFICADA"
    assert report["totals"]["remittances"] == 2
    assert report["directions"]["BO_TO_CL"]["categories"]["PROVISIONAL_CODE_PAIR"] == 1
    assert report["directions"]["CL_TO_BO"]["categories"]["PROVISIONAL_CODE_PAIR"] == 1
    html = render_html(report)
    assert "INFORME PRELIMINAR" in html
    assert "NO VERIFICADA" in html
    assert "Enero" in html


def test_filters_next_year_and_after_cutoff():
    rows = [operation("BOLIVIA", "A", 16),
            operation("BOLIVIA", "B", 16, 4, 1),
            operation("BOLIVIA", "C", 16, 12, 31)]
    report = build_summary(rows, [], through=date(2026, 3, 2))
    assert report["totals"]["remittances"] == 1
    assert len(report["monthly"]) == 3


def test_missing_dates_not_assumed_2026():
    assert not inside_period(None, 2026, date(2026, 11, 12))


def test_does_not_claim_no_payment_is_discrepancy():
    rem = [operation("BOLIVIA", "ONLY-ORIGIN", 16)]
    report = build_summary(rem, [], through=date(2026, 11, 12))
    assert report["directions"]["BO_TO_CL"]["categories"] == {"NO_PAYMENT_IN_SAMPLE": 1}
    html = render_html(report)
    assert "no equivale a pago faltante" in html


def test_reject_non_2026_report():
    with pytest.raises(ValueError):
        build_summary([], [], year=2025, through=date(2025, 12, 31))
