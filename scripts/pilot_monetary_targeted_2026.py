"""Bounded 12-operation financial field diagnostic, source READ ONLY.

Sampling is deterministic and stratified by currency pair. Reads at most 12
paired remittance/payment records with SQL parameters and indexed EXPLAIN.
Writes only a private HTML/CSV; does not import or certify accounting data.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

from app.core.config import get_settings
from app.infrastructure.models import SourceRecord
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.pilot_operation_detail_2026 import safe_csv_value, validate_export_path

PAIRS = (("BOB","CLP"),("BOB","USD"),("USD","CLP"))
CAP_PER_PAIR = 4
SQL = {
    ("BOLIVIA","remittance"): """SELECT id_remesa, id_operacion, codigo, monto,
      mon_rec, cambio, tipo_cambio, tipo_cambio_clp, total_cambio,
      comision, comision_bob, comision_gambarte, comision_gambarte_bob
      FROM remesa WHERE id_remesa=:pk AND id_operacion=:op
      AND codigo=:code LIMIT 2""",
    ("CHILE","remittance"): """SELECT id_remesa, id_operacion, codigo, id_destino,
      envio, moneda, monto_clp, tipo_cambio, comision, comision_bob
      FROM tmp_reporte_remesa FORCE INDEX (PRIMARY)
      WHERE id_operacion=:op AND codigo=:code AND id_destino=:dest LIMIT 2""",
    ("BOLIVIA","payment"): """SELECT id_pago, id_operacion, codigo, monto, mon_rec,
      tipo_cambio, comision_bob, id_forma_pago, id_tipo_pago
      FROM pago WHERE id_pago=:pk AND id_operacion=:op AND codigo=:code LIMIT 2""",
    ("CHILE","payment"): """SELECT id_pago, id_operacion, codigo, monto, mon_rec,
      tipo_cambio, id_forma_pago, id_tipo_pago
      FROM pago WHERE id_pago=:pk AND id_operacion=:op AND codigo=:code LIMIT 2""",
}
DETAIL_FIELDS = ("monto","mon_rec","envio","moneda","monto_clp","tipo_cambio",
                 "tipo_cambio_clp","total_cambio","cambio","comision",
                 "comision_bob","comision_gambarte","comision_gambarte_bob",
                 "id_forma_pago","id_tipo_pago")
COLUMNS = (
    ("direction","Dirección"),("cohort","Cohorte"),("code","Código"),
    ("origin_source","Sistema remesa"),("payment_source","Sistema pago"),
    ("origin_key","Clave remesa"),("payment_key","Clave pago"),
    ("origin_currency","Moneda remesa normalizada"),
    ("payment_currency","Moneda pago normalizada"),
    ("origin_amount","Importe remesa del reporte"),
    ("payment_amount","Importe pago del reporte"),
    ("origin_source_monto","Origen monto"),("origin_source_mon_rec","Origen mon_rec"),
    ("origin_source_envio","Origen envio"),("origin_source_moneda","Origen moneda"),
    ("origin_source_monto_clp","Origen monto_clp"),
    ("origin_source_tipo_cambio","Origen tipo_cambio"),
    ("origin_source_tipo_cambio_clp","Origen tipo_cambio_clp"),
    ("origin_source_total_cambio","Origen total_cambio"),
    ("origin_source_cambio","Origen cambio"),("origin_source_comision","Origen comision"),
    ("origin_source_comision_bob","Origen comision_bob"),
    ("payment_source_monto","Pago monto"),("payment_source_mon_rec","Pago mon_rec"),
    ("payment_source_tipo_cambio","Pago tipo_cambio"),
    ("payment_source_comision_bob","Pago comision_bob"),
    ("payment_source_id_forma_pago","Pago id_forma_pago"),
    ("payment_source_id_tipo_pago","Pago id_tipo_pago"),
    ("origin_explain","EXPLAIN remesa"),("payment_explain","EXPLAIN pago"),
    ("evidence_flag","Estado evidencia"),("review","Interpretación pendiente"),
)


def select_cases(rows):
    """Four cases per mismatch, reserving one December case when available."""
    groups=defaultdict(list)
    for row in rows:
        pair=(row["Moneda origen"],row["Moneda pago"])
        if pair not in PAIRS or row["Clasificación monetaria"]!="FX_SEMANTICS_UNVERIFIED":
            continue
        if row["Dirección"]!="BO_TO_CL":
            raise ValueError("Unexpected currency-mismatch direction")
        if not row["Clave origen"] or not row["Clave pago"]:
            raise ValueError("Incomplete source linkage for diagnostic")
        groups[pair].append(row)
    selected=[]
    for pair in PAIRS:
        cases=groups[pair]
        if len(cases)<CAP_PER_PAIR:
            raise RuntimeError("Insufficient candidates for "+"/".join(pair))
        dec=sorted((r for r in cases if r["Cohorte"]=="DECEMBER_ORIGIN_JANUARY_PAYMENT"),
                   key=lambda r:r["Código"])
        jan=sorted((r for r in cases if r["Cohorte"]=="JANUARY_ORIGIN"),
                   key=lambda r:r["Código"])
        chosen=(dec[:1]+jan[:CAP_PER_PAIR-1] if dec
                else jan[:CAP_PER_PAIR])
        if len(chosen)!=CAP_PER_PAIR:
            raise RuntimeError("Insufficient stratified cases")
        selected.extend(chosen)
    if len(selected)!=12:
        raise RuntimeError("Expected precisely 12 cases")
    return selected


def original_key(row,kind,pilot_map):
    """Resolve pilot SourceRecord ID or already explicit December source key."""
    source=row["Sistema remesa"] if kind=="remittance" else row["Sistema pago"]
    identifier=row["Clave origen"] if kind=="remittance" else row["Clave pago"]
    if row["Cohorte"]=="JANUARY_ORIGIN" or kind=="payment" and row["Cohorte"]=="JANUARY_ORIGIN":
        try:
            record=pilot_map[int(identifier)]
        except (KeyError,ValueError) as exc:
            raise RuntimeError("Pilot SourceRecord missing") from exc
        if record.source!=source or record.dataset!=kind or record.code!=row["Código"]:
            raise RuntimeError("Pilot identity does not match requested operation")
        return record.source_id
    # December cohort original source keys are embedded in the private cutoff CSV.
    return identifier


def identity_params(source,kind,key,code):
    parts=key.split(":")
    if len(parts)!=(3 if source=="CHILE" and kind=="remittance" else 2):
        raise ValueError("Unexpected original source key shape")
    try:
        op=int(parts[0])
        if source=="CHILE" and kind=="remittance":
            if int(parts[1])!=int(code):
                raise ValueError("Chile source code identity mismatch")
            return dict(op=op,code=code,dest=int(parts[2]))
        pk=int(parts[1])
    except (TypeError,ValueError) as exc:
        raise ValueError("Invalid source key") from exc
    if pk<=0 or op<=0:
        raise ValueError("Invalid source identifier")
    return dict(op=op,code=code,pk=pk)


def safe_plan(plan):
    if len(plan)!=1:
        raise RuntimeError("Targeted EXPLAIN must have one plan")
    item=plan[0]
    access=str(item.get("type") or "")
    key=item.get("key")
    estimate=int(item.get("rows") or 0)
    if access in ("ALL","index") or not key or estimate>5000:
        raise RuntimeError("Unindexed or high-cost targeted operation query")
    return f"{access}/{key}/{estimate}"


def source_details(engine,source,kind,key,code):
    sql=SQL[(source,kind)]
    validate_read_query(sql)
    params=identity_params(source,kind,key,code)
    with read_only_transaction(engine) as con:
        plans=con.execute(text("EXPLAIN "+sql),params).mappings().all()
        plan=safe_plan(plans)
        records=con.execute(text(sql),params).mappings().all()
    if len(records)!=1:
        raise RuntimeError("Source operation not unique or absent; manual review required")
    record=dict(records[0])
    if str(record["codigo"])!=str(code):
        raise RuntimeError("Code changed between pilot and source")
    return record,plan


def output_row(row,origin,payment,oplan,pplan):
    result=dict(
        direction=row["Dirección"],cohort=row["Cohorte"],code=row["Código"],
        origin_source=row["Sistema remesa"],payment_source=row["Sistema pago"],
        origin_key=row["Clave origen"],payment_key=row["Clave pago"],
        origin_currency=row["Moneda origen"],payment_currency=row["Moneda pago"],
        origin_amount=row["Importe origen"],payment_amount=row["Importe pago"],
        origin_explain=oplan,payment_explain=pplan,
    )
    for field in DETAIL_FIELDS:
        if field in origin:
            result["origin_source_"+field]=str(origin[field]) if origin[field] is not None else ""
        if field in payment:
            result["payment_source_"+field]=str(payment[field]) if payment[field] is not None else ""
    # Check normalized report amounts against the exact source fields used in ingestion.
    source_field="monto" if row["Sistema remesa"]=="BOLIVIA" else "envio"
    changed=(Decimal(str(origin[source_field]))!=Decimal(row["Importe origen"])
             or Decimal(str(payment["monto"]))!=Decimal(row["Importe pago"]))
    result["evidence_flag"]="SOURCE_AMOUNT_CHANGED_REVIEW" if changed else "SOURCE_AMOUNTS_MATCH_PILOT"
    result["review"]="No inferir FX o saldos: confirmar rol de campos, moneda, comisiones y pago liquidado"
    return result


def html_document(rows):
    payload=json.dumps(rows,ensure_ascii=False,default=str).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    columns=json.dumps(COLUMNS,ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Diagnóstico monetario dirigido</title>
<style>
:root{font-family:Segoe UI,Arial,sans-serif;background:#f2f5f9;color:#18304d}
body{margin:0}main{max-width:1500px;margin:auto;padding:24px}
header{background:#102e50;color:white;border-radius:12px;padding:24px}
h1{font-size:26px;margin:6px 0}.notice{background:#fff7e7;border:1px solid #d4a75c;padding:15px;border-radius:9px;margin:18px 0}
.wrap{overflow:auto;border:1px solid #dee5ee;background:white;border-radius:12px}
table{border-collapse:collapse;white-space:nowrap;font-size:12px;width:100%}
td,th{padding:10px;border-bottom:1px solid #e3e9f0;text-align:left}
th{background:#e8eff7;position:sticky;top:0}
select,input{padding:10px;border:1px solid #bbc9d8;border-radius:8px;margin:14px 8px 14px 0}
</style></head><body><main>
<header><small>GAMBARTE · CONTROL PRIVADO</small>
<h1>Diagnóstico de campos monetarios — 12 operaciones</h1>
<p>Evidencia de solo lectura de Bolivia y Chile; no certifica liquidaciones.</p></header>
<div class="notice"><strong>NO ES CONCILIACIÓN FINANCIERA.</strong> Las columnas son datos originales
y sus nombres técnicos, no se ha confirmado su significado ni equivalencia. No inferir tasas
FX, comisiones efectivas ni saldos. No distribuir este archivo.</div>
<input id="search" placeholder="Buscar código..." aria-label="Buscar código">
<select id="pair"><option value="">Todas las monedas</option></select>
<p id="count"></p><div class="wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>
const ROWS=__ROWS__,COLS=__COLS__,pair=document.querySelector('#pair');
for(const value of [...new Set(ROWS.map(r=>r.origin_currency+' → '+r.payment_currency))]){
const option=document.createElement('option');option.value=value;option.textContent=value;pair.append(option)}
let header=document.createElement('tr');for(const [,label] of COLS){const th=document.createElement('th');th.textContent=label;header.append(th)}document.querySelector('#head').append(header);
function render(){const q=document.querySelector('#search').value.trim().toLowerCase();
const filtered=ROWS.filter(r=>(!pair.value||r.origin_currency+' → '+r.payment_currency===pair.value)&&(!q||r.code.toLowerCase().includes(q)));
const body=document.querySelector('#body');body.replaceChildren();
for(const row of filtered){const tr=document.createElement('tr');for(const [key] of COLS){const td=document.createElement('td');td.textContent=String(row[key]??'');tr.append(td)}body.append(tr)}
document.querySelector('#count').textContent=filtered.length+' operaciones';}
document.querySelector('#search').addEventListener('input',render);
pair.addEventListener('input',render);render();
</script></main></body></html>""".replace("__ROWS__",payload).replace("__COLS__",columns)


def run(input_csv,output):
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Requires isolated pilot")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL/mapping must remain disabled")
    dest=validate_export_path(output)
    csv_dest=dest.with_suffix(".csv")
    if csv_dest.is_symlink():
        raise ValueError("Output CSV is symlink")
    with Path(input_csv).open("r",encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream)
        expected={title for _,title in (
            ("direction","Dirección"),("cohort","Cohorte"),
            ("code","Código"),("origin_source","País origen"),
            ("payment_source","País pago"),
            ("origin_currency","Moneda origen"),("payment_currency","Moneda pago"),
            ("origin_amount","Importe origen"),("payment_amount","Importe pago"),
            ("money_flag","Clasificación monetaria"),
            ("origin_key","Clave origen"),("payment_key","Clave pago"))}
        if not expected.issubset(reader.fieldnames or ()):
            raise ValueError("Expected private monetary-evidence CSV")
        rows=list(reader)
    if len(rows)>15000:
        raise ValueError("Excessive input row count")
    chosen=select_cases(rows)
    # Keep mapping bounded by exact identifiers needed for January cohort.
    wanted=set()
    for row in chosen:
        if row["Cohorte"]=="JANUARY_ORIGIN":
            wanted.add(int(row["Clave origen"]))
            wanted.add(int(row["Clave pago"]))
    db=pilot_engine(settings)
    try:
        with db.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                found=con.execute(select(SourceRecord.id,SourceRecord.source,
                  SourceRecord.dataset,SourceRecord.source_id,SourceRecord.code).where(
                  SourceRecord.id.in_(wanted))).all()
            finally:
                con.rollback()
    finally:
        db.dispose()
    mapped={r.id:r for r in found}
    if len(mapped)!=len(wanted):
        raise RuntimeError("Pilot identity metadata incomplete")
    engines={}
    try:
        results=[]
        for row in chosen:
            source=row["País origen"]
            destination=row["País pago"]
            if source not in ("BOLIVIA","CHILE") or destination not in ("BOLIVIA","CHILE") or source==destination:
                raise ValueError("Invalid cross-border direction")
            adapted=dict(row)
            adapted.update({"Sistema remesa":source,"Sistema pago":destination,
                "Clave origen":row["Clave origen"],"Clave pago":row["Clave pago"]})
            origin_key=original_key(adapted,"remittance",mapped)
            payment_key=original_key(adapted,"payment",mapped)
            for name in (source,destination):
                if name not in engines:
                    engines[name]=connect_source(settings,name)
            rem,rem_plan=source_details(engines[source],source,"remittance",origin_key,row["Código"])
            pay,pay_plan=source_details(engines[destination],destination,"payment",payment_key,row["Código"])
            results.append(output_row(adapted,rem,pay,rem_plan,pay_plan))
    finally:
        for engine in engines.values():
            engine.dispose()
    dest.write_text(html_document(results),encoding="utf-8")
    with csv_dest.open("w",encoding="utf-8-sig",newline="") as file:
        writer=csv.writer(file)
        writer.writerow([title for _,title in COLUMNS])
        for item in results:
            writer.writerow([safe_csv_value(item.get(name,"")) for name,_ in COLUMNS])
    summary=Counter((r["origin_currency"],r["payment_currency"]) for r in results)
    flags=Counter(r["evidence_flag"] for r in results)
    print("targeted_monetary_review=True source_read_only=True pilot_read_only=True "
          "imports=False financially_certified=False queries_per_source_record=1")
    print(f"records={len(results)} source_queries={len(results)*2}")
    for pair,n in sorted(summary.items()):
        print(f"pair={pair[0]}_TO_{pair[1]} samples={n}")
    for key,n in sorted(flags.items()):
        print(f"evidence={key} count={n}")
    print(f"files_created={dest.name},{csv_dest.name} private_export=True")
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    run(args.input_csv,args.output)


if __name__=="__main__":
    main()
