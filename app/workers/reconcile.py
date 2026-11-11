import logging
import time
from sqlalchemy import select
from app.core.database import SessionLocal
from app.infrastructure.models import ReconciliationRun, now
from app.application.reconciliation import execute

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("reconciler")

def poll():
    with SessionLocal() as db:
        pending=db.scalars(select(ReconciliationRun)
                     .where(ReconciliationRun.status=="PENDING")
                     .order_by(ReconciliationRun.id).limit(10)).all()
        for run in pending:
            rid=run.id
            try:
                execute(db,run)
            except Exception:
                log.exception("Reconciliation %d failed",rid)
                db.rollback()
                failed=db.get(ReconciliationRun,rid)
                failed.status="FAILED"
                failed.finished_at=now()
                db.commit()

def main():
    while True:
        poll()
        time.sleep(30)

if __name__=="__main__":
    main()
