"""Idempotent source persistence and derived operational projections."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.models import (
    Payment, Remittance, RemittanceEvent, SourceLink, SourceRecord, SourceVersion, now,
)


def safe(value):
    if isinstance(value, (datetime, date, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    return value


def _source_link(session: Session, record_id: int, kind: str, entity_id: int) -> None:
    existing = session.scalar(select(SourceLink.id).where(
        SourceLink.source_record_id == record_id,
        SourceLink.entity_type == kind,
        SourceLink.entity_id == entity_id,
    ))
    if existing is None:
        session.add(SourceLink(
            source_record_id=record_id, entity_type=kind, entity_id=entity_id,
            role="SOURCE", created_at=now(),
        ))


def ingest(session: Session, row) -> bool:
    """Persist one source version and update its normalized projection in the same TX.

    The extractor must select only fields required for reconciliation.
    """
    payload = safe(row.raw)
    signature = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    record = session.scalar(select(SourceRecord).where(
        SourceRecord.source == row.source,
        SourceRecord.dataset == row.dataset,
        SourceRecord.source_id == row.source_id,
    ))
    if record is not None and record.payload_hash == signature:
        return False

    if record is None:
        record = SourceRecord(
            source=row.source, dataset=row.dataset, source_id=row.source_id,
            code=row.code, status=row.status, amount=row.amount, currency=row.currency,
            payload=payload, payload_hash=signature,
        )
        session.add(record)
        session.flush()
    else:
        record.code = row.code
        record.status = row.status
        record.amount = row.amount
        record.currency = row.currency
        record.payload_hash = signature
        record.payload = payload
        session.flush()

    version = SourceVersion(record_id=record.id, payload_hash=signature, payload=payload)
    session.add(version)
    session.flush()

    if row.dataset == "remittance":
        projection = session.scalar(select(Remittance).where(
            Remittance.source_record_id == record.id
        ))
        old_status = projection.status if projection is not None else None
        if projection is None:
            projection = Remittance(source_record_id=record.id)
            session.add(projection)
        projection.source = row.source
        projection.code = row.code
        projection.operation_type = row.operation_type
        projection.direction = row.direction
        projection.status = row.status
        projection.amount = row.amount
        projection.currency = row.currency
        projection.occurred_at = row.occurred_at
        projection.observed_at = now()
        session.flush()
        _source_link(session, record.id, "REMITTANCE", projection.id)
        session.add(RemittanceEvent(
            remittance_id=projection.id, source_version_id=version.id,
            event_type=("OBSERVED_CREATED" if old_status is None
                        else "OBSERVED_STATUS_CHANGE" if old_status != row.status
                        else "OBSERVED_DATA_CHANGE"),
            status_before=old_status, status_after=row.status,
            effective_at=row.occurred_at if old_status is None else None,
            observed_at=now(),
        ))
    elif row.dataset == "payment":
        projection = session.scalar(select(Payment).where(
            Payment.source_record_id == record.id
        ))
        if projection is None:
            projection = Payment(source_record_id=record.id)
            session.add(projection)
        projection.source = row.source
        projection.code = row.code
        projection.operation_type = row.operation_type
        projection.amount = row.amount
        projection.currency = row.currency
        projection.occurred_at = row.occurred_at
        projection.observed_at = now()
        session.flush()
        _source_link(session, record.id, "PAYMENT", projection.id)
    else:
        raise ValueError(f"Unsupported dataset: {row.dataset}")
    return True
