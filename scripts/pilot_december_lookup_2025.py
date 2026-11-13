"""Targeted December 2025 lookup for unmatched January 2026 pilot payments.

NO import. No production writes. At most 25 distinct codes read from isolated
pilot, each source lookup uses parameterized query, EXPLAIN guard, read-only TX,
and strict December dates. Safe halt on missing index/costly plan.
"""
import argparse
from collections import Counter
from datetime import datetime
from sqlalchemy import select, text
from app.core.config import get_settings
from app.infrastructure.models import Payment, Remittance
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine, source_plan_guard
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.pilot_operation_detail_2026 import detail_rows

# Indexed lookup is not assumed; each plan is checked and rejected if unsuitable.
SQL = {
    "BOLIVIA": """SELECT r.codigo AS code, r.id_operacion AS operation_type,
        r.fec_crea_remesa AS occurred_at FROM remesa r
        WHERE r.id_operacion IN (4,16) AND r.codigo = :code
          AND r.fec_crea_remesa >= :start_date
          AND r.fec_crea_remesa < :end_date
        LIMIT 5""",
    "CHILE": """SELECT r.codigo AS code, r.id_operacion AS operation_type,
        r.fec_crea_remesa AS occurred_at
        FROM tmp_reporte_remesa r FORCE INDEX (PRIMARY)
        WHERE r.id_operacion IN (3,5,6,8) AND r.codigo = :code
          AND r.fec_crea_remesa >= :start_date
          AND r.fec_crea_remesa < :end_date
        LIMIT 5""",
}


def missing_january_payment_codes(rems, pays):
    paired = {r["destination_id"] for r in detail_rows(
        rems, pays, datetime(2026,1,31).date()
    ) if r["category"] == "PROVISIONAL_CODE_PAIR" and r["destination_id"] != ""}
    result = {"BOLIVIA": set(), "CHILE": set()}
    for p in pays:
        if (p.source_record_id not in paired and p.occurred_at is not None
                and datetime(2026,1,1) <= p.occurred_at < datetime(2026,2,1)):
            origin = "CHILE" if p.source == "BOLIVIA" else "BOLIVIA"
            result[origin].add(p.code)
    if sum(len(v) for v in result.values()) > 25:
        raise RuntimeError("Safety cap: more than 25 candidate codes; refuse lookup")
    return result


def run():
    settings = get_settings()
    if (settings.db_host, settings.db_name) != (PILOT_HOST,PILOT_DB):
        raise RuntimeError("Requires isolated pilot")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("ETL and mapping must remain disabled")
    pilot = pilot_engine(settings)
    rems = pays = None
    try:
        with pilot.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                rems = con.execute(select(
                    Remittance.source_record_id,Remittance.source,Remittance.code,
                    Remittance.operation_type,Remittance.status,Remittance.amount,
                    Remittance.currency,Remittance.occurred_at,
                )).all()
                pays = con.execute(select(
                    Payment.source_record_id,Payment.source,Payment.code,
                    Payment.operation_type,Payment.amount,Payment.currency,
                    Payment.occurred_at,
                )).all()
            finally:
                con.rollback()
    finally:
        pilot.dispose()
    targets = missing_january_payment_codes(rems,pays)
    # Explicitly do not proceed with any non-indexed plan; one code at a time.
    totals = Counter()
    for source,codes in targets.items():
        if not codes:
            continue
        sql = SQL[source]
        validate_read_query(sql)
        engine = connect_source(settings,source)
        try:
            for code in sorted(codes):
                params = {"code": code, "start_date": datetime(2025,12,1),
                          "end_date":datetime(2026,1,1)}
                with read_only_transaction(engine) as con:
                    plan = con.execute(text("EXPLAIN "+sql),params).mappings().all()
                    source_plan_guard(plan)
                    rows = con.execute(text(sql),params).mappings().all()
                if len(rows) >= 5:
                    totals["candidate_limit_reached"] += 1
                totals["codes_checked"] += 1
                totals["codes_found_in_december"] += bool(rows)
                totals["candidate_rows_seen"] += len(rows)
        finally:
            engine.dispose()
    print("december_targeted_lookup=True source_read_only=True "
          "pilot_writes=False imported=False certified=False")
    print("target_codes=" + str(sum(len(c) for c in targets.values())))
    for key,value in sorted(totals.items()):
        print(f"{key}={value}")
    print("note=Aggregate-only: no code or customer data printed")


if __name__=="__main__":
    run()
