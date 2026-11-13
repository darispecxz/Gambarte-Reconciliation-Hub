"""Offline safety checks for opt-in recent pilot refresh."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.integrations.source import SQL
from scripts.pilot_recent_refresh_2026 import PAIRS, recent_sql, validate


def settings(**changes):
    data = dict(db_host="pilot-db", db_name="gambarte_reconciliation_pilot",
                enable_source_etl=False, source_mapping_verified=False)
    data.update(changes)
    return SimpleNamespace(**data)


@pytest.mark.parametrize("source,dataset", PAIRS)
def test_recent_queries_are_select_only_and_bounded(source,dataset):
    sql = recent_sql(source,dataset)
    assert sql.lstrip().startswith("SELECT")
    assert ":cutoff" not in sql
    assert ":from_date" in sql and ":to_date" in sql
    assert "LIMIT :lim" in sql and "ORDER BY" in sql
    assert SQL[(source,dataset)] != sql
    if dataset == "remittance":
        assert "fec_mod_remesa >= :from_date" in sql


@pytest.mark.parametrize("changes", [
    dict(db_host="mariadb"),dict(db_name="gambarte_reconciliation"),
    dict(enable_source_etl=True),dict(source_mapping_verified=True),
])
def test_rejects_nonpilot_or_enabled_etl(changes):
    with pytest.raises(RuntimeError):
        validate(settings(**changes),date(2026,11,13),7,30,2,False,False)


@pytest.mark.parametrize("days,max_pages,pause", [
    (0,30,2),(15,30,2),(7,0,2),(7,201,2),(7,30,1),(7,30,61)
])
def test_rejects_unbounded_requests(days,max_pages,pause):
    with pytest.raises(ValueError):
        validate(settings(),date(2026,11,13),days,max_pages,pause,False,False)


def test_explicit_consent_required():
    with pytest.raises(ValueError,match="acknowledge"):
        validate(settings(),date(2026,11,13),7,30,2,True,False)
    validate(settings(),date(2026,11,13),7,30,2,True,True)
