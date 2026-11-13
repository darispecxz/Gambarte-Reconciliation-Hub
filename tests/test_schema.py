"""DDL/model smoke tests; production integration requires MariaDB test services."""
from sqlalchemy import MetaData
from app.core.database import Base
from app.infrastructure import models  # noqa: F401


def test_stage_b_tables_present():
    required = {
        "source_records", "source_versions", "sync_runs",
        "reconciliation_runs", "discrepancies", "sync_cursors",
        "source_links", "remittances", "payments", "remittance_events",
        "reconciliation_matches",
    }
    assert required.issubset(Base.metadata.tables)


def test_unique_identities_defined():
    source = Base.metadata.tables["source_records"]
    assert any(c.name == "uq_source" for c in source.constraints)
    rem = Base.metadata.tables["remittances"]
    assert any(c.name == "uq_remittance_record" for c in rem.constraints)
