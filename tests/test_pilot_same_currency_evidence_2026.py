"""Synthetic tests for isolated, private nominal match and cutoff audit."""
import pytest
from scripts.pilot_same_currency_evidence_2026 import analyze


def make(code,status="PAID_BY_CUTOFF",direction="CL_TO_BO",currency="BOB",key=None):
    key=key or code
    return {"Dirección":direction,"Cohorte":"JANUARY_ORIGIN",
        "Estado al corte":status,"Código":code,
        "País origen":"CHILE" if direction=="CL_TO_BO" else "BOLIVIA",
        "País pago":"BOLIVIA" if direction=="CL_TO_BO" else "CHILE",
        "Moneda origen":currency,"Moneda pago":currency,
        "Importe origen":"100.000000","Importe pago":"100",
        "Clasificación monetaria":"SAME_CURRENCY_EQUAL_NOT_SETTLED",
        "Clave origen":"r"+key,"Clave pago":"p"+key,
        "Fecha origen":"2026-01-01","Fecha pago":"2026-01-02"}


def test_three_cutoff_statuses_and_currency_routes():
    rows=[make("1"),make("2","PAID_AFTER_CUTOFF"),
          make("3","DECEMBER_ORIGIN_PAID_IN_JANUARY"),
          make("4",direction="BO_TO_CL",currency="USD")]
    out,summary,pairs=analyze(rows)
    assert len(out)==4
    assert summary["NOMINAL_EQUAL_PAID_BY_CUTOFF_PROVISIONAL"]==2
    assert summary["NOMINAL_EQUAL_PAID_AFTER_CUTOFF"]==1
    assert summary["NOMINAL_EQUAL_DEC_ORIGIN_JAN_PAYMENT_PROVISIONAL"]==1
    assert pairs[("BO_TO_CL","USD")]==1


def test_detect_duplicate_payment_reference_in_export():
    first=make("1",key="same")
    second=make("2",key="same")
    out,summary,_=analyze([first,second])
    assert summary["REFERENCE_DUPLICATE_REVIEW"]==2
    assert all("PAYMENT_KEY_REPEATED" in item["identity_alert"] for item in out)


def test_never_accept_mismatched_amount_as_nominal_match():
    row=make("1")
    row["Importe pago"]="99.00"
    with pytest.raises(ValueError):
        analyze([row])


def test_never_certifies_financial_settlement():
    row=make("1")
    out,_,_=analyze([row])
    assert out[0]["certification"]=="NOT_CERTIFIED"
    assert out[0]["identity_alert"]=="NONE_IN_EXPORTED_COHORT"


def test_unexpected_cutoff_status_stays_in_review():
    out,_,_=analyze([make("1",status="UNKNOWN")])
    assert out[0]["status"]=="UNEXPECTED_CUTOFF_STATUS_REVIEW"
