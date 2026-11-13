"""Source connection safety regression tests.

The integration test uses CI's disposable MariaDB (a writable user) to prove
that START TRANSACTION READ ONLY rejects updates at the database layer.
"""
import os
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.integrations.source import read_only_transaction, validate_read_query, SQL


@pytest.mark.parametrize("sql", [
    "UPDATE remesa SET estado=1",
    "DELETE FROM pago",
    "INSERT INTO pago (codigo) VALUES ('x')",
    "CALL some_proc()",
    "SELECT * FROM pago; DELETE FROM pago",
    "SELECT * FROM pago FOR UPDATE",
    "SELECT * FROM pago LOCK IN SHARE MODE",
    "SELECT * INTO OUTFILE '/tmp/data' FROM pago",
    "/* comment */ SELECT * FROM pago",
])
def test_mutating_or_multi_statement_sql_is_rejected(sql):
    with pytest.raises(ValueError):
        validate_read_query(sql)


def test_all_predefined_source_queries_are_single_nonlocking_selects():
    for sql in SQL.values():
        validate_read_query(sql)


def test_rollback_even_if_query_fails():
    fake_connection = MagicMock()
    fake_connection.exec_driver_sql.return_value = None
    fake_engine = MagicMock()
    fake_engine.connect.return_value.__enter__ = MagicMock(return_value=fake_connection)
    fake_engine.connect.return_value.__exit__ = MagicMock(return_value=None)

    with pytest.raises(RuntimeError, match="read failure"):
        with read_only_transaction(fake_engine) as connection:
            assert connection is fake_connection
            raise RuntimeError("read failure")
    fake_connection.exec_driver_sql.assert_called_once_with("START TRANSACTION READ ONLY")
    fake_connection.rollback.assert_called_once()


@pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1", reason="MariaDB CI integration only")
def test_real_mariadb_rejects_writes_during_read_only_transaction():
    # Use the isolated, writable central test DB to exercise the DB guard.
    # Never run this against the real Bolivia / Chile databases.
    from app.core.database import engine

    with read_only_transaction(engine) as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        with pytest.raises(DBAPIError):
            connection.exec_driver_sql("UPDATE sync_runs SET count = count WHERE id = -1")

    # Transaction guard must not leak across connections from the pool.
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
