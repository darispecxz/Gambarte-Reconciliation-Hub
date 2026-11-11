"""Read-only source extractors. SQL shapes are based on legacy systems and need production validation."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from app.core.config import get_settings
from app.domain.reconciliation import decimal_amount

@dataclass(frozen=True)
class Extracted:
    source: str
    dataset: str
    source_id: str
    code: str
    status: str
    amount: Decimal
    currency: str | None
    raw: dict

SQL = {
    ("BOLIVIA","remittance"): """
        SELECT r.id_remesa AS id, r.codigo AS code, r.estado AS status,
               r.monto AS amount, m.abreviatura AS currency,
               r.id_operacion AS operation_type, r.fec_mod_remesa AS updated_at
        FROM remesa r
        LEFT JOIN moneda m ON m.id_moneda = r.mon_rec
        WHERE r.id_operacion IN (4,16)
          AND (r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)
        ORDER BY r.id_remesa LIMIT :lim OFFSET :off
    """,
    ("CHILE","remittance"): """
        SELECT r.id_remesa AS id, r.codigo AS code, r.estado AS status,
               r.envio AS amount, r.moneda AS currency,
               r.id_operacion AS operation_type, r.abr_ori AS origin_country,
               r.abr_des AS destination_country, r.fec_mod_remesa AS updated_at
        FROM tmp_reporte_remesa r
        WHERE r.id_operacion IN (3,5,6,8)
          AND (r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)
        ORDER BY r.id_remesa LIMIT :lim OFFSET :off
    """,
    ("BOLIVIA","payment"): """
        SELECT p.id_pago AS id, p.codigo AS code, p.monto AS amount,
               m.abreviatura AS currency, p.id_operacion AS operation_type
        FROM pago p LEFT JOIN moneda m ON m.id_moneda=p.mon_rec
        WHERE p.id_operacion IN (4,7) AND p.fec_crea_pago >= :cutoff
        ORDER BY p.id_pago LIMIT :lim OFFSET :off
    """,
    ("CHILE","payment"): """
        SELECT p.id_pago AS id, p.codigo AS code, p.monto AS amount,
               p.id_operacion AS operation_type
        FROM pago p
        WHERE p.id_operacion IN (3,5,6,8) AND p.fec_crea_pago >= :cutoff
        ORDER BY p.id_pago LIMIT :lim OFFSET :off
    """,
}

def source_engine(source: str):
    s = get_settings()
    if source not in ("BOLIVIA", "CHILE"):
        raise ValueError("Unknown source")
    prefix = "bolivia" if source == "BOLIVIA" else "chile"
    host = getattr(s, prefix+"_db_host")
    user = getattr(s, prefix+"_db_user")
    password = getattr(s, prefix+"_db_password")
    db = getattr(s, prefix+"_db_name")
    if not all((host, user, password, db)):
        raise RuntimeError(source+" connection missing: configure a SELECT-only SQL account")
    return create_engine(URL.create("mysql+pymysql",username=user,password=password,
                         host=host,database=db,query={"charset":"utf8mb4"}),pool_pre_ping=True)

def map_status(source: str, value: object) -> str:
    statuses = {0:"PENDING",1:"PAID",2:"RETURNED",5:"CANCELLED"}
    if source == "CHILE":
        statuses.update({3:"RETURNED",4:"CHANGED",6:"TO_RETURN",7:"PROCESSING",8:"SAVINGS"})
    try:
        return statuses.get(int(value),"UNKNOWN")
    except (ValueError,TypeError):
        return "UNKNOWN"

def extract(source: str, dataset: str, cutoff: datetime, limit: int = 500):
    engine = source_engine(source)
    try:
        offset = 0
        with engine.connect() as connection:
            while True:
                rows = connection.execute(text(SQL[(source,dataset)]),
                      {"cutoff":cutoff,"lim":limit,"off":offset}).mappings().all()
                for row in rows:
                    raw = dict(row)
                    yield Extracted(
                        source=source, dataset=dataset, source_id=str(raw["id"]),
                        code=str(raw["code"]),
                        status=map_status(source,raw.get("status")) if dataset=="remittance" else "RECORDED",
                        amount=decimal_amount(raw.get("amount")),
                        currency=str(raw["currency"]).upper() if raw.get("currency") else None,
                        raw=raw,
                    )
                if len(rows)<limit:
                    break
                offset += len(rows)
    finally:
        engine.dispose()
