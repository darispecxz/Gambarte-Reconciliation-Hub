"""Read-only monthly coverage preflight for the isolated 2026 reconciliation pilot.

No source connections or mutations. Checks pilot extraction checkpoints for the
origin month, prior carry-in month, and next payment month. Exhaustion means only
the extractor reached the end of its scan, NOT financially certified coverage.
"""
import argparse
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import text
from app.core.config import get_settings
from scripts.pilot_backfill_2026 import month_window,pilot_engine
from scripts.pilot_backfill_status import DATASETS
from scripts.pilot_import import PILOT_DB,PILOT_HOST,check_marker
from scripts.pilot_operation_detail_2026 import safe_csv_value,validate_export_path

COLUMNS=("month","role","source","dataset","rows_seen","pages_seen",
         "scan_exhausted","status","coverage_certified")
ROLES=("PRIOR_CARRY_IN","TARGET_MONTH","NEXT_MONTH_PAYMENTS")

def adjacent(month):
    month_window(month)
    y,m=map(int,month.split("-"))
    previous=f"{y-1:04d}-12" if m==1 else f"{y:04d}-{m-1:02d}"
    subsequent=f"{y+1:04d}-01" if m==12 else f"{y:04d}-{m+1:02d}"
    return previous,month,subsequent

def requirements(month):
    prev,current,next_month=adjacent(month)
    req=[]
    for country,dataset in DATASETS:
        # Carry-in requires prior remittance AND payment history to validate links.
        req.append((prev,"PRIOR_CARRY_IN",country,dataset))
        req.append((current,"TARGET_MONTH",country,dataset))
        # An after-cutoff payment may occur in the next month: don't silently
        # discard cases when looking at the originating-month population.
        if dataset=="payment":
            req.append((next_month,"NEXT_MONTH_PAYMENTS",country,dataset))
    return req

def evaluate(month,progress):
    identity={}
    for p in progress:
        key=(p["month_key"],p["source"],p["dataset"])
        if key in identity: raise ValueError("Duplicate checkpoint identity")
        identity[key]=p
    out=[]
    for period,role,source,dataset in requirements(month):
        p=identity.get((period,source,dataset))
        exhausted=bool(p["scan_exhausted"]) if p else False
        status="SCAN_EXHAUSTED_NOT_CERTIFIED" if exhausted else (
            "IN_PROGRESS" if p else "NOT_STARTED")
        out.append(dict(month=period,role=role,source=source,dataset=dataset,
            rows_seen=int(p["rows_seen"]) if p else 0,
            pages_seen=int(p["pages_seen"]) if p else 0,
            scan_exhausted=str(exhausted).lower(),status=status,
            coverage_certified="false"))
    ready=all(x["status"]=="SCAN_EXHAUSTED_NOT_CERTIFIED" for x in out)
    return out,"READY_FOR_MANUAL_COVERAGE_VALIDATION" if ready else "BLOCKED_INCOMPLETE_PILOT"
def page(rows,month,decision):
    payload=json.dumps(rows,ensure_ascii=False).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    return """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Preflight mensual</title><style>body{background:#f4f7fb;color:#183550;font:14px Segoe UI,Arial;margin:0}
main{max-width:1200px;margin:auto;padding:24px}header{background:#163653;color:white;padding:25px;border-radius:12px}
section{background:white;margin:16px 0;padding:16px;border-radius:10px;border:1px solid #d8e2ed}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:10px;border-bottom:1px solid #d8e2ed;text-align:left}
th{background:#eaf0f6}.wrap{overflow:auto}strong{font-size:16px}</style>
<body><main><header><small>GAMBARTE · PILOTO PRIVADO</small><h1>Preflight mensual: __MONTH__</h1>
<p>Estado: __DECISION__</p></header><section><strong>No certifica cobertura ni liquidación</strong>
<p>Un extractor agotado no demuestra que todos los movimientos históricos, correcciones o pagos
tardíos estén incluidos. Esta comprobación sólo lee checkpoints del piloto; no consulta producción.
Para certificar cobertura se requiere comparación independiente por período y fuente.</p></section>
<section class="wrap"><table><thead><tr><th>Mes</th><th>Función</th><th>País</th><th>Datos</th><th>Filas</th><th>Páginas</th><th>Estado</th></tr></thead><tbody id="body"></tbody></table></section>
<script>const R=__ROWS__,b=document.getElementById('body');
for(const r of R){const tr=document.createElement('tr');for(const k of ['month','role','source','dataset','rows_seen','pages_seen','status']){let td=document.createElement('td');td.textContent=r[k];tr.appendChild(td)}b.appendChild(tr)}
</script></main></body></html>""".replace("__ROWS__",payload).replace("__MONTH__",month).replace("__DECISION__",decision)

def run(month,output):
    s=get_settings()
    if (s.db_host,s.db_name)!=(PILOT_HOST,PILOT_DB) or s.enable_source_etl or s.source_mapping_verified:
        raise RuntimeError("Only isolated pilot allowed with source ETL disabled")
    if month=="2026-01":
        raise ValueError("For January use existing January closure; start monthly preflight at 2026-02")
    if month=="2026-12":
        raise ValueError("2026-12 requires 2027 payment checkpoint support not yet implemented")
    month_window(month)
    target=validate_export_path(output)
    csv_path=target.with_suffix(".csv")
    if csv_path.is_symlink(): raise ValueError("Output CSV symlink blocked")
    engine=pilot_engine(s)
    try:
        with engine.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                exists=con.execute(text("""SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pilot_backfill_progress'""")).scalar_one()
                if exists:
                    months=sorted({p for p,_,_,_ in requirements(month)})
                    rows=con.execute(text("""SELECT month_key,source,dataset,rows_seen,pages_seen,scan_exhausted
                        FROM pilot_backfill_progress
                        WHERE month_key IN :months""").bindparams(
                            __import__('sqlalchemy').bindparam("months",expanding=True)),
                        {"months":months}).mappings().all()
                else: rows=[]
            finally: con.rollback()
    finally: engine.dispose()
    result,status=evaluate(month,rows)
    target.write_text(page(result,month,status),encoding="utf-8")
    with csv_path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow(COLUMNS)
        for row in result:w.writerow([safe_csv_value(row[c]) for c in COLUMNS])
    print(f"month={month} readiness={status} requirements={len(result)} source_queries=0")
    for k,n in sorted(Counter(x["status"] for x in result).items()):print(f"status={k} count={n}")
    print("financially_certified=False coverage_certified=False sources_untouched=True")
    print(f"files_created={target.name},{csv_path.name}")
    return result,status

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--month",required=True,help="2026-02 through 2026-11")
    p.add_argument("--output",required=True)
    a=p.parse_args();run(a.month,a.output)
if __name__=="__main__":main()
