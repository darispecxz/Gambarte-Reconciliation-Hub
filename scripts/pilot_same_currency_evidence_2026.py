"""Private same-currency operational evidence audit from existing monetary CSV.

No connections to either production source or to pilot. Reports evidence
available *in the exported cohort*, not the full database. Never certifies
settlement, reversals, beneficiary identity, payment completeness, or closure.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scripts.pilot_operation_detail_2026 import safe_csv_value, validate_export_path
from app.domain.currency_routes import classify_currency_route

MAX_ROWS=15000
REQUIRED={
    "Dirección", "Cohorte", "Estado al corte", "Código", "País origen",
    "País pago", "Moneda origen", "Moneda pago", "Importe origen",
    "Importe pago", "Clasificación monetaria", "Ruta de moneda",
    "Clave origen", "Clave pago",
}
FIELDS=(
    ("direction","Dirección"),("cohort","Cohorte"),("cutoff_status","Estado al corte"),
    ("code","Código"),("currency","Moneda"),
    ("origin_amount","Importe envío"),("payment_amount","Importe pago"),
    ("difference","Diferencia nominal"),("origin_key","Clave origen"),
    ("payment_key","Clave pago"),("origin_date","Fecha envío"),("payment_date","Fecha pago"),
    ("status","Auditoría de corte"),("identity_alert","Alerta de referencia"),
    ("certification","Certificación financiera"),("notes","Observación"),
)
STATUS_MAP={
    "PAID_BY_CUTOFF":"NOMINAL_EQUAL_PAID_BY_CUTOFF_PROVISIONAL",
    "PAID_AFTER_CUTOFF":"NOMINAL_EQUAL_PAID_AFTER_CUTOFF",
    "DECEMBER_ORIGIN_PAID_IN_JANUARY":"NOMINAL_EQUAL_DEC_ORIGIN_JAN_PAYMENT_PROVISIONAL",
}


def load(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Private monetary CSV must exist and not be symlink")
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not REQUIRED.issubset(reader.fieldnames or ()):
            raise ValueError("Expected monetary route V2 CSV with original column labels")
        rows=[]
        for record in reader:
            rows.append(record)
            if len(rows)>MAX_ROWS:
                raise ValueError("Input safety cap exceeded")
    if not rows:
        raise ValueError("Empty report")
    return rows


def as_amount(value):
    try:
        n=Decimal(value)
    except (InvalidOperation,TypeError) as exc:
        raise ValueError("Invalid monetary amount") from exc
    if not n.is_finite() or n<=0:
        raise ValueError("Nonpositive or nonfinite money")
    return n


def analyze(rows):
    candidates=[]
    for r in rows:
        if r["Clasificación monetaria"]!="SAME_CURRENCY_EQUAL_NOT_SETTLED":
            continue
        direction=r["Dirección"]
        origin=r["Moneda origen"].strip()
        payment=r["Moneda pago"].strip()
        if origin!=payment:
            raise ValueError("Same-currency classified row has different currency units")
        if classify_currency_route(direction,origin,payment,r["País origen"],r["País pago"])!=(
                "VALID_CURRENCY_ROUTE_FINANCIAL_PENDING"):
            raise ValueError("Same-currency classified row has invalid operational route")
        amount=as_amount(r["Importe origen"])
        paid=as_amount(r["Importe pago"])
        if amount!=paid:
            raise ValueError("Same-currency classified row has mismatched nominal amounts")
        if not r["Clave origen"] or not r["Clave pago"] or not r["Código"]:
            raise ValueError("Missing reference in paired monetary evidence")
        candidates.append({
            "direction":direction,"cohort":r["Cohorte"],"cutoff_status":r["Estado al corte"],
            "code":r["Código"],"currency":origin,
            "origin_amount":str(amount),"payment_amount":str(paid),
            "difference":"0","origin_key":r["Clave origen"],"payment_key":r["Clave pago"],
            "origin_date":r.get("Fecha origen",""),"payment_date":r.get("Fecha pago",""),
            "status":STATUS_MAP.get(r["Estado al corte"],"UNEXPECTED_CUTOFF_STATUS_REVIEW"),
            "certification":"NOT_CERTIFIED",
            "notes":"Código/importe coincidente; no certifica pago, beneficiario, reversa ni liquidación",
        })
    if not candidates:
        raise ValueError("No same-currency candidates in input")
    keys_origin=Counter((r["direction"],r["origin_key"]) for r in candidates)
    keys_payment=Counter((r["direction"],r["payment_key"]) for r in candidates)
    codes=Counter((r["Dirección"],r["Código"]) for r in rows)
    for r in candidates:
        warnings=[]
        if codes[(r["direction"],r["code"])]>1:
            warnings.append("CODE_REPEATED_IN_EXPORTED_COHORT")
        if keys_origin[(r["direction"],r["origin_key"])]>1:
            warnings.append("ORIGIN_KEY_REPEATED_IN_SAME_CURRENCY")
        if keys_payment[(r["direction"],r["payment_key"])]>1:
            warnings.append("PAYMENT_KEY_REPEATED_IN_SAME_CURRENCY")
        r["identity_alert"]=";".join(warnings) if warnings else "NONE_IN_EXPORTED_COHORT"
        if warnings:
            r["status"]="REFERENCE_DUPLICATE_REVIEW"
    summary=Counter(r["status"] for r in candidates)
    pairs=Counter((r["direction"],r["currency"]) for r in candidates)
    return candidates,summary,pairs


def page(rows,summary,pairs):
    def js(data):
        return json.dumps(data,ensure_ascii=False).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gambarte · Validación nominal misma moneda</title>
<style>:root{font-family:Segoe UI,Arial,sans-serif;background:#f1f5f9;color:#142c4d}
body{margin:0}main{max-width:1400px;margin:auto;padding:22px}header{background:#153657;color:white;padding:25px;border-radius:12px}
h1{margin:6px 0} .alert{padding:15px;background:#fff4db;border:1px solid #e6bb72;border-radius:10px;margin:18px 0;line-height:1.6}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}.stat{flex:1;min-width:155px;padding:14px;background:white;border:1px solid #d9e3ee;border-radius:9px}
.stat b{display:block;font-size:23px}.stat small{color:#607287}input,select{padding:10px;border-radius:8px;border:1px solid #bdcddd;margin:12px 8px 12px 0}
.wrapper{overflow:auto;background:white;border:1px solid #dce5ef;border-radius:10px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:12px}
td,th{padding:10px;border-bottom:1px solid #e4ebf3;text-align:left}th{background:#e7eef7;position:sticky;top:0}</style></head>
<body><main><header><small>GAMBARTE · EVIDENCIA PRIVADA</small><h1>Igualdad nominal y corte operacional</h1>
<p>Enero 2026 · sin acceso a producción · sin certificación financiera</p></header>
<div class="alert"><strong>NO ES CONCILIACIÓN FINANCIERA.</strong> Igualdad numérica de la misma moneda no demuestra
liquidación, titularidad, ausencia de duplicaciones en origen, ni inexistencia de reversas. La revisión de referencias
solo detecta repeticiones dentro del CSV exportado. Pagos posteriores al corte no forman parte de los pagos de enero.</div>
<section class="stats" id="stats"></section><h2>Detalle por operación</h2>
<input id="q" placeholder="Buscar código" aria-label="Buscar código">
<select id="status"><option value="">Todos los estados</option></select>
<p id="count"></p><div class="wrapper"><table><thead id="head"></thead><tbody id="body"></tbody></table></div>
<script>
const ROWS=__ROWS__, SUMMARY=__SUMMARY__, PAIRS=__PAIRS__, COLS=__COLS__;
const n=x=>new Intl.NumberFormat('es-BO').format(x);
for(const [name,num] of Object.entries(SUMMARY)){let div=document.createElement('div');div.className='stat';
let small=document.createElement('small');small.textContent=name;let b=document.createElement('b');b.textContent=n(num);
div.append(small,b);document.querySelector('#stats').append(div);
let option=document.createElement('option');option.value=name;option.textContent=name;document.querySelector('#status').append(option)}
let thead=document.createElement('tr');
for(const [,label] of COLS){let th=document.createElement('th');th.textContent=label;thead.append(th)}
document.querySelector('#head').append(thead);
function render(){const q=document.querySelector('#q').value.trim().toLowerCase(),s=document.querySelector('#status').value;
const list=ROWS.filter(r=>(!s||r.status===s)&&(!q||r.code.toLowerCase().includes(q)));
document.querySelector('#count').textContent=n(list.length)+' registros · primeros 200 visibles · CSV completo';
const body=document.querySelector('#body');body.replaceChildren();
for(const row of list.slice(0,200)){const tr=document.createElement('tr');
for(const [key] of COLS){const td=document.createElement('td');td.textContent=String(row[key]??'');tr.append(td)}body.append(tr)}}
document.querySelector('#q').addEventListener('input',render);
document.querySelector('#status').addEventListener('change',render);render();
</script></main></body></html>""".replace("__ROWS__",js(rows)).replace("__SUMMARY__",js(summary)).replace("__PAIRS__",js({f"{d}/{c}":n for (d,c),n in pairs.items()})).replace("__COLS__",js(FIELDS))


def run(input_csv,output):
    dest=validate_export_path(output)
    csv_dest=dest.with_suffix(".csv")
    if csv_dest.is_symlink():
        raise ValueError("Private CSV output is a symlink")
    rows,summary,pairs=analyze(load(input_csv))
    dest.write_text(page(rows,summary,pairs),encoding="utf-8")
    with csv_dest.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f)
        writer.writerow([title for _,title in FIELDS])
        for row in rows:
            writer.writerow([safe_csv_value(row.get(key,"")) for key,_ in FIELDS])
    print("same_currency_evidence=True source_connections=False pilot_connections=False "
          "financial_certification=False reversal_verified=False")
    print(f"same_currency_rows={len(rows)}")
    for key,num in sorted(summary.items()):
        print(f"status={key} count={num}")
    for (direction,currency),num in sorted(pairs.items()):
        print(f"currency={direction}/{currency} count={num}")
    print(f"files_created={dest.name},{csv_dest.name}")
    return rows,summary,pairs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    run(args.input_csv,args.output)


if __name__=="__main__":
    main()
