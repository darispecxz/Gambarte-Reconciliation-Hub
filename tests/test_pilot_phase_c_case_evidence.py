"""Offline regressions for Phase C evidence-only anomaly evaluation."""
from datetime import datetime,timedelta
from scripts.pilot_phase_c_case_evidence import suspected_duplicate,modality_assessment,next_steps


def payment(payment_id,second=0):
    return dict(source="BOLIVIA", payment_id=payment_id, code="TEST-001",
        operation_type=7,agency_id=9,user_id=102,amount="900.000000",
        currency_id=2,receipt="RECEIPT-001",commission="27.090000",
        occurred_at=datetime(2026,2,10,10,58,32)+timedelta(seconds=second))


def test_near_identical_payments_are_suspected_not_proven():
    label=suspected_duplicate(payment(1),payment(2,16))
    assert label=="SUSPECTED_DUPLICATE_RECORD_MANUAL_REVIEW"
    assert "LEDGER" in next_steps(label)


def test_differing_receipt_or_missing_receipt_is_not_duplicate_proof():
    first=payment(1)
    second=payment(2,16)
    second["receipt"]="DIFFERENT"
    assert suspected_duplicate(first,second)=="INCONCLUSIVE_DUPLICATE_EVIDENCE"
    second["receipt"]=None
    assert suspected_duplicate(first,second)=="INCONCLUSIVE_DUPLICATE_EVIDENCE"


def test_same_payment_or_far_apart_dates_are_not_near_duplicate():
    assert suspected_duplicate(payment(1),payment(1))=="SAME_RECORD_NOT_DUPLICATE"
    assert suspected_duplicate(payment(1),payment(2,120))=="INCONCLUSIVE_TIME_DISTANCE"


def test_equal_amount_and_code_cannot_override_modality_mapping():
    origin=dict(code="TEST-002",amount="494.00000",currency="BOB")
    payout=dict(code="TEST-002",amount="494.000000",currency="BOB",operation_type=4)
    label=modality_assessment(origin,payout,{7})
    assert label=="REVIEW_MODALITY_MISMATCH_SAME_CURRENCY_AMOUNT"
    assert "CHANNEL" in next_steps(label)


def test_compatible_mode_remains_provisional_only():
    origin=dict(code="TEST-002",amount=494,currency="BOB")
    payout=dict(code="TEST-002",amount=494,currency="BOB",operation_type=7)
    assert modality_assessment(origin,payout,{7})=="PROVISIONAL_CODE_TYPE_AMOUNT_COMPATIBLE"
