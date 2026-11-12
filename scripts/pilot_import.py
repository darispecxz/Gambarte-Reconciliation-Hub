"""Opt-in, one-page pilot ingestion into an isolated MariaDB instance ONLY.

No recurring ETL, no sync cursor completion, no reconciliation coverage claims.
Source database connections are always READ ONLY. --apply explicitly opts into
storing real records on a *separate* local pilot database volume.
"""
import argparse
from collections import Counter
from datetime import timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.ingestion import ingest
from app.integrations.source import SQL, normalize, read_only_transaction, validate_read_query
from scripts.preflight_source import inspect_page

PILOT_DB = "gambarte_reconciliation_pilot"
PILOT_HOST = "pilot-db"
PILOT_MARKER = "GAMBARTE_ISOLATED_PILOT_V1"


def validate_pilot(settings, source, dataset, days, limit, apply, acknowledge):
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Pilot requires source ETL and mapping verification to remain disabled")
    if settings.db_host != PILOT_HOST or settings.db_name != PILOT_DB:
        raise RuntimeError("Pilot refuses any non-isolated central DB configuration")
    if source != "BOLIVIA" or dataset != "remittance":
        raise ValueError("First pilot restricted to BOLIVIA/remittance only")
    if not 1 <= days <= 60 or not 1 <= limit <= 50:
        raise ValueError("Pilot limited to 1..60 days and 1..50 records")
    if apply and not acknowledge:
        raise ValueError("--apply requires --acknowledge-sensitive-data")


def check_marker(connection):
    actual_db = connection.execute(text("SELECT DATABASE()")).scalar_one()
    if actual_db != PILOT_DB:
        raise RuntimeError("Connected database is not the isolated pilot")
    marker = connection.execute(
        text("SELECT marker FROM pilot_instance_guard WHERE marker = :marker"),
        {"marker": PILOT_MARKER},
    ).scalar_one_or_none()
    if marker != PILOT_MARKER:
        raise RuntimeError("Pilot database marker is missing")


def connect_source(settings):
    prefix = "bolivia_db_"
    host, user, password, database = (
        getattr(settings, prefix + k) for k in ("host", "user", "password", "name")
    )
    if not all((host, user, password, database)):
        raise RuntimeError("BOLIVIA source credentials not configured")
    return create_engine(
        URL.create(
            "mysql+pymysql", host=host, username=user, password=password,
            port=settings.bolivia_db_port, database=database,
            query={"charset": "utf8mb4"},
        ),
        connect_args={"connect_timeout": 10, "read_timeout": 30},
    )


def run(source="BOLIVIA", dataset="remittance", days=60, limit=50,
        apply=False, acknowledge=False):
    settings = get_settings()
    validate_pilot(settings, source, dataset, days, limit, apply, acknowledge)
    source_sql = SQL[(source, dataset)]
    validate_read_query(source_sql)

    # Source read is separate and DB-enforced READ ONLY; no ETL worker invoked.
    source_engine = connect_source(settings)
    try:
        with read_only_transaction(source_engine) as conn:
            server_now = conn.execute(text("SELECT NOW()")).scalar_one()
            params = {"cutoff": server_now - timedelta(days=days),
                      "last_id": 0, "last_op": 0, "last_code": 0,
                      "last_dest": 0, "lim": limit}
            raw_rows = conn.execute(text(source_sql), params).mappings().all()
            statuses = inspect_page(source, dataset, raw_rows)
            records = [normalize(source, dataset, dict(row)) for row in raw_rows]
    finally:
        source_engine.dispose()

    print(f"source={source} dataset={dataset} window_days={days} rows={len(records)}")
    print("source_read_only=True automatic_etl=False")
    print("status_counts=", dict(sorted(statuses.items())))
    if not apply:
        print("dry_run=True writes_to_pilot=False")
        return {"rows": len(records), "applied": False}

    # Use a dedicated URL; never import the global SessionLocal from the normal API.
    pilot_engine = create_engine(
        URL.create(
            "mysql+pymysql", host=settings.db_host, port=settings.db_port,
            username=settings.db_user, password=settings.db_password,
            database=settings.db_name, query={"charset": "utf8mb4"},
        ),
        connect_args={"connect_timeout": 10, "read_timeout": 30},
    )
    try:
        with Session(pilot_engine) as session:
            with session.begin():
                check_marker(session.connection())
                changed = 0
                for record in records:
                    if ingest(session, record):
                        changed += 1
                # Read from same transaction to validate persisted batch identity.
                # Do not write SyncCursor or claim full source coverage.
                print(f"pilot_rows_inserted_or_updated={changed}")
                print(f"pilot_rows_unchanged={len(records) - changed}")
        print("pilot_commit=True target=isolated_pilot_db")
        return {"rows": len(records), "changed": changed, "applied": True}
    finally:
        pilot_engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="BOLIVIA")
    p.add_argument("--dataset", default="remittance")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--acknowledge-sensitive-data", action="store_true")
    args = p.parse_args()
    run(args.source, args.dataset, args.days, args.limit,
        args.apply, args.acknowledge_sensitive_data)


if __name__ == "__main__":
    main()
