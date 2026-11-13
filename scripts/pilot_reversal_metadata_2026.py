"""Metadata-only inventory for bounded duplicate and reversal checks.

No transaction rows, no customer data, no unsafe joins. Only information_schema
for verified Bolivia/Chile schema with DB-enforced read-only transactions.
This inventory does not prove whether a reversal exists.
"""
import argparse
import csv
import json
from collections import Counter

from sqlalchemy import text
from app.core.config import get_settings
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_import import PILOT_DB, PILOT_HOST, connect_source
from scripts.pilot_operation_detail_2026 import safe_csv_value, validate_export_path

# Fixed schema metadata; no dynamic table SQL and no transaction table reads.
TABLE_SQL = """SELECT TABLE_NAME, TABLE_TYPE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA=:schema AND (
 LOWER(TABLE_NAME) LIKE '%revers%'
 OR LOWER(TABLE_NAME) LIKE '%devol%'
 OR LOWER(TABLE_NAME) LIKE '%anul%'
 OR LOWER(TABLE_NAME) LIKE '%bitac%'
 OR LOWER(TABLE_NAME) LIKE '%hist%'
 OR LOWER(TABLE_NAME) LIKE '%pago%'
 OR LOWER(TABLE_NAME) LIKE '%remesa%'
 OR LOWER(TABLE_NAME) LIKE '%giro%')
ORDER BY TABLE_NAME LIMIT 200"""
COLUMN_SQL = """SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA=:schema AND TABLE_NAME IN ('pago','remesa','tmp_reporte_remesa')
AND (COLUMN_NAME IN ('codigo','estado','id_pago','id_remesa','id_operacion',
'id_destino','fec_crea_pago','fec_mod_pago','fec_crea_remesa','fec_mod_remesa')
OR LOWER(COLUMN_NAME) LIKE '%revers%'
OR LOWER(COLUMN_NAME) LIKE '%devol%'
OR LOWER(COLUMN_NAME) LIKE '%anul%'
OR LOWER(COLUMN_NAME) LIKE '%estado%'
OR LOWER(COLUMN_NAME) LIKE '%fecha%'
OR LOWER(COLUMN_NAME) LIKE '%fec_%')
ORDER BY TABLE_NAME,COLUMN_NAME LIMIT 200"""
INDEX_SQL = """SELECT TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX,COLUMN_NAME,NON_UNIQUE
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA=:schema AND TABLE_NAME IN ('pago','remesa','tmp_reporte_remesa')
ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX LIMIT 200"""
QUERIES=(TABLE_SQL,COLUMN_SQL,INDEX_SQL)
FIELDS=("Fuente","Tipo evidencia","Tabla","Elemento","Detalle","Interpretación")

def parse_metadata(source,tables,columns,indexes):
    items=[]
    for r in tables:
        items.append((source,"CANDIDATE_TABLE",r["TABLE_NAME"],"",r["TABLE_TYPE"],
            "Nombre candidato; no prueba registros de reversa ni vinculación"))
    for r in columns:
        items.append((source,"SOURCE_COLUMN",r["TABLE_NAME"],r["COLUMN_NAME"],
            r["DATA_TYPE"],"Campo presente; significado pendiente de verificar"))
    for r in indexes:
        items.append((source,"SOURCE_INDEX",r["TABLE_NAME"],r["INDEX_NAME"],
            str(r["SEQ_IN_INDEX"])+":"+r["COLUMN_NAME"]+
            (" (UNIQUE)" if int(r["NON_UNIQUE"])==0 else ""),
            "Índice visible; EXPLAIN obligatorio antes de consultar movimientos"))
    return items

def html(rows):
    payload=json.dumps(rows,ensure_ascii=False).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Gambarte · Inventario seguro de evidencia</title>
<style>body{font:14px Segoe UI,Arial;background:#f3f6fa;color:#17314a;margin:0}
main{max-width:1300px;margin:auto;padding:20px}header{background:#183b5b;color:#fff;padding:24px;border-radius:12px}
aside{margin:16px 0;padding:14px;background:#fff6df;border:1px solid #d8af65}
table{border-collapse:collapse;background:white;width:100%;font-size:12px}th,td{text-align:left;padding:9px;border-bottom:1px solid #dae3ec}
th{background:#e5eef7}input,select{padding:10px;margin:12px 8px 12px 0}.wrap{overflow:auto}</style>
<body><main><header><small>REVISIÓN PRIVADA DE ESQUEMA</small><h1>Índices y posibles registros de reversa</h1>
<p>Solo metadatos · cero filas transaccionales</p></header>
<aside><b>NO CERTIFICA PAGOS NI AUSENCIA DE REVERSAS.</b> Los nombres de tablas
son candidatos sin semántica confirmada. No se consultaron movimientos ni datos personales.</aside>
<input id="q" placeholder="Buscar tabla o columna"><select id="kind"><option value="">Todos</option></select>
<p id="count"></p><div class="wrap"><table><thead><tr>
<th>Fuente</th><th>Tipo</th><th>Tabla</th><th>Elemento</th><th>Detalle</th><th>Interpretación</th>
</tr></thead><tbody id="body"></tbody></table></div>
<script>
const R=__DATA__,kind=document.querySelector('#kind');
for(let k of [...new Set(R.map(r=>r[1]))]){let o=document.createElement('option');o.value=k;o.textContent=k;kind.append(o)}
function render(){let q=document.querySelector('#q').value.toLowerCase(),k=kind.value;
let items=R.filter(r=>(!k||r[1]===k)&&(!q||r.some(v=>String(v).toLowerCase().includes(q))));
let b=document.querySelector('#body');b.replaceChildren();
for(let r of items){let tr=document.createElement('tr');for(let v of r){let td=document.createElement('td');td.textContent=v;tr.append(td)}b.append(tr)}
document.querySelector('#count').textContent=items.length+' metadatos';}
document.querySelector('#q').oninput=render;kind.onchange=render;render();
</script></main></body></html>""".replace("__DATA__",payload)

def run(output):
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Isolated pilot required")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Automatic ETL and mapping must remain disabled")
    for sql in QUERIES:
        validate_read_query(sql)
    dest=validate_export_path(output)
    csv_dest=dest.with_suffix(".csv")
    if csv_dest.is_symlink():
        raise ValueError("Private output CSV symlink blocked")
    data=[]
    for source in ("BOLIVIA","CHILE"):
        engine=connect_source(settings,source)
        try:
            schema=getattr(settings,source.lower()+"_db_name")
            with read_only_transaction(engine) as con:
                raw=[con.execute(text(sql),{"schema":schema}).mappings().all()
                     for sql in QUERIES]
                if any(len(x)>=200 for x in raw):
                    raise RuntimeError("Metadata cap reached; inventory may be incomplete")
                data.extend(parse_metadata(source,*raw))
        finally:
            engine.dispose()
    dest.write_text(html(data),encoding="utf-8")
    with csv_dest.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.writer(f);writer.writerow(FIELDS)
        for r in data:
            writer.writerow([safe_csv_value(x) for x in r])
    print("source_read_only=True metadata_only=True transaction_rows_scanned=0 production_writes=False")
    print("counts="+str(dict(sorted(Counter(r[1] for r in data).items()))))
    print("files_created="+dest.name+","+csv_dest.name+" private=True")
    return data

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",required=True)
    run(p.parse_args().output)

if __name__=="__main__":
    main()
