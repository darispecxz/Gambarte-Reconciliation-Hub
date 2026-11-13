"""Bounded 306-case January FX evidence: Bolivia remesa vs Chile pago.

Read-only primary-key queries, strict 306-row input, 20-case progress batches.
Verifies stored CLP totals and arithmetic only; not cash settlement.
"""
import argparse
import csv
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.infrastructure.models import SourceRecord
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_import import PILOT_DB,PILOT_HOST,check_marker,connect_source
from scripts.pilot_legacy_payment_total_2026 import source_record,calculate
from scripts.pilot_operation_detail_2026 import safe_csv_value,validate_export_path

REQUIRED={"Dirección","Cohorte","Estado al corte","Código","País origen","País pago",
 "Moneda origen","Moneda pago","Importe origen","Importe pago","Clave origen",
 "Clave pago","Clasificación monetaria","Fecha pago"}
PAIRS={("BOB","CLP"):254,("BOB","USD"):25,("USD","CLP"):27}
CLP_TOLERANCE=Decimal("10")  # Operational threshold supplied by GAMBARTE
COHORTS={"JANUARY_ORIGIN","DECEMBER_ORIGIN_JANUARY_PAYMENT"}
STATUSES={"PAID_BY_CUTOFF","PAID_AFTER_CUTOFF","DECEMBER_ORIGIN_PAID_IN_JANUARY"}
FIELDS=(
 ("code","Código"),("pair","Ruta"),("cohort","Cohorte"),
 ("cutoff","Estado al corte del piloto"),("payment_date_pilot","Fecha pago del piloto"),
 ("payment_date_source","Fecha pago fuente"),("origin_key","ID real remesa"),
 ("payment_key","ID real pago"),("origin_amount_report","Importe remesa piloto"),
 ("payment_amount_report","pago.monto piloto"),("origin_amount_source","remesa.monto fuente"),
 ("payment_amount_source","pago.monto fuente"),
 ("remesa_total_clp","remesa.total_clp"),("pago_total_clp","pago.total"),
 ("pago_tipo_cambio","pago.tipo_cambio"),("remesa_tipo_cambio_clp","remesa.tipo_cambio_clp"),
 ("calculated_total","ROUND(pago.monto × pago.tipo_cambio, 0)"),
 ("diff_source_vs_payment","Diferencia remesa.total_clp - pago.total"),
 ("diff_payment_vs_formula","Diferencia pago.total - fórmula"),
 ("amount_identity","Control importes originales"),
 ("rate_match","Comparación numérica tasas"),
 ("formula_result","Control fórmula"),("total_result","Control total CLP"),
 ("tolerance_result","Control tolerancia ±10 CLP"),
 ("origin_explain","EXPLAIN Bolivia"),("payment_explain","EXPLAIN Chile"),
 ("certification","Certificación financiera"),
)
def read_routes(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink():
        raise ValueError("Private regular January currency routes CSV required")
    with p.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not REQUIRED.issubset(reader.fieldnames or ()):
            raise ValueError("Invalid January currency route headers")
        all_rows=list(reader)
    if len(all_rows)>15000:
        raise ValueError("Input exceeds strict safety cap")
    rows=[x for x in all_rows if x["Clasificación monetaria"]=="FX_SEMANTICS_UNVERIFIED"]
    if len(rows)!=306:
        raise ValueError("Expected exactly 306 FX pairs")
    if Counter((r["Moneda origen"],r["Moneda pago"]) for r in rows)!=Counter(PAIRS):
        raise ValueError("Unexpected pair distribution")
    identities=set()
    for r in rows:
        if (r["Dirección"]!="BO_TO_CL" or r["País origen"]!="BOLIVIA"
            or r["País pago"]!="CHILE" or r["Cohorte"] not in COHORTS
            or r["Estado al corte"] not in STATUSES
            or not r["Código"].isdigit() or not r["Clave origen"] or not r["Clave pago"]):
            raise ValueError("Invalid FX cohort or source identity")
        try:
            amount=Decimal(r["Importe origen"]); payment=Decimal(r["Importe pago"])
            if not amount.is_finite() or not payment.is_finite() or amount<=0 or payment<=0:
                raise ValueError("Invalid monetary amount")
        except Exception as exc:
            raise ValueError("Invalid monetary amount") from exc
        if r["Cohorte"]=="JANUARY_ORIGIN":
            if not r["Clave origen"].isdigit() or not r["Clave pago"].isdigit():
                raise ValueError("January pilot IDs must be integers")
        else:
            for col in ("Clave origen","Clave pago"):
                if len(r[col].split(":"))!=2 or not all(v.isdigit() and int(v)>0 for v in r[col].split(":")):
                    raise ValueError("December row requires original 2-segment source keys")
        key=(r["Código"],r["Cohorte"])
        if key in identities:
            raise ValueError("Repeated code and cohort")
        identities.add(key)
    return sorted(rows,key=lambda r:(r["Cohorte"],int(r["Código"])))

def map_january(cfg,rows):
    wanted={int(r[k]) for r in rows if r["Cohorte"]=="JANUARY_ORIGIN"
            for k in ("Clave origen","Clave pago")}
    engine=pilot_engine(cfg)
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                found=conn.execute(select(SourceRecord.id,SourceRecord.source,
                    SourceRecord.dataset,SourceRecord.source_id,SourceRecord.code)
                    .where(SourceRecord.id.in_(wanted))).all()
            finally:
                conn.rollback()
    finally:
        engine.dispose()
    mapped={x.id:x for x in found}
    if len(mapped)!=len(wanted):
        raise RuntimeError("Incomplete January source identity mapping")
    return mapped

def identity(r,kind,mapped):
    col="Clave origen" if kind=="remittance" else "Clave pago"
    if r["Cohorte"]=="DECEMBER_ORIGIN_JANUARY_PAYMENT":
        return r[col]
    record=mapped[int(r[col])]
    if ((record.source,record.dataset,record.code)!=
        (("BOLIVIA" if kind=="remittance" else "CHILE"),kind,r["Código"])):
        raise RuntimeError("Source identity mismatch")
    return record.source_id

def evidence(r,origin,payment,ok,pk,oplan,pplan):
    origin_amount=Decimal(str(origin["monto"]))
    payment_amount=Decimal(str(payment["monto"]))
    identity_check=("SOURCE_AMOUNTS_MATCH_PILOT" if
        origin_amount==Decimal(r["Importe origen"]) and
        payment_amount==Decimal(r["Importe pago"])
        else "SOURCE_AMOUNT_CHANGED_REVIEW")
    a=Decimal(str(origin["total_clp"])) if origin["total_clp"] is not None else None
    b=Decimal(str(payment["total"])) if payment["total"] is not None else None
    tc1=Decimal(str(origin["tipo_cambio_clp"])) if origin["tipo_cambio_clp"] is not None else None
    tc2=Decimal(str(payment["tipo_cambio"])) if payment["tipo_cambio"] is not None else None
    calculated=calculate(payment_amount,tc2) if tc2 is not None else None
    formula=("NOT_AVAILABLE" if b is None or calculated is None else
        "MATCH_STORED_PAGO_TOTAL" if b==calculated else "FORMULA_DIFF_REVIEW")
    total=("NOT_AVAILABLE" if a is None or b is None else
        "MATCH_ORIGIN_TOTAL_CLP" if a==b else "TOTAL_CLP_DIFFERENCE_REVIEW")
    tolerance=("NOT_AVAILABLE" if a is None or b is None else
        "EXACT_MATCH" if a==b else
        "WITHIN_CLP_TOLERANCE" if abs(a-b)<=CLP_TOLERANCE else "OUTSIDE_CLP_TOLERANCE")
    raw_payment_date=str(payment["fec_crea_pago"]) if payment["fec_crea_pago"] is not None else ""
    if str(payment["mon_rec"])!=("2" if r["Moneda pago"]=="CLP" else "1"):
        total="CURRENCY_CODE_REVIEW"
        tolerance="CURRENCY_CODE_REVIEW"
    return dict(code=r["Código"],pair=r["Moneda origen"]+" → "+r["Moneda pago"],
        cohort=r["Cohorte"],cutoff=r["Estado al corte"],
        payment_date_pilot=r["Fecha pago"],payment_date_source=raw_payment_date,
        origin_key=ok,payment_key=pk,
        origin_amount_report=r["Importe origen"],payment_amount_report=r["Importe pago"],
        origin_amount_source=str(origin_amount),payment_amount_source=str(payment_amount),
        remesa_total_clp=str(a) if a is not None else "",pago_total_clp=str(b) if b is not None else "",
        pago_tipo_cambio=str(tc2) if tc2 is not None else "",
        remesa_tipo_cambio_clp=str(tc1) if tc1 is not None else "",
        calculated_total=str(calculated) if calculated is not None else "",
        diff_source_vs_payment=str(a-b) if a is not None and b is not None else "",
        diff_payment_vs_formula=str(b-calculated) if b is not None and calculated is not None else "",
        amount_identity=identity_check,
        rate_match="YES_NUMERIC_ONLY" if tc1 is not None and tc2 is not None and tc1==tc2 else "NO_OR_MISSING",
        formula_result=formula,total_result=total,tolerance_result=tolerance,
        origin_explain=oplan,payment_explain=pplan,certification="NOT_CERTIFIED")

def html_document(rows):
    data=json.dumps(rows,ensure_ascii=False).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    cols=json.dumps(FIELDS,ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Conciliación de equivalentes CLP</title>
<style>body{margin:0;background:#f1f5f9;color:#17324e;font:14px Segoe UI,Arial}
main{max-width:1500px;margin:auto;padding:22px}header{background:#173b5b;color:white;padding:23px;border-radius:12px}
aside{margin:16px 0;padding:15px;background:#fff5df;border:1px solid #d7b66f}
table{border-collapse:collapse;background:white;width:100%;font-size:12px;white-space:nowrap}
td,th{padding:9px;border-bottom:1px solid #d9e3ef;text-align:left}th{background:#e4eef8;position:sticky;top:0}
.wrap{overflow:auto;border-radius:10px}input,select{padding:10px;margin:12px 8px 12px 0}</style>
<body><main><header><small>REPORTE PRIVADO · LECTURA INDEXADA</small>
<h1>Conciliación de equivalentes CLP — 306 remesas</h1><p>Bolivia: remesa.total_clp · Chile: pago.total</p></header>
<aside><b>NO CERTIFICA ENTREGA NI LIQUIDACIÓN.</b> Los campos cotejados representan
totales registrados; no prueban que el efectivo haya sido entregado.
Los pagos después del cierre se mantienen identificados por separado.
Tolerancia operativa acordada: ±10 CLP, inclusive; coincidencia dentro de tolerancia
no demuestra entrega ni autoriza certificación. Los horarios entre sistemas no se normalizan en este informe.</aside>
<input id="q" placeholder="Buscar código"><select id="route"><option value="">Todas las rutas</option></select>
<select id="status"><option value="">Todos los resultados</option></select>
<p id="count"></p><div class="wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>const R=__ROWS__,C=__COLS__,a=document.querySelector('#route'),s=document.querySelector('#status');
for(let v of [...new Set(R.map(x=>x.pair))]){let o=document.createElement('option');o.value=v;o.textContent=v;a.append(o)}
for(let v of [...new Set(R.map(x=>x.total_result))]){let o=document.createElement('option');o.value=v;o.textContent=v;s.append(o)}
let h=document.createElement('tr');for(let [,v] of C){let t=document.createElement('th');t.textContent=v;h.append(t)}document.querySelector('#head').append(h);
function draw(){let q=document.querySelector('#q').value.toLowerCase(),r=a.value,t=s.value;
let subset=R.filter(x=>(!r||x.pair===r)&&(!t||x.total_result===t)&&(!q||x.code.includes(q)));
let b=document.querySelector('#body');b.replaceChildren();for(let row of subset){
let tr=document.createElement('tr');for(let [k] of C){let td=document.createElement('td');td.textContent=row[k]??'';tr.append(td)}b.append(tr)}
document.querySelector('#count').textContent=subset.length+' de '+R.length+' operaciones';}
document.querySelector('#q').oninput=draw;a.onchange=draw;s.onchange=draw;draw();
</script></main></body></html>""".replace("__ROWS__",data).replace("__COLS__",cols)

def run(input_csv,output):
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Isolated pilot required")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL and verified mapping must stay disabled")
    dst=validate_export_path(output);out_csv=dst.with_suffix(".csv")
    if out_csv.is_symlink():
        raise ValueError("Output CSV symlink blocked")
    cases=read_routes(input_csv)
    mapped=map_january(settings,cases)
    engines={"BOLIVIA":connect_source(settings,"BOLIVIA"),
             "CHILE":connect_source(settings,"CHILE")}
    rows=[]
    try:
        for offset in range(0,len(cases),20):
            for case in cases[offset:offset+20]:
                ok=identity(case,"remittance",mapped)
                pk=identity(case,"payment",mapped)
                original,oplan=source_record(engines["BOLIVIA"],"origin",ok,case["Código"])
                payment,pplan=source_record(engines["CHILE"],"payment",pk,case["Código"])
                rows.append(evidence(case,original,payment,ok,pk,oplan,pplan))
            print(f"batch_complete={min(offset+20,len(cases))}/{len(cases)}")
    finally:
        for engine in engines.values():
            engine.dispose()
    dst.write_text(html_document(rows),encoding="utf-8")
    with out_csv.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow([name for _,name in FIELDS])
        for item in rows:
            w.writerow([safe_csv_value(item.get(key,"")) for key,_ in FIELDS])
    print("source_read_only=True source_queries=612 indexed=True source_writes=False financially_certified=False")
    for field in ("total_result","tolerance_result","formula_result","amount_identity","rate_match","cutoff"):
        for k,n in sorted(Counter(r[field] for r in rows).items()):
            print(f"{field}={k} count={n}")
    print(f"files_created={dst.name},{out_csv.name} rows={len(rows)}")
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    run(a.input_csv,a.output)

if __name__=="__main__":
    main()
