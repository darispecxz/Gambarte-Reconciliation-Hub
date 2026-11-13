"""Offline runner tests. All source/pilot operations mocked."""
from types import SimpleNamespace
from unittest.mock import patch, call
import pytest

from scripts.pilot_backfill_runner import (
    check_request, run, selected_datasets, verified_result,
)


def config():
    return SimpleNamespace(
        db_host="pilot-db", db_name="gambarte_reconciliation_pilot",
        enable_source_etl=False, source_mapping_verified=False,
    )


def test_selector_is_deterministic():
    assert selected_datasets("CHILE", "all") == [
        ("CHILE", "remittance"), ("CHILE", "payment")]
    assert len(selected_datasets("ALL", "all")) == 4


def test_guard_rejects_apply_without_ack_and_unbounded_work():
    with patch("scripts.pilot_backfill_runner.get_settings", return_value=config()):
        with pytest.raises(ValueError, match="acknowledge"):
            check_request("2026-01", "CHILE", "payment", True, False, 5, 2, 50, 2)
        with pytest.raises(ValueError, match="max-batches"):
            check_request("2026-01", "CHILE", "payment", False, False, 6, 2, 50, 2)
        with pytest.raises(ValueError):
            check_request("2026-01", "ALL", "all", False, False, 5, 2, 51, 2)


def test_verify_only_skips_ingestion_and_audit():
    with (patch("scripts.pilot_backfill_runner.get_settings", return_value=config()),
          patch("scripts.pilot_backfill_runner.verify_month", return_value={
              "counted": True, "status": "COUNT_MATCH_NOT_CERTIFIED",
          }) as verify,
          patch("scripts.pilot_backfill_runner.execute") as ingest,
          patch("scripts.pilot_backfill_runner.audit") as audit):
        result = run("2026-01", "CHILE", "all")
    assert len(result) == 2
    assert verify.call_count == 2
    ingest.assert_not_called()
    audit.assert_not_called()


def test_applied_batches_resume_and_verify_on_exhaustion():
    with (patch("scripts.pilot_backfill_runner.get_settings", return_value=config()),
          patch("scripts.pilot_backfill_runner.execute",
                side_effect=[{"rows": 100, "exhausted": False},
                             {"rows": 46, "exhausted": True}]) as ingest,
          patch("scripts.pilot_backfill_runner.audit") as audit,
          patch("scripts.pilot_backfill_runner.sleep") as pause,
          patch("scripts.pilot_backfill_runner.verify_month", return_value={
              "counted": True, "status": "COUNT_MATCH_NOT_CERTIFIED",
          }) as verify):
        result = run("2026-01", "CHILE", "payment", apply=True,
                     acknowledge=True, max_batches=3)
    assert ingest.call_count == 2
    assert audit.call_count == 2
    pause.assert_called_once_with(2)
    verify.assert_called_once_with("CHILE", "payment", "2026-01", count=True)
    assert result[("CHILE", "payment")] == "COUNT_MATCH_NOT_CERTIFIED"


def test_cap_does_not_count_or_claim_finished():
    with (patch("scripts.pilot_backfill_runner.get_settings", return_value=config()),
          patch("scripts.pilot_backfill_runner.execute",
                return_value={"rows": 100, "exhausted": False}) as ingest,
          patch("scripts.pilot_backfill_runner.audit"),
          patch("scripts.pilot_backfill_runner.sleep"),
          patch("scripts.pilot_backfill_runner.verify_month") as verify):
        result = run("2026-01", "CHILE", "payment", apply=True,
                     acknowledge=True, max_batches=2)
    assert ingest.call_count == 2
    verify.assert_not_called()
    assert result[("CHILE", "payment")] == "IN_PROGRESS"


def test_mismatch_stops_runner():
    with (patch("scripts.pilot_backfill_runner.get_settings", return_value=config()),
          patch("scripts.pilot_backfill_runner.verify_month", return_value={
              "counted": True, "status": "COUNT_MISMATCH_REVIEW_REQUIRED",
          })):
        with pytest.raises(RuntimeError, match="mismatch"):
            run("2026-01", "CHILE", "payment")


def test_never_accepts_incomplete_result_as_verified():
    with pytest.raises(RuntimeError):
        verified_result({"counted": True, "status": "SCAN_INCOMPLETE"},
                        "CHILE", "payment", "2026-01")


def test_unindexed_count_is_blocked_but_other_dataset_is_checked():
    with (patch("scripts.pilot_backfill_runner.get_settings", return_value=config()),
          patch("scripts.pilot_backfill_runner.verify_month", side_effect=[
              {"counted": False, "status": "COUNT_PLAN_BLOCKED"},
              {"counted": True, "status": "COUNT_MATCH_NOT_CERTIFIED"},
          ]) as verify,
          patch("scripts.pilot_backfill_runner.execute") as ingest):
        with pytest.raises(RuntimeError, match="COUNT plan blocked"):
            run("2026-01", "CHILE", "all")
    assert verify.call_count == 2
    ingest.assert_not_called()
