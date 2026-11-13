"""Synthetic audit assertions; no production DB access."""
from decimal import Decimal
from scripts.pilot_fx_306_source_totals_2026 import evidence,PAIRS
def test_distribution():
    assert sum(PAIRS.values())==306
def test_source_total_match_does_not_certify():
    r={"Código":"11518","Moneda origen":"USD","Moneda pago":"CLP",
       "Cohorte":"JANUARY_ORIGIN","Estado al corte":"PAID_BY_CUTOFF",
       "Fecha pago":"2026-01-21 12:00:00","Importe origen":"700",
       "Importe pago":"700"}
    origin={"monto":700,"total_clp":618100,"tipo_cambio_clp":883}
    payment={"monto":700,"total":618100,"tipo_cambio":883,
             "mon_rec":2,"fec_crea_pago":"2026-01-21 12:00:00"}
    value=evidence(r,origin,payment,"16:1","3:2","const/PRIMARY/1","const/PRIMARY/1")
    assert value["total_result"]=="MATCH_ORIGIN_TOTAL_CLP"
    assert value["formula_result"]=="MATCH_STORED_PAGO_TOTAL"
    assert value["certification"]=="NOT_CERTIFIED"
def test_difference_is_explicit():
    r={"Código":"11518","Moneda origen":"USD","Moneda pago":"CLP",
       "Cohorte":"JANUARY_ORIGIN","Estado al corte":"PAID_BY_CUTOFF",
       "Fecha pago":"2026-01-21 12:00:00","Importe origen":"700",
       "Importe pago":"700"}
    origin={"monto":700,"total_clp":618200,"tipo_cambio_clp":883}
    payment={"monto":700,"total":618100,"tipo_cambio":883,
             "mon_rec":2,"fec_crea_pago":"2026-01-21 12:00:00"}
    v=evidence(r,origin,payment,"16:1","3:2","const/PRIMARY/1","const/PRIMARY/1")
    assert Decimal(v["diff_source_vs_payment"])==100
    assert v["total_result"]=="TOTAL_CLP_DIFFERENCE_REVIEW"

def test_clp_tolerance_inclusive_boundaries():
    from scripts.pilot_fx_306_source_totals_2026 import CLP_TOLERANCE
    assert CLP_TOLERANCE == Decimal("10")
    row={"Código":"11518","Moneda origen":"USD","Moneda pago":"CLP",
         "Cohorte":"JANUARY_ORIGIN","Estado al corte":"PAID_BY_CUTOFF",
         "Fecha pago":"2026-01-21 12:00:00","Importe origen":"700",
         "Importe pago":"700"}
    for clp,expected in ((618100,"EXACT_MATCH"),(618110,"WITHIN_CLP_TOLERANCE"),
                          (618090,"WITHIN_CLP_TOLERANCE"),(618111,"OUTSIDE_CLP_TOLERANCE"),
                          (618089,"OUTSIDE_CLP_TOLERANCE")):
        origin={"monto":700,"total_clp":clp,"tipo_cambio_clp":883}
        payment={"monto":700,"total":618100,"tipo_cambio":883,
                 "mon_rec":2,"fec_crea_pago":"2026-01-21 12:00:00"}
        value=evidence(row,origin,payment,"16:1","3:2","const/PRIMARY/1","const/PRIMARY/1")
        assert value["tolerance_result"]==expected
        assert value["certification"]=="NOT_CERTIFIED"
