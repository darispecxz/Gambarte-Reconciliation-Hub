"""Operational reconciliation use-case: requires complete, fresh source coverage."""
from collections import defaultdict
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.matching import Decision, OperationEvidence, PaymentEvidence, decide
from app.infrastructure.models import (
    Discrepancy, Payment, ReconciliationMatch, ReconciliationRun, Remittance,
    SyncCursor, SyncRun, now,
)

DATASETS = tuple((country, dataset)
                 for country in ("BOLIVIA", "CHILE")
                 for dataset in ("remittance", "payment"))


def source_readiness(session: Session) -> tuple[bool, str, dict]:
    s = get_settings()
    if not s.source_mapping_verified:
        return False, "Source mappings have not been approved", {}
    last_success = {}
    for country, dataset in DATASETS:
        successful = session.scalar(
            select(SyncRun).where(
                SyncRun.source == country, SyncRun.dataset == dataset,
                SyncRun.status == "COMPLETED",
            ).order_by(SyncRun.id.desc()).limit(1)
        )
        latest = session.scalar(
            select(SyncRun).where(SyncRun.source == country, SyncRun.dataset == dataset)
            .order_by(SyncRun.id.desc()).limit(1)
        )
        if not successful or not successful.finished_at:
            return False, f"No successful synchronization: {country}/{dataset}", {}
        if latest and latest.status in {"FAILED", "RUNNING"}:
            return False, f"Latest synchronization not complete: {country}/{dataset}", {}
        if now() - successful.finished_at > timedelta(minutes=s.max_source_age_minutes):
            return False, f"Stale synchronization: {country}/{dataset}", {}
        cursor = session.scalar(select(SyncCursor).where(
            SyncCursor.source == country, SyncCursor.dataset == dataset
        ))
        if cursor is None or cursor.in_progress or cursor.window_start is None:
            return False, f"Missing extraction coverage: {country}/{dataset}", {}
        last_success[(country, dataset)] = {
            "finished_at": successful.finished_at.isoformat(),
            "window_start": cursor.window_start.isoformat(),
            "window_start_dt": cursor.window_start,
        }
    return True, "ready", last_success


def _operation(row: Remittance) -> OperationEvidence:
    return OperationEvidence(
        id=row.id, source=row.source, code=row.code, direction=row.direction,
        operation_type=row.operation_type, status=row.status,
        amount=row.amount, currency=row.currency,
    )


def _payment(row: Payment) -> PaymentEvidence:
    return PaymentEvidence(
        id=row.id, source=row.source, code=row.code, operation_type=row.operation_type,
        amount=row.amount, currency=row.currency,
    )


def execute(session: Session, run: ReconciliationRun) -> int:
    if run.status != "PENDING":
        raise ValueError("Only pending runs are executable")
    ready, reason, coverage = source_readiness(session)
    if not ready:
        run.status = "BLOCKED"
        run.message = reason
        run.finished_at = now()
        session.commit()
        return 0

    run.status = "RUNNING"
    session.flush()
    try:
        remittances = session.scalars(select(Remittance).order_by(Remittance.id)).all()
        payments = session.scalars(select(Payment).order_by(Payment.id)).all()
        index: dict[tuple[str, str], list[Remittance]] = defaultdict(list)
        payment_index: dict[tuple[str, str], list[PaymentEvidence]] = defaultdict(list)
        for rem in remittances:
            index[(rem.source, rem.code)].append(rem)
        for payment in payments:
            payment_index[(payment.source, payment.code)].append(_payment(payment))

        count = 0
        processed = set()
        for rem in remittances:
            if rem.id in processed:
                continue
            evidence = _operation(rem)
            if rem.direction in ("BO_TO_CL", "CL_TO_BO"):
                origin = "BOLIVIA" if rem.direction == "BO_TO_CL" else "CHILE"
                if rem.source != origin:
                    if index.get((origin, rem.code)):
                        # Will be evaluated by the origin's own record.
                        continue
                    decision = Decision("MISSING_ORIGIN", "Origin operation not found")
                    candidates = []
                    destination = rem.source
                else:
                    destination = "CHILE" if origin == "BOLIVIA" else "BOLIVIA"
                    candidates = [c for c in index.get((destination, rem.code), [])
                                  if c.direction in (None, rem.direction)]
                    # Multiple same-code origin rows cannot be safely paired.
                    if len(index[(origin, rem.code)]) > 1:
                        decision = Decision("MANUAL_REVIEW", "Ambiguous origin code")
                    elif not candidates and index.get((destination, rem.code)):
                        decision = Decision("STATUS_MISMATCH", "Counterpart has a contradictory direction")
                    else:
                        # Destination may have only a payment, not a mirrored remesa.
                        decision = decide(evidence, [_operation(c) for c in candidates],
                                          payment_index.get((destination, rem.code), []))
            else:
                candidates = []
                destination = "CHILE" if rem.source == "BOLIVIA" else "BOLIVIA"
                decision = Decision("INSUFFICIENT_DATA", "Direction not established")

            # The persisted coverage describes the latest rolling window, not a
            # complete historical index. Never call old unmatched rows missing.
            window = coverage[(destination, "remittance")]["window_start_dt"]
            if rem.occurred_at is None or rem.occurred_at < window:
                if decision.result in {"MISSING_ORIGIN", "MISSING_DESTINATION", "PAYMENT_MISSING"}:
                    decision = Decision("INSUFFICIENT_DATA",
                                        "Historical coverage cannot prove absence")
            counterpart_id = candidates[0].id if len(candidates) == 1 else None
            session.add(ReconciliationMatch(
                run_id=run.id, remittance_id=rem.id, counterpart_id=counterpart_id,
                result=decision.result, reason=decision.reason,
                evidence={
                    "source_record_id": rem.source_record_id,
                    "candidate_ids": [c.id for c in candidates],
                    "destination": destination,
                    "verified_amount": decision.verified_amount,
                    "source_sync_finished_at": coverage[(rem.source, "remittance")]["finished_at"],
                    "destination_sync_finished_at": coverage[(destination, "remittance")]["finished_at"],
                },
                checked_at=now(),
            ))
            processed.add(rem.id)
            if counterpart_id is not None:
                processed.add(counterpart_id)
            if decision.result not in {"MATCHED", "PENDING"}:
                session.add(Discrepancy(
                    run_id=run.id, code=rem.code,
                    category=decision.result, description=decision.reason,
                ))
                count += 1

        run.status = "COMPLETED"
        run.finished_at = now()
        run.message = (
            f"{count} findings; operational presence only, "
            "payment amounts and financial settlements are NOT certified"
        )
        session.commit()
        return count
    except Exception:
        session.rollback()
        raise
