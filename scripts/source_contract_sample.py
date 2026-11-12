"""Tiny Chile type examples for local business review; source is READ ONLY."""
import argparse
import csv
from pathlib import Path

import pymysql

from app.core.config import get_settings
from scripts.audit_payment_age import connect_readonly


OUTPUT = Path("/export/validation_sample.csv")
TYPES = (5, 6, 8)
QUERIES = (
    ("remittance", "SELECT id_operacion,codigo,id_destino,estado,"
     "fec_crea_remesa FROM tmp_reporte_remesa "
     "WHERE id_operacion=%s LIMIT 2"),
    ("payment", "SELECT id_operacion,id_pago,codigo,"
     "fec_crea_pago FROM pago WHERE id_operacion=%s LIMIT 2"),
)


def run(sample=False):
    settings = get_settings()
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Sampling requires automatic ETL to remain disabled")
    if sample and not OUTPUT.is_file():
        raise RuntimeError("Create the private pilot sample file first")
    connection = connect_readonly("CHILE")
    exported = []
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("START TRANSACTION READ ONLY")
            for dataset, sql in QUERIES:
                for operation in TYPES:
                    cursor.execute("EXPLAIN " + sql, (operation,))
                    plan = cursor.fetchall()
                    for item in plan:
                        print(f"CHILE/{dataset}/type_{operation}: "
                              f"access={item.get('type')} key={item.get('key')} "
                              f"estimated_rows={item.get('rows')} "
                              f"extra={item.get('Extra')}")
                        if (item.get("type") in {"ALL", "index"}
                                or not item.get("key")):
                            if sample:
                                raise RuntimeError("Unindexed source lookup refused")
                    if sample:
                        cursor.execute(sql, (operation,))
                        rows = cursor.fetchall()
                        print(f"CHILE/{dataset}/type_{operation}: "
                              f"sample_rows={len(rows)}")
                        for row in rows:
                            code = str(row["codigo"])
                            if dataset == "remittance":
                                source_id = (f"{operation}:{code}:"
                                             f"{row['id_destino']}")
                                status = f"source_status_{row['estado']}"
                                occurred_at = row["fec_crea_remesa"]
                            else:
                                source_id = f"{operation}:{row['id_pago']}"
                                status = "RECORDED"
                                occurred_at = row["fec_crea_pago"]
                            exported.append(("CHILE", dataset, operation,
                                             source_id, code, status, occurred_at))
    finally:
        connection.rollback()
        connection.close()
    if sample:
        with OUTPUT.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(exported)
        print(f"additional_rows={len(exported)} local_file_written=True "
              "identifiers_logged=False")
    print("source_read_only=True source_rollback=True")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", action="store_true")
    run(sample=p.parse_args().sample)
