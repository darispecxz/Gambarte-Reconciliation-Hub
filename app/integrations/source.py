"""Explicit, read-only SQL adapters; mappings MUST be verified before enabling ETL.

The Chile remittance source is tmp_reporte_remesa: it consolidates remesa
and deposito_bancario. Only projected fields needed for reconciliation are read.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, URL
from app.core.config import get_settings
from app.domain.reconciliation import decimal_amount


@dataclass(frozen=True)
class Extracted:
    source: str
    dataset: str
    source_id: str
    code: str
    status: str
    amount: Decimal | None
    currency: str | None
    raw: dict
    operation_type: int | None = None
    direction: str | None = None
    occurred_at: datetime | None = None
    source_pk: int = 0


# Cursor = (primary key, operation type). The second component makes Chile
# consolidated rows disambiguatable, but uniqueness must be validated in DB.
SQL = {
    ("BOLIVIA", "remittance"): """
        SELECT r.id_remesa AS source_pk, r.codigo AS code, r.estado AS status_code,
               r.monto AS amount, r.mon_rec AS currency_id, r.id_operacion AS operation_type,
               r.fec_crea_remesa AS occurred_at, r.fec_mod_remesa AS updated_at
        FROM remesa r
        WHERE r.id_operacion IN (4,16)
          AND (r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)
          AND (r.id_remesa > :last_id OR
               (r.id_remesa = :last_id AND r.id_operacion > :last_op))
        ORDER BY r.id_remesa, r.id_operacion LIMIT :lim
    """,
    ("CHILE", "remittance"): """
        SELECT r.id_remesa AS source_pk, r.codigo AS code, r.estado AS status_code,
               r.envio AS amount, r.moneda AS currency_id, r.id_operacion AS operation_type,
               r.fec_crea_remesa AS occurred_at, r.fec_mod_remesa AS updated_at,
               r.abr_ori AS origin_country, r.abr_des AS destination_country
        FROM tmp_reporte_remesa r
        WHERE r.id_operacion IN (3,5,6,8)
          AND (r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)
          AND (r.id_remesa > :last_id OR
               (r.id_remesa = :last_id AND r.id_operacion > :last_op))
        ORDER BY r.id_remesa, r.id_operacion LIMIT :lim
    """,
    ("BOLIVIA", "payment"): """
        SELECT p.id_pago AS source_pk, p.codigo AS code, p.monto AS amount,
               p.mon_rec AS currency_id, p.id_operacion AS operation_type,
               p.fec_crea_pago AS occurred_at
        FROM pago p
        WHERE p.id_operacion IN (4,7) AND p.fec_crea_pago >= :cutoff
          AND (p.id_pago > :last_id OR
               (p.id_pago = :last_id AND p.id_operacion > :last_op))
        ORDER BY p.id_pago, p.id_operacion LIMIT :lim
    """,
    ("CHILE", "payment"): """
        SELECT p.id_pago AS source_pk, p.codigo AS code, p.monto AS amount,
               p.mon_rec AS currency_id, p.id_operacion AS operation_type,
               p.fec_crea_pago AS occurred_at
        FROM pago p
        WHERE p.id_operacion IN (3,5,6,8) AND p.fec_crea_pago >= :cutoff
          AND (p.id_pago > :last_id OR
               (p.id_pago = :last_id AND p.id_operacion > :last_op))
        ORDER BY p.id_pago, p.id_operacion LIMIT :lim
    """,
}


def source_engine(source: str):
    s = get_settings()
    if not (s.enable_source_etl and s.source_mapping_verified):
        raise RuntimeError("Real source extraction requires explicit mapping verification")
    if source not in ("BOLIVIA", "CHILE"):
        raise ValueError("Unknown source")
    prefix = source.lower()
    host, user, password, db = (
        getattr(s, f"{prefix}_db_{part}") for part in ("host", "user", "password", "name")
    )
    if not all((host, user, password, db)):
        raise RuntimeError(f"{source}: configure SELECT-only source credentials")
    return create_engine(
        URL.create("mysql+pymysql", username=user, password=password, host=host,
                   port=getattr(s, f"{prefix}_db_port"), database=db,
                   query={"charset": "utf8mb4"}),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10, "read_timeout": 30},
    )


# These are fixed queries in source code; never accept SQL from HTTP/user input.
# Guard against accidentally changing an extractor to a mutating statement.
_UNSAFE_SELECT = re.compile(
    r"\b(?:INTO\s+(?:OUTFILE|DUMPFILE)|FOR\s+UPDATE|LOCK\s+IN\s+SHARE\s+MODE)\b",
    re.IGNORECASE,
)


def validate_read_query(sql: str) -> None:
    """Allow one non-locking SELECT only, not arbitrary SQL or stored procedures."""
    statement = sql.strip()
    if (not re.match(r"^SELECT\b", statement, flags=re.IGNORECASE)
            or ";" in statement or "--" in statement or "/*" in statement
            or "#" in statement or _UNSAFE_SELECT.search(statement)):
        raise ValueError("Source adapters accept only single, non-locking SELECT statements")


@contextmanager
def read_only_transaction(engine: Engine) -> Iterator[Connection]:
    """Begin a DB-enforced READ ONLY transaction and ALWAYS roll back.

    MariaDB rejects ordinary INSERT/UPDATE/DELETE/DDL within this transaction
    even if the configured user has write privileges. It is not equivalent to
    a database SELECT-only user: the same credential can open other sessions.
    """
    with engine.connect() as connection:
        try:
            connection.exec_driver_sql("START TRANSACTION READ ONLY")
            yield connection
        finally:
            connection.rollback()


# Status codes are provisional. UNKNOWN intentionally prevents unsupported
# "paid" interpretations until code tables are verified for each operation.
PROVISIONAL_STATUS = {
    "BOLIVIA": {0: "PENDING", 1: "PAID", 2: "RETURNED", 5: "CANCELLED"},
    "CHILE": {0: "PENDING", 1: "PAID", 2: "RETURNED", 3: "RETURNED",
              4: "CHANGED", 5: "CANCELLED", 6: "TO_RETURN", 7: "PROCESSING",
              8: "SAVINGS"},
}


def map_status(source: str, value: object) -> str:
    try:
        return PROVISIONAL_STATUS[source].get(int(value), "UNKNOWN")
    except (ValueError, TypeError, KeyError):
        return "UNKNOWN"


def infer_direction(raw: dict) -> str | None:
    """Never guess direction solely from the system that contains the row."""
    origin = str(raw.get("origin_country") or "").strip().upper()
    dest = str(raw.get("destination_country") or "").strip().upper()
    if origin in {"CHL", "CL", "CHILE"} and dest in {"BOL", "BO", "BOLIVIA"}:
        return "CL_TO_BO"
    if origin in {"BOL", "BO", "BOLIVIA"} and dest in {"CHL", "CL", "CHILE"}:
        return "BO_TO_CL"
    return None


def normalize(source: str, dataset: str, raw: dict) -> Extracted:
    operation = int(raw["operation_type"]) if raw.get("operation_type") is not None else None
    pk = int(raw["source_pk"])
    # Keep currency ID as evidence, not ISO code: mon_rec can be an internal FK.
    # CL view moneda may already be a code or an integer; never label it USD/CLP without verification.
    raw_currency = raw.get("currency_id")
    currency = (str(raw_currency).upper() if raw_currency is not None else None)
    # Unknown currency identity is excluded from monetary comparison.
    if currency not in {"USD", "BOB", "CLP"}:
        currency = None
    direction = infer_direction(raw) if dataset == "remittance" else None
    if dataset == "remittance" and source == "BOLIVIA" and direction is None:
        approved = {int(item.strip()) for item in get_settings().bolivia_to_chile_operation_types.split(",")
                    if item.strip().isdigit()}
        if get_settings().source_mapping_verified and operation in approved:
            direction = "BO_TO_CL"
    return Extracted(
        source=source,
        dataset=dataset,
        source_id=f"{operation}:{pk}",
        code=str(raw["code"]).strip(),
        status=map_status(source, raw.get("status_code")) if dataset == "remittance"
               else "RECORDED",
        amount=decimal_amount(raw["amount"]) if raw.get("amount") is not None else None,
        currency=currency,
        raw=raw,
        operation_type=operation,
        direction=direction,
        occurred_at=raw.get("occurred_at"),
        source_pk=pk,
    )


def fetch_page(source: str, dataset: str, cutoff: datetime, last_id: int = 0,
               last_operation_id: int = 0, limit: int = 500) -> list[Extracted]:
    if not 1 <= limit <= 2000:
        raise ValueError("Invalid page size")
    # Validate source SQL before attempting to open a connection.
    sql = SQL[(source, dataset)]
    validate_read_query(sql)
    engine = source_engine(source)
    try:
        with read_only_transaction(engine) as connection:
            rows = connection.execute(
                text(sql),
                {"cutoff": cutoff, "last_id": last_id,
                 "last_op": last_operation_id, "lim": limit},
            ).mappings().all()
            return [normalize(source, dataset, dict(row)) for row in rows]
    finally:
        engine.dispose()
