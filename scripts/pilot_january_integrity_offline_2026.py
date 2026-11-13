"""Offline integrity check for the 2026-01 operational reconciliation.

Only reads three existing private CSVs; never connects to source or pilot DB.
Checks disjoint populations, required IDs, currency-route identities, Decimal
amount equality, cutoff cohorts, and consistent consolidated classification.
"""
import argparse
import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path

REQUIRED = {
    "same": {"Dirección","Código","Moneda","Importe envío","Importe pago",
             "Clave origen","Clave pago","Estado al corte"},
    "fx": {"Código","Ruta","Estado al corte del piloto","Diferencia remesa.total_clp - pago.total"},
    "close": {"code","direction","monetary","period_group"},
}
COUNT_BY_GROUP={"same":2600,"fx":306,"close":2917}
CLP_LIMIT=Decimal("10")

def load(path,kind):
    p=Path(path)
    if not p.is_file() or p.is_symlink():
        raise ValueError("Regular private CSV required: "+kind)
    with p.open(encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        if not REQUIRED[kind].issubset(reader.fieldnames or []):
            raise ValueError("Unexpected CSV schema: "+kind)
        rows=list(reader)
    if len(rows)!=COUNT_BY_GROUP[kind]:
        raise ValueError("Unexpected population size: "+kind)
    return rows

def check(same,fx,close):
    same_keys=set()
    for r in same:
        key=(r["Dirección"],r["Código"])
        if key in same_keys: raise ValueError("Repeated same-currency identity")
        same_keys.add(key)
        if (not r["Clave origen"] or not r["Clave pago"] or
            Decimal(r["Importe envío"])!=Decimal(r["Importe pago"])):
            raise ValueError("Incomplete source key or unequal same-currency amount")
        if (r["Dirección"],r["Moneda"]) not in {("CL_TO_BO","BOB"),("BO_TO_CL","USD")}:
            raise ValueError("Unsupported same-currency route")
    fx_keys=set()
    outcomes=Counter()
    for r in fx:
        key=("BO_TO_CL",r["Código"])
        if key in fx_keys: raise ValueError("Repeated FX identity")
        fx_keys.add(key)
        d=Decimal(r["Diferencia remesa.total_clp - pago.total"])
        if not d.is_finite(): raise ValueError("Nonfinite FX difference")
        label="COINCIDENCIA_EXACTA_CLP" if d==0 else (
            "DENTRO_TOLERANCIA_10_CLP" if abs(d)<=CLP_LIMIT else "FUERA_TOLERANCIA_10_CLP")
        outcomes[label]+=1
    if same_keys & fx_keys: raise ValueError("Overlap between payment cohorts")
    consolidated={}
    for r in close:
        key=(r["direction"],r["code"])
        if key in consolidated: raise ValueError("Repeated consolidated identity")
        consolidated[key]=r
    if not (same_keys|fx_keys).issubset(consolidated):
        raise ValueError("Payment population missing from consolidated")
    closed_keys=set(consolidated)-(same_keys|fx_keys)
    if len(closed_keys)!=11: raise ValueError("Unexpected closed remainder")
    closed=Counter(consolidated[k]["period_group"] for k in closed_keys)
    if closed!=Counter({"ANULADA":8,"DEVUELTA":3}):
        raise ValueError("Unexpected closed classifications")
    for key in same_keys:
        if consolidated[key]["monetary"]!="IGUALDAD_NOMINAL_MISMA_MONEDA":
            raise ValueError("Same-currency consolidated mismatch")
    for key in fx_keys:
        observed=consolidated[key]["monetary"]
        diff=Decimal(next(r["Diferencia remesa.total_clp - pago.total"]
            for r in fx if r["Código"]==key[1]))
        expected="COINCIDENCIA_EXACTA_CLP" if diff==0 else (
            "DENTRO_TOLERANCIA_10_CLP" if abs(diff)<=CLP_LIMIT else "FUERA_TOLERANCIA_10_CLP")
        if observed!=expected: raise ValueError("FX consolidated mismatch: "+key[1])
    periods=Counter(r["period_group"] for r in close)
    if periods!=Counter({"PAGO_EN_ENERO":2853,"PAGO_POSTERIOR_AL_CORTE":53,
                         "ANULADA":8,"DEVUELTA":3}):
        raise ValueError("Unexpected cutoff populations")
    return {"same_currency":len(same_keys),"fx":len(fx_keys),
            "closed_cancelled":closed["ANULADA"],"closed_returned":closed["DEVUELTA"],
            "exact_clp":outcomes["COINCIDENCIA_EXACTA_CLP"],
            "within_10_clp":outcomes["DENTRO_TOLERANCIA_10_CLP"],
            "outside_10_clp":outcomes["FUERA_TOLERANCIA_10_CLP"],
            "total":len(consolidated),"payment_in_january":periods["PAGO_EN_ENERO"],
            "payment_after_cutoff":periods["PAGO_POSTERIOR_AL_CORTE"]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--same",required=True)
    p.add_argument("--fx",required=True)
    p.add_argument("--close",required=True)
    args=p.parse_args()
    values=check(load(args.same,"same"),load(args.fx,"fx"),load(args.close,"close"))
    for key,value in values.items(): print(f"{key}={value}")
    print("integrity=PASS source_connections=0 financially_certified=False")

if __name__=="__main__":main()
