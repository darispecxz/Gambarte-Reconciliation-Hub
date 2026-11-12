"""Independent historical source counts; read-only and opt-in per month/dataset.

First invocation shows EXPLAIN only. --count executes SELECT COUNT(*)
against the source only after source plan safety checks. This validates
row counts for the creation-date filter, not completeness of payments
created in earlier years or late corrections. Never prints identities.
"""
import argparse
from datetime import date

from sqlalchemy import text

from app.core.config import get_settings
from app.integrations.source import validate_read_query, read_only_transaction
from scripts.pilot_backfill_2026 import (
    month_window, source_plan_guard, pilot_engine, checkpoint_params,
    read_checkpoint,
)
from scripts.pilot_import import (
    PILOT_DB, PILOT_HOST, check_marker, connect_source,
)

COUNT_SQL = {
    ("BOLIVIA", "remittance"): """
        SELECT COUNT(*) AS total FROM remesa r
        WHERE r.id_operacion IN (4,16)
          AND r.fec_crea_remesa >= :from_date
          AND r.fec_crea_remesa < :to_date
    """,
    ("CHILE", "remittance"): """
        SELECT COUNT(*) AS total FROM tmp_reporte_remesa r
        WHERE r.id_operacion IN (3,5,6,8)
          AND r.fec_crea_remesa >= :from_date
          AND r.fec_crea_remesa < :to_date
    """,
    ("BOLIVIA", "payment"): """
        SELECT COUNT(*) AS total FROM pago p
        WHERE p.id_operacion IN (4,7)
          AND p.fec_crea_pago >= :from_date
          AND p.fec_crea_pago < :to_date
    """,
    ("CHILE", "payment"): """
        SELECT COUNT(*) AS total FROM pago p
        WHERE p.id_operacion IN (3,5,6,8)
          AND p.fec_crea_pago >= :from_date
          AND p.fec_crea_pago < :to_date
    """,
}


def compare_status(checked, scan_exhausted, rows_seen, count):
    if not checked:
        return "NOT_COUNTED"
    if not scan_exhausted:
        return "SCAN_INCOMPLETE"
    if rows_seen == count:
        return "COUNT_MATCH_NOT_CERTIFIED"
    return "COUNT_MISMATCH_REVIEW_REQUIRED"


def validate_settings(s, source, dataset, month):
    if s.enable_source_etl or s.source_mapping_verified:
        raise RuntimeError("Keep source ETL and mapping verification disabled")
    if (s.db_host, s.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Refusing non-isolated pilot target")
    if (source, dataset) not in COUNT_SQL:
        raise ValueError("Unsupported source or dataset")
    month_window(month)


def run(source, dataset, month, count=False):
    s = get_settings()
    validate_settings(s, source, dataset, month)
    start, end = month_window(month)
    identity = checkpoint_params(source, dataset, month)
    pilot = pilot_engine(s)
    try:
        with pilot.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                exists = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE()
                      AND TABLE_NAME='pilot_backfill_progress'
                """)).scalar_one()
                checkpoint = read_checkpoint(conn, identity) if exists else {
                    "rows_seen": 0, "scan_exhausted": False, "pages_seen": 0,
                }
            finally:
                conn.rollback()
    finally:
        pilot.dispose()

    sql = COUNT_SQL[(source, dataset)]
    validate_read_query(sql)
    source_engine = connect_source(s, source)
    try:
        with read_only_transaction(source_engine) as connection:
            # Constrain the COUNT plan before executing expensive aggregation.
            plan = connection.execute(
                text("EXPLAIN " + sql),
                {"from_date": start, "to_date": end},
            ).mappings().all()
            print("count_explain=" + ",".join(
                f"{item.get('type')}/{item.get('key')}/{item.get('rows')}"
                for item in plan), flush=True)
            try:
                source_plan_guard(plan)
            except RuntimeError as exc:
                print(f"count_blocked=True reason={exc} "
                      "source_read_only=True writes_to_pilot=False", flush=True)
                return {"counted": False, "status": "COUNT_PLAN_BLOCKED"}
            if not count:
                print("count_not_executed=True dry_run=True source_read_only=True")
                return {"counted": False}
            total = int(connection.execute(text(sql),
                        {"from_date": start, "to_date": end}).scalar_one())
    finally:
        source_engine.dispose()

    scanned = int(checkpoint["rows_seen"])
    exhausted = bool(checkpoint["scan_exhausted"])
    status = compare_status(True, exhausted, scanned, total)
    print(f"month={month} source={source} dataset={dataset} "
          f"source_count={total} pilot_rows_scanned={scanned} "
          f"scan_exhausted={exhausted} comparison={status}")
    print("count_is_point_in_time=True source_read_only=True "
          "coverage_certified=False writes_to_pilot=False")
    return {"counted": True, "source_count": total,
            "pilot_rows_scanned": scanned, "status": status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=("BOLIVIA", "CHILE"))
    parser.add_argument("--dataset", required=True, choices=("remittance", "payment"))
    parser.add_argument("--month", required=True)
    parser.add_argument("--count", action="store_true",
                        help="Execute source COUNT(*) after reviewing EXPLAIN")
    args = parser.parse_args()
    run(args.source, args.dataset, args.month, args.count)


if __name__ == "__main__":
    main()
