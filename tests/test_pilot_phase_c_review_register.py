"""Offline tests for pilot-only immutable review event rules."""
import pytest
from scripts.pilot_phase_c_review_register import validate_record


def case():
    return dict(direction="CL_TO_BO",code="2101877",payment_source="BOLIVIA",
                payment_record_id="454900",
                classification_snapshot="AMBIGUOUS_OR_DUPLICATE_CODE_REVIEW",
                decision="CONFIRMED_DUPLICATE_RECORD_CONNECTIVITY",
                reviewer="operations_team",evidence_ref="OPS-2026-2101877")


def test_valid_manual_event_does_not_change_automatic_classification():
    result=validate_record(case())
    assert result["payment_record_id"]==454900
    assert result["classification_snapshot"]=="AMBIGUOUS_OR_DUPLICATE_CODE_REVIEW"
    assert result["decision"]=="CONFIRMED_DUPLICATE_RECORD_CONNECTIVITY"


def test_rejects_wrong_source_for_direction():
    value=case()
    value["payment_source"]="CHILE"
    with pytest.raises(ValueError,match="direction"):
        validate_record(value)


def test_rejects_decision_not_supported_by_auto_classification():
    value=case()
    value["decision"]="REVIEW_EXCEPTIONAL_PAYMENT_CHANNEL"
    with pytest.raises(ValueError,match="incompatible"):
        validate_record(value)


def test_rejects_sensitive_free_text_in_evidence_reference():
    value=case()
    value["evidence_ref"]="customer account 12345 and name"
    with pytest.raises(ValueError,match="non-sensitive"):
        validate_record(value)


def test_rejects_non_numeric_code_and_missing_reviewer():
    value=case()
    value["code"]="2101877 OR 1=1"
    with pytest.raises(ValueError,match="code"):
        validate_record(value)
    value=case()
    value["reviewer"]=""
    with pytest.raises(ValueError,match="reviewer"):
        validate_record(value)


def test_exceptional_channel_must_remain_review_pending():
    value=case()
    value.update(code="7737958",payment_record_id="456498",
                 classification_snapshot="PAYMENT_TYPE_NOT_COMPATIBLE_WITH_ORIGIN",
                 decision="REVIEW_EXCEPTIONAL_PAYMENT_CHANNEL")
    assert validate_record(value)["decision"]=="REVIEW_EXCEPTIONAL_PAYMENT_CHANNEL"
