"""Read-only, index-guarded search for additional Bolivia payment records.

Scope: six sampled Chile -> Bolivia BOB -> BOB payments previously verified
by original payment ID. No Chile codigo scans: Chile pago lacks that index.
No reversal, final settlement, or global uniqueness certification.
"""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from decimal import Decimal

from sqlalchemy import text

from app.core.config import get_settings
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_import import PILOT_DB, PILOT_HOST, connect_source
from scripts.pilot_monetary_targeted_2026 import safe_plan
from scripts.pilot_operation_detail_2026 import safe_csv_value, validate_export_path

INDEX = "wdbi_codigo_id_operacion_9fed4c1e2655"
QUERY = """SELECT id_pago,id_operacion,codigo,monto,fec_crea_pago,id_tipo_pago
FROM pago FORCE INDEX (wdbi_codigo_id_operacion_9fed4c1e2655)
WHERE codigo=:code AND id_operacion=:op LIMIT 6"""
CAP=6
OUTPUT_FIELDS=(
    ("code","Código"),("payment_original_id","Pago original"),
    ("expected_amount","Monto esperado"),("matched_payments","Pagos hallados (mismo código/tipo)"),
    ("other_payment_ids","Otros IDs pago"),("explain","EXPLAIN"),
    ("status","Resultado"),("scope","Alcance"),
)

def read_input(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Original payment diagnostic CSV required")
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        required={"Dirección","Código","Moneda","ID real pago","Importe pago fuente",
            "Registro de pago","Resultado contraste de importes"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("Unexpected payment diagnostic headers")
        rows=list(reader)
    if len(rows)!=12:
        raise ValueError("Expected exactly 12 diagnostic rows")
    selected=[r for r in rows if r["Dirección"]=="CL_TO_BO" and r["Moneda"]=="BOB"]
    if len(selected)!=CAP:
        raise ValueError("Expected six Chile to Bolivia BOB records")
    ids=[]
    codes=[]
    for r in selected:
        parts=r["ID real pago"].split(":")
        if (len(parts)!=2 or not all(p.isdecimal() and int(p)>0 for p in parts)
            or int(parts[0]) not in (4,7)
            or not r["Código"].isdecimal()
            or r["Registro de pago"]!="EXACT_SOURCE_RECORD_FOUND"
            or r["Resultado contraste de importes"]!="SOURCE_AMOUNTS_MATCH_EXPORTED"):
            raise ValueError("Unverified/malformed Bolivia payment reference")
        Decimal(r["Importe pago fuente"])
        ids.append(r["ID real pago"])
        codes.append(r["Código"])
    if len(set(ids))!=CAP or len(set(codes))!=CAP:
        raise ValueError("Sample identities must be distinct")
    return sorted(selected,key=lambda r:int(r["Código"]))

def classify(records,expected_id,expected_amount):
    if not any(int(r["id_pago"])==expected_id for r in records):
        return "EXPECTED_PAYMENT_ABSENT_REVIEW", []
    other=[str(r["id_pago"]) for r in records if int(r["id_pago"])!=expected_id]
    if len(records)>=CAP:
        return "BOUNDED_RESULT_LIMIT_REVIEW",other
    if other:
        return "ADDITIONAL_PAYMENT_ROWS_REVIEW",other
    expected=next(r for r in records if int(r["id_pago"])==expected_id)
    if Decimal(str(expected["monto"]))!=expected_amount:
        return "EXPECTED_PAYMENT_AMOUNT_CHANGED_REVIEW",[]
    return "ONE_PAYMENT_ROW_IN_INDEXED_CODE_TYPE_SCOPE",[]

def html(rows):
    data=json.dumps(rows,ensure_ascii=False).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    cols=json.dumps(OUTPUT_FIELDS,ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Gambarte · Pagos adicionales por código, Bolivia</title>
<style>body{font:14px Segoe UI,Arial;background:#f3f6fa;color:#17314a;margin:0}
main{max-width:1400px;margin:auto;padding:22px}header{background:#183a5b;color:white;border-radius:12px;padding:22px}
aside{padding:14px;margin:16px 0;background:#fff4de;border:1px solid #ddac61}
table{border-collapse:collapse;width:100%;background:white;font-size:12px}th,td{padding:10px;text-align:left;border-bottom:1px solid #d9e3ee}th{background:#e6edf7}
.wrap{overflow:auto}</style><body><main><header><small>CONTROL PRIVADO / SOLO LECTURA</small>
<h1>Posibles pagos adicionales — Bolivia</h1><p>6 códigos Chile → Bolivia, misma moneda BOB</p></header>
<aside><b>NO CERTIFICA AUSENCIA DE PAGOS DUPLICADOS NI REVERSAS.</b>
Se buscan pagos por código y tipo de operación en Bolivia exclusivamente.
No incluye otros tipos, operaciones históricas no conservadas, ni Chile.</aside>
<div class="wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>const R=__DATA__,C=__COLS__;
let h=document.createElement('tr');for(let [,v] of C){let x=document.createElement('th');x.textContent=v;h.append(x)}document.querySelector('#head').append(h);
for(let r of R){let tr=document.createElement('tr');for(let [k] of C){let x=document.createElement('td');x.textContent=String(r[k]??'');tr.append(x)}document.querySelector('#body').append(tr)}
</script></main></body></html>""".replace("__DATA__",data).replace("__COLS__",cols)

def run(input_csv,output):
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Pilot environment required")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL must remain disabled")
    destination=validate_export_path(output)
    output_csv=destination.with_suffix(".csv")
    if output_csv.is_symlink():
        raise ValueError("Output CSV symlink blocked")
    validate_read_query(QUERY)
    samples=read_input(input_csv)
    engine=connect_source(settings,"BOLIVIA")
    rows=[]
    try:
        for sample in samples:
            op,expected_id=map(int,sample["ID real pago"].split(":"))
            params={"op":op,"code":int(sample["Código"])}
            with read_only_transaction(engine) as connection:
                plan=safe_plan(connection.execute(text("EXPLAIN "+QUERY),params).mappings().all())
                records=connection.execute(text(QUERY),params).mappings().all()
            status,other=classify(records,expected_id,Decimal(sample["Importe pago fuente"]))
            rows.append(dict(code=sample["Código"],payment_original_id=sample["ID real pago"],
                expected_amount=sample["Importe pago fuente"],
                matched_payments=str(len(records)),other_payment_ids=",".join(other),
                explain=plan,status=status,
                scope="BOLIVIA.pago codigo + id_operacion; hasta 6 filas"))
    finally:
        engine.dispose()
    destination.write_text(html(rows),encoding="utf-8")
    with output_csv.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f);writer.writerow([label for _,label in OUTPUT_FIELDS])
        for row in rows:
            writer.writerow([safe_csv_value(row.get(key,"")) for key,_ in OUTPUT_FIELDS])
    print("source_read_only=True source=Bolivia indexed_only=True chile_scans=False certified=False")
    print(f"cases={len(rows)} source_queries={len(rows)}")
    for k,v in sorted(Counter(r["status"] for r in rows).items()):
        print(f"result={k} count={v}")
    print(f"files_created={destination.name},{output_csv.name}")
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    run(args.input_csv,args.output)

if __name__=="__main__":
    main()
