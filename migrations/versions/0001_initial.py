"""Initial central ingesta and reconciliation schema."""
from alembic import op
from app.core.database import Base
from app.infrastructure import models  # noqa: F401

revision="0001_initial"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
