"""Provisional pilot decisions never certify absence or settlement."""
from decimal import Decimal
from types import SimpleNamespace

from scripts.pilot_reconcile import classify, summarize


def row(source, code, operation_type, status="PAID"):
    return SimpleNamespace(source=source, code=code,
                           operation_type=operation_type, status=status,
                           amount=Decimal("1"), currency="USD")


def test_classification_is_conservative():
    assert classify("PAID", 1, [], True) == "NO_PAYMENT_IN_SAMPLE"
    assert classify("PENDING", 1, [], True) == "PENDING_IN_SAMPLE"
    assert classify("PAID", 1, [object()], True) == "PROVISIONAL_CODE_PAIR"
    assert classify("PAID", 2, [object()], True) == "MANUAL_REVIEW_AMBIGUOUS_CODE"
    assert classify("PAID", 1, [object(), object()], True) == "MANUAL_REVIEW_AMBIGUOUS_CODE"
    assert classify("CANCELLED", 1, [object()], True) == "MANUAL_REVIEW_CLOSED_WITH_PAYMENT"
    assert classify("PENDING", 1, [object()], True) == "MANUAL_REVIEW_STATUS_WITH_PAYMENT"
    assert classify("PAID", 1, [object()], False) == "INSUFFICIENT_DATA"


def test_direction_uses_only_origin_and_opposite_country_payment():
    origins = [row("BOLIVIA", "A", 16), row("CHILE", "B", 3)]
    payments = [row("CHILE", "A", 3, "RECORDED"),
                row("BOLIVIA", "B", 4, "RECORDED")]
    result = summarize(origins, payments)
    assert result["BO_TO_CL"]["categories"] == {"PROVISIONAL_CODE_PAIR": 1}
    assert result["CL_TO_BO"]["categories"] == {"PROVISIONAL_CODE_PAIR": 1}


def test_chile_remittance_payment_types_are_contractual():
    origins = [row("CHILE", "CASH", 3), row("CHILE", "BANK5", 5),
               row("CHILE", "BANK6", 6), row("CHILE", "LOAN8", 8)]
    correct = [row("BOLIVIA", "CASH", 4, "RECORDED"),
               row("BOLIVIA", "BANK5", 7, "RECORDED"),
               row("BOLIVIA", "BANK6", 7, "RECORDED"),
               row("BOLIVIA", "LOAN8", 7, "RECORDED")]
    result = summarize(origins, correct)
    assert result["CL_TO_BO"]["categories"] == {"PROVISIONAL_CODE_PAIR": 4}

    wrong = [row("BOLIVIA", "CASH", 7, "RECORDED"),
             row("BOLIVIA", "BANK5", 4, "RECORDED"),
             row("BOLIVIA", "BANK6", 4, "RECORDED"),
             row("BOLIVIA", "LOAN8", 4, "RECORDED")]
    result = summarize(origins, wrong)
    assert result["CL_TO_BO"]["categories"] == {
        "MANUAL_REVIEW_UNEXPECTED_PAYMENT_TYPE": 4
    }
