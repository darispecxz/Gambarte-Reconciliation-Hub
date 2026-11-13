"""Offline FX audit: never certify numeric ratios as payout FX."""
from scripts.pilot_fx_contract_2026 import analyze,EXPECTED_RAW

def sample(code="1"):
    return {"Dirección":"BO_TO_CL","Código":code,"Estado evidencia":"SOURCE_AMOUNTS_MATCH_PILOT",
        "Moneda remesa normalizada":"USD","Moneda pago normalizada":"CLP",
        "Importe remesa del reporte":"700","Importe pago del reporte":"700",
        "Pago monto":"700","Origen mon_rec":"1","Pago mon_rec":"2",
        "Origen tipo_cambio_clp":"883","Pago tipo_cambio":"883",
        "Origen comision":"16"}

def test_raw_currency_contract_mapping():
    assert EXPECTED_RAW[("USD","CLP")]==("1","2")

def test_sample_must_match_pilot():
    routes=[{"Dirección":"BO_TO_CL","Código":"1","Moneda origen":"USD","Moneda pago":"CLP",
        "Importe origen":"700","Importe pago":"701","Clave pago":"123",
        "Clasificación monetaria":"FX_SEMANTICS_UNVERIFIED","Cohorte":"JANUARY_ORIGIN",
        "Estado al corte":"PAID_BY_CUTOFF"}]
    try:
        analyze(routes,[sample()])
    except ValueError as exc:
        assert "Sample differs" in str(exc)
    else:
        raise AssertionError("Must fail closed on source discrepancy")
