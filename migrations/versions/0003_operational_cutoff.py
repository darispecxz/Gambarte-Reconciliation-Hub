"""Add optional historical cutoff for operational reconciliation.

Revision ID: 0003_operational_cutoff
Revises: 0002_operational
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_operational_cutoff"
down_revision = "0002_operational"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reconciliation_runs", sa.Column("cutoff_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("reconciliation_runs", "cutoff_at")
