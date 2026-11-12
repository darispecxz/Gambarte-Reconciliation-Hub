"""Offline tests for indexed, resumable Chile count verification."""
from types import SimpleNamespace
import pytest
from app.integrations.source import validate_read_query
from scripts.pilot_chile_count_scan import (
    SQL, compare, validate_request, key, advance,
)


def settings(**overrides):
    values=dict(db_host="pilot-db",db_name="gambarte_reconciliation_pilot",
                enable_source_etl=False,source_mapping_verified=False)
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("dataset",["payment","remittance"])
def test_indexed_queries_only_return_primary_keys(dataset):
    sql=SQL[dataset]
    validate_read_query(sql)
    assert "FORCE INDEX (PRIMARY)" in sql
    assert "LIMIT :lim" in sql
    assert ":from_date" in sql and ":to_date" in sql
    assert "COUNT(*)" not in sql
    assert "ORDER BY" in sql


def test_count_status_requires_both_scans_exhausted():
    imp=dict(rows_seen=339,scan_exhausted=True)
    assert compare(dict(rows_counted=339,scan_exhausted=True),imp)=="COUNT_MATCH_NOT_CERTIFIED"
    assert compare(dict(rows_counted=338,scan_exhausted=True),imp)=="COUNT_MISMATCH_REVIEW_REQUIRED"
    assert compare(dict(rows_counted=339,scan_exhausted=False),imp)=="COUNT_SCAN_IN_PROGRESS"
    assert compare(dict(rows_counted=339,scan_exhausted=True),
                   dict(rows_seen=339,scan_exhausted=False))=="IMPORT_SCAN_INCOMPLETE"


def test_composite_cursors_do_not_reset():
    row=dict(operation_type=5,code=876,cursor_destination=7)
    assert key("remittance",row)==(5,876,7)
    state=dict(last_id=0,last_op=0,last_code=0,last_dest=0)
    changed=advance("remittance",row,state)
    assert changed["last_op"]==5 and changed["last_code"]==876
    assert changed["last_dest"]==7 and state["last_op"]==0
    pay=dict(source_pk=100,operation_type=3)
    assert key("payment",pay)==(100,3)
    assert advance("payment",pay,state)["last_id"]==100


def test_safety_rejects_nonpilot_and_missing_permission():
    with pytest.raises(RuntimeError):
        validate_request(settings(db_host="main-db"),"payment","2026-01",50,2,True,True,2)
    with pytest.raises(ValueError):
        validate_request(settings(),"payment","2026-01",50,2,True,False,2)
    with pytest.raises(ValueError):
        validate_request(settings(),"payment","2026-01",51,2,True,True,2)
    with pytest.raises(ValueError):
        validate_request(settings(),"payment","2026-01",50,11,True,True,2)
