"""Safely refresh a single Bolivia payment by reconciliation code into isolated pilot.

Explicit per-code operation, not a recurring ETL or historical rescan.
Source is READ ONLY; EXPLAIN must pass before fetching. Writes only to
the marked pilot with --apply and explicit sensitive-data acknowledgement.
"""
import argparse
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.ingestion import ingest
from app.integrations.source import SQL, normalize, read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine, source_plan_guard
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.preflight_source import inspect_page

# Do not use a date-based cursor for a payment that may have arrived after
# a historical checkpoint was marked exhausted.
BASE = SQL[("BOLIVIA", "payment")]
ORIGINAL = "AND p.fec_crea_pago >= :cutoff"
if BASE.count(ORIGINAL) != 1:
    raise RuntimeError("Bolivia payment SQL contract changed; review required")
QUERY = BASE.replace(ORIGINAL, "AND p.codigo = :code")
validate_read_query(QUERY)
LIMIT = 50


def run(code, apply=False, acknowledge=False):
    if not re.fullmatch(r"[0-9]{1,30}", code) or int(code) == 0:
        raise ValueError("A positive numeric reconciliation code is required")
    if apply and not acknowledge:
        raise ValueError("--apply requires --acknowledge-sensitive-data")
    settings = get_settings()
    if ((settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Only the isolated pilot with source ETL disabled is allowed")
    pilot = pilot_engine(settings)
    remote = None
    try:
        with pilot.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
            finally:
                conn.rollback()
        remote = connect_source(settings, "BOLIVIA")
        params = {"code": code, "last_id": 0, "last_op": 0,
                  "last_code": 0, "last_dest": 0, "lim": LIMIT}
        with read_only_transaction(remote) as conn:
            plan = conn.execute(text("EXPLAIN " + QUERY), params).mappings().all()
            source_plan_guard(plan)
            print("source_explain=" + ",".join(
                f"{p.get('type')}/{p.get('key')}/{p.get('rows')}" for p in plan),
                flush=True)
            raw = conn.execute(text(QUERY), params).mappings().all()
            inspect_page("BOLIVIA", "payment", raw)
            # A full page may hide additional matching payments: refuse apply.
            if len(raw) == LIMIT:
                raise RuntimeError("50 matching records reached cap; refusing incomplete refresh")
            records = [normalize("BOLIVIA", "payment", dict(row)) for row in raw]
        print(f"source=BOLIVIA dataset=payment matching_rows={len(records)} "
              f"dry_run={not apply} source_read_only=True", flush=True)
        if not apply:
            print("pilot_writes=False source_writes=False coverage_certified=False")
            return
        changes = 0
        with Session(pilot) as session:
            with session.begin():
                check_marker(session.connection())
                for item in records:
                    changes += int(ingest(session, item))
        print(f"pilot_changed_rows={changes} pilot_writes=True "
              "source_writes=False coverage_certified=False", flush=True)
    finally:
        if remote is not None:
            remote.dispose()
        pilot.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--code", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--acknowledge-sensitive-data", action="store_true")
    a = p.parse_args()
    run(a.code, a.apply, a.acknowledge_sensitive_data)


if __name__ == "__main__":
    main()
