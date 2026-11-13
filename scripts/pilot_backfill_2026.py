"""Bounded, resumable calendar-month 2026 backfill to isolated pilot ONLY.

One country/dataset/month per command; source READ ONLY, EXPLAIN first,
and a hard cap of 2 pages * 50 records per invocation. Progress checkpoints
are stored atomically alongside ingested records in the pilot DB and DO NOT
certify source coverage. No automatic workers or recurring scheduling.
"""
import argparse
from datetime import date, datetime
import re
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.ingestion import ingest
from app.integrations.source import SQL, normalize, read_only_transaction, validate_read_query
from scripts.pilot_import import (
    PILOT_DB, PILOT_HOST, check_marker, connect_source,
)
from scripts.preflight_source import inspect_page, key_for, next_cursor_params

DATE_FILTERS = {
    ("BOLIVIA", "remittance"): (
        "(r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)",
        "(r.fec_crea_remesa >= :from_date AND r.fec_crea_remesa < :to_date)"),
    ("CHILE", "remittance"): (
        "(r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)",
        "(r.fec_crea_remesa >= :from_date AND r.fec_crea_remesa < :to_date)"),
    ("BOLIVIA", "payment"): (
        "p.fec_crea_pago >= :cutoff",
        "(p.fec_crea_pago >= :from_date AND p.fec_crea_pago < :to_date)"),
    ("CHILE", "payment"): (
        "p.fec_crea_pago >= :cutoff",
        "(p.fec_crea_pago >= :from_date AND p.fec_crea_pago < :to_date)"),
}

CHECKPOINT_SQL = """
CREATE TABLE IF NOT EXISTS pilot_backfill_progress (
    source VARCHAR(20) NOT NULL,
    dataset VARCHAR(20) NOT NULL,
    month_key CHAR(7) NOT NULL,
    last_id BIGINT NOT NULL DEFAULT 0,
    last_op INTEGER NOT NULL DEFAULT 0,
    last_code BIGINT NOT NULL DEFAULT 0,
    last_dest INTEGER NOT NULL DEFAULT 0,
    rows_seen BIGINT NOT NULL DEFAULT 0,
    pages_seen INTEGER NOT NULL DEFAULT 0,
    scan_exhausted BOOLEAN NOT NULL DEFAULT FALSE,
    changed_at DATETIME NOT NULL,
    PRIMARY KEY (source, dataset, month_key)
) ENGINE=InnoDB
"""

PROGRESS_SQL = text("""
SELECT last_id, last_op, last_code, last_dest, rows_seen,
       pages_seen, scan_exhausted FROM pilot_backfill_progress
WHERE source=:source AND dataset=:dataset AND month_key=:month_key
""")
LOCK_SQL = text(str(PROGRESS_SQL) + " FOR UPDATE")
INSERT_PROGRESS_SQL = text("""
INSERT INTO pilot_backfill_progress
(source,dataset,month_key,last_id,last_op,last_code,last_dest,
 rows_seen,pages_seen,scan_exhausted,changed_at)
VALUES (:source,:dataset,:month_key,0,0,0,0,0,0,0,UTC_TIMESTAMP())
""")
UPDATE_PROGRESS_SQL = text("""
UPDATE pilot_backfill_progress
SET last_id=:last_id, last_op=:last_op, last_code=:last_code,
    last_dest=:last_dest, rows_seen=rows_seen+:row_count,
    pages_seen=pages_seen+1, scan_exhausted=:exhausted,
    changed_at=UTC_TIMESTAMP()
WHERE source=:source AND dataset=:dataset AND month_key=:month_key
""")
ZERO = {"last_id": 0, "last_op": 0, "last_code": 0, "last_dest": 0,
        "rows_seen": 0, "pages_seen": 0, "scan_exhausted": False}


def month_window(month_key: str, today: date | None = None):
    today = today or date.today()
    if len(month_key) != 7 or month_key[4] != "-" or not (
        month_key[:4].isdigit() and month_key[5:].isdigit()
    ):
        raise ValueError("Month must be YYYY-MM")
    year, month = int(month_key[:4]), int(month_key[5:])
    if year != 2026 or not 1 <= month <= 12:
        raise ValueError("Pilot backfill supports 2026 months only")
    start = date(year, month, 1)
    if start > today:
        raise ValueError("Future month is not allowed")
    end = date(year + (month == 12), month % 12 + 1, 1)
    return datetime.combine(start, datetime.min.time()), datetime.combine(
        end, datetime.min.time()
    )


def historical_sql(source: str, dataset: str):
    pair = (source, dataset)
    if pair not in DATE_FILTERS:
        raise ValueError("Unsupported source dataset")
    original, replacement = DATE_FILTERS[pair]
    base = SQL[pair]
    if base.count(original) != 1:
        raise RuntimeError("Source SQL date clause changed; review backfill contract")
    sql = base.replace(original, replacement)
    validate_read_query(sql)
    return sql


def validate_request(settings, source, dataset, month_key, limit, pages, apply, ack):
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Both ETL and source mapping must remain disabled")
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Refusing a non-pilot destination")
    month_window(month_key)
    if (source, dataset) not in SQL:
        raise ValueError("Unknown source/dataset")
    if not 1 <= limit <= 50 or not 1 <= pages <= 2:
        raise ValueError("Limit must be 1..50 and pages 1..2")
    if apply and not ack:
        raise ValueError("Import requires --acknowledge-sensitive-data")


def source_plan_guard(plan):
    if not plan:
        raise RuntimeError("EXPLAIN returned no plan")
    for row in plan:
        access = str(row.get("type") or "")
        key = row.get("key")
        # Some MariaDB EXPLAIN variants encode an estimated row count as
        # '430 (11%)'. Only accept a plain non-negative integer with an
        # optional percentage; reject anything else rather than bypass safety.
        raw_rows = row.get("rows")
        if isinstance(raw_rows, int) and not isinstance(raw_rows, bool):
            estimate = raw_rows
        else:
            matched = re.fullmatch(
                r"\\s*(\\d+)(?:\\s+\\(\\d+(?:\\.\\d+)?%\\))?\\s*",
                str(raw_rows) if raw_rows is not None else "",
            )
            if not matched:
                raise RuntimeError("Backfill refused: unexpected EXPLAIN rows estimate")
            estimate = int(matched.group(1))
        extra = str(row.get("Extra") or "")
        if not key or access in {"ALL", "index"}:
            raise RuntimeError("Backfill refused: unindexed source plan")
        if estimate > 500_000 or (estimate > 100_000 and "filesort" in extra.lower()):
            raise RuntimeError("Backfill refused: costly source EXPLAIN plan")


def pilot_engine(settings):
    return create_engine(URL.create(
        "mysql+pymysql", host=settings.db_host, port=settings.db_port,
        username=settings.db_user, password=settings.db_password,
        database=settings.db_name, query={"charset": "utf8mb4"},
    ), connect_args={"connect_timeout": 10, "read_timeout": 30})


def checkpoint_params(source, dataset, month_key):
    return {"source": source, "dataset": dataset, "month_key": month_key}


def read_checkpoint(conn, identity):
    return dict(conn.execute(PROGRESS_SQL, identity).mappings().first() or ZERO)


def execute(source: str, dataset: str, month_key: str, limit=50,
            pages=1, apply=False, acknowledge=False):
    settings = get_settings()
    validate_request(settings, source, dataset, month_key, limit, pages, apply,
                     acknowledge)
    start, end = month_window(month_key)
    sql = historical_sql(source, dataset)
    identity = checkpoint_params(source, dataset, month_key)
    central = pilot_engine(settings)
    remote = None
    try:
        # Always verify the isolation marker before even considering writes.
        with central.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                has_table = con.execute(text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='pilot_backfill_progress'
                """)).scalar_one()
                checkpoint = read_checkpoint(con, identity) if has_table else dict(ZERO)
            finally:
                con.rollback()
        if checkpoint["scan_exhausted"]:
            print(f"source={source} dataset={dataset} month={month_key} "
                  "status=SCAN_EXHAUSTED_NOT_CERTIFIED")
            return {"exhausted": True, "rows": 0}

        params = {
            "from_date": start, "to_date": end, "last_id": checkpoint["last_id"],
            "last_op": checkpoint["last_op"], "last_code": checkpoint["last_code"],
            "last_dest": checkpoint["last_dest"], "lim": limit,
        }
        remote = connect_source(settings, source)
        total = changed = 0
        for page_index in range(pages):
            with read_only_transaction(remote) as source_conn:
                plan = source_conn.execute(text("EXPLAIN " + sql), params).mappings().all()
                source_plan_guard(plan)
                print("source_explain=" + ",".join(
                    f"{p.get('type')}/{p.get('key')}/{p.get('rows')}" for p in plan))
                tick = perf_counter()
                raw_rows = source_conn.execute(text(sql), params).mappings().all()
                elapsed = perf_counter() - tick
                inspect_page(source, dataset, raw_rows)
                previous = ((params["last_op"], params["last_code"], params["last_dest"])
                            if (source, dataset) == ("CHILE", "remittance")
                            else (params["last_id"], params["last_op"]))
                if raw_rows and key_for(source, dataset, raw_rows[0]) <= previous:
                    raise RuntimeError("Backfill page overlaps committed cursor")
                normalized = [normalize(source, dataset, dict(row)) for row in raw_rows]

            next_params = (next_cursor_params(source, dataset, raw_rows[-1], params)
                           if raw_rows else dict(params))
            # Exactly limit rows => next page may be empty. Only a short page
            # demonstrates exhaustion, not proof of historical completeness.
            exhausted = len(raw_rows) < limit

            if apply:
                # Only create the checkpoint table AFTER checking the marker.
                # DDL stays inside the dedicated local pilot database.
                if not has_table:
                    with central.connect() as con:
                        check_marker(con)
                        con.execute(text(CHECKPOINT_SQL))
                        con.commit()
                    has_table = True
                with Session(central) as session:
                    with session.begin():
                        check_marker(session.connection())
                        # A row lock prevents competing runs on this same
                        # month/dataset from advancing a stale checkpoint.
                        saved = session.execute(LOCK_SQL, identity).mappings().first()
                        if saved is None:
                            if checkpoint != ZERO:
                                raise RuntimeError("Backfill checkpoint unexpectedly missing")
                            session.execute(INSERT_PROGRESS_SQL, identity)
                            saved = session.execute(LOCK_SQL, identity).mappings().one()
                        for field, param in (("last_id", "last_id"), ("last_op", "last_op"),
                                             ("last_code", "last_code"), ("last_dest", "last_dest")):
                            if int(saved[field]) != int(params[param]):
                                raise RuntimeError("Concurrent pilot import detected; retry")
                        if saved["scan_exhausted"]:
                            raise RuntimeError("Concurrent pilot scan completion detected")
                        n_changed = 0
                        for record in normalized:
                            if ingest(session, record):
                                n_changed += 1
                        session.execute(UPDATE_PROGRESS_SQL, {
                            **identity,
                            "last_id": next_params["last_id"],
                            "last_op": next_params["last_op"],
                            "last_code": next_params["last_code"],
                            "last_dest": next_params["last_dest"],
                            "row_count": len(normalized),
                            "exhausted": int(exhausted),
                        })
                changed += n_changed
            total += len(raw_rows)
            print(f"month={month_key} source={source} dataset={dataset} "
                  f"page={page_index+1} rows={len(raw_rows)} "
                  f"elapsed_seconds={elapsed:.3f} "
                  f"writes_to_pilot={apply} scan_exhausted={exhausted}")
            if not apply:
                # Dry run is always one page, no persisted cursor.
                break
            params = next_params
            if exhausted:
                break

        print(f"selected_rows={total} changed_pilot_rows={changed} "
              f"scope=monthly_sample_only coverage_certified=False")
        return {"rows": total, "changed": changed,
                "exhausted": exhausted, "applied": apply}
    finally:
        if remote is not None:
            remote.dispose()
        central.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, choices=("BOLIVIA", "CHILE"))
    p.add_argument("--dataset", required=True, choices=("remittance", "payment"))
    p.add_argument("--month", required=True, help="2026-MM")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--acknowledge-sensitive-data", action="store_true")
    args = p.parse_args()
    execute(args.source, args.dataset, args.month, args.limit, args.pages,
            args.apply, args.acknowledge_sensitive_data)


if __name__ == "__main__":
    main()
