"""Aggregate code overlap in the isolated pilot; never asserts a match."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.core.config import get_settings
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker


OVERLAP_SQL = text("""
    WITH origins AS (
        SELECT code, COUNT(*) AS origin_count,
               SUM(status = 'PAID') AS paid_count
        FROM remittances WHERE source = :origin GROUP BY code
    ), payouts AS (
        SELECT code, COUNT(*) AS payment_count
        FROM payments WHERE source = :destination GROUP BY code
    )
    SELECT COUNT(*) AS origin_code_groups,
           COALESCE(SUM(o.origin_count), 0) AS origin_rows,
           COALESCE(SUM(o.origin_count > 1), 0) AS ambiguous_origin_codes,
           COALESCE(SUM(COALESCE(p.payment_count, 0) = 0), 0) AS no_payment_in_sample,
           COALESCE(SUM(p.payment_count = 1), 0) AS one_payment_in_sample,
           COALESCE(SUM(p.payment_count > 1), 0) AS multiple_payments_in_sample,
           COALESCE(SUM(o.origin_count = 1 AND p.payment_count = 1
                        AND o.paid_count = 1), 0) AS unique_paid_candidates
    FROM origins o LEFT JOIN payouts p ON p.code = o.code
""")

UNLINKED_PAYMENT_SQL = text("""
    WITH origins AS (
        SELECT DISTINCT code FROM remittances WHERE source = :origin
    ), payouts AS (
        SELECT code, COUNT(*) AS payment_count
        FROM payments WHERE source = :destination GROUP BY code
    )
    SELECT COUNT(*) AS payment_codes_without_sample_origin,
           COALESCE(SUM(p.payment_count), 0) AS payment_rows_without_sample_origin
    FROM payouts p LEFT JOIN origins o ON o.code = p.code
    WHERE o.code IS NULL
""")


def run():
    settings = get_settings()
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Candidate audit refuses non-pilot target")
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
                for direction, origin, destination in (
                    ("BO_TO_CL", "BOLIVIA", "CHILE"),
                    ("CL_TO_BO", "CHILE", "BOLIVIA"),
                ):
                    params = {"origin": origin, "destination": destination}
                    overlap = connection.execute(OVERLAP_SQL, params).mappings().one()
                    unlinked = connection.execute(UNLINKED_PAYMENT_SQL, params).mappings().one()
                    print(f"direction={direction}")
                    for name, value in {**overlap, **unlinked}.items():
                        print(f"{name}={value}")
            finally:
                connection.rollback()
    finally:
        engine.dispose()
    print("sample_only=True read_only=True operational_matches_certified=False")


if __name__ == "__main__":
    run()
