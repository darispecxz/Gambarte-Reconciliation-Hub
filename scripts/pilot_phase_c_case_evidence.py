"""Phase C evidence-only review for duplicate payments and modality mismatches.

Never resolves an anomaly automatically. Pure decision helpers require verified
source facts; missing evidence remains inconclusive. Do not persist identities,
receipts, account numbers or sensitive user notes in Git.
"""
from datetime import datetime
from decimal import Decimal


DUPLICATE_FIELDS=("code","operation_type","agency_id","user_id",
                  "amount","currency_id","receipt","commission")
MAX_NEAR_SECONDS=60


def suspected_duplicate(first, second):
    """Return evidence label, not proof of a duplicate financial settlement.

    Equal receipt, amount and other operational fields plus timestamps no more
    than one minute apart indicate a possible duplicate recording. Any missing
    required field blocks that label. Does NOT authorize deletion or reversal.
    """
    if first.get("source")!="BOLIVIA" or second.get("source")!="BOLIVIA":
        return "INCONCLUSIVE_SOURCE"
    if first.get("payment_id")==second.get("payment_id"):
        return "SAME_RECORD_NOT_DUPLICATE"
    if any(first.get(k) is None or second.get(k) is None
           or first[k]!=second[k] for k in DUPLICATE_FIELDS):
        return "INCONCLUSIVE_DUPLICATE_EVIDENCE"
    if not str(first.get("receipt") or "").strip() or str(first["receipt"]).strip().upper()=="N/A":
        return "INCONCLUSIVE_RECEIPT"
    a=first.get("occurred_at")
    b=second.get("occurred_at")
    if not isinstance(a,datetime) or not isinstance(b,datetime):
        return "INCONCLUSIVE_TIMESTAMPS"
    seconds=abs((a-b).total_seconds())
    if seconds>MAX_NEAR_SECONDS:
        return "INCONCLUSIVE_TIME_DISTANCE"
    return "SUSPECTED_DUPLICATE_RECORD_MANUAL_REVIEW"


def modality_assessment(origin, payment, allowed_types):
    """Preserve modality contract; same code/amount cannot override it."""
    if origin.get("code") != payment.get("code"):
        return "REVIEW_CODE_MISMATCH"
    if origin.get("currency") != payment.get("currency"):
        return "REVIEW_FX_OR_CURRENCY"
    if origin.get("amount") is None or payment.get("amount") is None:
        return "REVIEW_MISSING_AMOUNTS"
    if Decimal(str(origin["amount"])) != Decimal(str(payment["amount"])):
        return "REVIEW_AMOUNT_DIFFERENCE"
    if payment.get("operation_type") not in (allowed_types or set()):
        return "REVIEW_MODALITY_MISMATCH_SAME_CURRENCY_AMOUNT"
    return "PROVISIONAL_CODE_TYPE_AMOUNT_COMPATIBLE"


def next_steps(label):
    """Require operational/ledger evidence before changing financial statuses."""
    if label=="SUSPECTED_DUPLICATE_RECORD_MANUAL_REVIEW":
        return "VERIFY_LEDGER_BALANCE_IMPACT_AND_RECEIPT_BEFORE_REVERSAL"
    if label=="REVIEW_MODALITY_MISMATCH_SAME_CURRENCY_AMOUNT":
        return "CONFIRM_AUTHORIZED_PAYMENT_CHANNEL_BEFORE_MAPPING_CHANGE"
    return "REVIEW_SOURCE_EVIDENCE"
