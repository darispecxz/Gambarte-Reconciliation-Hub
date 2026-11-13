"""Operational stage B: source cursors, source links, normalized data and match results.

Revision ID: 0002_operational
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_operational"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_cursors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("dataset", sa.String(20), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("scan_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_source_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_operation_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_progress", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("source", "dataset", name="uq_cursor_source_dataset"),
    )
    op.create_table(
        "source_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_record_id", sa.BigInteger(), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_record_id", "entity_type", "entity_id", name="uq_source_link"),
    )
    op.create_index("ix_source_link_target", "source_links", ["entity_type", "entity_id"])
    op.create_index("ix_source_links_source_record_id", "source_links", ["source_record_id"])
    op.create_table(
        "remittances",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_record_id", sa.BigInteger(), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("operation_type", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(10), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("amount", sa.Numeric(22, 6), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_record_id", name="uq_remittance_record"),
    )
    op.create_index("ix_remittance_match", "remittances", ["code", "direction", "operation_type"])
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_record_id", sa.BigInteger(), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("operation_type", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(22, 6), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_record_id", name="uq_payment_record"),
    )
    op.create_index("ix_payment_code", "payments", ["source", "code", "operation_type"])
    op.create_table(
        "remittance_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("remittance_id", sa.BigInteger(), sa.ForeignKey("remittances.id"), nullable=False),
        sa.Column("source_version_id", sa.BigInteger(), sa.ForeignKey("source_versions.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("status_before", sa.String(30), nullable=True),
        sa.Column("status_after", sa.String(30), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_version_id", name="uq_event_source_version"),
    )
    op.create_index("ix_remittance_events_remittance_id", "remittance_events", ["remittance_id"])
    op.create_table(
        "reconciliation_matches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("reconciliation_runs.id"), nullable=False),
        sa.Column("remittance_id", sa.BigInteger(), sa.ForeignKey("remittances.id"), nullable=False),
        sa.Column("counterpart_id", sa.BigInteger(), sa.ForeignKey("remittances.id"), nullable=True),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_match_run_result", "reconciliation_matches", ["run_id", "result"])
    op.create_index("ix_reconciliation_matches_run_id", "reconciliation_matches", ["run_id"])
    op.create_index("ix_reconciliation_matches_remittance_id", "reconciliation_matches", ["remittance_id"])


def downgrade() -> None:
    op.drop_table("reconciliation_matches")
    op.drop_table("remittance_events")
    op.drop_table("payments")
    op.drop_table("remittances")
    op.drop_table("source_links")
    op.drop_table("sync_cursors")
