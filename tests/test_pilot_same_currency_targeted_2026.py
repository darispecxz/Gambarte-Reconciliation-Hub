"""No production DB access in tests; synthetic sampling and source policies."""
from scripts.pilot_same_currency_targeted_2026 import select_cases, SQL
from app.integrations.source import validate_read_query

def sample(direction, currency, n):
    return {"Dirección":direction,"Código":str(n),"Moneda":currency,
        "Certificación financiera":"NOT_CERTIFIED","Diferencia nominal":"0",
        "Estado al corte":"PAID_BY_CUTOFF","Clave origen":str(n),
        "Clave pago":str(n+100),"Importe envío":"100","Importe pago":"100"}

def test_six_per_pair_only():
    rows=[sample("CL_TO_BO","BOB",i) for i in range(10)]
    rows += [sample("BO_TO_CL","USD",i) for i in range(20,30)]
    cases=select_cases(rows)
    assert len(cases)==12
    assert sum(x["Dirección"]=="CL_TO_BO" for x in cases)==6
    assert sum(x["Dirección"]=="BO_TO_CL" for x in cases)==6

def test_all_queries_are_nonlocking_selects():
    assert len(SQL)==4
    for query in SQL.values():
        validate_read_query(query)
        assert "LIMIT 2" in query
        assert "codigo=:code" in query

def test_no_after_cutoff_sampled():
    rows=[sample("CL_TO_BO","BOB",i) for i in range(6)]
    rows += [sample("BO_TO_CL","USD",i) for i in range(20,26)]
    rows[0]["Estado al corte"]="PAID_AFTER_CUTOFF"
    try:
        select_cases(rows)
    except RuntimeError as err:
        assert "Insufficient" in str(err)
    else:
        raise AssertionError("After-cutoff item must not count")
