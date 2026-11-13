"""January cutoff distinct cohorts; accounting balance is never inferred."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from scripts.pilot_january_cutoff_2026 import (
    payment_cutoff, january_rows, december_rows, summarize,
)


def rem(code,id=1):
    return SimpleNamespace(source_record_id=id,source="CHILE",code=code,
        operation_type=3,status="PAID",amount=Decimal("100"),currency="BOB",
        occurred_at=datetime(2026,1,31,12))


def pay(code,id,day=2,month=2):
    return SimpleNamespace(source_record_id=id,source="BOLIVIA",code=code,
        operation_type=4,amount=Decimal("100"),currency="BOB",
        occurred_at=datetime(2026,month,day,10))


def test_february_payment_is_not_january_settlement():
    rows=january_rows([rem("001")],[pay("001",2)])
    assert rows[0]["as_of_status"]=="PAID_AFTER_CUTOFF"
    summary=summarize(rows,[pay("001",2)])
    assert summary["CL_TO_BO"]["origin_paid_by_cutoff"]==0
    assert summary["CL_TO_BO"]["origin_paid_after_cutoff"]==1


def test_chile_jan_31_2330_is_before_bolivia_cutoff():
    assert payment_cutoff("CHILE",datetime(2026,1,31,23,30))=="JANUARY_BY_CUTOFF"


def test_bolivia_feb_1_midnight_outside_cutoff():
    assert payment_cutoff("BOLIVIA",datetime(2026,2,1,0,0))=="AFTER_CUTOFF"


def test_january_payment_pair():
    rows=january_rows([rem("01")],[pay("01",3,day=31,month=1)])
    assert rows[0]["as_of_status"]=="PAID_BY_CUTOFF"


def test_december_row_counted_separately():
    p=pay("old",4,day=5,month=1)
    d={"Dirección":"CL_TO_BO","Código":"old","ID piloto pago":"4",
       "Clasificación":"CROSS_MONTH_PROVISIONAL_PAIR",
       "Fecha envío":"2025-12-31 13:00:00",
       "Importe envío":"100.00000","Moneda envío":"BOB",
       "Clave real remesa diciembre":"3:old:8","Clave real pago enero":"4:4"}
    december=december_rows([d],[p])
    summary=summarize(december,[p])
    assert summary["CL_TO_BO"]["december_origin_paid_in_january"]==1
    assert summary["CL_TO_BO"]["payments_in_january_without_cohort_match"]==0
