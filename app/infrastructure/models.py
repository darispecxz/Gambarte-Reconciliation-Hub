"""Persistence models. Source evidence and normalized projections are separate concerns."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        Index, Integer, JSON, Numeric, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def now() -> datetime:
    """Use naive UTC consistently for MariaDB DATETIME columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("source", "dataset", "source_id", name="uq_source"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    dataset: Mapped[str] = mapped_column(String(20), index=True)
    source_id: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(22, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class SourceVersion(Base):
    __tablename__ = "source_versions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20))
    dataset: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    cutoff_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Discrepancy(Base):
    __tablename__ = "discrepancies"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id"), index=True)
    code: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    __table_args__ = (UniqueConstraint("source", "dataset", name="uq_cursor_source_dataset"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20))
    dataset: Mapped[str] = mapped_column(String(20))
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scan_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_source_id: Mapped[int] = mapped_column(BigInteger, default=0)
    last_operation_id: Mapped[int] = mapped_column(Integer, default=0)
    last_code: Mapped[int] = mapped_column(BigInteger, default=0)
    last_destination_id: Mapped[int] = mapped_column(Integer, default=0)
    in_progress: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SourceLink(Base):
    __tablename__ = "source_links"
    __table_args__ = (
        UniqueConstraint("source_record_id", "entity_type", "entity_id", name="uq_source_link"),
        Index("ix_source_link_target", "entity_type", "entity_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(30), default="SOURCE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Remittance(Base):
    """One normalized row per source operation; never merge cross-border rows by code."""
    __tablename__ = "remittances"
    __table_args__ = (
        UniqueConstraint("source_record_id", name="uq_remittance_record"),
        Index("ix_remittance_match", "code", "direction", "operation_type"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    source: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(100))
    operation_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(22, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("source_record_id", name="uq_payment_record"),
                      Index("ix_payment_code", "source", "code", "operation_type"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    source: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(100))
    operation_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(22, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class RemittanceEvent(Base):
    __tablename__ = "remittance_events"
    __table_args__ = (UniqueConstraint("source_version_id", name="uq_event_source_version"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    remittance_id: Mapped[int] = mapped_column(ForeignKey("remittances.id"), index=True)
    source_version_id: Mapped[int] = mapped_column(ForeignKey("source_versions.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    status_before: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status_after: Mapped[str] = mapped_column(String(30))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ReconciliationMatch(Base):
    __tablename__ = "reconciliation_matches"
    __table_args__ = (Index("ix_match_run_result", "run_id", "result"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id"), index=True)
    remittance_id: Mapped[int] = mapped_column(ForeignKey("remittances.id"), index=True)
    counterpart_id: Mapped[int | None] = mapped_column(ForeignKey("remittances.id"), nullable=True)
    result: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=now)
