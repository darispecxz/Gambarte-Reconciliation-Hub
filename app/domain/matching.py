"""Operational evidence decisions; never assert monetary settlement from presence alone."""
from dataclasses import dataclass
from datetime import datetime
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
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class Decision:
    result: str
    reason: str
    verified_amount: bool = False


NONPAID = {"PENDING", "PROCESSING", "CHANGED", "TO_RETURN", "SAVINGS"}
CLOSED = {"CANCELLED", "RETURNED", "RETURNED_SC"}


def decide(
    original: OperationEvidence,
    counterparts: list[OperationEvidence],
    destination_payments: list[PaymentEvidence],
    cutoff_at: datetime | None = None,
) -> Decision:
    """Reconcile confirmed origin remesa vs destination pago by identical codigo.

    A mirror remittance is optional; payment is authoritative evidence of
    execution in the destination. All amounts remain unverified. For historical
    runs, compare only payments dated on/before cutoff; a current status does
    not establish the historical status at cutoff.
    """
    if not original.direction or original.status == "UNKNOWN":
        return Decision("INSUFFICIENT_DATA", "Direction or source status unverified")
    if len(counterparts) > 1:
        return Decision("MANUAL_REVIEW", "Multiple counterpart remittances with same code")
    if counterparts:
        counterpart = counterparts[0]
        if counterpart.direction and counterpart.direction != original.direction:
            return Decision("STATUS_MISMATCH", "Counterpart direction conflicts")
        if counterpart.status == "UNKNOWN":
            return Decision("INSUFFICIENT_DATA", "Counterpart status unverified")

    if cutoff_at is not None:
        # Unknown dates cannot safely prove presence at a historical cutoff.
        if any(p.occurred_at is None for p in destination_payments):
            return Decision("INSUFFICIENT_DATA", "Payment date unknown at historical cutoff")
        eligible = [p for p in destination_payments if p.occurred_at <= cutoff_at]
        future = [p for p in destination_payments if p.occurred_at > cutoff_at]
        if not eligible and future:
            return Decision("PENDING_AS_OF", "Payment occurred after requested cutoff")
        destination_payments = eligible

    if len(destination_payments) > 1:
        return Decision("MANUAL_REVIEW", "Multiple destination payments; duplicate versus partial unverified")

    if original.status in CLOSED:
        if destination_payments:
            return Decision("MANUAL_REVIEW", "Payment recorded for returned/cancelled remittance; review reversal")
        return Decision("CLOSED", "Remittance returned/cancelled; no active payout expected")

    if original.status in NONPAID:
        if destination_payments:
            return Decision("STATUS_MISMATCH", "Destination payment exists but origin not marked paid")
        return Decision("PENDING", "Origin remittance not yet marked paid")

    if original.status != "PAID":
        return Decision("INSUFFICIENT_DATA", "Unknown operational lifecycle status")

    if not destination_payments:
        return Decision("PAYMENT_MISSING", "Origin marked paid but destination payment evidence absent")

    pay = destination_payments[0]
    if pay.amount is None or not pay.currency or original.amount is None or not original.currency:
        return Decision("INSUFFICIENT_DATA", "Payment or remittance monetary metadata is incomplete")
    # Never compare principal with payout without independently verified roles/FX.
    return Decision("MATCHED",
                    "Origin paid and destination payment present by codigo; no mirrored remittance required; amount NOT validated")


def ambiguity_by_code(rows: list[OperationEvidence]) -> bool:
    return len(rows) > 1
