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
        raw={"source_pk": ident, "operation_type": 4 if dataset == "payment" and source == "BOLIVIA" else 3, "code": code,
             "amount": "100.00" if origin else "690.00", "status_code": 1},
        operation_type=4 if dataset == "payment" and source == "BOLIVIA" else 3,
        direction="CL_TO_BO" if dataset == "remittance" and source == "CHILE" else None,
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


def test_bolivia_origin_chile_payment_without_mirrored_remittance():
    # Real-world contract confirmed: BO.remesa.codigo == CL.pago.codigo.
    # No CL.remesa is required. Use only the isolated CI database.
    code = "TEST-BO-CL-CROSS-BORDER"
    bo_remittance = Extracted(
        source="BOLIVIA", dataset="remittance", source_id="16:41005",
        code=code, status="PAID", amount=Decimal("100"),
        currency="USD", raw={"source_pk": 41005, "operation_type": 16,
                             "code": code, "currency_id": 1, "status_code": 1},
        operation_type=16, direction="BO_TO_CL", occurred_at=now(), source_pk=41005,
    )
    cl_payment = Extracted(
        source="CHILE", dataset="payment", source_id="3:42005",
        code=code, status="RECORDED", amount=Decimal("90000"),
        currency="CLP", raw={"source_pk": 42005, "operation_type": 3,
                             "code": code, "currency_id": 2},
        operation_type=3, occurred_at=now(), source_pk=42005,
    )
    with SessionLocal() as db:
        ingest(db, bo_remittance)
        ingest(db, cl_payment)
        for country in ("BOLIVIA", "CHILE"):
            for dataset in ("remittance", "payment"):
                cursor = db.scalar(select(SyncCursor).where(
                    SyncCursor.source == country, SyncCursor.dataset == dataset
                ))
                if cursor is None:
                    db.add(SyncCursor(
                        source=country, dataset=dataset,
                        window_start=now() - timedelta(days=7),
                        scan_started_at=now(), last_success_at=now(),
                        in_progress=False, last_source_id=0, last_operation_id=0,
                    ))
                db.add(SyncRun(
                    source=country, dataset=dataset, status="COMPLETED",
                    count=0, started_at=now(), finished_at=now(),
                ))
        run = ReconciliationRun(status="PENDING")
        db.add(run)
        db.commit()
        execute(db, run)
        original = db.scalar(select(Remittance).where(
            Remittance.source == "BOLIVIA", Remittance.code == code
        ))
        matches = db.scalars(select(ReconciliationMatch).where(
            ReconciliationMatch.run_id == run.id,
            ReconciliationMatch.remittance_id == original.id,
        )).all()
        assert len(matches) == 1
        assert matches[0].result == "MATCHED"
        assert matches[0].counterpart_id is None
        assert len(matches[0].evidence["matched_payment_ids"]) == 1
        assert matches[0].evidence["verified_amount"] is False


def test_historical_cutoff_retains_late_payment_without_false_discrepancy():
    # Create source record before cutoff, destination payment after cutoff.
    code = "TEST-STAGE-B-ASOF-LATE"
    with SessionLocal() as db:
        ingest(db, Extracted(
            source="BOLIVIA", dataset="remittance", source_id="16:50111",
            code=code, status="PAID", amount=Decimal("200"), currency="USD",
            raw={"source_pk": 50111, "operation_type": 16, "code": code,
                 "status_code": 1}, operation_type=16, direction="BO_TO_CL",
            occurred_at=now() - timedelta(days=2), source_pk=50111,
        ))
        ingest(db, Extracted(
            source="CHILE", dataset="payment", source_id="3:50112",
            code=code, status="RECORDED", amount=Decimal("120000"), currency="CLP",
            raw={"source_pk": 50112, "operation_type": 3, "code": code},
            operation_type=3, occurred_at=now(), source_pk=50112,
        ))
        for source_name in ("BOLIVIA", "CHILE"):
            for dataset in ("remittance", "payment"):
                cursor = db.scalar(select(SyncCursor).where(
                    SyncCursor.source == source_name,
                    SyncCursor.dataset == dataset,
                ))
                if cursor is None:
                    db.add(SyncCursor(source=source_name, dataset=dataset,
                                      window_start=now() - timedelta(days=7),
                                      scan_started_at=now(), last_success_at=now(),
                                      in_progress=False, last_source_id=0,
                                      last_operation_id=0))
                db.add(SyncRun(source=source_name, dataset=dataset,
                               status="COMPLETED", count=0,
                               started_at=now(), finished_at=now()))
        run = ReconciliationRun(status="PENDING", cutoff_at=now() - timedelta(days=1))
        db.add(run)
        db.commit()
        execute(db, run)
        rem = db.scalar(select(Remittance).where(
            Remittance.source == "BOLIVIA", Remittance.code == code
        ))
        match = db.scalar(select(ReconciliationMatch).where(
            ReconciliationMatch.run_id == run.id,
            ReconciliationMatch.remittance_id == rem.id,
        ))
        assert match.result == "PENDING_AS_OF"
        assert match.evidence["matched_payment_ids"] == []
        assert len(match.evidence["payments_after_cutoff_ids"]) == 1
