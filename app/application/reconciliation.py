from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.domain.reconciliation import Remittance, Payment, reconcile
from app.infrastructure.models import SourceRecord, ReconciliationRun, Discrepancy, SyncRun, now

def execute(session: Session, run: ReconciliationRun) -> int:
    if run.status != "PENDING":
        raise ValueError("Only pending runs are executable")
    # Incomplete source syncs invalidate an apparently successful reconciliation.
    recent = session.scalars(select(SyncRun).order_by(SyncRun.id.desc())).all()
    statuses = {}
    for item in recent:
        statuses.setdefault((item.source,item.dataset),item.status)
    if any(statuses.get((src,ds)) != "COMPLETED" for src in ("BOLIVIA","CHILE")
           for ds in ("remittance","payment")):
        run.status="BLOCKED"
        run.message="Required source datasets not successfully synchronized"
        run.finished_at=now()
        session.commit()
        return 0
    run.status="RUNNING"
    session.flush()
    try:
        records = session.scalars(select(SourceRecord)).all()
        payment_index = defaultdict(list)
        for r in records:
            if r.dataset=="payment":
                payment_index[(r.source,r.code)].append(
                    Payment(r.code,r.amount or Decimal("0"),r.currency))
        count=0
        # Full code correlation is provisional: don't produce financial balances.
        for r in records:
            if r.dataset!="remittance" or r.status!="PAID":
                continue
            target = "CHILE" if r.source=="BOLIVIA" else "BOLIVIA"
            rem = Remittance(r.code,r.status,r.amount or Decimal("0"),r.currency)
            for result in reconcile(rem,payment_index.get((target,r.code),[])):
                session.add(Discrepancy(run_id=run.id,code=result.code,
                      category=result.category,description=result.description))
                count+=1
        run.status="COMPLETED"
        run.finished_at=now()
        run.message=f"{count} provisional findings; no financial balance calculated"
        session.commit()
        return count
    except Exception:
        session.rollback()
        raise
