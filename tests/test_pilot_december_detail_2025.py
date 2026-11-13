"""Synthetic December/January cross-month classification and timezone tests."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from scripts.pilot_december_detail_2025 import (
    classify_candidate, compare_time, make_report_row,
)


def origin(source="CHILE",amount="100",currency="USD",status="PAID"):
    return SimpleNamespace(
        source=source,source_id="3:42:4",code="123",operation_type=3,
        occurred_at=datetime(2025,12,31,23,30),
        amount=Decimal(amount),currency=currency,status=status,
        raw={"currency_id":1},
    )


def payment(source="BOLIVIA",amount="100",currency="USD"):
    return SimpleNamespace(source=source,source_record_id=10,
        code="123",operation_type=4,occurred_at=datetime(2026,1,1,1),
        amount=Decimal(amount),currency=currency)


def test_santiago_summer_time_difference():
    flag,a,b,elapsed=compare_time(
        "CHILE", datetime(2025,12,31,23,30),
        "BOLIVIA", datetime(2025,12,31,23,0))
    assert flag=="TIME_ORDERED_AFTER_TZ"
    assert elapsed=="0.50"
    assert a.endswith("+00:00") and b.endswith("+00:00")


def test_santiago_winter_same_offset():
    flag,_,_,elapsed=compare_time(
        "CHILE",datetime(2026,6,1,12),
        "BOLIVIA",datetime(2026,6,1,12,30))
    assert flag=="TIME_ORDERED_AFTER_TZ"
    assert elapsed=="0.50"


def test_unique_compatible_cross_month_pair():
    category,candidate=classify_candidate("CHILE",payment(),[origin()])
    assert category=="CROSS_MONTH_PROVISIONAL_PAIR"
    assert candidate is not None


def test_same_currency_difference_must_be_reviewed():
    category,_=classify_candidate("CHILE",payment(),[origin(amount="101")])
    assert category=="MANUAL_REVIEW_AMOUNT_DIFFERENCE"


def test_ambiguous_or_invalid_type_is_not_auto_paired():
    assert classify_candidate("CHILE",payment(),[origin(),origin()])[0].startswith("MANUAL_REVIEW")
    bad=origin()
    bad.operation_type=16
    assert classify_candidate("CHILE",payment(),[bad])[0]=="MANUAL_REVIEW_ORIGIN_TYPE_OR_DUPLICATE"


def test_private_evidence_flags_fx_not_certified():
    item=make_report_row(payment(), "CHILE", [origin(amount="105",currency="CLP")], "4:100")
    assert item["category"]=="CROSS_MONTH_PROVISIONAL_PAIR"
    assert item["money_flag"]=="FX_REVIEW_DIFFERENT_CURRENCIES"
    assert item["difference"]==""
