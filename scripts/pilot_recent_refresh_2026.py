"""Opt-in, bounded, resumable recent-window refresh to the isolated pilot.

Four source/dataset pairs. A new daily window intentionally overlaps earlier
windows to catch late arrivals and source remittance status changes. Historical
backfill checkpoints are never altered. Sources are read-only, EXPLAIN guarded.
No scheduling, no full-coverage or financial certification.
"""
import argparse
from datetime import date, datetime, timedelta
from time import sleep

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.ingestion import ingest
from app.integrations.source import SQL, normalize, read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine, source_plan_guard
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.preflight_source import inspect_page, key_for, next_cursor_params

PAIRS = (("BOLIVIA", "remittance"), ("BOLIVIA", "payment"),
         ("CHILE", "remittance"), ("CHILE", "payment"))
PAGE_LIMIT = 50
DDL = """
CREATE TABLE IF NOT EXISTS pilot_recent_refresh_progress (
 source VARCHAR(20) NOT NULL, dataset VARCHAR(20) NOT NULL,
 as_of_date DATE NOT NULL, lookback_days INT NOT NULL,
 last_id BIGINT NOT NULL DEFAULT 0, last_op INT NOT NULL DEFAULT 0,
 last_code BIGINT NOT NULL DEFAULT 0, last_dest INT NOT NULL DEFAULT 0,
 rows_seen BIGINT NOT NULL DEFAULT 0, pages_seen INT NOT NULL DEFAULT 0,
 scan_exhausted BOOLEAN NOT NULL DEFAULT FALSE,
 changed_at DATETIME NOT NULL,
 PRIMARY KEY (source, dataset, as_of_date, lookback_days)
) ENGINE=InnoDB
"""
SELECT_PROGRESS = text("""
SELECT last_id,last_op,last_code,last_dest,rows_seen,pages_seen,scan_exhausted
FROM pilot_recent_refresh_progress
WHERE source=:source AND dataset=:dataset
  AND as_of_date=:as_of_date AND lookback_days=:lookback_days
""")
INSERT_PROGRESS = text("""
INSERT INTO pilot_recent_refresh_progress
(source,dataset,as_of_date,lookback_days,last_id,last_op,last_code,last_dest,
 rows_seen,pages_seen,scan_exhausted,changed_at)
VALUES (:source,:dataset,:as_of_date,:lookback_days,0,0,0,0,0,0,0,UTC_TIMESTAMP())
""")
ADVANCE_PROGRESS = text("""
UPDATE pilot_recent_refresh_progress
SET last_id=:last_id,last_op=:last_op,last_code=:last_code,last_dest=:last_dest,
    rows_seen=rows_seen+:row_count,pages_seen=pages_seen+1,
    scan_exhausted=:scan_exhausted,changed_at=UTC_TIMESTAMP()
WHERE source=:source AND dataset=:dataset
  AND as_of_date=:as_of_date AND lookback_days=:lookback_days
""")
ZERO = dict(last_id=0,last_op=0,last_code=0,last_dest=0,rows_seen=0,
            pages_seen=0,scan_exhausted=False)


def recent_sql(source, dataset):
    pair = (source, dataset)
    if pair not in PAIRS:
        raise ValueError("Unsupported source/dataset")
    original = ("(r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)"
                if dataset == "remittance" else "p.fec_crea_pago >= :cutoff")
    replacement = (
        "((r.fec_crea_remesa >= :from_date AND r.fec_crea_remesa < :to_date) "
        "OR (r.fec_mod_remesa >= :from_date AND r.fec_mod_remesa < :to_date))"
        if dataset == "remittance" else
        "(p.fec_crea_pago >= :from_date AND p.fec_crea_pago < :to_date)"
    )
    base = SQL[pair]
    if base.count(original) != 1:
        raise RuntimeError("Source query changed; review required before refreshing")
    statement = base.replace(original, replacement)
    validate_read_query(statement)
    return statement


def validate(settings, as_of, days, max_pages, pause, apply, ack):
    if ((settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Refusing anything except isolated pilot with ETL disabled")
    if not date(2026, 1, 1) <= as_of <= date.today():
        raise ValueError("--as-of must be a reached date in 2026")
    if not 1 <= days <= 14 or not 1 <= max_pages <= 200 or not 2 <= pause <= 60:
        raise ValueError("Limits: days 1..14, max-pages 1..200, pause 2..60")
    if apply and not ack:
        raise ValueError("--apply requires --acknowledge-sensitive-data")


def check_table(pilot):
    with pilot.connect() as conn:
        try:
            conn.exec_driver_sql("START TRANSACTION READ ONLY")
            check_marker(conn)
            present = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE()
                AND TABLE_NAME='pilot_recent_refresh_progress'
            """)).scalar_one()
            return bool(present)
        finally:
            conn.rollback()


def create_table(pilot):
    # Only isolated pilot DDL, never source databases.
    with pilot.begin() as conn:
        check_marker(conn)
        conn.execute(text(DDL))


def current_progress(pilot, identity):
    with pilot.connect() as conn:
        try:
            conn.exec_driver_sql("START TRANSACTION READ ONLY")
            check_marker(conn)
            return dict(conn.execute(SELECT_PROGRESS, identity).mappings().first() or ZERO)
        finally:
            conn.rollback()


def validate_cursor(previous, new, source, dataset):
    old_key = ((previous["last_op"], previous["last_code"], previous["last_dest"])
               if (source, dataset) == ("CHILE", "remittance") else
               (previous["last_id"], previous["last_op"]))
    if new and key_for(source, dataset, new[0]) <= old_key:
        raise RuntimeError("Refusing overlapping or regressed source keyset")


def save_page(pilot, identity, previous, params, data, exhausted):
    with Session(pilot) as session:
        with session.begin():
            check_marker(session.connection())
            saved = session.execute(text(str(SELECT_PROGRESS) + " FOR UPDATE"),
                                    identity).mappings().first()
            if saved is None:
                if previous != ZERO:
                    raise RuntimeError("Checkpoint disappeared; refusing stale cursor")
                session.execute(INSERT_PROGRESS, identity)
                saved = session.execute(text(str(SELECT_PROGRESS) + " FOR UPDATE"),
                                        identity).mappings().one()
            for field in ("last_id", "last_op", "last_code", "last_dest"):
                if int(saved[field]) != int(previous[field]):
                    raise RuntimeError("Concurrent refresh detected; abort")
            if saved["scan_exhausted"]:
                raise RuntimeError("Window already exhausted by concurrent refresh")
            changed = sum(bool(ingest(session, record)) for record in data)
            session.execute(ADVANCE_PROGRESS, {
                **identity, **{field: params[field] for field in
                               ("last_id","last_op","last_code","last_dest")},
                "row_count": len(data), "scan_exhausted": int(exhausted),
            })
            return changed


def run(as_of, days=7, max_pages=30, pause=2, apply=False, ack=False):
    settings = get_settings()
    validate(settings, as_of, days, max_pages, pause, apply, ack)
    start_day = as_of - timedelta(days=days - 1)
    window_start = datetime.combine(start_day, datetime.min.time())
    window_end = datetime.combine(as_of + timedelta(days=1), datetime.min.time())
    pilot = pilot_engine(settings)
    total_pages = selected = changed_total = finished = 0
    try:
        exists = check_table(pilot)
        if apply and not exists:
            create_table(pilot)
            exists = True
        print(f"window_start={window_start} window_end_exclusive={window_end} "
              f"lookback_days={days} apply={apply}", flush=True)
        for source,dataset in PAIRS:
            identity = dict(source=source,dataset=dataset,as_of_date=as_of,
                            lookback_days=days)
            checkpoint = (current_progress(pilot, identity) if exists else dict(ZERO))
            if checkpoint["scan_exhausted"]:
                finished += 1
                print(f"skip={source}/{dataset} window_already_scanned=True "
                      "coverage_certified=False", flush=True)
                continue
            statement = recent_sql(source,dataset)
            remote = connect_source(settings, source)
            try:
                while total_pages < max_pages:
                    params = dict(from_date=window_start,to_date=window_end,
                                  lim=PAGE_LIMIT,
                                  **{field: int(checkpoint[field]) for field in
                                     ("last_id","last_op","last_code","last_dest")})
                    with read_only_transaction(remote) as conn:
                        plan = conn.execute(text("EXPLAIN " + statement),
                                            params).mappings().all()
                        source_plan_guard(plan)
                        raw = conn.execute(text(statement),params).mappings().all()
                        inspect_page(source,dataset,raw)
                        validate_cursor(checkpoint,raw,source,dataset)
                        data = [normalize(source,dataset,dict(r)) for r in raw]
                    next_params = (next_cursor_params(source,dataset,raw[-1],params)
                                   if raw else dict(params))
                    exhausted = len(raw) < PAGE_LIMIT
                    if apply:
                        changed_total += save_page(
                            pilot,identity,checkpoint,next_params,data,exhausted)
                        checkpoint = current_progress(pilot,identity)
                    total_pages += 1
                    selected += len(raw)
                    print(f"page={total_pages} pair={source}/{dataset} "
                          f"rows={len(raw)} exhausted={exhausted}",flush=True)
                    if exhausted:
                        finished += 1
                        break
                    if not apply:
                        print("dry_run_stops_after_one_page=True",flush=True)
                        break
                    if total_pages < max_pages:
                        sleep(pause)
                if total_pages >= max_pages:
                    break
            finally:
                remote.dispose()
        print(f"summary pages={total_pages} rows_selected={selected} "
              f"pilot_changed_rows={changed_total} "
              f"pairs_exhausted_or_skipped={finished}/4 "
              f"page_limit_reached={total_pages >= max_pages} "
              f"source_writes=False coverage_certified=False",flush=True)
    finally:
        pilot.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--as-of",type=date.fromisoformat,
                   default=date.today(),help="2026-MM-DD; stable checkpoint day")
    p.add_argument("--days",type=int,default=7)
    p.add_argument("--max-pages",type=int,default=30)
    p.add_argument("--pause-seconds",type=int,default=2)
    p.add_argument("--apply",action="store_true")
    p.add_argument("--acknowledge-sensitive-data",action="store_true")
    args = p.parse_args()
    run(args.as_of,args.days,args.max_pages,args.pause_seconds,
        args.apply,args.acknowledge_sensitive_data)


if __name__ == "__main__":
    main()
