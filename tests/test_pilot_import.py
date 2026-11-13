"""Pilot safety tests without source or database access."""
from types import SimpleNamespace
import pytest
from scripts.pilot_import import validate_pilot


def settings(**changes):
    base = dict(enable_source_etl=False, source_mapping_verified=False,
                db_host="pilot-db", db_name="gambarte_reconciliation_pilot")
    base.update(changes)
    return SimpleNamespace(**base)


def test_accepts_bounded_dry_run_with_pilot_settings():
    validate_pilot(settings(), "BOLIVIA", "remittance", 60, 50, False, False)
    validate_pilot(settings(), "BOLIVIA", "payment", 60, 50, True, True)
    validate_pilot(settings(), "CHILE", "payment", 60, 50, True, True)
    validate_pilot(settings(), "CHILE", "remittance", 60, 50, True, True)


@pytest.mark.parametrize("source,dataset", [
    ("OTHER", "remittance"), ("CHILE", "other"),
])
def test_unknown_datasets_are_rejected(source, dataset):
    with pytest.raises(ValueError, match="Unsupported pilot"):
        validate_pilot(settings(), source, dataset, 60, 50, True, True)


@pytest.mark.parametrize("overrides", [
    {"db_host": "mariadb"}, {"db_name": "gambarte_reconciliation"},
    {"enable_source_etl": True}, {"source_mapping_verified": True},
])
def test_refuses_unsafe_target_or_enabled_workers(overrides):
    with pytest.raises(RuntimeError):
        validate_pilot(settings(**overrides), "BOLIVIA", "remittance",
                       60, 50, True, True)


def test_apply_requires_explicit_acknowledgment():
    with pytest.raises(ValueError, match="acknowledge"):
        validate_pilot(settings(), "BOLIVIA", "remittance", 60, 50, True, False)


@pytest.mark.parametrize("source,dataset,days,limit", [
    ("BOLIVIA", "remittance", 61, 50),
    ("BOLIVIA", "remittance", 60, 51),
])
def test_rejects_out_of_scope_or_unbounded(source, dataset, days, limit):
    with pytest.raises(ValueError):
        validate_pilot(settings(), source, dataset, days, limit, True, True)


def test_rejects_more_than_two_pages():
    with pytest.raises(ValueError, match="1..2 pages"):
        validate_pilot(settings(), "BOLIVIA", "remittance",
                       60, 50, True, True, pages=3)
