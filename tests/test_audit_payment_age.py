"""Pure classification tests; no production connections."""
from datetime import datetime, timedelta
from scripts.audit_payment_age import summarize


def test_age_groups_and_missing_origin_are_aggregated_only():
    t = datetime(2026, 11, 11, 14, 0)
    rows = [("1", t), ("2", t), ("3", t), ("4", t), ("5", t), ("6", t)]
    origins = {
        "1": [t - timedelta(days=40)],
        "2": [t - timedelta(days=10)],
        "3": [t - timedelta(days=1)],
        "4": [t - timedelta(days=9), t - timedelta(days=10)],
        "6": [t + timedelta(days=4)],
    }
    result = summarize(rows, origins)
    assert result["sampled_payments"] == 6
    assert result["paid_more_than_30_days_after_origin"] == 1
    assert result["paid_between_7_and_30_days_after_origin"] == 1
    assert result["paid_within_7_days_or_clock_skew"] == 1
    assert result["ambiguous_origin_code"] == 1
    assert result["origin_not_found_in_selected_types"] == 1
    assert result["origin_created_after_payment"] == 1


def test_breakdown_above_30_days_and_max_lag():
    paid = datetime(2026, 11, 11, 14, 0)
    sample = [("31", paid), ("61", paid), ("91", paid), ("3", paid)]
    origins = {
        "31": [paid - timedelta(days=31)],
        "61": [paid - timedelta(days=61)],
        "91": [paid - timedelta(days=91)],
        "3": [paid - timedelta(days=3)],
    }
    result = summarize(sample, origins)
    assert result["paid_more_than_30_days_after_origin"] == 3
    assert result["paid_between_30_and_60_days_after_origin"] == 1
    assert result["paid_between_60_and_90_days_after_origin"] == 1
    assert result["paid_more_than_90_days_after_origin"] == 1
    assert result["max_lag_days"] == 91
