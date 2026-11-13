"""Explicit, bounded, resumable 2026 pilot backfill across country/dataset/month.

Reads source databases only through pilot_backfill_2026's guarded, read-only
queries. Writes only to the isolated local pilot and never certifies coverage.
Stops on the first source-plan rejection or any other error.
"""
import argparse
from datetime import date
from time import sleep

from sqlalchemy import text

from app.core.config import get_settings
from scripts.pilot_backfill_2026 import (
    execute, month_window, pilot_engine, checkpoint_params, read_checkpoint,
)
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker

PAIRS = (
    ("BOLIVIA", "remittance"),
    ("BOLIVIA", "payment"),
    ("CHILE", "remittance"),
    ("CHILE", "payment"),
)


def read_progress(settings):
    """Fetch checkpoints from the pilot only; no source DB connection."""
    engine = pilot_engine(settings)
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                exists = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'pilot_backfill_progress'
                """)).scalar_one()
                if not exists:
                    return {}
                rows = conn.execute(text("""
                    SELECT source, dataset, month_key, rows_seen, pages_seen,
                           scan_exhausted
                    FROM pilot_backfill_progress
                """)).mappings().all()
                return {(r["source"], r["dataset"], r["month_key"]): dict(r)
                        for r in rows}
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def run(max_batches=30, pause_seconds=3, through_month=None,
        apply=False, acknowledge=False):
    if not 1 <= max_batches <= 200:
        raise ValueError("--max-batches must be between 1 and 200")
    if not 2 <= pause_seconds <= 60:
        raise ValueError("--pause-seconds must be between 2 and 60")
    if not apply or not acknowledge:
        raise ValueError("Explicit --apply and --acknowledge-sensitive-data required")
    settings = get_settings()
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Refusing non-isolated pilot destination")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL and mapping verification must remain disabled")
    current_month = date.today().strftime("%Y-%m")
    end_month = through_month or current_month
    month_window(end_month)
    if end_month > current_month:
        raise ValueError("Cannot process a future month")

    checkpoints = read_progress(settings)
    jobs = [(source, dataset, f"2026-{month:02d}")
            for month in range(1, int(end_month[5:7]) + 1)
            for source, dataset in PAIRS]
    completed = 0
    skipped = 0
    batches = 0
    rows = 0
    try:
        for source, dataset, month in jobs:
            key = (source, dataset, month)
            saved = checkpoints.get(key, {})
            if saved.get("scan_exhausted"):
                skipped += 1
                print(f"skip={source}/{dataset}/{month} status=SCAN_EXHAUSTED_NOT_CERTIFIED "
                      f"rows_seen={saved.get('rows_seen', 0)}", flush=True)
                continue
            print(f"starting={source}/{dataset}/{month}", flush=True)
            while True:
                if batches >= max_batches:
                    print(f"batch_limit_reached={max_batches} "
                          "remaining_jobs_not_processed=True", flush=True)
                    return {"batches": batches, "rows": rows,
                            "completed": completed, "skipped": skipped,
                            "limit_reached": True}
                # This function enforces EXPLAIN and a hard 2 pages x 50 rows
                # per invocation, with atomic cursor updates in the pilot.
                outcome = execute(source, dataset, month, limit=50, pages=2,
                                  apply=True, acknowledge=True)
                batches += 1
                rows += outcome.get("rows", 0)
                if outcome.get("exhausted"):
                    completed += 1
                    print(f"finished={source}/{dataset}/{month} "
                          "coverage_certified=False", flush=True)
                    break
                sleep(pause_seconds)
        return {"batches": batches, "rows": rows,
                "completed": completed, "skipped": skipped,
                "limit_reached": False}
    finally:
        print(f"summary batches={batches} selected_rows={rows} "
              f"jobs_completed_now={completed} jobs_already_exhausted={skipped} "
              "coverage_certified=False source_writes=False", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through-month", help="Last month YYYY-MM (default current month)")
    parser.add_argument("--max-batches", type=int, default=30,
                        help="Maximum number of guarded 2-page batch calls (1..200)")
    parser.add_argument("--pause-seconds", type=int, default=3,
                        help="Delay between non-final batches (2..60)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-sensitive-data", action="store_true")
    args = parser.parse_args()
    run(args.max_batches, args.pause_seconds, args.through_month,
        args.apply, args.acknowledge_sensitive_data)


if __name__ == "__main__":
    main()
