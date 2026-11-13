"""Exercise changed-source versioning on pilot with synthetic rows, then roll back."""
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.infrastructure.ingestion import ingest
from app.infrastructure.models import RemittanceEvent, SourceRecord, SourceVersion
from app.integrations.source import Extracted
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker


def run():
    settings = get_settings()
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Probe refuses non-pilot target")
    engine = create_engine(URL.create(
        "mysql+pymysql", host=settings.db_host, port=settings.db_port,
        username=settings.db_user, password=settings.db_password,
        database=settings.db_name, query={"charset": "utf8mb4"},
    ), connect_args={"connect_timeout": 10, "read_timeout": 30})
    try:
        with Session(engine) as session:
            try:
                check_marker(session.connection())
                token = uuid4().hex
                raw = {"source_pk": -1, "operation_type": 16,
                       "code": f"SYNTHETIC-{token}", "status_code": 0}
                row = Extracted(
                    source="BOLIVIA", dataset="remittance",
                    source_id=f"16:SYNTHETIC-{token}", code=raw["code"],
                    status="PENDING", amount=Decimal("1"), currency="BOB",
                    raw=raw, operation_type=16, source_pk=-1,
                )
                assert ingest(session, row)
                assert not ingest(session, row)
                changed = replace(row, status="PAID",
                                  raw={**raw, "status_code": 1})
                assert ingest(session, changed)
                record = session.scalar(select(SourceRecord).where(
                    SourceRecord.source == row.source,
                    SourceRecord.dataset == row.dataset,
                    SourceRecord.source_id == row.source_id,
                ))
                version_count = session.scalar(select(func.count()).select_from(
                    SourceVersion).where(SourceVersion.record_id == record.id))
                event_types = session.scalars(select(RemittanceEvent.event_type)
                    .join(SourceVersion, RemittanceEvent.source_version_id == SourceVersion.id)
                    .where(SourceVersion.record_id == record.id)
                    .order_by(RemittanceEvent.id)).all()
                if version_count != 2 or event_types != [
                    "OBSERVED_CREATED", "OBSERVED_STATUS_CHANGE"
                ] or record.status != "PAID":
                    raise RuntimeError("Synthetic version transition failed")
                print("synthetic_versions=2 synthetic_events=2 transition_valid=True")
            finally:
                session.rollback()
        print("synthetic_probe_rolled_back=True")
    finally:
        engine.dispose()


if __name__ == "__main__":
    run()
