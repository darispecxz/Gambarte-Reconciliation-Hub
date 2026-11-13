from datetime import date
from scripts.pilot_backfill_status import summarize


def test_monthly_scan_progress_does_not_certify():
    rows = [{"source": "BOLIVIA", "dataset": "remittance",
             "month_key": "2026-01", "rows_seen": 99,
             "pages_seen": 2, "scan_exhausted": 1}]
    result = summarize(rows, date(2026, 2, 3))
    assert len(result) == 8
    assert result[0] == ("2026-01", "BOLIVIA", "remittance",
                         "SCAN_EXHAUSTED_NOT_CERTIFIED", 99, 2)
    assert result[1][3] == "NOT_STARTED"
