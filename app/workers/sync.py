import logging
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.integrations.source import extract
from app.infrastructure.ingestion import ingest
from app.infrastructure.models import SyncRun, now

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("sync")

def sync(source: str, dataset: str, days: int = 30):
    since=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=days)
    with SessionLocal() as db:
        run=SyncRun(source=source,dataset=dataset,status="RUNNING")
        db.add(run)
        db.commit()
        rid=run.id
        try:
            for row in extract(source,dataset,since):
                ingest(db,row)
                run.count+=1
                if run.count % 500 == 0:
                    db.commit()
            run.status="COMPLETED"
            run.finished_at=now()
            db.commit()
        except Exception as error:
            db.rollback()
            failed=db.get(SyncRun,rid)
            failed.status="FAILED"
            failed.finished_at=now()
            failed.error=str(error)[:1000]
            db.commit()
            log.exception("Sync failed: %s %s",source,dataset)

def main():
    while True:
        for source in ("BOLIVIA","CHILE"):
            for dataset in ("remittance","payment"):
                sync(source,dataset)
        time.sleep(300)

if __name__=="__main__":
    main()
