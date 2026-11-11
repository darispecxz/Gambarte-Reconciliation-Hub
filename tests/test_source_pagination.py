"""Keyset boundary contract, independent of production sources."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from app.integrations.source import fetch_page


def _row(pk, operation=3):
    return {"source_pk": pk, "operation_type": operation, "code": pk,
            "status_code": 1, "amount": Decimal("1"),
            "currency_id": "BOB", "occurred_at": datetime(2026, 11, 1)}


def _engine_rows(rows):
    engine = MagicMock()
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.execute.return_value.mappings.return_value.all.return_value = rows
    return engine, connection


def test_duplicate_cursor_in_chile_consolidated_view_fails_closed():
    engine, conn = _engine_rows([_row(1), _row(1)])
    with patch("app.integrations.source.source_engine", return_value=engine):
        with pytest.raises(RuntimeError, match="non-unique source cursor"):
            fetch_page("CHILE", "remittance", datetime(2026, 11, 1), limit=1)
    engine.dispose.assert_called_once()


def test_one_extra_row_protects_pagination_boundary():
    engine, conn = _engine_rows([_row(1), _row(2)])
    with patch("app.integrations.source.source_engine", return_value=engine):
        page = fetch_page("CHILE", "remittance", datetime(2026, 11, 1), limit=1)
    assert len(page) == 1
    assert page[0].source_pk == 1
    assert conn.execute.call_args.args[1]["lim"] == 2
