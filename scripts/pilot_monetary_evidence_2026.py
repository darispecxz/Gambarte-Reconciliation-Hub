"""Private monetary evidence audit from January cutoff CSV; no DB connections.

This report diagnoses currency mapping and amount ratios. It NEVER assumes
an exchange rate, financial equivalence, accounting balance, or settlement.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median

from scripts.pilot_operation_detail_2026 import safe_csv_value, validate_export_path
from app.domain.currency_routes import classify_currency_route

COLUMNS=(
    ("direction","Dirección"),("cohort","Cohorte"),("as_of_status","Estado al corte"),
    ("code","Código"),("origin_source","País origen"),("payment_source","País pago"),
    ("origin_currency","Moneda origen"),("payment_currency","Moneda pago"),
    ("origin_amount","Importe origen"),("payment_amount","Importe pago"),
    ("ratio_payment_per_origin","Cociente pago/origen (NO tipo de cambio)"),
    ("money_flag","Clasificación monetaria"),
    ("currency_route_status","Ruta de moneda"),("financial_status","Estado financiero"),
    ("origin_key","Clave origen"),
    ("payment_key","Clave pago"),("origin_date","Fecha origen"),
    ("payment_date","Fecha pago"),("review","Revisión requerida"),
)
INPUT_COLUMNS={
    "Dirección":"direction","Cohorte":"cohort","Estado al cierre":"as_of_status",
    "Código":"code","País origen":"origin_source","País pago":"payment_source",
    "Moneda envío":"origin_currency","Moneda pago":"payment_currency",
    "Importe envío":"origin_amount","Importe pago":"payment_amount",
    "Identificador piloto/origen":"origin_key","Identificador pago":"payment_key",
    "Fecha envío local":"origin_date","Fecha pago local":"payment_date",
}
MAX_ROWS=15000


def parse_csv(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Private cutoff CSV must exist and not be a symlink")
    with path.open("r",encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        if not set(INPUT_COLUMNS).issubset(reader.fieldnames or ()):
            raise ValueError("Expected original January cutoff CSV headers")
        raw=[]
        for item in reader:
            raw.append({field:item[source] for source,field in INPUT_COLUMNS.items()})
            if len(raw)>MAX_ROWS:
                raise ValueError("Safety cap exceeded")
    return raw


def monetary_classification(row):
    """Never use a ratio to assert a verified FX conversion."""
    a=row["origin_amount"].strip()
    b=row["payment_amount"].strip()
    ac=row["origin_currency"].strip()
    bc=row["payment_currency"].strip()
    if not row["payment_key"]:
        return "NO_MATCHED_PAYMENT", "", "Sin pago identificado; no comparar importes"
    if not (a and b and ac and bc):
        return "MONETARY_DATA_INCOMPLETE", "", "Revisar campos monetarios faltantes"
    try:
        origin=Decimal(a)
        payment=Decimal(b)
    except InvalidOperation:
        return "MONETARY_DATA_INVALID", "", "Revisar importe inválido"
    if not origin.is_finite() or not payment.is_finite():
        return "MONETARY_DATA_INVALID", "", "Importe no finito"
    if origin<=0 or payment<0:
        return "NONPOSITIVE_AMOUNT_REVIEW", "", "Revisar importe cero/negativo"
    ratio=payment/origin
    display=format(ratio.quantize(Decimal("0.000001")),"f")
    if ac!=bc:
        return "FX_SEMANTICS_UNVERIFIED",display,(
            "No inferir FX; verificar contrato, unidad monetaria, importe real pagado y comisiones"
        )
    if payment!=origin:
        return "SAME_CURRENCY_AMOUNT_DIFFERENCE",display,(
            "Verificar monto liquidado, comisión y ajustes"
        )
    return "SAME_CURRENCY_EQUAL_NOT_SETTLED",display,(
        "Importes nominales idénticos; comprobar liquidación y titularidad"
    )


def build(rows):
    classified=[]
    for item in rows:
        row=dict(item)
        category,ratio,note=monetary_classification(row)
        route=classify_currency_route(
            row["direction"],row["origin_currency"],row["payment_currency"],
            row.get("origin_source"),row.get("payment_source"))
        finance=("NO_PAYMENT_EVIDENCE" if category=="NO_MATCHED_PAYMENT" else
                 "FINANCIAL_VALIDATION_PENDING")
        row.update(money_flag=category,ratio_payment_per_origin=ratio,review=note,
                   currency_route_status=route,financial_status=finance)
        classified.append(row)
    summary=Counter(r["money_flag"] for r in classified)
    groups=defaultdict(list)
    for r in classified:
        if r["money_flag"]=="FX_SEMANTICS_UNVERIFIED":
            key=(r["direction"],r["cohort"],r["origin_currency"],r["payment_currency"])
            groups[key].append(Decimal(r["ratio_payment_per_origin"]))
    grouped=[]
    for key,values in sorted(groups.items()):
        grouped.append({
            "direction":key[0],"cohort":key[1],
            "origin_currency":key[2],"payment_currency":key[3],
            "count":len(values),"min_ratio":str(min(values)),
            "median_ratio":str(median(values)),"max_ratio":str(max(values)),
        })
    return classified,summary,grouped


def private_html(rows,summary,grouped):
    def safe(obj):
        return json.dumps(obj,ensure_ascii=False,default=str).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Auditoría monetaria preliminar enero 2026</title>
<style>
:root{font-family:Segoe UI,Arial,sans-serif;background:#f3f6fa;color:#152b49}
*{box-sizing:border-box}body{margin:0}main{max-width:1450px;margin:auto;padding:20px}
header{background:#142f50;color:#fff;border-radius:14px;padding:24px}
h1{font-size:25px;margin:5px 0}.notice{padding:15px;background:#fff7e8;border:1px solid #dfbb80;border-radius:8px;margin:15px 0;line-height:1.6}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:15px 0}
.metric{background:#fff;padding:15px;border-radius:10px;border:1px solid #dee5ed}
.metric small{display:block;color:#647287}.metric strong{font-size:23px}
.wrap{overflow:auto;border:1px solid #dae2ec;border-radius:10px;background:white}
table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}
th,td{border-bottom:1px solid #e8edf2;padding:10px;text-align:left}
th{background:#eaf0f7;position:sticky;top:0}
input,select{padding:10px;border:1px solid #c8d3df;border-radius:7px;margin:10px 8px 10px 0}
</style></head><body><main>
<header><small>GAMBARTE · CONTROL PRIVADO</small><h1>Validación de importes y monedas</h1>
<p>Enero 2026 y cruces diciembre–febrero · Evidencia preliminar, sin liquidación verificada</p></header>
<div class="notice"><strong>NO ES CONCILIACIÓN FINANCIERA.</strong>
Los cocientes entre importes son únicamente indicadores numéricos, NO tipos de cambio.
Se debe confirmar el significado y unidad de monto/envio, moneda contractual,
comisiones, tasa pactada, moneda efectivamente entregada y asiento de liquidación.
La coincidencia exacta de importes tampoco certifica pago o titularidad. La ruta permitida no valida la moneda real de entrega; los campos de Chile siguen bajo revisión.</div>
<div class="metrics" id="metrics"></div><h2>Rutas de moneda operativas (no financieras)</h2><div class="metrics" id="routes"></div>
<h2>Monedas diferentes, agrupadas</h2>
<div class="wrap"><table id="groups"></table></div>
<h2>Detalle de revisión</h2>
<input id="q" placeholder="Buscar código, moneda..." aria-label="Buscar código">
<select id="flag"><option value="">Todas las clasificaciones</option></select>
<p id="count"></p><div class="wrap"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>
const ROWS=__ROWS__, SUMMARY=__SUMMARY__, GROUPS=__GROUPS__, COLS=__COLS__;
const ROUTES={};for(const r of ROWS){ROUTES[r.currency_route_status]=(ROUTES[r.currency_route_status]||0)+1}
for(const [key,value] of Object.entries(ROUTES)){
let el=document.createElement('div');el.className='metric';
let name=document.createElement('small');name.textContent=key;
let count=document.createElement('strong');count.textContent=new Intl.NumberFormat('es-BO').format(value);
el.append(name,count);document.querySelector('#routes').append(el)}
const n=x=>new Intl.NumberFormat('es-BO').format(x);
for(const [key,value] of Object.entries(SUMMARY)){
let box=document.createElement('div');box.className='metric';
let small=document.createElement('small');small.textContent=key;
let strong=document.createElement('strong');strong.textContent=n(value);
box.append(small,strong);document.querySelector('#metrics').append(box)}
const groupCols=[['direction','Dirección'],['cohort','Cohorte'],['origin_currency','Moneda origen'],['payment_currency','Moneda pago'],['count','Cantidad'],['min_ratio','Ratio mínimo'],['median_ratio','Ratio mediano'],['max_ratio','Ratio máximo']];
const headRow=(cols)=>{let tr=document.createElement('tr');for(const [,title] of cols){let th=document.createElement('th');th.textContent=title;tr.append(th)}return tr};
let groupTable=document.querySelector('#groups');groupTable.append(headRow(groupCols));
for(const r of GROUPS){let tr=document.createElement('tr');for(const [k] of groupCols){let td=document.createElement('td');td.textContent=String(r[k]);tr.append(td)}groupTable.append(tr)}
document.querySelector('#head').append(headRow(COLS));
for(const key of Object.keys(SUMMARY)){const o=document.createElement('option');o.value=key;o.textContent=key;document.querySelector('#flag').append(o)}
function render(){let q=document.querySelector('#q').value.trim().toLowerCase(),flag=document.querySelector('#flag').value;
let filtered=ROWS.filter(r=>(!flag||r.money_flag===flag)&&(!q||[r.code,r.direction,r.cohort,r.origin_currency,r.payment_currency].some(x=>String(x).toLowerCase().includes(q))));
document.querySelector('#count').textContent=n(filtered.length)+' registros; primeros 200 visibles, CSV incluye todos';
let body=document.querySelector('#body');body.replaceChildren();
for(const r of filtered.slice(0,200)){let tr=document.createElement('tr');for(const [k] of COLS){let td=document.createElement('td');td.textContent=String(r[k]??'');tr.append(td)}body.append(tr)}}
document.querySelector('#q').addEventListener('input',render);
document.querySelector('#flag').addEventListener('input',render);render();
</script></main></body></html>""".replace("__ROWS__",safe(rows)).replace("__SUMMARY__",safe(summary)).replace("__GROUPS__",safe(grouped)).replace("__COLS__",safe(COLUMNS))


def run(input_csv,output):
    destination=validate_export_path(output)
    csv_dest=destination.with_suffix(".csv")
    if csv_dest.is_symlink():
        raise ValueError("CSV export is symlinked")
    rows,summary,grouped=build(parse_csv(input_csv))
    destination.write_text(private_html(rows,summary,grouped),encoding="utf-8")
    with csv_dest.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.writer(handle)
        writer.writerow([label for _,label in COLUMNS])
        for r in rows:
            writer.writerow([safe_csv_value(r.get(key,"")) for key,_ in COLUMNS])
    print("monetary_evidence=True source_connections=False pilot_connections=False "
          "financial_certification=False no_fx_rate_inferred=True")
    for key,value in sorted(summary.items()):
        print(f"{key}={value}")
    for key,value in sorted(Counter(r["currency_route_status"] for r in rows).items()):
        print(f"currency_route={key} count={value}")
    for g in grouped:
        print("fx_group="+"/".join((g["direction"],g["cohort"],
                                 g["origin_currency"],g["payment_currency"]))+
              f" count={g['count']} median_numeric_ratio={g['median_ratio']} not_fx=True")
    print(f"files_created={destination.name},{csv_dest.name}")
    return rows,summary,grouped


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    run(a.input_csv,a.output)


if __name__=="__main__":
    main()
