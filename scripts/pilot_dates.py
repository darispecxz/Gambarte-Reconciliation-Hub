"""Print only aggregate date ranges for the isolated pilot samples."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.core.config import get_settings
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker


RANGES = text("""
    SELECT source, 'remittance' AS dataset, COUNT(*) AS rows_checked,
           MIN(occurred_at) AS earliest, MAX(occurred_at) AS latest
    FROM remittances GROUP BY source
    UNION ALL
    SELECT source, 'payment' AS dataset, COUNT(*) AS rows_checked,
           MIN(occurred_at) AS earliest, MAX(occurred_at) AS latest
    FROM payments GROUP BY source
    ORDER BY source, dataset
""")


def run():
    settings = get_settings()
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Date audit refuses non-pilot target")
    engine = create_engine(URL.create(
        "mysql+pymysql", host=settings.db_host, port=settings.db_port,
        username=settings.db_user, password=settings.db_password,
        database=settings.db_name, query={"charset": "utf8mb4"},
    ), connect_args={"connect_timeout": 10, "read_timeout": 30})
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(connection)
                for row in connection.execute(RANGES).mappings():
                    print(f"{row['source']}/{row['dataset']}: "
                          f"rows={row['rows_checked']} "
                          f"earliest={row['earliest']} latest={row['latest']}")
            finally:
                connection.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    run()
