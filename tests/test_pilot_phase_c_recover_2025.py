"""Offline checks for gated cross-year recovery of prior-year remittances."""
from datetime import datetime
import pytest

from scripts.pilot_phase_c_recover_2025 import pending_cases, verify_recovery


def case(payment_type=3, direction="BO_TO_CL", code="1123"):
    return dict(direction=direction,code=code,payment_type=payment_type,
                payment_source="CHILE" if direction=="BO_TO_CL" else "BOLIVIA")


def source_row(year=2025,operation=16,code="1123"):
    return dict(code=code,source_pk=200,operation_type=operation,
                occurred_at=datetime(year,12,25,10,30))


def test_unique_2025_origin_is_eligible():
    assert verify_recovery(case(),[source_row()])=="ELIGIBLE_2025_SOURCE"
    assert verify_recovery(case(4,"CL_TO_BO"),
                           [source_row(operation=3)])=="ELIGIBLE_2025_SOURCE"


def test_recovery_rejects_non_2025_null_dates_or_multiple_rows():
    assert verify_recovery(case(),[])=="REVIEW_SOURCE_ROW_COUNT"
    assert verify_recovery(case(),[source_row(),source_row()])=="REVIEW_SOURCE_ROW_COUNT"
    assert verify_recovery(case(),[source_row(year=2026)])=="REVIEW_NOT_2025"
    row=source_row()
    row["occurred_at"]=None
    assert verify_recovery(case(),[row])=="REVIEW_NOT_2025"


def test_recovery_rejects_wrong_payment_type_or_code():
    assert verify_recovery(case(payment_type=7),[source_row()])=="REVIEW_PAYMENT_MODALITY"
    assert verify_recovery(case(),[source_row(code="333")])=="REVIEW_CODE_MISMATCH"


def test_recovery_selects_only_non_return_unique_cases():
    items=[
        dict(direction="BO_TO_CL",payment_code="1123",
             payment_source="CHILE",payment_type=3,
             same_code_payment_candidates=1,assessment="NO_ORIGIN_IN_PILOT"),
        dict(direction="CL_TO_BO",payment_code="27691",
             payment_source="BOLIVIA",payment_type=4,
             same_code_payment_candidates=1,assessment="RETURNED_LOCALLY_IN_BOLIVIA"),
    ]
    result=pending_cases(items,25)
    assert len(result)==1 and result[0]["code"]=="1123"


def test_recovery_fails_closed_on_duplicate_payment_or_cap():
    example=dict(direction="BO_TO_CL",payment_code="1123",
                 payment_source="CHILE",payment_type=3,
                 same_code_payment_candidates=2,assessment="NO_ORIGIN_IN_PILOT")
    with pytest.raises(RuntimeError,match="Duplicate"):
        pending_cases([example],25)
    example["same_code_payment_candidates"]=1
    with pytest.raises(RuntimeError,match="Multiple"):
        pending_cases([example,example],25)
    with pytest.raises(ValueError,match="1..25"):
        pending_cases([],26)
