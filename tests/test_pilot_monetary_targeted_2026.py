"""Synthetic tests for bounded monetary source review."""
import pytest
from types import SimpleNamespace
from scripts.pilot_monetary_targeted_2026 import (
    select_cases,identity_params,safe_plan,original_key,output_row,
)


def make(pair,cohort,code):
    return {
        "Moneda origen":pair[0],"Moneda pago":pair[1],
        "Clasificación monetaria":"FX_SEMANTICS_UNVERIFIED",
        "Dirección":"BO_TO_CL","Cohorte":cohort,"Código":str(code),
        "Clave origen":"10" if cohort=="JANUARY_ORIGIN" else "16:90",
        "Clave pago":"20" if cohort=="JANUARY_ORIGIN" else "3:200",
    }


def test_twelve_stratified_cases():
    rows=[]
    for pair in (("BOB","CLP"),("BOB","USD"),("USD","CLP")):
        rows.extend(make(pair,"JANUARY_ORIGIN",i) for i in range(10,15))
        if pair!=("USD","CLP"):
            rows.append(make(pair,"DECEMBER_ORIGIN_JANUARY_PAYMENT",1))
    chosen=select_cases(rows)
    assert len(chosen)==12
    assert sum(x["Cohorte"]=="DECEMBER_ORIGIN_JANUARY_PAYMENT" for x in chosen)==2


def test_bounded_identity_validation():
    assert identity_params("CHILE","remittance","3:4277474:8","4277474")==dict(
        op=3,code="4277474",dest=8)
    assert identity_params("BOLIVIA","payment","4:100","123")["pk"]==100
    with pytest.raises(ValueError):
        identity_params("CHILE","remittance","3:999:8","123")


def test_unindexed_plan_is_rejected():
    with pytest.raises(RuntimeError):
        safe_plan([{"type":"ALL","key":None,"rows":1}])
    assert safe_plan([{"type":"const","key":"PRIMARY","rows":1}])=="const/PRIMARY/1"


def test_january_pilot_source_mapping():
    row={"Sistema remesa":"BOLIVIA","Cohorte":"JANUARY_ORIGIN",
         "Código":"123","Clave origen":"10"}
    records={10:SimpleNamespace(source="BOLIVIA",dataset="remittance",
                                code="123",source_id="16:999")}
    assert original_key(row,"remittance",records)=="16:999"


def test_original_money_check_does_not_infer_fx():
    row={"Dirección":"BO_TO_CL","Cohorte":"JANUARY_ORIGIN","Código":"123",
      "Sistema remesa":"BOLIVIA","Sistema pago":"CHILE","Clave origen":"1",
      "Clave pago":"2","Moneda origen":"BOB","Moneda pago":"CLP",
      "Importe origen":"373.61","Importe pago":"39"}
    output=output_row(row,{"monto":373.61},{"monto":39},"ref/idx/1","ref/idx/1")
    assert output["evidence_flag"]=="SOURCE_AMOUNTS_MATCH_PILOT"
    assert "FX" in output["review"]
