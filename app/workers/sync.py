"""Crash-resumable keyset-based ingestion using a persisted per-source cursor.

Single-worker deployment assumed. Locking across multiple replicas is a P0
enhancement and should be added before horizontal scaling.
"""
import logging
import time
from datetime import timedelta
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.integrations.source import fetch_page
from app.infrastructure.ingestion import ingest
from app.infrastructure.models import SyncCursor, SyncRun, now

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sync")

DATASETS = tuple((source, kind)
                 for source in ("BOLIVIA", "CHILE")
                 for kind in ("remittance", "payment"))


def sync(source: str, dataset: str, page_size: int = 500) -> int:
    s = get_settings()
    if not (s.enable_source_etl and s.source_mapping_verified):
        raise RuntimeError("Source extraction disabled until schema/mapping validation")

    with SessionLocal() as db:
        cursor = db.scalar(select(SyncCursor).where(
            SyncCursor.source == source, SyncCursor.dataset == dataset
        ))
        if cursor is None:
            cursor = SyncCursor(source=source, dataset=dataset)
            db.add(cursor)
            db.flush()

        if not cursor.in_progress:
            started = now()
            cursor.window_start = (
                started - timedelta(days=s.backfill_days) if cursor.last_success_at is None
                else cursor.last_success_at - timedelta(days=s.overlap_days)
            )
            cursor.scan_started_at = started
            cursor.last_source_id = 0
            cursor.last_operation_id = 0
            cursor.in_progress = True
        run = SyncRun(source=source, dataset=dataset, status="RUNNING", count=0)
        db.add(run)
        db.commit()
        run_id = run.id
        total = 0
        try:
            while True:
                rows = fetch_page(source, dataset, cursor.window_start,
                                  cursor.last_source_id, cursor.last_operation_id, page_size)
                for row in rows:
                    ingest(db, row)
                    cursor.last_source_id = row.source_pk
                    cursor.last_operation_id = row.operation_type or 0
                    total += 1
                run.count += len(rows)
                db.commit()  # data and cursor progress commit atomically
                if len(rows) < page_size:
                    break
            cursor.in_progress = False
            cursor.last_success_at = now()
            cursor.last_source_id = 0
            cursor.last_operation_id = 0
            run.status = "COMPLETED"
            run.finished_at = now()
            db.commit()
            return total
        except Exception as error:
            db.rollback()
            failed = db.get(SyncRun, run_id)
            failed.status = "FAILED"
            failed.finished_at = now()
            failed.error = f"{type(error).__name__}: {error}"[:1000]
            db.commit()
            log.exception("Source sync failed: %s/%s", source, dataset)
            raise


def main() -> None:
    s = get_settings()
    while True:
        if not (s.enable_source_etl and s.source_mapping_verified):
            log.warning("ETL disabled; configure verified source schema before enabling")
        else:
            for source, kind in DATASETS:
                try:
                    sync(source, kind)
                except Exception:
                    log.exception("Dataset left incomplete: %s/%s", source, kind)
        time.sleep(max(30, s.sync_interval_seconds))


if __name__ == "__main__":
    main()
