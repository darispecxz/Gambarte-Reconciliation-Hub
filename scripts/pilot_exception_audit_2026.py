"""Review-only reconciliation exception audit from the isolated pilot.

Creates private exception detail and aggregate summaries; never changes pilot
or source records. Currency mismatches and payment timestamps are review
signals, not proof of financial discrepancy or late payment.
"""
import argparse
import csv
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.infrastructure.models import Remittance, Payment
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker
from scripts.pilot_operation_detail_2026 import detail_rows, safe_csv_value
from scripts.management_report_2026 import EXPORT_DIR

FIELDS = (
    "priority", "flags", "direction", "category", "reason", "code",
    "origin_id", "origin_date", "origin_status", "origin_type",
    "origin_amount", "origin_currency", "destination_id", "destination_date",
    "destination_type", "destination_amount", "destination_currency",
    "difference", "payment_candidates", "unexpected_payment_types",
    "delta_minutes_unadjusted", "cutoff", "certified",
)
SUMMARY_FIELDS = ("dimension", "value", "operations", "certified")


def validate_destination(path):
    dest = Path(path)
    if not dest.is_absolute() or dest.parent != EXPORT_DIR or dest.suffix.lower() != ".csv":
        raise ValueError("CSV must be directly under /export")
    if not EXPORT_DIR.is_dir() or dest.parent.resolve(strict=True) != EXPORT_DIR.resolve(strict=True):
        raise RuntimeError("Mount a private /export directory")
    if dest.is_symlink():
        raise ValueError("Symlink destination refused")
    return dest


def analyze(rows, cutoff):
    exceptions = []
    metrics = Counter()
    for row in rows:
        category = row["category"]
        flags = []
        if category != "PROVISIONAL_CODE_PAIR":
            flags.append(category)
        if category == "NO_PAYMENT_IN_SAMPLE" and row["origin_status"] == "PAID":
            flags.append("PAID_WITHOUT_MATCH_IN_PILOT")
        same_currency = (row["origin_currency"] and row["destination_currency"]
                         and row["origin_currency"] == row["destination_currency"])
        if category == "PROVISIONAL_CODE_PAIR" and not same_currency:
            flags.append("CROSS_CURRENCY_FX_UNVERIFIED")
        if category == "PROVISIONAL_CODE_PAIR" and same_currency and row["difference"]:
            if Decimal(str(row["difference"])) != 0:
                flags.append("SAME_CURRENCY_AMOUNT_DIFFERENCE")
        delta_minutes = ""
        if category == "PROVISIONAL_CODE_PAIR" and row["destination_date"] and row["origin_date"]:
            delta = (datetime.fromisoformat(row["destination_date"])
                     - datetime.fromisoformat(row["origin_date"])).total_seconds() / 60
            delta_minutes = str(round(delta, 2))
            # Neither origin nor destination timestamps are timezone-normalized.
            if delta < 0:
                flags.append("PAYMENT_BEFORE_ORIGIN_UNNORMALIZED")
            elif delta > 30 * 24 * 60:
                flags.append("PAYMENT_OVER_30_DAYS_UNNORMALIZED")
            elif delta > 7 * 24 * 60:
                flags.append("PAYMENT_OVER_7_DAYS_UNNORMALIZED")
        metrics[("direction", row["direction"])] += 1
        metrics[("category", category)] += 1
        if not flags:
            continue
        priority = ("HIGH_REVIEW" if category.startswith("MANUAL_REVIEW_")
                    or "PAID_WITHOUT_MATCH_IN_PILOT" in flags
                    or "SAME_CURRENCY_AMOUNT_DIFFERENCE" in flags
                    else "REVIEW")
        record = {field: row.get(field, "") for field in FIELDS}
        record.update(priority=priority, flags="|".join(flags),
                      delta_minutes_unadjusted=delta_minutes,
                      cutoff=cutoff.isoformat(), certified="False")
        exceptions.append(record)
        for flag in flags:
            metrics[("flag", flag)] += 1
    metrics[("total", "origin_remittances")] = len(rows)
    metrics[("total", "flagged_origin_remittances")] = len(exceptions)
    return exceptions, [
        {"dimension": dim, "value": key, "operations": count, "certified": "False"}
        for (dim, key), count in sorted(metrics.items())
    ]


def load_pilot(cutoff):
    s = get_settings()
    if ((s.db_host, s.db_name) != (PILOT_HOST, PILOT_DB)
            or s.enable_source_etl or s.source_mapping_verified):
        raise RuntimeError("Only isolated pilot with source ETL disabled is permitted")
    db = pilot_engine(s)
    try:
        with db.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                rems = con.execute(select(
                    Remittance.source_record_id, Remittance.source,
                    Remittance.code, Remittance.operation_type, Remittance.status,
                    Remittance.amount, Remittance.currency, Remittance.occurred_at,
                )).all()
                pays = con.execute(select(
                    Payment.source_record_id, Payment.source,
                    Payment.code, Payment.operation_type, Payment.amount,
                    Payment.currency, Payment.occurred_at,
                )).all()
                return detail_rows(rems, pays, cutoff)
            finally:
                con.rollback()
    finally:
        db.dispose()


def write_csv(path, fields, data):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: safe_csv_value(row.get(key, "")) for key in fields}
                         for row in data)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--through", required=True, type=date.fromisoformat)
    p.add_argument("--output", required=True, help="Private exception CSV under /export")
    args = p.parse_args()
    if args.through.year != 2026 or args.through > date.today():
        p.error("Cutoff must be in 2026 and cannot be in the future")
    destination = validate_destination(args.output)
    summary_path = validate_destination(str(destination.with_name(
        destination.stem + "_resumen.csv")))
    if summary_path == destination:
        raise ValueError("Summary must differ from detail")
    data = load_pilot(args.through)
    exceptions, summary = analyze(data, args.through)
    write_csv(destination, FIELDS, exceptions)
    write_csv(summary_path, SUMMARY_FIELDS, summary)
    categories = Counter(row["category"] for row in data)
    print(f"analyzed={len(data)} provisional_pairs={categories['PROVISIONAL_CODE_PAIR']} "
          f"flagged_distinct={len(exceptions)} summary_rows={len(summary)} "
          "coverage_certified=False source_connections=0 "
          "source_writes=False pilot_writes=False", flush=True)
    print(f"files_created={destination.name},{summary_path.name} private_export=True",
          flush=True)


if __name__ == "__main__":
    main()
