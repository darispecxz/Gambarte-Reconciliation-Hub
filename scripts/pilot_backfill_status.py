"""Aggregated pilot backfill progress. SCAN_EXHAUSTED is NOT certified coverage."""
import argparse
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from app.core.config import get_settings
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker

DATASETS = (("BOLIVIA", "remittance"), ("BOLIVIA", "payment"),
            ("CHILE", "remittance"), ("CHILE", "payment"))


def summarize(progress, through):
    if through.year != 2026:
        raise ValueError("2026 only")
    index = {(r["source"], r["dataset"], r["month_key"]): r for r in progress}
    result = []
    for month in range(1, through.month + 1):
        month_key = f"2026-{month:02d}"
        for country, dataset in DATASETS:
            row = index.get((country, dataset, month_key))
            status = ("SCAN_EXHAUSTED_NOT_CERTIFIED" if row and row["scan_exhausted"]
                      else "IN_PROGRESS" if row else "NOT_STARTED")
            result.append((month_key, country, dataset, status,
                           int(row["rows_seen"]) if row else 0,
                           int(row["pages_seen"]) if row else 0))
    return result


def run(through):
    if through.year != 2026 or through > date.today():
        raise ValueError("Cutoff must be a non-future day in 2026")
    s = get_settings()
    if ((s.db_host, s.db_name) != (PILOT_HOST, PILOT_DB)
            or s.enable_source_etl or s.source_mapping_verified):
        raise RuntimeError("Only isolated pilot with ETL disabled")
    engine = create_engine(URL.create("mysql+pymysql",
        host=s.db_host, port=s.db_port, database=s.db_name,
        username=s.db_user, password=s.db_password,
        query={"charset": "utf8mb4"}),
        connect_args={"connect_timeout": 10, "read_timeout": 30})
    try:
        with engine.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                exists = con.execute(text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE()
                    AND TABLE_NAME='pilot_backfill_progress'
                """)).scalar_one()
                rows = (con.execute(text("""
                    SELECT source,dataset,month_key,rows_seen,pages_seen,
                           scan_exhausted FROM pilot_backfill_progress
                """)).mappings().all() if exists else [])
            finally:
                con.rollback()
    finally:
        engine.dispose()
    result = summarize(rows, through)
    for month, country, dataset, status, count, pages in result:
        print(f"{month} {country}/{dataset} {status} rows_scanned={count} pages={pages}")
    print("historical_coverage_certified=False source_count_verified=False")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    run(args.through)


if __name__ == "__main__":
    main()
