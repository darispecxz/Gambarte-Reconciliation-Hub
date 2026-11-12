"""Manual, bounded single-month coordinator for the isolated 2026 pilot.

No scheduler, no annual loop. Uses existing atomic per-page checkpoints,
one source/dataset at a time, with per-invocation rate limits and an
integrity audit after each applied batch. Independent COUNT verification
runs after scan exhaustion. Any error/mismatch aborts immediately.

Default --verify-only: independent READ ONLY COUNT for exhausted datasets.
--apply explicitly opts in to importing up to N x 100 rows into pilot.
"""
import argparse
from time import sleep

from app.core.config import get_settings
from scripts.pilot_backfill_2026 import (
    execute, month_window, validate_request,
)
from scripts.pilot_backfill_status import DATASETS
from scripts.pilot_import import PILOT_DB, PILOT_HOST
from scripts.pilot_month_count import run as verify_month
from scripts.pilot_audit import run as audit


def selected_datasets(source, dataset):
    return [(s, d) for s, d in DATASETS
            if (source == "ALL" or s == source)
            and (dataset == "all" or d == dataset)]


def check_request(month, source, dataset, apply, ack, max_batches, pause,
                  limit, pages):
    settings = get_settings()
    month_window(month)
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Runner refuses non-pilot destination")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL and mapping verification must remain disabled")
    if source not in {"ALL", "BOLIVIA", "CHILE"} or dataset not in {
            "all", "remittance", "payment"}:
        raise ValueError("Invalid source/dataset")
    if not 1 <= max_batches <= 5 or not 0 <= pause <= 30:
        raise ValueError("Safety limits: max-batches 1..5, pause-seconds 0..30")
    if not 1 <= limit <= 50 or not 1 <= pages <= 2:
        raise ValueError("Safety limits: limit 1..50, pages 1..2")
    if apply and not ack:
        raise ValueError("--apply requires --acknowledge-sensitive-data")
    for s, d in selected_datasets(source, dataset):
        validate_request(settings, s, d, month, limit, pages, apply, ack)


def verified_result(result, source, dataset, month):
    if not result.get("counted"):
        raise RuntimeError(f"{month} {source}/{dataset}: count not executed")
    if result.get("status") != "COUNT_MATCH_NOT_CERTIFIED":
        raise RuntimeError(
            f"{month} {source}/{dataset}: verification incomplete or mismatch "
            f"({result.get('status')})"
        )


def run(month, source="ALL", dataset="all", apply=False,
        acknowledge=False, max_batches=5, pause_seconds=2,
        limit=50, pages=2):
    check_request(month, source, dataset, apply, acknowledge,
                  max_batches, pause_seconds, limit, pages)
    pairs = selected_datasets(source, dataset)
    print(f"runner_month={month} datasets={len(pairs)} "
          f"mode={'PILOT_WRITE' if apply else 'VERIFY_ONLY'} "
          f"max_batches={max_batches} max_rows_per_batch={limit*pages} "
          "production_writes=False annual_automation=False")
    results = {}
    for s, d in pairs:
        print(f"dataset_started={month}/{s}/{d}")
        exhausted = False
        if apply:
            for batch in range(max_batches):
                result = execute(
                    s, d, month, limit=limit, pages=pages,
                    apply=True, acknowledge=True,
                )
                audit()
                exhausted = bool(result.get("exhausted"))
                print(f"dataset_batch={batch+1} source={s} dataset={d} "
                      f"rows={result.get('rows', 0)} exhausted={exhausted} "
                      "pilot_audit_passed=True")
                if exhausted:
                    break
                if batch + 1 < max_batches:
                    sleep(pause_seconds)
            if not exhausted:
                print(f"dataset_paused={month}/{s}/{d} "
                      "reason=MAX_BATCHES_REACHED resume_with_same_command=True")
                results[(s, d)] = "IN_PROGRESS"
                # Do not run expensive source COUNT for incomplete datasets.
                continue
        comparison = verify_month(s, d, month, count=True)
        verified_result(comparison, s, d, month)
        results[(s, d)] = comparison["status"]
        print(f"dataset_verified={month}/{s}/{d} "
              "status=COUNT_MATCH_NOT_CERTIFIED")
    print("runner_finished=True coverage_certified=False "
          "historical_corrections_checked=False")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="2026-MM (one month only)")
    parser.add_argument("--source", choices=("ALL", "BOLIVIA", "CHILE"),
                        default="ALL")
    parser.add_argument("--dataset", choices=("all", "remittance", "payment"),
                        default="all")
    parser.add_argument("--apply", action="store_true",
                        help="Opt in to capped pilot writes")
    parser.add_argument("--acknowledge-sensitive-data", action="store_true")
    parser.add_argument("--max-batches", type=int, default=5)
    parser.add_argument("--pause-seconds", type=float, default=2)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--pages", type=int, default=2)
    args = parser.parse_args()
    run(args.month, args.source, args.dataset, args.apply,
        args.acknowledge_sensitive_data, args.max_batches,
        args.pause_seconds, args.limit, args.pages)


if __name__ == "__main__":
    main()
