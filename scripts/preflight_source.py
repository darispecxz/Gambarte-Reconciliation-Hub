"""Read-only, bounded preflight for one real source extractor (no ETL writes).

Uses the exact SQL from app.integrations.source.SQL. Does not call source_engine
or ingest; never persists rows/cursors; prints only aggregate or EXPLAIN data.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.core.config import get_settings
from app.integrations.source import SQL, normalize, read_only_transaction, validate_read_query


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, choices=("BOLIVIA", "CHILE"))
    p.add_argument("--dataset", required=True, choices=("remittance", "payment"))
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--explain-only", action="store_true")
    return p


def key_for(source, dataset, row):
    if (source, dataset) == ("CHILE", "remittance"):
        return (int(row["operation_type"]), int(row["code"]),
                int(row["cursor_destination"]))
    return (int(row["source_pk"]), int(row["operation_type"]))


def inspect_page(source, dataset, rows):
    keys = [key_for(source, dataset, row) for row in rows]
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise RuntimeError("Non-unique or unordered source keys: no ETL should run")
    # No source identities, codes, amounts, or individual statuses are printed.
    statuses = Counter()
    for row in rows:
        record = normalize(source, dataset, dict(row))
        statuses[record.status] += 1
    return statuses


def run(source, dataset, days, limit, explain_only=False):
    if not 1 <= days <= 90 or not 1 <= limit <= 100:
        raise ValueError("Safety limits: 1..90 days and 1..100 rows")
    settings = get_settings()
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError(
            "Run preflight only with ENABLE_SOURCE_ETL=false and "
            "SOURCE_MAPPING_VERIFIED=false"
        )
    prefix = source.lower()
    values = [getattr(settings, f"{prefix}_db_{part}")
              for part in ("host", "user", "password", "name")]
    if not all(values):
        raise RuntimeError(f"{source}: missing source credentials")
    host, user, password, db = values
    sql = SQL[(source, dataset)]
    validate_read_query(sql)
    engine = create_engine(
        URL.create(
            "mysql+pymysql", username=user, password=password, host=host,
            port=getattr(settings, f"{prefix}_db_port"), database=db,
            query={"charset": "utf8mb4"},
        ),
        connect_args={"connect_timeout": 10, "read_timeout": 30},
    )
    try:
        # Explicitly readonly at the database level, independently of ETL settings.
        # Cutoff uses the DB server's own NOW(), avoiding client timezone mismatch.
        with read_only_transaction(engine) as conn:
            server_now = conn.execute(text("SELECT NOW()")).scalar_one()
            cutoff = server_now - timedelta(days=days)
            params = {
                "cutoff": cutoff, "last_id": 0, "last_op": 0,
                "last_code": 0, "last_dest": 0, "lim": limit,
            }
            plan = conn.execute(text("EXPLAIN " + sql), params).mappings().all()
            print(f"source={source} dataset={dataset} lookback_days={days} max_rows={limit}")
            print("read_only=True writes_to_central=False")
            for item in plan:
                print("EXPLAIN",
                      "access=", item.get("type"),
                      "key=", item.get("key"),
                      "estimated_rows=", item.get("rows"),
                      "extra=", item.get("Extra"))
            if explain_only:
                return {"plan_only": True}
            started = perf_counter()
            rows = conn.execute(text(sql), params).mappings().all()
            elapsed = perf_counter() - started
            statuses = inspect_page(source, dataset, rows)
            print(f"selected_rows={len(rows)} elapsed_seconds={elapsed:.3f}")
            print("ordered_unique_keys=True")
            print("status_counts=", dict(sorted(statuses.items())))
            print("sample_is_capped=", len(rows) == limit)
            print("NOTE: one page only, not a complete historical coverage audit.")
            return {"count": len(rows), "statuses": statuses}
    finally:
        engine.dispose()


def main():
    args = parser().parse_args()
    run(args.source, args.dataset, args.days, args.limit, args.explain_only)


if __name__ == "__main__":
    main()
