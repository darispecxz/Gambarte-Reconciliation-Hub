"""Integration against isolated MariaDB. Never point this test at a CGR database."""
import os
from datetime import timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.integrations.source import Extracted
from app.infrastructure.ingestion import ingest
from app.infrastructure.models import (
    ReconciliationMatch, ReconciliationRun, Remittance, RemittanceEvent,
    SourceRecord, SourceVersion, SyncCursor, SyncRun, now,
)
from app.application.reconciliation import execute

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Requires isolated MariaDB with Alembic migrations",
)


def example_row(source, dataset, ident, code="TEST-CL-100"):
    origin = source == "CHILE"
    return Extracted(
        source=source, dataset=dataset, source_id=f"3:{ident}",
        code=code, status="PAID" if dataset == "remittance" else "RECORDED",
        amount=Decimal("100.00") if origin else Decimal("690.00"),
        currency="USD" if origin else "BOB",
        raw={"source_pk": ident, "operation_type": 3, "code": code,
             "amount": "100.00" if origin else "690.00", "status_code": 1},
        operation_type=3, direction="CL_TO_BO" if dataset == "remittance" else None,
        occurred_at=now(), source_pk=ident,
    )


def test_idempotent_ingestion_and_operational_match():
    with SessionLocal() as db:
        unique_code = "TEST-STAGE-B-LOCAL"
        for source in ("BOLIVIA", "CHILE"):
            ingest(db, example_row(source, "remittance", 11001, unique_code))
        ingest(db, example_row("BOLIVIA", "payment", 22001, unique_code))
        db.commit()

        # Re-ingesting the same source rows cannot create new versions/events.
        assert not ingest(db, example_row("CHILE", "remittance", 11001, unique_code))
        records = db.scalars(select(SourceRecord).where(SourceRecord.code == unique_code)).all()
        assert len(records) == 3
        ids = [record.id for record in records]
        versions = db.scalars(select(SourceVersion).where(SourceVersion.record_id.in_(ids))).all()
        assert len(versions) == 3
        for dataset in ("remittance", "payment"):
            for source in ("BOLIVIA", "CHILE"):
                previous = db.scalar(select(SyncCursor).where(
                    SyncCursor.source == source, SyncCursor.dataset == dataset,
                ))
                if previous is None:
                    db.add(SyncCursor(
                        source=source, dataset=dataset,
                        window_start=now() - timedelta(days=7),
                        scan_started_at=now(), last_success_at=now(),
                        in_progress=False, last_source_id=0, last_operation_id=0,
                    ))
                db.add(SyncRun(
                    source=source, dataset=dataset, status="COMPLETED",
                    count=0, started_at=now(), finished_at=now(),
                ))
        run = ReconciliationRun(status="PENDING")
        db.add(run)
        db.commit()
        count = execute(db, run)
        assert count >= 0
        matches = db.scalars(select(ReconciliationMatch).where(
            ReconciliationMatch.run_id == run.id
        )).all()
        assert any(m.result == "MATCHED" and m.evidence["verified_amount"] is False
                   for m in matches)
        events = db.scalars(select(RemittanceEvent).where(
            RemittanceEvent.remittance_id.in_(
                select(Remittance.id).where(Remittance.code == unique_code)
            )
        )).all()
        assert len(events) == 2
