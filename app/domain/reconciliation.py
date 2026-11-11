from dataclasses import dataclass
from decimal import Decimal

def decimal_amount(value: object) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Financial amounts must not use binary floating point")
    return Decimal(str(0 if value is None else value))

@dataclass(frozen=True)
class Remittance:
    code: str
    status: str
    amount: Decimal
    currency: str | None

@dataclass(frozen=True)
class Payment:
    code: str
    amount: Decimal
    currency: str | None

@dataclass(frozen=True)
class Finding:
    code: str
    category: str
    description: str

def reconcile(remittance: Remittance, payments: list[Payment]) -> list[Finding]:
    if not payments:
        return ([Finding(remittance.code, "PAID_WITHOUT_PAYMENT",
                         "Origin marked paid but destination payment is absent")]
                if remittance.status == "PAID" else [])
    if len(payments) > 1:
        return [Finding(remittance.code, "MULTIPLE_PAYMENTS",
                        "Multiple payments detected; confirm whether partial payments are legitimate")]
    payment = payments[0]
    if (remittance.currency and payment.currency
            and remittance.currency == payment.currency
            and abs(remittance.amount - payment.amount) > Decimal("0.01")):
        return [Finding(remittance.code, "AMOUNT_MISMATCH", "Amount differs in same currency")]
    return []
