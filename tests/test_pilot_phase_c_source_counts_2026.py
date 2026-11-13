"""No-source offline validation for Phase C monthly count safety gates."""
from datetime import date,datetime
import pytest

from scripts.pilot_phase_c_source_counts_2026 import (
    SOURCE_COUNT_SQL,interval,assess
)
from app.integrations.source import validate_read_query


def test_month_window_normal_and_partial_cutoff():
    first,last=interval("2026-02",date(2026,11,13))
    assert first==datetime(2026,2,1)
    assert last==datetime(2026,3,1)
    first,last=interval("2026-11",date(2026,11,13))
    assert first==datetime(2026,11,1)
    assert last==datetime(2026,11,14)


def test_month_window_2026_only():
    with pytest.raises(ValueError):
        interval("2025-12",date(2026,11,13))
    with pytest.raises(ValueError):
        interval("2026-12",date(2026,11,13))


def test_queries_are_fixed_safe_selects_and_have_bound_dates():
    assert len(SOURCE_COUNT_SQL)==4
    for sql in SOURCE_COUNT_SQL.values():
        validate_read_query(sql)
        assert ":start_date" in sql and ":end_date" in sql
        assert "COUNT(*)" in sql


def test_count_parity_never_certifies_identity():
    assert assess(17,17)=="MONTHLY_COUNTS_EQUAL_IDENTITIES_UNVERIFIED"
    assert assess(16,17)=="MONTHLY_COUNT_DIFFERENCE_REVIEW"
