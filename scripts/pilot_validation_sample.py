"""Export a tiny local lookup sample from the pilot; never print identifiers."""
import csv
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

from app.core.config import get_settings
from app.infrastructure.models import Payment, Remittance, SourceRecord
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker


OUTPUT = Path("/export/validation_sample.csv")
TARGETS = {
    ("CHILE", "remittance"): {3, 5, 6, 8},
    ("CHILE", "payment"): {3, 5, 6, 8},
    ("BOLIVIA", "payment"): {4, 7},
}


def run():
    settings = get_settings()
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Sample export refuses non-pilot target")
    if not OUTPUT.parent.is_dir():
        raise RuntimeError("Mount a local private directory at /export")
    engine = create_engine(URL.create(
        "mysql+pymysql", host=settings.db_host, port=settings.db_port,
        username=settings.db_user, password=settings.db_password,
        database=settings.db_name, query={"charset": "utf8mb4"},
    ), connect_args={"connect_timeout": 10, "read_timeout": 30})
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(connection)
                records = connection.execute(select(
                    SourceRecord.source, SourceRecord.dataset,
                    SourceRecord.source_id, SourceRecord.code,
                    SourceRecord.status, SourceRecord.id,
                )).all()
                remittances = connection.execute(select(
                    Remittance.source_record_id, Remittance.operation_type,
                    Remittance.occurred_at,
                )).all()
                payments = connection.execute(select(
                    Payment.source_record_id, Payment.operation_type,
                    Payment.occurred_at,
                )).all()
            finally:
                connection.rollback()
    finally:
        engine.dispose()
    details = {row.source_record_id: ("remittance", row.operation_type,
                                      row.occurred_at) for row in remittances}
    details.update({row.source_record_id: ("payment", row.operation_type,
                                           row.occurred_at) for row in payments})
    counts = Counter()
    chosen = defaultdict(int)
    selected = []
    for row in records:
        dataset, operation, occurred_at = details[row.id]
        key = (row.source, dataset, operation)
        if operation not in TARGETS.get((row.source, dataset), set()):
            continue
        counts[key] += 1
        if chosen[key] < 2:
            selected.append((row.source, dataset, operation, row.source_id,
                             row.code, row.status, occurred_at))
            chosen[key] += 1
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("source", "dataset", "operation_type", "source_id",
                         "codigo", "status", "occurred_at_source_local"))
        writer.writerows(selected)
    for (source, dataset), types in TARGETS.items():
        for operation in sorted(types):
            print(f"{source}/{dataset}/type_{operation}: "
                  f"pilot_rows={counts[source, dataset, operation]} "
                  f"sample_rows={chosen[source, dataset, operation]}")
    print(f"sample_rows_total={len(selected)} local_file_written=True "
          "identifiers_logged=False source_databases_touched=False")


if __name__ == "__main__":
    run()
