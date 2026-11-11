"""Versioned REST API for operational reconciliation; no source database access."""
import hmac
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.infrastructure.models import (
    Discrepancy, Payment, ReconciliationMatch, ReconciliationRun,
    Remittance, RemittanceEvent, SourceRecord, SourceVersion, SyncCursor, SyncRun,
)

router = APIRouter(prefix="/api/v1")


def auth(x_api_key: str | None = Header(default=None)):
    key = get_settings().api_key
    if not key or not x_api_key or not hmac.compare_digest(key, x_api_key):
        raise HTTPException(status_code=401, detail="API key required")


@router.get("/health")
def health(db: Session = Depends(get_session)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable")
    return {"status": "ok"}


@router.get("/sync/status", dependencies=[Depends(auth)])
def sync_status(db: Session = Depends(get_session)):
    runs = db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(20)).all()
    return [
        {
            "id": run.id, "source": run.source, "dataset": run.dataset,
            "status": run.status, "count": run.count,
            "started_at": run.started_at, "finished_at": run.finished_at,
        }
        for run in runs
    ]


@router.get("/sync/cursors", dependencies=[Depends(auth)])
def sync_cursors(db: Session = Depends(get_session)):
    rows = db.scalars(select(SyncCursor).order_by(SyncCursor.source, SyncCursor.dataset)).all()
    return [
        {
            "source": r.source, "dataset": r.dataset, "in_progress": r.in_progress,
            "window_start": r.window_start, "last_source_id": r.last_source_id,
            "last_operation_id": r.last_operation_id, "last_success_at": r.last_success_at,
        }
        for r in rows
    ]


@router.get("/remittances", dependencies=[Depends(auth)])
def list_remittances(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: str | None = None,
    status: str | None = None,
    code: str | None = None,
    db: Session = Depends(get_session),
):
    stmt = select(Remittance)
    if source:
        stmt = stmt.where(Remittance.source == source.upper())
    if status:
        stmt = stmt.where(Remittance.status == status.upper())
    if code:
        stmt = stmt.where(Remittance.code == code)
    rows = db.scalars(stmt.order_by(Remittance.id).limit(limit).offset(offset)).all()
    return [
        {
            "id": r.id, "source": r.source, "code": r.code,
            "operation_type": r.operation_type, "direction": r.direction,
            "status": r.status, "amount": str(r.amount) if r.amount is not None else None,
            "currency": r.currency, "occurred_at": r.occurred_at,
            "source_record_id": r.source_record_id,
        }
        for r in rows
    ]


@router.get("/remittances/{remittance_id}", dependencies=[Depends(auth)])
def get_remittance(remittance_id: int, db: Session = Depends(get_session)):
    r = db.get(Remittance, remittance_id)
    if not r:
        raise HTTPException(404, "Remittance not found")
    return {
        "id": r.id, "source": r.source, "code": r.code,
        "operation_type": r.operation_type, "direction": r.direction,
        "status": r.status, "amount": str(r.amount) if r.amount is not None else None,
        "currency": r.currency, "occurred_at": r.occurred_at,
        "source_record_id": r.source_record_id,
    }


@router.get("/remittances/{remittance_id}/events", dependencies=[Depends(auth)])
def get_remittance_events(
    remittance_id: int, limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_session),
):
    if not db.get(Remittance, remittance_id):
        raise HTTPException(404, "Remittance not found")
    rows = db.scalars(select(RemittanceEvent).where(
        RemittanceEvent.remittance_id == remittance_id
    ).order_by(RemittanceEvent.id).limit(limit)).all()
    return [
        {
            "id": e.id, "event_type": e.event_type, "status_before": e.status_before,
            "status_after": e.status_after, "effective_at": e.effective_at,
            "observed_at": e.observed_at, "source_version_id": e.source_version_id,
        }
        for e in rows
    ]


@router.get("/payments", dependencies=[Depends(auth)])
def list_payments(
    code: str | None = None, source: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
):
    stmt = select(Payment)
    if code:
        stmt = stmt.where(Payment.code == code)
    if source:
        stmt = stmt.where(Payment.source == source.upper())
    rows = db.scalars(stmt.order_by(Payment.id).limit(limit).offset(offset)).all()
    return [
        {
            "id": p.id, "source": p.source, "code": p.code,
            "operation_type": p.operation_type,
            "amount": str(p.amount) if p.amount is not None else None,
            "currency": p.currency, "occurred_at": p.occurred_at,
            "source_record_id": p.source_record_id,
        }
        for p in rows
    ]


@router.post("/reconciliations", status_code=202, dependencies=[Depends(auth)])
def create_reconciliation(db: Session = Depends(get_session)):
    run = ReconciliationRun(status="PENDING")
    db.add(run)
    db.commit()
    return {"id": run.id, "status": run.status}


@router.get("/reconciliations", dependencies=[Depends(auth)])
def list_reconciliations(
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_session)
):
    rows = db.scalars(select(ReconciliationRun).order_by(
        ReconciliationRun.id.desc()).limit(limit)).all()
    return [
        {
            "id": r.id, "status": r.status, "created_at": r.created_at,
            "finished_at": r.finished_at, "message": r.message,
        }
        for r in rows
    ]


@router.get("/reconciliations/{run_id}", dependencies=[Depends(auth)])
def get_reconciliation(run_id: int, db: Session = Depends(get_session)):
    run = db.get(ReconciliationRun, run_id)
    if not run:
        raise HTTPException(404, "Reconciliation not found")
    return {
        "id": run.id, "status": run.status, "message": run.message,
        "created_at": run.created_at, "finished_at": run.finished_at,
    }


@router.get("/reconciliations/{run_id}/matches", dependencies=[Depends(auth)])
def get_matches(
    run_id: int, result: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
):
    if not db.get(ReconciliationRun, run_id):
        raise HTTPException(404, "Reconciliation not found")
    stmt = select(ReconciliationMatch).where(ReconciliationMatch.run_id == run_id)
    if result:
        stmt = stmt.where(ReconciliationMatch.result == result.upper())
    rows = db.scalars(stmt.order_by(ReconciliationMatch.id).limit(limit).offset(offset)).all()
    return [
        {
            "id": m.id, "remittance_id": m.remittance_id,
            "counterpart_id": m.counterpart_id, "result": m.result,
            "reason": m.reason, "evidence": m.evidence,
            "checked_at": m.checked_at,
        }
        for m in rows
    ]


@router.get("/reconciliations/{run_id}/discrepancies", dependencies=[Depends(auth)])
def get_discrepancies(
    run_id: int, limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0), db: Session = Depends(get_session),
):
    if not db.get(ReconciliationRun, run_id):
        raise HTTPException(404, "Reconciliation not found")
    rows = db.scalars(select(Discrepancy).where(
        Discrepancy.run_id == run_id
    ).order_by(Discrepancy.id).limit(limit).offset(offset)).all()
    return [
        {
            "id": d.id, "code": d.code, "category": d.category,
            "description": d.description,
        }
        for d in rows
    ]
