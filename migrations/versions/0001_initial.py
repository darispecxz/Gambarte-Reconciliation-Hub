"""Frozen original five-table schema; no dynamic create_all in migrations.

Changed before first deployment because create_all would generate future tables
on a fresh database, then migration 0002 would fail.
"""
from alembic import op
import sqlalchemy as sa
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("source_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("dataset", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("amount", sa.Numeric(22,6), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source","dataset","source_id",name="uq_source"))
    for column in ("source","dataset","code"):
        op.create_index("ix_source_records_"+column,"source_records",[column])
    op.create_table("source_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("record_id", sa.BigInteger(), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False))
    op.create_index("ix_source_versions_record_id","source_versions",["record_id"])
    op.create_table("sync_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("dataset", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True))
    op.create_table("reconciliation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True))
    op.create_index("ix_reconciliation_runs_status","reconciliation_runs",["status"])
    op.create_table("discrepancies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("reconciliation_runs.id"), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False))
    op.create_index("ix_discrepancies_run_id","discrepancies",["run_id"])

def downgrade():
    for table in ("discrepancies","reconciliation_runs","sync_runs","source_versions","source_records"):
        op.drop_table(table)
