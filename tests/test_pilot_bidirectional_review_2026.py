"""Synthetic tests for isolated, bidirectional report."""
from datetime import date,datetime
from decimal import Decimal
from types import SimpleNamespace

from scripts.pilot_bidirectional_review_2026 import build_rows,temporal_flag


def rem(source,code,op,id,month=1,status="PAID",currency="USD",amount="100"):
    return SimpleNamespace(source_record_id=id,source=source,code=code,
        operation_type=op,occurred_at=datetime(2026,month,10,10),
        amount=Decimal(amount),currency=currency,status=status)


def pay(source,code,op,id,month=1):
    return SimpleNamespace(source_record_id=id,source=source,code=code,
        operation_type=op,occurred_at=datetime(2026,month,11,10),
        amount=Decimal("100"),currency="USD")


def test_missing_origin_is_not_confirmed_orphan():
    rows=build_rows([], [pay("BOLIVIA","X",4,1)],[],date(2026,1,31))
    assert len(rows)==1
    assert rows[0]["category"]=="PAYMENT_ORIGIN_NOT_IN_PILOT"


def test_cross_month_origin_is_distinguished():
    rows=build_rows([rem("CHILE","X",3,1,month=2)],
                    [pay("BOLIVIA","X",4,2)],[],date(2026,1,31))
    assert len(rows)==1
    assert rows[0]["category"]=="PAYMENT_ORIGIN_OUTSIDE_PERIOD"


def test_unpaired_payment_with_closed_origin_is_review():
    rows=build_rows([rem("CHILE","X",3,1,status="CANCELLED")],
                    [pay("BOLIVIA","X",4,2)],[],date(2026,1,31))
    assert len(rows)==2
    assert rows[-1]["category"]=="PAYMENT_ORIGIN_IN_PERIOD_REVIEW"


def test_provisional_pair_not_duplicated_as_unpaired_payment():
    rows=build_rows([rem("CHILE","X",3,1)],
                    [pay("BOLIVIA","X",4,2)],[],date(2026,1,31))
    assert len(rows)==1
    assert rows[0]["record_type"]=="REMITTANCE"


def test_negative_timestamp_flag_requires_timezone_review():
    a=rem("BOLIVIA","X",16,1)
    b=pay("CHILE","X",3,2)
    b.occurred_at=a.occurred_at.replace(hour=9)
    assert temporal_flag(a,b)=="PAYMENT_BEFORE_ORIGIN_TIMEZONE_NOT_VALIDATED"
