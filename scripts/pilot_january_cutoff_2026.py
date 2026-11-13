"""Private January 2026 operational cutoff ledger, not a financial trial balance.

Combines isolated pilot January remittances/payments and a user-supplied
December-to-January targeted evidence CSV. All source systems stay untouched.
Counts are cohorts: January origin and January cash/payment are distinct.
Monetary opening/closing balances are deliberately NOT asserted.
"""
import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

from sqlalchemy import select, text
from app.core.config import get_settings
from app.infrastructure.models import Remittance, Payment
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_december_detail_2025 import datetime_in_utc
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker
from scripts.pilot_operation_detail_2026 import detail_rows, safe_csv_value, validate_export_path

START = datetime(2026,1,1)
END = datetime(2026,2,1)
CUTOFF_UTC = datetime_in_utc("BOLIVIA",END)
COLUMNS = (
    ("direction","Dirección"),("cohort","Cohorte"),
    ("as_of_status","Estado al cierre"),("code","Código"),
    ("origin_source","País origen"),("origin_date","Fecha envío local"),
    ("payment_source","País pago"),("payment_date","Fecha pago local"),
    ("payment_utc","Fecha pago UTC"),("origin_amount","Importe envío"),
    ("origin_currency","Moneda envío"),("payment_amount","Importe pago"),
    ("payment_currency","Moneda pago"),("money_flag","Alerta moneda"),
    ("origin_key","Identificador piloto/origen"),("payment_key","Identificador pago"),
    ("notes","Observación"),
)


def payment_cutoff(source, occurred_at):
    """An event belongs to the Bolivia-office Jan closing if UTC < Feb 1, 04:00."""
    if occurred_at is None:
        return "UNKNOWN"
    paid_utc=datetime_in_utc(source,occurred_at)
    if paid_utc < datetime_in_utc("BOLIVIA",START):
        return "BEFORE_PERIOD"
    if paid_utc < CUTOFF_UTC:
        return "JANUARY_BY_CUTOFF"
    return "AFTER_CUTOFF"


def find_status(rem_row, rem, pay):
    cat=rem_row["category"]
    if cat=="PROVISIONAL_CODE_PAIR" and pay is not None:
        when=payment_cutoff(pay.source,pay.occurred_at)
        if when=="JANUARY_BY_CUTOFF":
            return "PAID_BY_CUTOFF"
        if when=="AFTER_CUTOFF":
            return "PAID_AFTER_CUTOFF"
        return "REVIEW_PAYMENT_TIME"
    if cat=="CLOSED_IN_SAMPLE":
        return "CLOSED_STATUS_REVIEW"
    if cat.startswith("MANUAL_REVIEW") or cat.startswith("INSUFFICIENT"):
        return "MANUAL_REVIEW"
    if cat in ("NO_PAYMENT_IN_SAMPLE","PENDING_IN_SAMPLE"):
        return "NO_IDENTIFIED_PAYMENT_BY_CUTOFF"
    return "MANUAL_REVIEW"


def january_rows(remittances,payments):
    detail=detail_rows(remittances,payments,date(2026,1,31))
    rem_map={r.source_record_id:r for r in remittances}
    pay_map={p.source_record_id:p for p in payments}
    result=[]
    for d in detail:
        rem=rem_map[d["origin_id"]]
        pay=pay_map.get(d["destination_id"])
        status=find_status(d,rem,pay)
        result.append({
            "direction":d["direction"],"cohort":"JANUARY_ORIGIN",
            "as_of_status":status,"code":d["code"],
            "origin_source":rem.source,
            "origin_date":str(rem.occurred_at or ""),
            "payment_source":pay.source if pay else "",
            "payment_date":str(pay.occurred_at or "") if pay else "",
            "payment_utc":datetime_in_utc(pay.source,pay.occurred_at).isoformat() if pay and pay.occurred_at else "",
            "origin_amount":str(rem.amount) if rem.amount is not None else "",
            "origin_currency":rem.currency or "",
            "payment_amount":str(pay.amount) if pay and pay.amount is not None else "",
            "payment_currency":pay.currency or "" if pay else "",
            "money_flag":(
                "NO_IDENTIFIED_PAYMENT" if pay is None else
                "INCOMPLETE" if rem.amount is None or pay.amount is None or not rem.currency or not pay.currency else
                "FX_REVIEW" if rem.currency != pay.currency else
                "SAME_CURRENCY_EQUAL" if rem.amount==pay.amount else
                "AMOUNT_DIFFERENCE_REVIEW"),
            "origin_key":str(rem.source_record_id),
            "payment_key":str(pay.source_record_id) if pay else "",
            "notes":d["category"]+"; "+d["reason"],
        })
    return result


def read_december_evidence(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Private December CSV file must exist and not be a symlink")
    with path.open("r",encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream)
        required={"Dirección","Código","Clasificación","Fecha envío","Fecha pago",
                  "Importe envío","Moneda envío","Importe pago","Moneda pago",
                  "Clave real remesa diciembre","Clave real pago enero"}
        if not required.issubset(set(reader.fieldnames or ())):
            raise ValueError("Expected dedicated December evidence CSV, not generic report")
        data=list(reader)
    if len(data)>25:
        raise ValueError("December evidence safety cap: up to 25 rows")
    if len({(d["Dirección"],d["Código"],d["Clave real pago enero"]) for d in data})!=len(data):
        raise ValueError("Duplicate December evidence payment key")
    for d in data:
        if not (d["Fecha envío"].startswith("2025-12-") and
                d["Fecha pago"].startswith("2026-01-")):
            raise ValueError("December evidence is outside expected month windows")
        if not d["Clave real remesa diciembre"] or not d["Clave real pago enero"]:
            raise ValueError("December evidence requires original source keys")
    return data


def december_rows(evidence, payments):
    by_original_id={p.source_record_id:p for p in payments}
    # The evidence's 'ID piloto pago' is the pilot SourceRecord ID.
    result=[]
    for d in evidence:
        p_id=int(d["ID piloto pago"])
        payment=by_original_id.get(p_id)
        if payment is None:
            raise RuntimeError("December evidence references payment missing from pilot")
        if d["Código"] != payment.code:
            raise RuntimeError("December evidence payment code differs from pilot")
        expected_destination=("CHILE" if d["Dirección"]=="BO_TO_CL" else "BOLIVIA"
                              if d["Dirección"]=="CL_TO_BO" else None)
        if expected_destination!=payment.source:
            raise RuntimeError("December evidence direction does not match pilot")
        if d["Clasificación"]!="CROSS_MONTH_PROVISIONAL_PAIR":
            classification="DECEMBER_ORIGIN_MANUAL_REVIEW"
        else:
            classification="DECEMBER_ORIGIN_PAID_IN_JANUARY"
        if payment_cutoff(payment.source,payment.occurred_at)!="JANUARY_BY_CUTOFF":
            classification="DECEMBER_ORIGIN_MANUAL_REVIEW"
        result.append({
            "direction":d["Dirección"],"cohort":"DECEMBER_ORIGIN_JANUARY_PAYMENT",
            "as_of_status":classification,"code":d["Código"],
            "origin_source":"BOLIVIA" if expected_destination=="CHILE" else "CHILE",
            "origin_date":d["Fecha envío"],
            "payment_source":payment.source,
            "payment_date":str(payment.occurred_at or ""),
            "payment_utc":datetime_in_utc(payment.source,payment.occurred_at).isoformat() if payment.occurred_at else "",
            "origin_amount":d["Importe envío"],
            "origin_currency":d["Moneda envío"],
            "payment_amount":str(payment.amount) if payment.amount is not None else "",
            "payment_currency":payment.currency or "",
            "money_flag":(
                "FX_REVIEW" if d["Moneda envío"]!=payment.currency else
                "SAME_CURRENCY_EQUAL" if d["Importe envío"] and payment.amount is not None
                  and __import__("decimal").Decimal(d["Importe envío"])==payment.amount else
                "AMOUNT_DIFFERENCE_REVIEW"),
            "origin_key":d["Clave real remesa diciembre"],
            "payment_key":d["Clave real pago enero"],
            "notes":d["Clasificación"]+"; evidence imported from private CSV (not DB)",
        })
    return result


def summarize(rows,payments):
    jan=[r for r in rows if r["cohort"]=="JANUARY_ORIGIN"]
    december=[r for r in rows if r["cohort"]=="DECEMBER_ORIGIN_JANUARY_PAYMENT"]
    assert len(jan)==len({r["origin_key"] for r in jan}), "Duplicate January origin identity"
    used={r["payment_key"] for r in jan if r["payment_key"]}
    matched_dec_ids={p.source_record_id for p in payments if any(
        r["code"]==p.code and r["payment_source"]==p.source
        and r["payment_date"]==str(p.occurred_at or "")
        for r in december)}
    jan_payments=[p for p in payments if payment_cutoff(p.source,p.occurred_at)=="JANUARY_BY_CUTOFF"]
    used_jan={int(r["payment_key"]) for r in jan
              if r["payment_key"] and r["as_of_status"]=="PAID_BY_CUTOFF"}
    if used_jan & matched_dec_ids:
        raise RuntimeError("Payment used as both December and January origin settlement")
    matched=used_jan | matched_dec_ids
    by_country={}
    for direction in ("BO_TO_CL","CL_TO_BO"):
        j=[r for r in jan if r["direction"]==direction]
        d=[r for r in december if r["direction"]==direction]
        destination="CHILE" if direction=="BO_TO_CL" else "BOLIVIA"
        payments_scope=[p for p in jan_payments if p.source==destination]
        matched_local={p_id for p_id in matched if any(p.source_record_id==p_id for p in payments_scope)}
        by_country[direction]=dict(
            january_remittances=len(j),
            origin_paid_by_cutoff=sum(x["as_of_status"]=="PAID_BY_CUTOFF" for x in j),
            origin_paid_after_cutoff=sum(x["as_of_status"]=="PAID_AFTER_CUTOFF" for x in j),
            origin_without_identified_payment=sum(x["as_of_status"]=="NO_IDENTIFIED_PAYMENT_BY_CUTOFF" for x in j),
            origin_closed=sum(x["as_of_status"]=="CLOSED_STATUS_REVIEW" for x in j),
            origin_manual_review=sum(x["as_of_status"] in ("MANUAL_REVIEW","REVIEW_PAYMENT_TIME") for x in j),
            december_origin_paid_in_january=sum(x["as_of_status"]=="DECEMBER_ORIGIN_PAID_IN_JANUARY" for x in d),
            payments_in_january=len(payments_scope),
            payments_in_january_without_cohort_match=len(payments_scope)-len(matched_local),
        )
    return by_country


def html_page(rows,summary):
    payload=json.dumps(rows,ensure_ascii=False,default=str).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    summary_json=json.dumps(summary,ensure_ascii=False)
    columns=json.dumps(COLUMNS,ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Corte operativo enero 2026</title>
<style>
:root{font-family:Segoe UI,Arial,sans-serif;background:#f3f6fa;color:#142944}
*{box-sizing:border-box}body{margin:0}main{max-width:1500px;margin:auto;padding:24px}
header{background:#112d4e;color:white;border-radius:14px;padding:24px}
header h1{font-size:26px;margin:8px 0}header p{color:#d3dce7}
.notice{background:#fff7e9;border:1px solid #dbb476;padding:15px;border-radius:9px;margin:16px 0;line-height:1.5}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:16px 0}
.metric{background:white;border:1px solid #dce4ed;padding:15px;border-radius:10px}
.metric strong{display:block;font-size:25px}.metric span{font-size:12px;color:#577}
table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}
th,td{padding:10px;border-bottom:1px solid #e0e7ef;text-align:left}
th{background:#e6eef6;position:sticky;top:0}.wrap{overflow:auto;background:white;border-radius:10px;border:1px solid #dce4ed}
input,select{font:inherit;padding:9px;border:1px solid #b9c7d8;border-radius:7px}
.controls{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
footer{color:#657689;padding:18px 0;font-size:12px}
</style></head><body><main>
<header><small>GAMBARTE · REVISIÓN PRIVADA</small><h1>Cierre operativo · Enero 2026</h1>
<p>Corte: 31/01/2026 23:59:59 Bolivia (UTC−4). Comparación de eventos usando zonas locales.</p></header>
<section class="notice"><strong>NO ES UN BALANCE CONTABLE NI UNA CERTIFICACIÓN.</strong>
El saldo inicial monetario y los saldos financieros por moneda no se calculan: requieren
posición pendiente certificada de diciembre, moneda contractual, liquidaciones,
tasas FX y movimientos/reversas del libro mayor. Los 20 casos de diciembre son solo
pagos identificados por búsqueda dirigida, no el total de operaciones abiertas en diciembre.
Los estados son provisionales basados en las extracciones existentes.</section>
<div class="metrics" id="metrics"></div><h2>Movimientos y corte por dirección</h2>
<div class="wrap"><table id="summary"></table></div>
<h2>Detalle de operaciones</h2><div class="controls">
<input id="search" placeholder="Buscar código o estado..." aria-label="Buscar código">
<select id="direction"><option value="">Ambas direcciones</option><option value="BO_TO_CL">Bolivia → Chile</option><option value="CL_TO_BO">Chile → Bolivia</option></select>
<select id="cohort"><option value="">Ambas cohortes</option><option value="JANUARY_ORIGIN">Envíos enero</option><option value="DECEMBER_ORIGIN_JANUARY_PAYMENT">Origen diciembre, pago enero</option></select>
<select id="status"><option value="">Todos los estados</option></select>
</div><p id="count"></p><div class="wrap"><table><thead id="headers"></thead><tbody id="body"></tbody></table></div>
<footer>Informe solo para uso interno. No compartir datos de remesas, pagos o importes en repositorios ni correo.
Sin valor financiero hasta verificar liquidaciones, corte, titulares y cobertura de apertura.</footer>
<script>
const ROWS=__ROWS__, SUMMARY=__SUMMARY__, COLS=__COLS__;
const money=(n)=>new Intl.NumberFormat('es-BO').format(n);
const all=(s)=>Object.values(SUMMARY).reduce((a,r)=>a+(r[s]||0),0);
const metrics=[['Envíos originados enero',all('january_remittances')],
 ['Pagados al corte',all('origin_paid_by_cutoff')],
 ['Pagados después del corte',all('origin_paid_after_cutoff')],
 ['Pagos enero de origen diciembre identificado',all('december_origin_paid_in_january')],
 ['Pendientes de identificar al corte',all('origin_without_identified_payment')],
 ['Pagos enero sin cohorte asociada',all('payments_in_january_without_cohort_match')]];
for(const [name,val] of metrics){let e=document.createElement('div');e.className='metric';let a=document.createElement('span');a.textContent=name;let b=document.createElement('strong');b.textContent=money(val);e.append(a,b);document.querySelector('#metrics').append(e)}
let h='<tr><th>Dirección</th><th>Envíos enero</th><th>Pagados al corte</th><th>Pagados después</th><th>Sin pago identificado</th><th>Cerradas/reversas</th><th>Revisión</th><th>Origen diciembre pagado enero</th><th>Pagos enero</th><th>Sin cohorte</th></tr>';
for(const [direction,r] of Object.entries(SUMMARY)){h+='<tr><td>'+direction+'</td>'+['january_remittances','origin_paid_by_cutoff','origin_paid_after_cutoff','origin_without_identified_payment','origin_closed','origin_manual_review','december_origin_paid_in_january','payments_in_january','payments_in_january_without_cohort_match'].map(k=>'<td>'+money(r[k])+'</td>').join('')+'</tr>'}
document.querySelector('#summary').innerHTML=h;
const status=document.querySelector('#status');for(const val of [...new Set(ROWS.map(r=>r.as_of_status))].sort()){const o=document.createElement('option');o.value=val;o.textContent=val;status.append(o)}
const header=document.createElement('tr');for(const [key,label] of COLS){const c=document.createElement('th');c.textContent=label;header.append(c)}document.querySelector('#headers').append(header);
function render(){let s=document.querySelector('#search').value.toLowerCase().trim(),d=document.querySelector('#direction').value,c=document.querySelector('#cohort').value,t=status.value;
let filtered=ROWS.filter(r=>(!d||r.direction===d)&&(!c||r.cohort===c)&&(!t||r.as_of_status===t)&&(!s||(r.code+' '+r.notes+' '+r.as_of_status).toLowerCase().includes(s)));
document.querySelector('#count').textContent=money(filtered.length)+' operaciones (máximo 200 visibles; CSV contiene todas)';
const body=document.querySelector('#body');body.replaceChildren();
for(const r of filtered.slice(0,200)){const tr=document.createElement('tr');for(const [key] of COLS){const td=document.createElement('td');td.textContent=String(r[key]??'');tr.append(td)}body.append(tr)}}
for(const el of document.querySelectorAll('.controls input,.controls select'))el.addEventListener('input',render);render();
</script></main></body></html>""".replace("__ROWS__",payload).replace("__SUMMARY__",summary_json).replace("__COLS__",columns)


def run(output,december_csv):
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB) or (
        settings.enable_source_etl or settings.source_mapping_verified
    ):
        raise RuntimeError("Isolated pilot only; no real ETL")
    destination=validate_export_path(output)
    csv_dest=destination.with_suffix(".csv")
    if csv_dest.is_symlink():
        raise ValueError("CSV output must not be symlink")
    dec_evidence=read_december_evidence(december_csv)
    pilot=pilot_engine(settings)
    try:
        with pilot.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                rems=con.execute(select(
                    Remittance.source_record_id,Remittance.source,Remittance.code,
                    Remittance.operation_type,Remittance.status,Remittance.amount,
                    Remittance.currency,Remittance.occurred_at)).all()
                pays=con.execute(select(
                    Payment.source_record_id,Payment.source,Payment.code,
                    Payment.operation_type,Payment.amount,Payment.currency,
                    Payment.occurred_at)).all()
            finally:
                con.rollback()
    finally:
        pilot.dispose()
    january=january_rows(rems,pays)
    december=december_rows(dec_evidence,pays)
    rows=january+december
    summary=summarize(rows,pays)
    destination.write_text(html_page(rows,summary),encoding="utf-8")
    with csv_dest.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.writer(handle)
        writer.writerow([v for _,v in COLUMNS])
        for row in rows:
            writer.writerow([safe_csv_value(row.get(k,"")) for k,_ in COLUMNS])
    print("january_cutoff_report=True no_source_connection=True pilot_read_only=True "
          "certified=False accounting_balances_computed=False")
    for direction,values in summary.items():
        print("direction="+direction+" "+" ".join(f"{k}={v}" for k,v in values.items()))
    print(f"files_created={destination.name},{csv_dest.name}")
    return rows,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    parser.add_argument("--december-csv",required=True,
                        help="Private previously generated December-January evidence")
    a=parser.parse_args()
    run(a.output,a.december_csv)


if __name__=="__main__":
    main()
