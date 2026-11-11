"""Pure domain contract tests: no external databases or real financial data."""
from decimal import Decimal
from app.domain.matching import Decision, OperationEvidence, PaymentEvidence, decide
from app.integrations.source import normalize, infer_direction
from app.infrastructure.ingestion import safe


def operation(status="PAID", direction="CL_TO_BO", amount=Decimal("100")):
    return OperationEvidence(
        id=1, source="CHILE", code="CL123", direction=direction,
        operation_type=3, status=status, amount=amount, currency="USD",
    )


def counterpart(direction="CL_TO_BO", status="PAID"):
    return OperationEvidence(
        id=2, source="BOLIVIA", code="CL123", direction=direction,
        operation_type=4, status=status, amount=Decimal("690"), currency="BOB",
    )


def payment(currency="BOB"):
    return PaymentEvidence(
        id=3, source="BOLIVIA", code="CL123", operation_type=4,
        amount=Decimal("690"), currency=currency,
    )


def test_matching_evidence_without_false_fx_comparison():
    result = decide(operation(), [counterpart()], [payment()])
    assert result.result == "MATCHED"
    assert not result.verified_amount


def test_missing_payment_is_a_finding():
    assert decide(operation(), [counterpart()], []).result == "PAYMENT_MISSING"


def test_uncertain_direction_blocks_matching():
    assert decide(operation(direction=None), [counterpart()], [payment()]).result == (
        "INSUFFICIENT_DATA"
    )


def test_ambiguous_counterpart_requires_review():
    assert decide(operation(), [counterpart(), counterpart()], [payment()]).result == (
        "MANUAL_REVIEW"
    )


def test_several_payments_do_not_imply_duplicate():
    assert decide(operation(), [counterpart()], [payment(), payment()]).result == (
        "MANUAL_REVIEW"
    )


def test_status_conflict():
    assert decide(operation(), [counterpart(status="PENDING")], [payment()]).result == (
        "STATUS_MISMATCH"
    )


def test_infer_chile_direction_and_unknown():
    assert infer_direction({"origin_country": "CHL", "destination_country": "BOL"}) == (
        "CL_TO_BO"
    )
    assert infer_direction({"origin_country": "", "destination_country": "BOL"}) is None


def test_verified_internal_currency_ids_map_to_iso():
    row = normalize("BOLIVIA", "remittance", {
        "source_pk": 20, "operation_type": 4, "code": 123,
        "status_code": 1, "amount": Decimal("100.00"),
        "currency_id": 1, "occurred_at": None,
    })
    assert row.currency == "USD"
    assert row.source_id == "4:20"


def test_json_safe():
    assert safe({"amount": Decimal("12.30")}) == {"amount": "12.30"}

def test_payment_in_destination_without_mirrored_remittance():
    # Common legacy pattern: only source remesa plus destination pago.
    result = decide(operation(), [], [payment()])
    assert result.result == "MATCHED"
    assert "no mirrored remittance required" in result.reason


def test_payment_missing_without_mirrored_remittance():
    assert decide(operation(), [], []).result == "PAYMENT_MISSING"

from unittest.mock import patch
import pytest
from app.core.config import Settings
from app.integrations.source import resolve_currency, approved_operation_types


def test_currency_id_is_country_specific():
    assert resolve_currency("BOLIVIA", 2) == "BOB"
    assert resolve_currency("CHILE", 2) == "CLP"
    assert resolve_currency("BOLIVIA", 3) == "CLP"
    assert resolve_currency("CHILE", 3) == "BOB"
    assert resolve_currency("CHILE", 18) == "USD"
    assert resolve_currency("CHILE", 19) == "BOB"
    assert resolve_currency("CHILE", 20) == "USD"
    assert resolve_currency("CHILE", "BOB") == "BOB"
    assert resolve_currency("CHILE", 999) is None
    assert resolve_currency("BOLIVIA", None) is None


def test_locality_codes_do_not_infer_countries():
    assert infer_direction({"origin_country": "AGR", "destination_country": "CBA"}) is None
    assert infer_direction({"origin_country": "AIQ", "destination_country": "LPM"}) is None


def test_direction_requires_approved_country_specific_operation_types():
    settings = Settings(
        _env_file=None,
        source_mapping_verified=True,
        bolivia_to_chile_operation_types="16",
        chile_to_bolivia_operation_types="3",
    )
    with patch("app.integrations.source.get_settings", return_value=settings):
        bo = normalize("BOLIVIA", "remittance", {
            "source_pk": 1, "operation_type": 16, "code": 123,
            "status_code": 0, "amount": Decimal("10"),
            "currency_id": 2,
        })
        cl = normalize("CHILE", "remittance", {
            "source_pk": 2, "operation_type": 3, "code": 456,
            "status_code": 0, "amount": Decimal("10"),
            "currency_id": "BOB", "origin_country": "AGR", "destination_country": "CBA",
            "cursor_destination": 11,
        })
        other = normalize("CHILE", "remittance", {
            "source_pk": 3, "operation_type": 5, "code": 789,
            "cursor_destination": 12,
            "status_code": 0, "amount": Decimal("10"),
            "currency_id": "BOB",
        })
    assert (bo.direction, bo.currency) == ("BO_TO_CL", "BOB")
    assert (cl.direction, cl.currency) == ("CL_TO_BO", "BOB")
    assert other.direction is None


def test_default_direction_requires_explicit_approval():
    settings = Settings(_env_file=None, source_mapping_verified=False,
                        bolivia_to_chile_operation_types="16",
                        chile_to_bolivia_operation_types="3")
    with patch("app.integrations.source.get_settings", return_value=settings):
        row = normalize("BOLIVIA", "remittance", {
            "source_pk": 9, "operation_type": 16, "code": 999,
            "status_code": 1, "amount": Decimal("10"), "currency_id": 1,
        })
    assert row.direction is None


def test_unknown_or_missing_code_is_rejected():
    with pytest.raises(ValueError, match="without a reconciliation code"):
        normalize("BOLIVIA", "payment", {
            "source_pk": 1, "operation_type": 4,
            "code": None, "amount": Decimal("1"), "currency_id": 2,
        })


def test_reject_malformed_operation_allowlist():
    with pytest.raises(ValueError):
        approved_operation_types("3,foo")
    assert approved_operation_types(" 3 , 5, 3 ") == {3, 5}


from datetime import datetime
from app.integrations.source import map_status


def test_all_poc_status_codes():
    assert [map_status("BOLIVIA", x) for x in (0, 1, 2, 5)] == [
        "PENDING", "PAID", "RETURNED", "CANCELLED"
    ]
    assert [map_status("CHILE", x) for x in range(9)] == [
        "PENDING", "PAID", "RETURNED", "RETURNED_SC", "CHANGED",
        "CANCELLED", "TO_RETURN", "PROCESSING", "SAVINGS",
    ]


def test_chile_negative_code_overrides_status_to_cancelled():
    row = normalize("CHILE", "remittance", {
        "source_pk": 11, "operation_type": 3, "code": -123,
        "cursor_destination": 1,
        "status_code": 1, "amount": Decimal("100"), "currency_id": "BOB",
    })
    assert row.code == "-123"
    assert row.status == "CANCELLED"


def test_pending_source_with_destination_payment_is_status_mismatch():
    assert decide(operation(status="PENDING"), [], [payment()]).result == "STATUS_MISMATCH"
    assert decide(operation(status="PROCESSING"), [], [payment()]).result == "STATUS_MISMATCH"


def test_cancelled_and_returned_are_not_incorrectly_matched():
    assert decide(operation(status="CANCELLED"), [], []).result == "CLOSED"
    assert decide(operation(status="RETURNED_SC"), [], [payment()]).result == "MANUAL_REVIEW"


def test_cutoff_only_later_payment_classified_pending_asof():
    dated = PaymentEvidence(
        id=99, source="BOLIVIA", code="CL123", operation_type=4,
        amount=Decimal("100"), currency="BOB",
        occurred_at=datetime(2026, 11, 4, 12, 0),
    )
    result = decide(operation(status="PAID"), [], [dated],
                    cutoff_at=datetime(2026, 10, 31, 23, 59, 59))
    assert result.result == "PENDING_AS_OF"
    assert decide(operation(status="PAID"), [], [dated],
                  cutoff_at=datetime(2026, 11, 5)).result == "MATCHED"


def test_cutoff_unknown_payment_date_is_insufficient():
    assert decide(operation(), [], [payment()],
                  cutoff_at=datetime(2026, 10, 31)).result == "INSUFFICIENT_DATA"

from app.domain.operation_types import classify_operation


def test_poc_operation_modalities_and_unknown():
    assert classify_operation("BOLIVIA", "remittance", 4) == "LEGACY_REMITTANCE"
    assert classify_operation("BOLIVIA", "remittance", 16) == "INTERNATIONAL_GIRO"
    assert classify_operation("BOLIVIA", "payment", 4) == "CASH_WINDOW"
    assert classify_operation("BOLIVIA", "payment", 7) == "BANK_DEPOSIT"
    assert classify_operation("CHILE", "remittance", 5) == "BANK_DEPOSIT"
    assert classify_operation("CHILE", "remittance", 6) == "BANK_DEPOSIT"
    assert classify_operation("CHILE", "remittance", 8) == "BANK_LOAN"
    assert classify_operation("CHILE", "payment", 8) == "LEGACY_TYPE_8"
    assert classify_operation("CHILE", "remittance", 999) == "UNKNOWN"
