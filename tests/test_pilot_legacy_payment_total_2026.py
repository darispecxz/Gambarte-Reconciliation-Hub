from decimal import Decimal
from scripts.pilot_legacy_payment_total_2026 import calculate,SQL,compare
from app.integrations.source import validate_read_query

def test_php_round_positive_amounts():
    assert calculate("700","883")==Decimal("618100")
    assert calculate("1.005","100")==Decimal("101")
    assert calculate("2.004","100")==Decimal("200")

def test_bounded_indexed_queries():
    for q in SQL.values():
        validate_read_query(q)
        assert "LIMIT 2" in q
        assert "id_operacion=:op" in q

def test_compare_never_certifies():
    sample={"Código":"11518","Cohorte":"JANUARY_ORIGIN",
        "Moneda remesa normalizada":"USD","Moneda pago normalizada":"CLP",
        "Pago monto":"700","Pago tipo_cambio":"883"}
    origin={"monto":700,"total_cambio":700,"total_clp":618100,
        "tipo_cambio_clp":883,"pago_comision":0}
    payment={"monto":700,"mon_rec":2,"tipo_cambio":883,"total":618100}
    r=compare(sample,origin,payment,"const/PRIMARY/1","const/PRIMARY/1","16:1","3:2")
    assert r["formula_result"]=="MATCH_STORED_PAGO_TOTAL"
    assert r["financial_certification"]=="NOT_CERTIFIED"
