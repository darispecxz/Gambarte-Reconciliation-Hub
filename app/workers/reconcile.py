"""One reconciliation worker instance; workers never touch source databases."""
import logging
import time
from sqlalchemy import select
from app.application.reconciliation import execute
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.infrastructure.models import ReconciliationRun, now

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reconciler")


def poll() -> None:
    with SessionLocal() as db:
        pending = db.scalars(
            select(ReconciliationRun).where(ReconciliationRun.status == "PENDING")
            .order_by(ReconciliationRun.id).limit(10)
        ).all()
        for run in pending:
            rid = run.id
            try:
                execute(db, run)
            except Exception:
                log.exception("Reconciliation %s failed", rid)
                db.rollback()
                failed = db.get(ReconciliationRun, rid)
                if failed:
                    failed.status = "FAILED"
                    failed.finished_at = now()
                    db.commit()


def main() -> None:
    while True:
        try:
            poll()
        except Exception:
            log.exception("Polling failure")
        time.sleep(max(10, get_settings().reconcile_interval_seconds))


if __name__ == "__main__":
    main()
