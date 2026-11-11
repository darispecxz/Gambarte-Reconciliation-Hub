import hmac
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.database import get_session
from app.infrastructure.models import SourceRecord, SyncRun, ReconciliationRun, Discrepancy

router = APIRouter(prefix="/api/v1")

def auth(x_api_key: str | None = Header(None)):
    key = get_settings().api_key
    if not key or not x_api_key or not hmac.compare_digest(key, x_api_key):
        raise HTTPException(401, "API key required")

@router.get("/health")
def health(db: Session = Depends(get_session)):
    try:
        db.execute(text("SELECT 1"))
        return {"status":"ok"}
    except Exception:
        raise HTTPException(503, "Database unavailable")

@router.get("/sync/status", dependencies=[Depends(auth)])
def sync_status(db: Session = Depends(get_session)):
    rows = db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(20)).all()
    return [{"id":r.id,"source":r.source,"dataset":r.dataset,"status":r.status,
             "count":r.count,"finished_at":r.finished_at} for r in rows]

@router.get("/remittances", dependencies=[Depends(auth)])
def remittances(limit: int = Query(50,ge=1,le=200), offset: int = Query(0,ge=0),
                db: Session = Depends(get_session)):
    rows = db.scalars(select(SourceRecord).where(SourceRecord.dataset=="remittance")
                      .order_by(SourceRecord.id).limit(limit).offset(offset)).all()
    return [{"id":r.id,"source":r.source,"code":r.code,"status":r.status,
             "amount":str(r.amount) if r.amount is not None else None,
             "currency":r.currency} for r in rows]

@router.post("/reconciliations", status_code=202, dependencies=[Depends(auth)])
def create_reconciliation(db: Session = Depends(get_session)):
    run = ReconciliationRun(status="PENDING")
    db.add(run)
    db.commit()
    return {"id":run.id, "status":run.status}

@router.get("/reconciliations/{run_id}", dependencies=[Depends(auth)])
def get_reconciliation(run_id: int, db: Session = Depends(get_session)):
    run = db.get(ReconciliationRun,run_id)
    if run is None:
        raise HTTPException(404,"Not found")
    return {"id":run.id,"status":run.status,"message":run.message,
            "created_at":run.created_at,"finished_at":run.finished_at}

@router.get("/reconciliations/{run_id}/discrepancies", dependencies=[Depends(auth)])
def discrepancies(run_id: int, limit: int = Query(50,ge=1,le=200),
                  db: Session = Depends(get_session)):
    if db.get(ReconciliationRun,run_id) is None:
        raise HTTPException(404,"Not found")
    rows = db.scalars(select(Discrepancy).where(Discrepancy.run_id==run_id)
                      .order_by(Discrepancy.id).limit(limit)).all()
    return [{"code":r.code,"category":r.category,"description":r.description} for r in rows]
