"""Offline safety tests for the Phase C bounded source-code investigation."""
from types import SimpleNamespace
import pytest

from scripts.pilot_phase_c_source_lookup_2026 import (
    candidates, classify_source_rows, targeted_sql, validate_code, PAGE_LIMIT,
)


@pytest.mark.parametrize("origin",["BOLIVIA","CHILE"])
def test_targeted_sql_uses_existing_projection_and_exact_code(origin):
    query=targeted_sql(origin)
    assert query.lstrip().startswith("SELECT")
    assert "r.codigo = :code" in query
    assert ":cutoff" not in query
    assert "ORDER BY" in query and "LIMIT :lim" in query


@pytest.mark.parametrize("bad",["", "0", "-123","1 OR 1=1","12;DELETE",
                                 "001", "a23", "9"*19])
def test_rejects_invalid_codes(bad):
    with pytest.raises(ValueError):
        validate_code(bad)


def test_only_no_origin_codes_selected_and_deduplicated():
    source=[
        dict(direction="BO_TO_CL",payment_code="123",
             payment_source="CHILE",assessment="NO_ORIGIN_IN_PILOT"),
        dict(direction="BO_TO_CL",payment_code="123",
             payment_source="CHILE",assessment="NO_ORIGIN_IN_PILOT"),
        dict(direction="CL_TO_BO",payment_code="456",
             payment_source="BOLIVIA",assessment="PROVISIONAL_INVERSE_PAIR"),
    ]
    result=candidates(source,25)
    assert len(result)==1
    assert result[0]["payment_records_in_pilot"]==2
    assert result[0]["payment_code"]=="123"


def test_hard_limit_does_not_silently_drop_cases():
    records=[dict(direction="BO_TO_CL",payment_source="CHILE",
                  payment_code=str(i+1),assessment="NO_ORIGIN_IN_PILOT")
             for i in range(26)]
    with pytest.raises(RuntimeError, match="exceed"):
        candidates(records,25)


def test_cross_year_source_counts_and_no_data():
    rows=[
        dict(code="123",operation_type=16,
             occurred_at=__import__("datetime").datetime(2025,12,28)),
        dict(code="123",operation_type=16,
             occurred_at=__import__("datetime").datetime(2026,1,5)),
    ]
    result=classify_source_rows(rows,"123")
    assert result["origin_rows_2025"]==1
    assert result["origin_rows_2026"]==1
    assert result["origin_rows_found"]==2
    assert classify_source_rows([],"123")["origin_rows_found"]==0


def test_refuses_query_cap_and_wrong_code():
    rows=[dict(code="123",operation_type=3,occurred_at=None)]*PAGE_LIMIT
    with pytest.raises(RuntimeError,match="50"):
        classify_source_rows(rows,"123")
    with pytest.raises(RuntimeError,match="different code"):
        classify_source_rows(rows[:1],"444")
