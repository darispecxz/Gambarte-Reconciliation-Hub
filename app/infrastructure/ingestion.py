import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.infrastructure.models import SourceRecord, SourceVersion

def safe(value):
    if isinstance(value, (datetime,date,Decimal)):
        return str(value)
    if isinstance(value,dict):
        return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value,list):
        return [safe(x) for x in value]
    return value

def ingest(session: Session, row) -> bool:
    payload = safe(row.raw)
    signature = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    record = session.scalar(select(SourceRecord).where(
        SourceRecord.source==row.source, SourceRecord.dataset==row.dataset,
        SourceRecord.source_id==row.source_id))
    if record and record.payload_hash == signature:
        return False
    if record is None:
        record = SourceRecord(source=row.source,dataset=row.dataset,
            source_id=row.source_id,code=row.code,status=row.status,
            amount=row.amount,currency=row.currency,payload=payload,payload_hash=signature)
        session.add(record)
        session.flush()
    else:
        record.code=row.code
        record.status=row.status
        record.amount=row.amount
        record.currency=row.currency
        record.payload=payload
        record.payload_hash=signature
    session.add(SourceVersion(record_id=record.id,payload=payload,payload_hash=signature))
    return True
