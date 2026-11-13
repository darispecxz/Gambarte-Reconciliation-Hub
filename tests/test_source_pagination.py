"""Chile remittance PRIMARY keyset: identity, boundaries and safety."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest

from app.integrations.source import fetch_page, normalize, SQL


def _row(code, operation=3, destination=1, remittance_id=99):
    return {
        "source_pk": remittance_id, "operation_type": operation, "code": code,
        "cursor_destination": destination,
        "status_code": 1, "amount": Decimal("1"), "currency_id": "BOB",
        "occurred_at": datetime(2026, 11, 1),
    }


def _engine_rows(rows):
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.mappings.return_value.all.return_value = rows
    return engine, conn


def test_chile_identity_uses_real_primary_not_id_remesa():
    first = normalize("CHILE", "remittance", _row(100, destination=1, remittance_id=9))
    second = normalize("CHILE", "remittance", _row(100, destination=2, remittance_id=9))
    assert first.source_id == "3:100:1"
    assert second.source_id == "3:100:2"
    assert first.source_id != second.source_id
    assert first.source_pk == second.source_pk == 9


def test_duplicate_primary_fails_closed():
    engine, _ = _engine_rows([_row(100), _row(100)])
    with patch("app.integrations.source.source_engine", return_value=engine):
        with pytest.raises(RuntimeError, match="non-unique source cursor"):
            fetch_page("CHILE", "remittance", datetime(2026, 11, 1), limit=1)
    engine.dispose.assert_called_once()


def test_one_extra_row_protects_page_boundary():
    engine, conn = _engine_rows([_row(100), _row(101)])
    with patch("app.integrations.source.source_engine", return_value=engine):
        page = fetch_page("CHILE", "remittance", datetime(2026, 11, 1), limit=1)
    assert len(page) == 1
    assert page[0].cursor_code == 100
    assert conn.execute.call_args.args[1]["lim"] == 2


def test_resumption_after_equal_code_different_destination():
    engine, conn = _engine_rows([_row(100, destination=2), _row(101)])
    with patch("app.integrations.source.source_engine", return_value=engine):
        page = fetch_page("CHILE", "remittance", datetime(2026, 11, 1),
                          last_operation_id=3, last_code=100,
                          last_destination=1, limit=1)
    assert page[0].source_id == "3:100:2"
    assert conn.execute.call_args.args[1]["last_dest"] == 1


def test_out_of_order_or_regression_fails_closed():
    engine, _ = _engine_rows([_row(101), _row(100)])
    with patch("app.integrations.source.source_engine", return_value=engine):
        with pytest.raises(RuntimeError, match="unordered or regressed"):
            fetch_page("CHILE", "remittance", datetime(2026, 11, 1), limit=1)


def test_sql_orders_by_primary_without_offset():
    sql = SQL[("CHILE", "remittance")]
    assert "ORDER BY r.id_operacion, r.codigo, r.id_destino" in sql
    assert "OFFSET" not in sql.upper()
    assert "r.fec_mod_remesa >= :cutoff" in sql
