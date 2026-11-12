"""Bounded monthly count helper tests (no external databases)."""
from types import SimpleNamespace
import pytest

from scripts.pilot_month_count import (
    COUNT_SQL, compare_status, validate_settings,
)
from app.integrations.source import validate_read_query


def test_count_contracts_are_nonlocking_selects():
    assert len(COUNT_SQL) == 4
    expected = {
        ("BOLIVIA", "remittance"): ("remesa r", "r.id_operacion IN (4,16)", "r.fec_crea_remesa"),
        ("CHILE", "remittance"): ("tmp_reporte_remesa r", "r.id_operacion IN (3,5,6,8)", "r.fec_crea_remesa"),
        ("BOLIVIA", "payment"): ("pago p", "p.id_operacion IN (4,7)", "p.fec_crea_pago"),
        ("CHILE", "payment"): ("pago p", "p.id_operacion IN (3,5,6,8)", "p.fec_crea_pago"),
    }
    for pair, query in COUNT_SQL.items():
        validate_read_query(query)
        assert all(fragment in query for fragment in expected[pair])
        assert ":from_date" in query and ":to_date" in query


def test_status_never_claims_certification():
    assert compare_status(False, True, 9, 9) == "NOT_COUNTED"
    assert compare_status(True, False, 9, 9) == "SCAN_INCOMPLETE"
    assert compare_status(True, True, 9, 9) == "COUNT_MATCH_NOT_CERTIFIED"
    assert compare_status(True, True, 9, 10) == "COUNT_MISMATCH_REVIEW_REQUIRED"


def test_rejects_main_db_and_active_etl():
    base = dict(db_host="pilot-db", db_name="gambarte_reconciliation_pilot",
                enable_source_etl=False, source_mapping_verified=False)
    validate_settings(SimpleNamespace(**base), "CHILE", "remittance", "2026-01")
    for invalid in ({"db_host": "db"}, {"enable_source_etl": True},
                    {"source_mapping_verified": True}):
        with pytest.raises(RuntimeError):
            validate_settings(SimpleNamespace(**{**base, **invalid}),
                              "CHILE", "remittance", "2026-01")
