"""Bounded read-only source evidence for 12 same-currency operations.

6 BOB->BOB Chile-origin and 6 USD->USD Bolivia-origin, chosen
deterministically from existing private CSV. Two indexed SELECTs per case.
A payment record is NOT proof of settlement, identity, or lack of reversal.
"""
import argparse
import csv
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text
from app.core.config import get_settings
from app.infrastructure.models import SourceRecord
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.pilot_monetary_targeted_2026 import identity_params, safe_plan
from scripts.pilot_operation_detail_2026 import safe_csv_value, validate_export_path

SQL = {
    ("CHILE", "remittance"): """SELECT id_operacion,codigo,id_destino,estado,
        envio,moneda,fec_crea_remesa,fec_mod_remesa
        FROM tmp_reporte_remesa FORCE INDEX (PRIMARY)
        WHERE id_operacion=:op AND codigo=:code AND id_destino=:dest LIMIT 2""",
    ("BOLIVIA", "remittance"): """SELECT id_remesa,id_operacion,codigo,estado,
        monto,mon_rec,fec_crea_remesa,fec_mod_remesa
        FROM remesa WHERE id_remesa=:pk AND id_operacion=:op AND codigo=:code LIMIT 2""",
    ("BOLIVIA", "payment"): """SELECT id_pago,id_operacion,codigo,monto,
        mon_rec,fec_crea_pago,id_forma_pago,id_tipo_pago
        FROM pago WHERE id_pago=:pk AND id_operacion=:op AND codigo=:code LIMIT 2""",
    ("CHILE", "payment"): """SELECT id_pago,id_operacion,codigo,monto,
        mon_rec,fec_crea_pago,id_forma_pago,id_tipo_pago
        FROM pago WHERE id_pago=:pk AND id_operacion=:op AND codigo=:code LIMIT 2""",
}
PAIRS = (("CL_TO_BO","BOB","CHILE","BOLIVIA"),
         ("BO_TO_CL","USD","BOLIVIA","CHILE"))
PER_PAIR=6
MAX_INPUT=3000
COLUMNS=(
    ("direction","Dirección"),("code","Código"),("currency","Moneda"),
    ("cutoff_status","Estado al corte"),("origin_key","Clave origen piloto"),
    ("payment_key","Clave pago piloto"),("origin_original_id","ID real remesa"),
    ("payment_original_id","ID real pago"),
    ("origin_amount_report","Importe origen reporte"),
    ("payment_amount_report","Importe pago reporte"),
    ("origin_amount_live","Importe origen fuente"),
    ("payment_amount_live","Importe pago fuente"),
    ("origin_status_raw","Estado origen (código fuente)"),
    ("origin_created_raw","Fecha creación remesa fuente"),
    ("origin_modified_raw","Fecha modificación remesa fuente"),
    ("payment_created_raw","Fecha creación pago fuente"),
    ("payment_method_raw","Forma pago fuente"),
    ("payment_type_raw","Tipo pago fuente"),
    ("origin_explain","EXPLAIN origen"),("payment_explain","EXPLAIN pago"),
    ("source_amount_result","Resultado contraste de importes"),
    ("payment_record_result","Registro de pago"),
    ("reversal_result","Verificación reversas"),
    ("settlement_result","Certificación financiera"),
)
def select_cases(rows):
    chosen=[]
    for direction,currency,source,paysource in PAIRS:
        cases=[r for r in rows if
            r["Dirección"]==direction and r["Moneda"]==currency
            and r["Certificación financiera"]=="NOT_CERTIFIED"
            and r["Diferencia nominal"] in ("0","0.000000")
            and r["Estado al corte"]=="PAID_BY_CUTOFF"]
        cases.sort(key=lambda r:(r["Código"],r["Clave origen"]))
        if len(cases)<PER_PAIR:
            raise RuntimeError("Insufficient same-currency cutoff cases: "+direction)
        chosen.extend(cases[:PER_PAIR])
    return chosen

def source_row(engine,source,kind,source_id,code):
    statement=SQL[(source,kind)]
    validate_read_query(statement)
    args=identity_params(source,kind,source_id,code)
    with read_only_transaction(engine) as con:
        explain=con.execute(text("EXPLAIN "+statement),args).mappings().all()
        plan=safe_plan(explain)
        matches=con.execute(text(statement),args).mappings().all()
    if len(matches)!=1 or str(matches[0]["codigo"])!=code:
        raise RuntimeError("Source identity missing/ambiguous or code changed")
    return dict(matches[0]),plan

def csv_rows(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Input must be a private regular CSV")
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        required={"Dirección","Código","Moneda","Clave origen","Clave pago",
            "Estado al corte","Diferencia nominal","Certificación financiera",
            "Importe envío","Importe pago"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("Expected private same-currency report headers")
        rows=list(reader)
    if len(rows)>MAX_INPUT:
        raise ValueError("Input exceeds bounded scope")
    return rows

def source_map(settings,ids):
    db=pilot_engine(settings)
    try:
        with db.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                matches=con.execute(select(SourceRecord.id,SourceRecord.source,
                    SourceRecord.dataset,SourceRecord.source_id,SourceRecord.code).where(
                    SourceRecord.id.in_(ids))).all()
            finally:
                con.rollback()
    finally:
        db.dispose()
    result={r.id:r for r in matches}
    if len(result)!=len(ids):
        raise RuntimeError("Missing pilot mapping, fail closed")
    return result

def html(rows):
    js=json.dumps(rows,ensure_ascii=False,default=str).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    cols=json.dumps(COLUMNS,ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Gambarte · Evidencia fuente de pagos, 12 operaciones</title>
<style>body{font-family:Segoe UI,Arial;background:#f3f6fa;color:#173052;margin:0}
main{max-width:1500px;margin:auto;padding:24px}header{background:#163552;color:white;padding:24px;border-radius:12px}
aside{margin:18px 0;padding:16px;background:#fff3df;border:1px solid #e4b96d;border-radius:9px}
.wrap{overflow:auto;background:white;border-radius:9px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:12px}
td,th{padding:10px;border-bottom:1px solid #dce3ed;text-align:left}th{background:#eaf0f8}
input{padding:10px;margin:14px 0;border:1px solid #b9c7d7;border-radius:8px}</style>
</head><body><main><header><small>CONTROL PRIVADO · SOLO LECTURA</small>
<h1>Diagnóstico de registros de pago — misma moneda</h1>
<p>6 CL→BO BOB/BOB + 6 BO→CL USD/USD · 24 consultas indexadas</p></header>
<aside><b>NO CERTIFICA LIQUIDACIÓN.</b> El registro de pago no prueba entrega,
beneficiario, reversa o ausencia de duplicación en tablas ajenas a esta consulta.
El estado de remesa es un código fuente actual, no reconstrucción histórica al corte.
No distribuir este informe.</aside>
<input id="q" placeholder="Buscar código o dirección"><p id="count"></p>
<div class="wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>
const R=__ROWS__,C=__COLS__;
let h=document.createElement('tr');for(let [,n] of C){let th=document.createElement('th');th.textContent=n;h.append(th)}
document.querySelector('#head').append(h);
function draw(){let q=document.querySelector('#q').value.toLowerCase(),list=R.filter(x=>x.code.includes(q)||x.direction.toLowerCase().includes(q));
let b=document.querySelector('#body');b.replaceChildren();
for(let x of list){let tr=document.createElement('tr');for(let [k] of C){let td=document.createElement('td');td.textContent=String(x[k]??'');tr.append(td)}b.append(tr)}
document.querySelector('#count').textContent=list.length+' casos';}
document.querySelector('#q').oninput=draw;draw();
</script></main></body></html>""".replace("__ROWS__",js).replace("__COLS__",cols)

def run(input_csv,output):
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Isolated pilot only")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL and mapping flags must stay off")
    destination=validate_export_path(output)
    csv_destination=destination.with_suffix(".csv")
    if csv_destination.is_symlink():
        raise ValueError("Output CSV symlink blocked")
    selected=select_cases(csv_rows(input_csv))
    wanted={int(r[k]) for r in selected for k in ("Clave origen","Clave pago")}
    mapping=source_map(settings,wanted)
    engines={}
    result=[]
    try:
        for item in selected:
            direction=item["Dirección"]
            origin="CHILE" if direction=="CL_TO_BO" else "BOLIVIA"
            payment="BOLIVIA" if direction=="CL_TO_BO" else "CHILE"
            rem=mapping[int(item["Clave origen"])]
            pay=mapping[int(item["Clave pago"])]
            if (rem.source,rem.dataset,rem.code)!=(origin,"remittance",item["Código"]):
                raise RuntimeError("Pilot origin identity mismatch")
            if (pay.source,pay.dataset,pay.code)!=(payment,"payment",item["Código"]):
                raise RuntimeError("Pilot payment identity mismatch")
            for system in (origin,payment):
                if system not in engines:
                    engines[system]=connect_source(settings,system)
            a,aplan=source_row(engines[origin],origin,"remittance",rem.source_id,item["Código"])
            b,bplan=source_row(engines[payment],payment,"payment",pay.source_id,item["Código"])
            amount_field="envio" if origin=="CHILE" else "monto"
            x=Decimal(str(a[amount_field]))
            y=Decimal(str(b["monto"]))
            compare=("SOURCE_AMOUNTS_MATCH_EXPORTED" if x==Decimal(item["Importe envío"])
                and y==Decimal(item["Importe pago"]) else "SOURCE_AMOUNT_CHANGED_REVIEW")
            result.append(dict(direction=direction,code=item["Código"],currency=item["Moneda"],
                cutoff_status=item["Estado al corte"],origin_key=item["Clave origen"],
                payment_key=item["Clave pago"],origin_original_id=rem.source_id,
                payment_original_id=pay.source_id,origin_amount_report=item["Importe envío"],
                payment_amount_report=item["Importe pago"],origin_amount_live=str(x),
                payment_amount_live=str(y),origin_status_raw=str(a["estado"]),
                origin_created_raw=str(a["fec_crea_remesa"]),
                origin_modified_raw=str(a["fec_mod_remesa"]),
                payment_created_raw=str(b["fec_crea_pago"]),
                payment_method_raw=str(b["id_forma_pago"]),
                payment_type_raw=str(b["id_tipo_pago"]),origin_explain=aplan,
                payment_explain=bplan,source_amount_result=compare,
                payment_record_result="EXACT_SOURCE_RECORD_FOUND",
                reversal_result="NOT_VERIFIED",settlement_result="NOT_CERTIFIED"))
    finally:
        for engine in engines.values():
            engine.dispose()
    destination.write_text(html(result),encoding="utf-8")
    with csv_destination.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f)
        writer.writerow([label for _,label in COLUMNS])
        for r in result:
            writer.writerow([safe_csv_value(r.get(key,"")) for key,_ in COLUMNS])
    print("source_read_only=True pilot_read_only=True production_writes=False reversal_verified=False financially_certified=False")
    print(f"cases={len(result)} source_queries={2*len(result)}")
    for key,count in sorted(Counter(r["source_amount_result"] for r in result).items()):
        print(f"comparison={key} count={count}")
    print(f"files_created={destination.name},{csv_destination.name} private=True")
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    run(a.input_csv,a.output)

if __name__=="__main__":
    main()
