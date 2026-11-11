"""Pure matching decisions. No currencies or timestamps are silently inferred."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OperationEvidence:
    id: int
    source: str
    code: str
    direction: str | None
    operation_type: int | None
    status: str
    amount: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class PaymentEvidence:
    id: int
    source: str
    code: str
    operation_type: int | None
    amount: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class Decision:
    result: str
    reason: str
    verified_amount: bool = False


def decide(
    original: OperationEvidence,
    counterparts: list[OperationEvidence],
    destination_payments: list[PaymentEvidence],
) -> Decision:
    """Only return MATCHED with an unambiguous operation and payment evidence.

    Monetary amounts are NOT compared: source remittance amount and destination
    payment amount may represent different roles/currencies, even if labels coincide.
    """
    if not original.direction or original.status == "UNKNOWN":
        return Decision("INSUFFICIENT_DATA", "Direction or source status is unverified")
    if len(counterparts) > 1:
        return Decision("MANUAL_REVIEW", "Multiple counterpart remittances share code and direction")
    if not counterparts:
        return Decision("MISSING_DESTINATION", "Destination remittance not found in covered period")
    counterpart = counterparts[0]
    if not counterpart.direction:
        return Decision("INSUFFICIENT_DATA", "Destination direction is unverified")
    if counterpart.direction != original.direction:
        return Decision("STATUS_MISMATCH", "Destination has a conflicting direction")
    if counterpart.status == "UNKNOWN":
        return Decision("INSUFFICIENT_DATA", "Destination status mapping is unverified")
    if original.status in {"CANCELLED", "RETURNED"}:
        return Decision("PENDING", "Cancelled or returned remittance requires lifecycle review")
    if original.status != "PAID":
        return Decision("PENDING", "Remittance is not marked paid at origin")
    if counterpart.status != "PAID":
        return Decision("STATUS_MISMATCH", "Origin paid; destination has another status")
    if not destination_payments:
        return Decision("PAYMENT_MISSING", "Paid remittance has no payment evidence in destination")
    if len(destination_payments) > 1:
        return Decision("MANUAL_REVIEW", "Several payments; partial payments versus duplicates unverified")
    pay = destination_payments[0]
    if pay.amount is None or not pay.currency:
        return Decision("INSUFFICIENT_DATA", "Payment amount or currency is unverified")
    if original.amount is None or not original.currency:
        return Decision("INSUFFICIENT_DATA", "Source amount or currency is unverified")
    # We do not equate source principal to destination payout without a verified
    # contract/mapping for destination expected amount.
    return Decision("MATCHED", "Operational existence/status/payment evidence matched; amount NOT validated")


def ambiguity_by_code(rows: list[OperationEvidence]) -> bool:
    return len(rows) > 1
