"""Bounded recent-source status sample; EXPLAIN before any data read."""
import argparse
from collections import Counter
import pymysql

from scripts.audit_payment_age import connect_readonly


DATASETS = (
    ("BOLIVIA", "remittance", "remesa", (4, 16), "fec_crea_remesa",
     "id_remesa", "estado"),
    ("CHILE", "remittance", "tmp_reporte_remesa", (3, 5, 6, 8),
     "fec_crea_remesa", "id_operacion, codigo, id_destino", "estado"),
    ("BOLIVIA", "payment", "pago", (4, 7), "fec_crea_pago",
     "id_pago", None),
    ("CHILE", "payment", "pago", (3, 5, 6, 8), "fec_crea_pago",
     "id_pago", None),
)


def query_for(dataset, table, types, date_column, key_columns, status_column):
    marks = ",".join(["%s"] * len(types))
    projection = status_column if status_column else "1"
    ordered_keys = key_columns.replace(", ", " DESC, ") + " DESC"
    return (f"SELECT {projection} FROM {table} "
            f"WHERE id_operacion IN ({marks}) "
            f"AND {date_column} >= NOW() - INTERVAL %s DAY "
            f"ORDER BY {date_column} DESC, {ordered_keys} LIMIT %s")


def run(days=7, limit=150, explain_only=True, selected_source=None,
        selected_dataset=None):
    if not 1 <= days <= 30 or not 1 <= limit <= 150:
        raise ValueError("Safety limits: 1..30 days and 1..150 rows")
    for country, dataset, table, types, date_col, keys, status_col in DATASETS:
        if selected_source and country != selected_source:
            continue
        if selected_dataset and dataset != selected_dataset:
            continue
        connection = connect_readonly(country)
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("START TRANSACTION READ ONLY")
                sql = query_for(dataset, table, types, date_col, keys, status_col)
                params = (*types, days, limit)
                cursor.execute("EXPLAIN " + sql, params)
                plan = cursor.fetchall()
                print(f"source={country} dataset={dataset} days={days} limit={limit}")
                for item in plan:
                    print(f"access={item.get('type')} key={item.get('key')} "
                          f"estimated_rows={item.get('rows')} extra={item.get('Extra')}")
                    if not explain_only and int(item.get("rows") or 0) > 50000:
                        raise RuntimeError(
                            "Recent sample plan exceeds safe estimate; "
                            "do not scan this source"
                        )
                if not explain_only:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    print(f"sample_rows={len(rows)} sample_capped={len(rows) == limit}")
                    if status_col:
                        counts = Counter(str(row[status_col]) for row in rows)
                        print(f"source_status_counts={dict(sorted(counts.items()))}")
        finally:
            connection.rollback()
            connection.close()
    print("read_only=True sample_only=True no_missing_payment_claim=True")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--limit", type=int, default=150)
    p.add_argument("--sample", action="store_true")
    p.add_argument("--source", choices=("BOLIVIA", "CHILE"))
    p.add_argument("--dataset", choices=("remittance", "payment"))
    args = p.parse_args()
    run(args.days, args.limit, explain_only=not args.sample,
        selected_source=args.source, selected_dataset=args.dataset)
