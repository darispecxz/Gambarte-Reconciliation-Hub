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
    # Legacy systems do not necessarily store a mirrored remittance in the
    # country that PAYS it. A destination payment can be the authoritative evidence.
    if counterparts:
        counterpart = counterparts[0]
        if not counterpart.direction:
            return Decision("INSUFFICIENT_DATA", "Counterpart direction unverified")
        if counterpart.direction != original.direction:
            return Decision("STATUS_MISMATCH", "Counterpart direction conflicts")
        if counterpart.status == "UNKNOWN":
            return Decision("INSUFFICIENT_DATA", "Counterpart status unverified")
        if original.status == "PAID" and counterpart.status != "PAID":
            return Decision("STATUS_MISMATCH", "Origin paid but counterpart status differs")
    if original.status in {"CANCELLED", "RETURNED"}:
        return Decision("PENDING", "Cancelled or returned: review lifecycle before payment check")
    if original.status != "PAID":
        return Decision("PENDING", "Origin remittance not marked paid")
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
    return Decision("MATCHED", "Origin status and destination payment evidence matched; no mirrored remittance required; amount NOT validated")


def ambiguity_by_code(rows: list[OperationEvidence]) -> bool:
    return len(rows) > 1
