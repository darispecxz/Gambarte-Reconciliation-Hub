"""Verify historical Chile pago.total vs payout arithmetic for 12 sampled FX remittances.

READ ONLY, indexed by real IDs. Reuses the already-reviewed 12-operation CSV,
pilot ID mapping and original source identifiers. No inference of cash delivered:
pago.total is the recorded accounting figure; cash confirmation isn't stored
in the sampled payout columns.
"""
import argparse
import csv
import json
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from sqlalchemy import select, text

from app.core.config import get_settings
from app.infrastructure.models import SourceRecord
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_import import PILOT_DB,PILOT_HOST,check_marker,connect_source
from scripts.pilot_monetary_targeted_2026 import identity_params,safe_plan
from scripts.pilot_operation_detail_2026 import safe_csv_value,validate_export_path

SQL={
 "origin": """SELECT id_remesa,id_operacion,codigo,monto,mon_rec,mon_ent,
     total_cambio,tipo_cambio_clp,total_clp,comision,comision_bob,pago_comision
     FROM remesa WHERE id_remesa=:pk AND id_operacion=:op
     AND codigo=:code LIMIT 2""",
 "payment": """SELECT id_pago,id_operacion,codigo,monto,mon_rec,tipo_cambio,
     total,fec_crea_pago,id_tipo_pago
     FROM pago WHERE id_pago=:pk AND id_operacion=:op
     AND codigo=:code LIMIT 2""",
}
FIELDS=(
 ("code","Código"),("pair","Ruta"),("cohort","Cohorte"),("origin_real_key","ID origen real"),
 ("payment_real_key","ID pago real"),("origin_monto","remesa.monto"),
 ("origin_total_cambio","remesa.total_cambio"),("origin_total_clp","remesa.total_clp"),
 ("origin_tc_clp","remesa.tipo_cambio_clp"),("origin_pago_comision","remesa.pago_comision"),
 ("payment_monto","pago.monto"),("payment_currency_id","pago.mon_rec"),
 ("payment_tc","pago.tipo_cambio"),("payment_total","pago.total"),
 ("calculated_total","ROUND(pago.monto × tipo_cambio,0)"),
 ("difference","Diferencia total almacenado vs cálculo"),
 ("formula_result","Verificación fórmula"),("origin_total_clp_result","Comparación con total_clp origen"),
 ("origin_explain","EXPLAIN remesa"),("payment_explain","EXPLAIN pago"),
 ("financial_certification","Certificación financiera"),
)
def read_samples(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Private sample CSV must be a regular file")
    with path.open(encoding="utf-8-sig",newline="") as f:
        rd=csv.DictReader(f)
        required={"Dirección","Cohorte","Código","Sistema remesa","Sistema pago","Clave remesa",
            "Clave pago","Moneda remesa normalizada","Moneda pago normalizada",
            "Pago monto","Pago tipo_cambio","Estado evidencia"}
        if not required.issubset(rd.fieldnames or ()):
            raise ValueError("Wrong 12-sample CSV columns")
        rows=list(rd)
    if len(rows)!=12:
        raise ValueError("Exactly 12 selected original samples required")
    if len({r["Código"] for r in rows})!=12:
        raise ValueError("Repeated sample code")
    for r in rows:
        if (r["Dirección"]!="BO_TO_CL" or r["Sistema remesa"]!="BOLIVIA"
            or r["Sistema pago"]!="CHILE" or
            r["Estado evidencia"]!="SOURCE_AMOUNTS_MATCH_PILOT"):
            raise ValueError("Unverified or unsupported sample")
    return rows

def source_record(engine,kind,key,code):
    system="BOLIVIA" if kind=="origin" else "CHILE"
    kind_name="remittance" if kind=="origin" else "payment"
    params=identity_params(system,kind_name,key,code)
    sql=SQL[kind]
    validate_read_query(sql)
    with read_only_transaction(engine) as conn:
        explain=safe_plan(conn.execute(text("EXPLAIN "+sql),params).mappings().all())
        rows=conn.execute(text(sql),params).mappings().all()
    if len(rows)!=1 or str(rows[0]["codigo"])!=code:
        raise RuntimeError("Ambiguous/absent source identity")
    return dict(rows[0]),explain

def calculate(monto,tc):
    # PHP round(...,0) for nonnegative values rounds half away from zero.
    return (Decimal(str(monto))*Decimal(str(tc))).quantize(Decimal("1"),rounding=ROUND_HALF_UP)

def compare(row,origin,payment,op,pp,origin_id,payment_id):
    if (Decimal(str(payment["monto"]))!=Decimal(row["Pago monto"]) or
        Decimal(str(payment["tipo_cambio"]))!=Decimal(row["Pago tipo_cambio"])):
        raise RuntimeError("Raw payment differs from previously reviewed sample")
    actual=Decimal(str(payment["total"]))
    calculated=calculate(payment["monto"],payment["tipo_cambio"])
    pair=row["Moneda remesa normalizada"]+" → "+row["Moneda pago normalizada"]
    if (row["Moneda pago normalizada"]=="CLP" and str(payment["mon_rec"])!="2"):
        raise RuntimeError("Unexpected Chile CLP currency ID")
    if (row["Moneda pago normalizada"]=="USD" and str(payment["mon_rec"])!="1"):
        raise RuntimeError("Unexpected Chile USD currency ID")
    origin_clp=Decimal(str(origin["total_clp"])) if origin["total_clp"] is not None else None
    return dict(code=row["Código"],pair=pair,cohort=row["Cohorte"],
        origin_real_key=origin_id,payment_real_key=payment_id,
        origin_monto=str(origin["monto"]),origin_total_cambio=str(origin["total_cambio"]),
        origin_total_clp=str(origin_clp) if origin_clp is not None else "",
        origin_tc_clp=str(origin["tipo_cambio_clp"]),
        origin_pago_comision=str(origin["pago_comision"]),
        payment_monto=str(payment["monto"]),payment_currency_id=str(payment["mon_rec"]),
        payment_tc=str(payment["tipo_cambio"]),payment_total=str(actual),
        calculated_total=str(calculated),difference=str(actual-calculated),
        formula_result="MATCH_STORED_PAGO_TOTAL" if actual==calculated else "FORMULA_DIFF_REVIEW",
        origin_total_clp_result=("NOT_AVAILABLE" if origin_clp is None else
            "MATCH_ORIGIN_TOTAL_CLP" if origin_clp==actual else "DIFFERENT_REQUIRES_SEMANTIC_REVIEW"),
        origin_explain=op,payment_explain=pp,financial_certification="NOT_CERTIFIED")

def html(rows):
    data=json.dumps(rows,ensure_ascii=False).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    cols=json.dumps(FIELDS,ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Gambarte · Validación de pago.total enero 2026</title>
<style>body{margin:0;background:#f2f5f9;color:#19334e;font:14px Segoe UI,Arial}
main{max-width:1450px;margin:auto;padding:20px}header{background:#173959;color:#fff;padding:23px;border-radius:12px}
aside{background:#fff2dc;padding:14px;margin:16px 0;border:1px solid #dab069;border-radius:8px}
.wrap{overflow:auto;background:#fff}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:12px}
td,th{padding:10px;border-bottom:1px solid #dde5ef;text-align:left}th{background:#eaf0f8}</style>
<body><main><header><h1>Verificación de la fórmula histórica de pago</h1>
<p>12 remesas BO→CL, cotejo indexado de registros originales</p></header>
<aside><b>NO CERTIFICA ENTREGA.</b> Se comprueba la correspondencia matemática
con el campo pago.total. La confirmación del desembolso, descuentos de caja,
saldos y reversas requieren evidencia independiente. Una diferencia con
remesa.total_clp puede obedecer a redondeos o reglas de comisión todavía no verificadas.</aside>
<div class="wrap"><table><thead id="h"></thead><tbody id="b"></tbody></table></div>
<script>const R=__ROWS__,C=__COLS__;
let h=document.createElement('tr');for(let [,v] of C){let t=document.createElement('th');t.textContent=v;h.append(t)}document.querySelector('#h').append(h);
for(let row of R){let tr=document.createElement('tr');for(let [k] of C){let td=document.createElement('td');td.textContent=row[k]??'';tr.append(td)}document.querySelector('#b').append(tr)}
</script></main></body></html>""".replace("__ROWS__",data).replace("__COLS__",cols)

def run(samples_csv,output):
    cfg=get_settings()
    if (cfg.db_host,cfg.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Pilot-only isolated environment required")
    if cfg.enable_source_etl or cfg.source_mapping_verified:
        raise RuntimeError("Automatic source ETL must remain disabled")
    dst=validate_export_path(output)
    csv_dst=dst.with_suffix(".csv")
    if csv_dst.is_symlink():
        raise ValueError("Output CSV symlink blocked")
    samples=read_samples(samples_csv)
    wanted={int(r[k]) for r in samples if r["Cohorte"]=="JANUARY_ORIGIN"
             for k in ("Clave remesa","Clave pago")}
    db=pilot_engine(cfg)
    try:
        with db.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                found=con.execute(select(SourceRecord.id,SourceRecord.source,
                    SourceRecord.dataset,SourceRecord.source_id,SourceRecord.code)
                    .where(SourceRecord.id.in_(wanted))).all() if wanted else []
            finally:
                con.rollback()
    finally:
        db.dispose()
    lookup={r.id:r for r in found}
    if len(lookup)!=len(wanted):
        raise RuntimeError("Missing pilot identity mapping")
    engines={"BOLIVIA":connect_source(cfg,"BOLIVIA"),"CHILE":connect_source(cfg,"CHILE")}
    results=[]
    try:
        for s in samples:
            def lookup_key(which,source,kind):
                k=s[which]
                if s["Cohorte"]=="DECEMBER_ORIGIN_JANUARY_PAYMENT":
                    return k
                r=lookup[int(k)]
                if (r.source,r.dataset,r.code)!=(source,kind,s["Código"]):
                    raise RuntimeError("Pilot identity mismatch")
                return r.source_id
            ok=lookup_key("Clave remesa","BOLIVIA","remittance")
            pk=lookup_key("Clave pago","CHILE","payment")
            original,oplan=source_record(engines["BOLIVIA"],"origin",ok,s["Código"])
            payment,pplan=source_record(engines["CHILE"],"payment",pk,s["Código"])
            results.append(compare(s,original,payment,oplan,pplan,ok,pk))
    finally:
        for e in engines.values():
            e.dispose()
    dst.write_text(html(results),encoding="utf-8")
    with csv_dst.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow([n for _,n in FIELDS])
        for r in results:
            w.writerow([safe_csv_value(r.get(k,"")) for k,_ in FIELDS])
    print("source_read_only=True exact_source_id=True queries=24 financially_certified=False")
    for key,n in sorted(Counter(r["formula_result"] for r in results).items()):
        print(f"formula={key} count={n}")
    for key,n in sorted(Counter(r["origin_total_clp_result"] for r in results).items()):
        print(f"origin_clp={key} count={n}")
    print(f"files_created={dst.name},{csv_dst.name}")
    return results

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--samples-csv",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    run(a.samples_csv,a.output)

if __name__=="__main__":
    main()
