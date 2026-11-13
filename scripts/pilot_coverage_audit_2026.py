"""Read-only pilot coverage audit for 2026: checkpoints versus local projections.

Never connects to Bolivia/Chile sources, never certifies coverage, and never
uses checkpoint rows_seen as proof of distinct transactions. Produces only a
private aggregate CSV (no codes, identities, amounts, or source credentials).
"""
import argparse
import csv
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from scripts.management_report_2026 import EXPORT_DIR
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker

PAIRS = (("BOLIVIA", "remittance"), ("BOLIVIA", "payment"),
         ("CHILE", "remittance"), ("CHILE", "payment"))
FIELDS = ("month", "source", "dataset", "checkpoint_status", "checkpoint_rows_seen",
          "checkpoint_pages_seen", "pilot_projection_rows", "pilot_missing_code",
          "pilot_missing_date", "difference_projection_minus_scanned",
          "assessment", "coverage_certified")
TABLES = {"remittance": "remittances", "payment": "payments"}


def validate_output(path):
    destination = Path(path)
    if (not destination.is_absolute() or destination.parent != EXPORT_DIR
            or destination.suffix.lower() != ".csv"):
        raise ValueError("Output must be a CSV directly under /export")
    if not EXPORT_DIR.is_dir():
        raise RuntimeError("Mount private local export directory at /export")
    if destination.is_symlink():
        raise ValueError("Output file cannot be a symlink")
    if destination.parent.resolve(strict=True) != EXPORT_DIR.resolve(strict=True):
        raise ValueError("Output mount resolves outside approved directory")
    return destination


def build_rows(checkpoints, projections, missing_dates, through_month):
    output = []
    for month_number in range(1, int(through_month[5:7]) + 1):
        month = f"2026-{month_number:02d}"
        for source, dataset in PAIRS:
            key = (source, dataset, month)
            cp = checkpoints.get(key)
            stats = projections.get(key, {})
            projected = int(stats.get("rows", 0))
            empty_codes = int(stats.get("missing_code", 0))
            scanned = int(cp["rows_seen"]) if cp else None
            difference = projected - scanned if scanned is not None else None
            # Missing dates cannot be attributed to a creation month. Surface
            # them conservatively against each month for the affected pair.
            undated = int(missing_dates.get((source, dataset), 0))
            status = ("NO_CHECKPOINT" if cp is None else
                      "SCAN_EXHAUSTED_NOT_CERTIFIED" if cp["scan_exhausted"] else
                      "SCAN_INCOMPLETE")
            if cp is None or not cp["scan_exhausted"]:
                assessment = "CHECKPOINT_INCOMPLETE"
            elif difference != 0:
                assessment = "PROJECTION_SCAN_DIFFERENCE_REVIEW"
            elif empty_codes or undated:
                assessment = "LOCAL_DATA_QUALITY_REVIEW"
            else:
                assessment = "LOCAL_COUNTS_MATCH_NOT_CERTIFIED"
            output.append({
                "month": month, "source": source, "dataset": dataset,
                "checkpoint_status": status,
                "checkpoint_rows_seen": scanned if scanned is not None else "",
                "checkpoint_pages_seen": cp["pages_seen"] if cp else "",
                "pilot_projection_rows": projected,
                "pilot_missing_code": empty_codes,
                "pilot_missing_date": undated,
                "difference_projection_minus_scanned": difference if difference is not None else "",
                "assessment": assessment, "coverage_certified": "False",
            })
    return output


def collect(through_month):
    settings = get_settings()
    if ((settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Requires isolated pilot with source ETL disabled")
    engine = pilot_engine(settings)
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                exists = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE()
                      AND TABLE_NAME='pilot_backfill_progress'
                """)).scalar_one()
                if not exists:
                    raise RuntimeError("pilot_backfill_progress missing; no scan evidence")
                raw = conn.execute(text("""
                    SELECT source, dataset, month_key, rows_seen, pages_seen, scan_exhausted
                    FROM pilot_backfill_progress
                    WHERE month_key >= '2026-01' AND month_key <= :through
                """), {"through": through_month}).mappings().all()
                checkpoints = {(r["source"], r["dataset"], r["month_key"]): dict(r)
                               for r in raw}
                projections = {}
                missing_dates = {}
                for dataset, table in TABLES.items():
                    # Fixed table identifiers, never derived from CLI input.
                    monthly = conn.execute(text(f"""
                        SELECT source, DATE_FORMAT(occurred_at, '%Y-%m') AS month_key,
                               COUNT(*) AS rows,
                               SUM(CASE WHEN code IS NULL OR TRIM(code) = ''
                                        THEN 1 ELSE 0 END) AS missing_code
                        FROM {table}
                        WHERE occurred_at >= '2026-01-01'
                          AND occurred_at < :end_date
                        GROUP BY source, DATE_FORMAT(occurred_at, '%Y-%m')
                    """), {"end_date": date(2027, 1, 1) if through_month == "2026-12"
                           else date(2026, int(through_month[5:7]) + 1, 1)}).mappings().all()
                    for r in monthly:
                        projections[(r["source"], dataset, r["month_key"])] = dict(r)
                    undated = conn.execute(text(f"""
                        SELECT source, COUNT(*) AS rows
                        FROM {table}
                        WHERE occurred_at IS NULL
                        GROUP BY source
                    """)).mappings().all()
                    for r in undated:
                        missing_dates[(r["source"], dataset)] = int(r["rows"])
                return build_rows(checkpoints, projections, missing_dates, through_month)
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through-month", default=date.today().strftime("%Y-%m"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if (len(args.through_month) != 7 or args.through_month[:5] != "2026-"
            or not args.through_month[5:].isdigit()
            or not 1 <= int(args.through_month[5:]) <= 12
            or args.through_month > date.today().strftime("%Y-%m")):
        parser.error("--through-month must be a reached month of 2026")
    destination = validate_output(args.output)
    rows = collect(args.through_month)
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    from collections import Counter
    counts = Counter(row["assessment"] for row in rows)
    print(f"report={destination.name} rows={len(rows)} "
          f"assessment_counts={dict(sorted(counts.items()))} "
          "source_connections=0 source_writes=False pilot_writes=False "
          "coverage_certified=False", flush=True)


if __name__ == "__main__":
    main()
