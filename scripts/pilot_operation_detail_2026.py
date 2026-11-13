"""Private, read-only transaction detail from isolated pilot for 2026.

Exports searchable HTML and Excel-compatible UTF-8 CSV. All matches are
provisional; missing pilot payments are not proven missing at destination.
No live source access, no certification, no source mutations.
"""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from html import escape
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

from app.core.config import get_settings
from app.domain.operation_types import allowed_destination_payment_types
from app.infrastructure.models import Remittance, Payment
from scripts.management_report_2026 import EXPORT_DIR, validate_export_path
from scripts.pilot_reconcile import DIRECTIONS, classify
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker

COLUMNS = (
    ("direction", "Dirección"), ("category", "Clasificación"),
    ("reason", "Motivo / revisión"), ("code", "Código"),
    ("origin_id", "ID piloto origen"), ("origin_type", "Tipo operación origen"),
    ("origin_date", "Fecha envío"), ("origin_status", "Estado envío"),
    ("origin_amount", "Importe envío"), ("origin_currency", "Moneda envío"),
    ("destination_id", "ID piloto pago"), ("destination_type", "Tipo pago destino"),
    ("destination_date", "Fecha pago"), ("destination_amount", "Importe pago"),
    ("destination_currency", "Moneda pago"), ("difference", "Diferencia (misma moneda)"),
    ("payment_candidates", "Candidatos de pago"), ("unexpected_payment_types", "Tipos pago inesperados"),
)
REASONS = {
    "PROVISIONAL_CODE_PAIR": "Código y tipo compatibles; verificar titularidad, moneda, importe y liquidación",
    "NO_PAYMENT_IN_SAMPLE": "Pago no identificado en datos disponibles; revisar origen, fechas y cobertura",
    "CLOSED_IN_SAMPLE": "Operación anulada o devuelta; revisar reversas y pagos",
    "PENDING_IN_SAMPLE": "Estado no pagado en origen; revisar su evolución",
    "INSUFFICIENT_DATA": "Estado o metadatos insuficientes para emparejar",
    "INSUFFICIENT_UNVERIFIED_PAYMENT_MAPPING": "No se verificó la modalidad origen-destino",
    "MANUAL_REVIEW_AMBIGUOUS_CODE": "Código duplicado en remesas o múltiples pagos candidatos",
    "MANUAL_REVIEW_UNEXPECTED_PAYMENT_TYPE": "Existe un pago con tipo no esperado para esta modalidad",
    "MANUAL_REVIEW_CLOSED_WITH_PAYMENT": "Anulada/devuelta pero tiene pago registrado",
    "MANUAL_REVIEW_STATUS_WITH_PAYMENT": "Estado del origen incompatible con pago",
}


def date_value(value):
    return value.isoformat(sep=" ") if value else ""


def amount_value(value):
    return str(value) if value is not None else ""


def detail_rows(remittances, payments, through):
    if through.year != 2026:
        raise ValueError("Only 2026 supported")
    end = date(2026, through.month, through.day)
    def in_scope(r):
        return r.occurred_at is not None and date(2026, 1, 1) <= r.occurred_at.date() <= end
    origins = [r for r in remittances if in_scope(r)]
    # A payment from another month can be a candidate for a January remittance.
    # This remains limited to payments currently present in the isolated pilot.
    available_payments = list(payments)
    output = []
    for direction, origin, destination, origin_types in DIRECTIONS:
        rems = [r for r in origins if r.source == origin and r.operation_type in origin_types]
        origin_by_code = defaultdict(list)
        payment_by_code = defaultdict(list)
        for r in rems:
            origin_by_code[r.code].append(r)
        for p in available_payments:
            if p.source == destination:
                payment_by_code[p.code].append(p)
        for r in rems:
            candidates_all = payment_by_code[r.code]
            allowed = allowed_destination_payment_types(origin, destination, r.operation_type)
            candidates = [p for p in candidates_all if allowed is not None and p.operation_type in allowed]
            unexpected = [p for p in candidates_all if allowed is not None and p.operation_type not in allowed]
            complete = (r.amount is not None and bool(r.currency) and
                        all(p.amount is not None and bool(p.currency) for p in candidates))
            if allowed is None:
                category = "INSUFFICIENT_UNVERIFIED_PAYMENT_MAPPING"
            elif unexpected:
                category = "MANUAL_REVIEW_UNEXPECTED_PAYMENT_TYPE"
            else:
                category = classify(r.status, len(origin_by_code[r.code]), candidates, complete)
            # Never silently assign a particular payment in ambiguous cases.
            p = candidates[0] if category == "PROVISIONAL_CODE_PAIR" and len(candidates) == 1 else None
            difference = ""
            if (p and r.currency == p.currency and r.amount is not None
                    and p.amount is not None):
                difference = str(Decimal(r.amount) - Decimal(p.amount))
            reason = REASONS.get(category, "Revisión manual")
            if p and r.currency != p.currency:
                reason += "; monedas distintas: no calcular diferencia sin FX acordado"
            elif p and difference and Decimal(difference) != 0:
                reason += "; importes distintos aun en igual moneda: revisar contrato"
            output.append({
                "direction": direction, "category": category, "reason": reason,
                "code": r.code, "origin_id": r.source_record_id,
                "origin_type": r.operation_type, "origin_date": date_value(r.occurred_at),
                "origin_status": r.status, "origin_amount": amount_value(r.amount),
                "origin_currency": r.currency or "",
                "destination_id": p.source_record_id if p else "",
                "destination_type": p.operation_type if p else "",
                "destination_date": date_value(p.occurred_at) if p else "",
                "destination_amount": amount_value(p.amount) if p else "",
                "destination_currency": p.currency or "" if p else "",
                "difference": difference, "payment_candidates": len(candidates),
                "unexpected_payment_types": ",".join(sorted({str(x.operation_type) for x in unexpected})),
            })
    output.sort(key=lambda row: (row["direction"], str(row["code"]), str(row["origin_id"])))
    return output


def safe_csv_value(value):
    value = str(value if value is not None else "")
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export_csv(destination, rows):
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([label for _, label in COLUMNS])
        for row in rows:
            writer.writerow([safe_csv_value(row.get(key, "")) for key, _ in COLUMNS])


def html_report(rows, through):
    counts = Counter(r["category"] for r in rows)
    directions = Counter(r["direction"] for r in rows)
    payload = json.dumps(rows, ensure_ascii=False, default=str).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    # Values are inserted using textContent, never as untrusted HTML.
    return """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Detalle operativo 2026</title>
<style>
:root{font-family:Inter,Segoe UI,Arial,sans-serif;color:#1b2d45;background:#f2f5f9}
*{box-sizing:border-box}body{margin:0}main{max-width:1550px;margin:auto;padding:24px}
header{background:#112a47;color:#fff;padding:28px;border-radius:16px}
header h1{margin:6px 0 10px;font-size:28px}header p{margin:0;opacity:.87}
.notice{padding:14px 17px;border:1px solid #e5bd79;background:#fff8eb;border-radius:9px;margin:18px 0;line-height:1.5}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:18px 0}
.kpi{background:#fff;padding:17px;border:1px solid #dbe2eb;border-radius:11px}
.kpi b{display:block;font-size:27px;margin-top:4px}.kpi span{font-size:12px;color:#56677d}
.controls{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin:16px 0}
input,select,button{border:1px solid #c7d2df;border-radius:8px;background:#fff;color:#1b2d45;padding:10px;font:inherit}
input{min-width:240px;flex:1}button{cursor:pointer;background:#15365a;color:#fff;border:0}
.table-wrap{overflow:auto;background:#fff;border:1px solid #dbe2eb;border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}
td,th{padding:10px 12px;border-bottom:1px solid #e9edf3;text-align:left}
th{background:#eaf0f6;position:sticky;top:0;z-index:1}
tr:hover{background:#f5f9fd}
footer{padding:15px;color:#5f7084;font-size:12px}
@media(max-width:750px){.kpis{grid-template-columns:repeat(2,1fr)}main{padding:9px}}
</style></head><body><main>
<header><small>GAMBARTE · CONTROL OPERATIVO PRIVADO</small><h1>Detalle de conciliación por operación</h1>
<p>Desde 01/01/2026 hasta __DATE__ · Lectura exclusiva del piloto aislado</p></header>
<div class="notice"><strong>PRELIMINAR — NO CERTIFICADO.</strong> Pareo por código y tipo esperado, sin validación de titularidad, equivalencia cambiaria, liquidación ni cobertura histórica completa. «Sin pago» significa no identificado en los registros disponibles, no ausencia confirmada. Los IDs son referencias internas del piloto.</div>
<section class="kpis"><div class="kpi"><span>Remesas incluidas</span><b id="total">—</b></div>
<div class="kpi"><span>Pares provisionales</span><b id="paired">—</b></div>
<div class="kpi"><span>Sin pago en registros</span><b id="missing">—</b></div>
<div class="kpi"><span>Anuladas / devueltas</span><b id="closed">—</b></div></section>
<div class="controls"><input id="search" placeholder="Buscar código, motivo o tipo..." aria-label="Buscar">
<select id="direction"><option value="">Todas las direcciones</option><option value="BO_TO_CL">Bolivia → Chile</option><option value="CL_TO_BO">Chile → Bolivia</option></select>
<select id="category"><option value="">Todas las clasificaciones</option></select>
<button id="download" type="button">Exportar filtrado a CSV (Excel)</button></div>
<p id="stats" aria-live="polite"></p><div class="table-wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<div class="controls"><button id="prev" type="button">Anterior</button><span id="page"></span><button id="next" type="button">Siguiente</button></div>
<footer>Archivo privado con códigos e importes: no enviar por correo ni subir a repositorios. Diferencias solo para monedas idénticas y pares unívocos; no equivalen a diferencias contables.</footer></main>
<script>
const DATA=__DATA__;
const COLS=__COLS__;
const search=document.querySelector('#search'),direction=document.querySelector('#direction'),category=document.querySelector('#category');
let current=0;const size=100;
const n=new Intl.NumberFormat('es-BO');
const cats=[...new Set(DATA.map(r=>r.category))].sort();
for(const c of cats){const o=document.createElement('option');o.value=c;o.textContent=c;category.append(o)}
function td(parent,tag,value){const el=document.createElement(tag);el.textContent=String(value??'');parent.append(el)}
const hdr=document.createElement('tr');for(const [,name] of COLS)td(hdr,'th',name);document.querySelector('#head').append(hdr);
function filtered(){const q=search.value.trim().toLocaleLowerCase();return DATA.filter(r=>
 (!direction.value||r.direction===direction.value)&&(!category.value||r.category===category.value)&&
 (!q||[r.code,r.reason,r.category,r.origin_type,r.destination_type].some(v=>String(v??'').toLocaleLowerCase().includes(q))))}
function render(){const items=filtered();const pages=Math.max(1,Math.ceil(items.length/size));current=Math.min(current,pages-1);
 const body=document.querySelector('#body');body.replaceChildren();
 for(const r of items.slice(current*size,(current+1)*size)){const tr=document.createElement('tr');for(const [key] of COLS)td(tr,'td',r[key]);body.append(tr)}
 document.querySelector('#stats').textContent=n.format(items.length)+' operaciones filtradas';
 document.querySelector('#page').textContent=(current+1)+' / '+pages;
 document.querySelector('#prev').disabled=current===0;document.querySelector('#next').disabled=current>=pages-1}
for(const x of [search,direction,category])x.addEventListener('input',()=>{current=0;render()});
document.querySelector('#prev').onclick=()=>{current--;render()};
document.querySelector('#next').onclick=()=>{current++;render()};
function csvCell(v){let s=String(v??'');if(/^[\\s]*[=+\\-@]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'}
document.querySelector('#download').onclick=()=>{
 const content='\\ufeff'+[COLS.map(x=>csvCell(x[1])).join(','),...filtered().map(r=>COLS.map(([key])=>csvCell(r[key])).join(','))].join('\\r\\n');
 const blob=new Blob([content],{type:'text/csv;charset=utf-8'});
 const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='conciliacion_filtrada_2026.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
document.querySelector('#total').textContent=n.format(DATA.length);
document.querySelector('#paired').textContent=n.format(DATA.filter(r=>r.category==='PROVISIONAL_CODE_PAIR').length);
document.querySelector('#missing').textContent=n.format(DATA.filter(r=>r.category==='NO_PAYMENT_IN_SAMPLE').length);
document.querySelector('#closed').textContent=n.format(DATA.filter(r=>r.category==='CLOSED_IN_SAMPLE').length);
render();
</script></body></html>""".replace("__DATE__", escape(through.strftime("%d/%m/%Y"))).replace("__DATA__", payload).replace("__COLS__", json.dumps(COLUMNS, ensure_ascii=False))


def run(through, output):
    s=get_settings()
    if ((s.db_host,s.db_name)!=(PILOT_HOST,PILOT_DB)
            or s.enable_source_etl or s.source_mapping_verified):
        raise RuntimeError("Report allowed only on isolated pilot with ETL disabled")
    if through.year!=2026 or through>date.today():
        raise ValueError("Date cutoff must be in 2026 and not future")
    destination=validate_export_path(output)
    csv_path=destination.with_suffix(".csv")
    if csv_path.is_symlink():
        raise ValueError("CSV destination must not be a symlink")
    db=create_engine(URL.create("mysql+pymysql",
        host=s.db_host,port=s.db_port,username=s.db_user,password=s.db_password,
        database=s.db_name,query={"charset":"utf8mb4"}),
        connect_args={"connect_timeout":10,"read_timeout":30})
    try:
        with db.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                rems=con.execute(select(Remittance.source_record_id,Remittance.source,
                    Remittance.code,Remittance.operation_type,Remittance.status,
                    Remittance.amount,Remittance.currency,Remittance.occurred_at)).all()
                pays=con.execute(select(Payment.source_record_id,Payment.source,
                    Payment.code,Payment.operation_type,Payment.amount,
                    Payment.currency,Payment.occurred_at)).all()
                rows=detail_rows(rems,pays,through)
            finally:
                con.rollback()
    finally:
        db.dispose()
    destination.write_text(html_report(rows,through),encoding="utf-8")
    export_csv(csv_path,rows)
    summary=Counter(x["category"] for x in rows)
    print(f"report_created=True count={len(rows)} cutoff={through} "
          f"provisional_pairs={summary['PROVISIONAL_CODE_PAIR']} "
          f"without_identified_payment={summary['NO_PAYMENT_IN_SAMPLE']} "
          "source_read_only=True certified=False")
    print(f"files_created={destination.name},{csv_path.name} private_export=True")
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--through",required=True,type=date.fromisoformat)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    run(a.through,a.output)


if __name__=="__main__":
    main()
