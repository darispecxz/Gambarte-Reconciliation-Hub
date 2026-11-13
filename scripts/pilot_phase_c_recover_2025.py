"""Recover only unique, cross-year 2025 remittances behind 2026 pilot payments.

Explicit manual opt-in. Sources always READ ONLY + guarded EXPLAIN.
Only the marked, isolated pilot may be written with --apply and acknowledgement.
No 2025 bulk backfill, no historical scan checkpoint, no certification.
"""
import argparse
from collections import Counter
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.operation_types import allowed_destination_payment_types
from app.infrastructure.ingestion import ingest
from app.integrations.source import normalize, read_only_transaction
from scripts.pilot_backfill_2026 import pilot_engine, source_plan_guard
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.pilot_phase_c_integrity_2026 import collect
from scripts.pilot_phase_c_source_lookup_2026 import (
    PAGE_LIMIT, SOURCE_FOR_DIRECTION, targeted_sql, validate_code,
)
from scripts.preflight_source import inspect_page


def pending_cases(exceptions, max_codes):
    """Return only cases with one non-return destination payment per code."""
    if not 1 <= max_codes <= 25:
        raise ValueError("max-codes must be 1..25")
    selected = {}
    for item in exceptions:
        if item["assessment"] != "NO_ORIGIN_IN_PILOT":
            continue
        direction = item["direction"]
        if direction not in SOURCE_FOR_DIRECTION:
            raise RuntimeError("Unexpected direction")
        code = validate_code(item["payment_code"])
        key = (direction, code)
        if key in selected:
            raise RuntimeError("Multiple payments per code: manual review required")
        if int(item["same_code_payment_candidates"]) != 1:
            raise RuntimeError("Duplicate payment code requires manual review")
        selected[key] = dict(direction=direction, code=code,
                             payment_type=int(item["payment_type"]),
                             payment_source=item["payment_source"])
    if len(selected) > max_codes:
        raise RuntimeError(f"{len(selected)} pending codes exceed max-codes={max_codes}")
    return [selected[key] for key in sorted(selected)]


def verify_recovery(case, raw):
    """Fail closed unless one 2025 remittance matches the 2026 payment modality."""
    if len(raw) != 1:
        return "REVIEW_SOURCE_ROW_COUNT"
    record = raw[0]
    if str(record["code"]).strip() != case["code"]:
        return "REVIEW_CODE_MISMATCH"
    created = record.get("occurred_at")
    if created is None or created.year != 2025:
        return "REVIEW_NOT_2025"
    origin = SOURCE_FOR_DIRECTION[case["direction"]]
    dest = "CHILE" if origin == "BOLIVIA" else "BOLIVIA"
    if case["payment_source"] != dest:
        return "REVIEW_DIRECTION_MISMATCH"
    allowed = allowed_destination_payment_types(
        origin, dest, int(record["operation_type"]))
    if allowed is None or case["payment_type"] not in allowed:
        return "REVIEW_PAYMENT_MODALITY"
    if int(record["source_pk"]) <= 0:
        return "REVIEW_SOURCE_ID"
    return "ELIGIBLE_2025_SOURCE"


def run(through, max_codes=25, apply=False, acknowledge=False):
    if not date(2026, 1, 1) <= through <= date.today():
        raise ValueError("Only reached 2026 cutoffs supported")
    if apply and not acknowledge:
        raise ValueError("--apply requires --acknowledge-sensitive-data")
    settings = get_settings()
    if ((settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Refusing non-isolated pilot or enabled ETL")

    # The inverse report excludes confirmed local Bolivia returns by motive.
    exceptions, _, _ = collect(through)
    cases = pending_cases(exceptions, max_codes)
    pilot = pilot_engine(settings)
    remotes = {}
    counts = Counter()
    changed = 0
    print(f"phase_c_recovery=True candidates={len(cases)} dry_run={not apply} "
          "source_read_only=True coverage_certified=False", flush=True)
    try:
        with pilot.connect() as connection:
            try:
                connection.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(connection)
            finally:
                connection.rollback()
        for index, case in enumerate(cases, 1):
            origin = SOURCE_FOR_DIRECTION[case["direction"]]
            if origin not in remotes:
                remotes[origin] = connect_source(settings, origin)
            params = dict(code=case["code"], last_id=0, last_op=0,
                          last_code=0, last_dest=0, lim=PAGE_LIMIT)
            query = targeted_sql(origin)
            # Do not mask unindexed or failed reads as missing records.
            with read_only_transaction(remotes[origin]) as source_conn:
                plan = source_conn.execute(text("EXPLAIN " + query),
                                           params).mappings().all()
                source_plan_guard(plan)
                raw = source_conn.execute(text(query), params).mappings().all()
                inspect_page(origin, "remittance", raw)
                if len(raw) >= PAGE_LIMIT:
                    raise RuntimeError("Source returned full per-code page; refusing partial import")
                verdict = verify_recovery(case, raw)
                normalized = (normalize(origin, "remittance", dict(raw[0]))
                              if verdict == "ELIGIBLE_2025_SOURCE" else None)
            counts[verdict] += 1
            # Only an explicitly eligible record is inserted or updated.
            if apply and normalized is not None:
                with Session(pilot) as session:
                    with session.begin():
                        check_marker(session.connection())
                        changed += int(ingest(session, normalized))
            print(f"checked={index}/{len(cases)} source={origin} "
                  f"verdict={verdict} pilot_changed_rows={changed} "
                  "source_writes=False", flush=True)
        print(f"summary={dict(sorted(counts.items()))} pilot_changed_rows={changed} "
              f"pilot_writes={apply} source_writes=False coverage_certified=False",
              flush=True)
        return counts
    finally:
        for engine in remotes.values():
            engine.dispose()
        pilot.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--max-codes", type=int, default=25)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-sensitive-data", action="store_true")
    args = parser.parse_args()
    run(args.through, args.max_codes, args.apply, args.acknowledge_sensitive_data)


if __name__ == "__main__":
    main()
