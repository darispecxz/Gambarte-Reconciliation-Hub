"""Offline review of 306 FX-labelled operations against 12 raw-source samples.

No database connections. No inferred FX, CLP disbursement, settlement, or
commission deductions. Highlights when payment.monto's displayed currency
cannot safely be interpreted as the final cash denomination.
"""
import argparse
import csv
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scripts.pilot_operation_detail_2026 import safe_csv_value, validate_export_path

MAX_INPUT=15000
FIELDS=(
    ("direction","Dirección"),("code","Código"),("cohort","Cohorte"),
    ("cutoff","Estado al corte"),("origin_currency","Moneda origen"),
    ("payment_currency","Moneda pago declarada"),("origin_amount","Importe origen reporte"),
    ("payment_amount","pago.monto normalizado"),("source_sample","Fuente original examinada"),
    ("origin_raw_mon_rec","Origen mon_rec"),("payment_raw_mon_rec","Pago mon_rec"),
    ("origin_raw_fx","Origen tipo_cambio_clp"),("payment_raw_fx","Pago tipo_cambio"),
    ("origin_raw_commission","Origen comision"),
    ("payment_equals_origin","Igualdad nominal (NO conversión)"),
    ("exchange_field_match","Coincidencia numérica tasa CLP en ambas fuentes"),
    ("evidence_status","Estado de evidencia"),
    ("financial_status","Estado financiero"),("review","Pendiente"),
)
PAIRS={("BOB","CLP"),("BOB","USD"),("USD","CLP")}
EXPECTED_RAW={
    ("BOB","CLP"):("2","2"),
    ("BOB","USD"):("2","1"),
    ("USD","CLP"):("1","2"),
}
def load_csv(path,required,limit):
    p=Path(path)
    if not p.is_file() or p.is_symlink():
        raise ValueError("Private regular CSV required")
    with p.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("Unexpected source CSV headers")
        rows=list(reader)
    if len(rows)>limit:
        raise ValueError("Input safety cap exceeded")
    return rows

def valid_amount(s):
    try:
        n=Decimal(s)
    except (InvalidOperation,TypeError) as exc:
        raise ValueError("Invalid amount") from exc
    if not n.is_finite() or n<=0:
        raise ValueError("Positive finite monetary amount required")
    return n

def analyze(routes,samples):
    detail={}
    for row in samples:
        if row["Dirección"]!="BO_TO_CL" or row["Estado evidencia"]!="SOURCE_AMOUNTS_MATCH_PILOT":
            raise ValueError("Unverified source evidence")
        key=(row["Dirección"],row["Código"])
        if key in detail:
            raise ValueError("Duplicate source sample")
        detail[key]=row
    result=[]
    observed=set()
    for r in routes:
        if r["Clasificación monetaria"]!="FX_SEMANTICS_UNVERIFIED":
            continue
        pair=(r["Moneda origen"],r["Moneda pago"])
        if r["Dirección"]!="BO_TO_CL" or pair not in PAIRS:
            raise ValueError("Unsupported FX classification/direction")
        if not r["Clave pago"]:
            raise ValueError("FX pair missing payment identity")
        origin=valid_amount(r["Importe origen"])
        paid=valid_amount(r["Importe pago"])
        raw=detail.get((r["Dirección"],r["Código"]))
        same=origin==paid
        if raw:
            observed.add((r["Dirección"],r["Código"]))
            if (pair!=(raw["Moneda remesa normalizada"],raw["Moneda pago normalizada"])
                or origin!=valid_amount(raw["Importe remesa del reporte"])
                or paid!=valid_amount(raw["Importe pago del reporte"])
                or paid!=valid_amount(raw["Pago monto"])):
                raise ValueError("Sample differs from full monetary report")
            rawcurr=(raw["Origen mon_rec"],raw["Pago mon_rec"])
            if rawcurr!=EXPECTED_RAW[pair]:
                status="SOURCE_CURRENCY_CODE_UNEXPECTED_REVIEW"
            elif same and pair==("USD","CLP"):
                status="CLP_PAYMENT_UNIT_NOT_PROVEN_FROM_MONTO"
            else:
                status="RAW_FIELDS_PRESENT_FX_RULE_PENDING"
            fx_a=raw["Origen tipo_cambio_clp"]
            fx_b=raw["Pago tipo_cambio"]
            rate_match=("YES_NUMERIC_ONLY" if fx_a and fx_b
                and Decimal(fx_a)==Decimal(fx_b) else "NO_OR_MISSING")
        else:
            status="SOURCE_FIELDS_NOT_SAMPLED"
            fx_a=fx_b=rate_match=""
        result.append(dict(direction=r["Dirección"],code=r["Código"],
            cohort=r["Cohorte"],cutoff=r["Estado al corte"],
            origin_currency=pair[0],payment_currency=pair[1],
            origin_amount=r["Importe origen"],payment_amount=r["Importe pago"],
            source_sample="YES" if raw else "NO",
            origin_raw_mon_rec=raw["Origen mon_rec"] if raw else "",
            payment_raw_mon_rec=raw["Pago mon_rec"] if raw else "",
            origin_raw_fx=fx_a,payment_raw_fx=fx_b,
            origin_raw_commission=raw["Origen comision"] if raw else "",
            payment_equals_origin="YES" if same else "NO",
            exchange_field_match=rate_match,evidence_status=status,
            financial_status="NOT_CERTIFIED",
            review=("Identificar importe efectivamente entregado en CLP, fórmula de pago, redondeo y comisiones"
                    if pair[1]=="CLP" else
                    "Verificar base imponible/comisión, tasa pactada y efectivo en USD")))
    if observed!=set(detail):
        raise ValueError("Source samples not all present in main report")
    if len(result)!=306:
        raise ValueError("Expected exactly 306 FX operations in January pilot")
    return result

def html(rows):
    data=json.dumps(rows,ensure_ascii=False).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    cols=json.dumps(FIELDS,ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Revisión de conversiones enero 2026</title>
<style>body{margin:0;background:#f2f5f9;color:#18314c;font:14px Segoe UI,Arial}
main{max-width:1480px;margin:auto;padding:22px}header{background:#143654;color:white;border-radius:12px;padding:22px}
aside{margin:16px 0;background:#fff6e7;border:1px solid #d7b77e;padding:16px;border-radius:9px}
input,select{padding:10px;border:1px solid #bccbdb;border-radius:8px;margin:12px 8px 12px 0}
.wrap{overflow:auto;background:white;border:1px solid #dce5ee;border-radius:10px}
table{border-collapse:collapse;font-size:12px;white-space:nowrap;width:100%}
td,th{padding:10px;border-bottom:1px solid #e4ebf3;text-align:left}th{background:#e9eff7;position:sticky;top:0}</style>
<body><main><header><small>CONTROL PRIVADO · SIN CONEXIONES DB</small>
<h1>Conversión monetaria: 306 operaciones</h1><p>12 muestras de campos originales · interpretación financiera pendiente</p></header>
<aside><b>NO ES LIQUIDACIÓN CERTIFICADA.</b> pago.monto es un número almacenado;
la moneda declarada no garantiza que represente el efectivo entregado.
La coincidencia entre tasas es solo numérica, no prueba la fórmula aplicada.
No sumar importes entre distintas monedas sin evidencia de conversión.</aside>
<input id="q" placeholder="Buscar código"><select id="pair"><option value="">Todas las rutas</option></select>
<p id="count"></p><div class="wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>const R=__DATA__,C=__COLS__,pair=document.querySelector('#pair');
for(let v of [...new Set(R.map(x=>x.origin_currency+' → '+x.payment_currency))]){
let o=document.createElement('option');o.value=v;o.textContent=v;pair.append(o)}
let h=document.createElement('tr');for(let [,v] of C){let th=document.createElement('th');th.textContent=v;h.append(th)}document.querySelector('#head').append(h);
function draw(){let q=document.querySelector('#q').value.toLowerCase(),v=pair.value;
let list=R.filter(x=>(!v||x.origin_currency+' → '+x.payment_currency==v)&&(!q||x.code.includes(q)));
let b=document.querySelector('#body');b.replaceChildren();for(let r of list.slice(0,300)){
let tr=document.createElement('tr');for(let [k] of C){let td=document.createElement('td');td.textContent=String(r[k]??'');tr.append(td)}b.append(tr)}
document.querySelector('#count').textContent=list.length+' operaciones · CSV incluye 306';}
document.querySelector('#q').oninput=draw;pair.onchange=draw;draw();</script></main></body></html>""".replace("__DATA__",data).replace("__COLS__",cols)

def run(routes_csv,samples_csv,output):
    route_required={"Dirección","Código","Moneda origen","Moneda pago",
        "Importe origen","Importe pago","Clave pago","Clasificación monetaria","Cohorte","Estado al corte"}
    sample_required={"Dirección","Código","Estado evidencia","Moneda remesa normalizada",
        "Moneda pago normalizada","Importe remesa del reporte","Importe pago del reporte",
        "Pago monto","Origen mon_rec","Pago mon_rec","Origen tipo_cambio_clp",
        "Pago tipo_cambio","Origen comision"}
    routes=load_csv(routes_csv,route_required,MAX_INPUT)
    samples=load_csv(samples_csv,sample_required,12)
    rows=analyze(routes,samples)
    dest=validate_export_path(output)
    csv_dest=dest.with_suffix(".csv")
    if csv_dest.is_symlink():
        raise ValueError("Output CSV symlink blocked")
    dest.write_text(html(rows),encoding="utf-8")
    with csv_dest.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow([n for _,n in FIELDS])
        for row in rows:
            w.writerow([safe_csv_value(row.get(key,"")) for key,_ in FIELDS])
    print("source_connections=False pilot_connections=False writes_to_sources=False financial_certification=False")
    print("fx_rows="+str(len(rows))+" sample_count="+str(sum(r["source_sample"]=="YES" for r in rows)))
    for k,n in sorted(Counter((r["origin_currency"],r["payment_currency"]) for r in rows).items()):
        print(f"pair={k[0]}->{k[1]} count={n}")
    for k,n in sorted(Counter(r["evidence_status"] for r in rows).items()):
        print(f"evidence={k} count={n}")
    print(f"files_created={dest.name},{csv_dest.name}")
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--routes-csv",required=True)
    p.add_argument("--samples-csv",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    run(a.routes_csv,a.samples_csv,a.output)

if __name__=="__main__":
    main()
