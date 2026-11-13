"""Use Chile real composite primary key for source synchronization.

Revision ID: 0004_chile_cursor
Revises: 0003_operational_cutoff
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_chile_cursor"
down_revision = "0003_operational_cutoff"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Cannot silently reinterpret old Chile source_ids as new (op,code,dest).
    # Require explicit migration/re-ingestion decision if the ETL was enabled.
    old_rows = connection.execute(sa.text(
        "SELECT COUNT(*) FROM source_records "
        "WHERE source = 'CHILE' AND dataset = 'remittance'"
    )).scalar_one()
    if old_rows:
        raise RuntimeError(
            "Existing Chile remittance records use the former source_id. "
            "Do not upgrade automatically: back up the central DB and plan "
            "a safe identity migration before re-enabling ETL."
        )
    op.add_column("sync_cursors", sa.Column(
        "last_code", sa.BigInteger(), nullable=False, server_default="0"
    ))
    op.add_column("sync_cursors", sa.Column(
        "last_destination_id", sa.Integer(), nullable=False, server_default="0"
    ))
    # Any interrupted Chile cursor used the wrong ordering. Restart from
    # beginning of its existing coverage window after migration.
    op.execute("UPDATE sync_cursors SET last_source_id = 0, "
               "last_operation_id = 0, in_progress = 0 "
               "WHERE source = 'CHILE' AND dataset = 'remittance'")


def downgrade():
    op.drop_column("sync_cursors", "last_destination_id")
    op.drop_column("sync_cursors", "last_code")
