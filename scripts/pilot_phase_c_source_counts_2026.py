"""Phase C: bounded monthly source-versus-pilot COUNT audit (NOT certification).

Exactly one source/dataset/month per call. No extraction of personal records.
Every production query is SELECT under READ ONLY transaction with guarded
EXPLAIN. Never bypass rejected plans. Compares source-created 2026 rows with
pilot projected occurred_at rows for the same interval. Count parity cannot
prove identity or status parity and is NOT a coverage certificate.
"""
import argparse
import csv
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from app.core.config import get_settings
from app.integrations.source import validate_read_query, read_only_transaction
from scripts.pilot_backfill_2026 import pilot_engine, source_plan_guard
from scripts.pilot_coverage_audit_2026 import validate_output
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source

# Fixed SQL contracts; do not build table/column identifiers from input.
# Chile source remittance is the verified tmp_reporte_remesa view.
SOURCE_COUNT_SQL = {
    ("BOLIVIA","remittance"): """SELECT COUNT(*) AS row_count FROM remesa r
        WHERE r.id_operacion IN (4,16)
          AND r.fec_crea_remesa >= :start_date
          AND r.fec_crea_remesa < :end_date""",
    ("CHILE","remittance"): """SELECT COUNT(*) AS row_count FROM tmp_reporte_remesa r
        WHERE r.id_operacion IN (3,5,6,8)
          AND r.fec_crea_remesa >= :start_date
          AND r.fec_crea_remesa < :end_date""",
    ("BOLIVIA","payment"): """SELECT COUNT(*) AS row_count FROM pago p
        WHERE p.id_operacion IN (4,7)
          AND p.fec_crea_pago >= :start_date
          AND p.fec_crea_pago < :end_date""",
    ("CHILE","payment"): """SELECT COUNT(*) AS row_count FROM pago p
        WHERE p.id_operacion IN (3,5,6,8)
          AND p.fec_crea_pago >= :start_date
          AND p.fec_crea_pago < :end_date""",
}
PILOT_TABLES = {"remittance":"remittances","payment":"payments"}
FIELDS = ("month","source","dataset","window_start","window_end_exclusive",
          "source_rows","pilot_rows","difference_pilot_minus_source",
          "assessment","source_plan_access","source_plan_key",
          "identity_verified","coverage_certified")


def interval(month, through):
    if (len(month)!=7 or month[:5]!="2026-" or not month[5:].isdigit()
            or not 1<=int(month[5:])<=12):
        raise ValueError("Month must be 2026-MM")
    if through.year!=2026 or through>date.today():
        raise ValueError("through must be a reached date in 2026")
    start=date(2026,int(month[5:]),1)
    if start>through:
        raise ValueError("Requested month is after cutoff")
    month_end=(date(2027,1,1) if start.month==12
               else date(2026,start.month+1,1))
    end=min(month_end,through+timedelta(days=1))
    return datetime.combine(start,time.min),datetime.combine(end,time.min)


def assess(source_rows,pilot_rows):
    if source_rows!=pilot_rows:
        return "MONTHLY_COUNT_DIFFERENCE_REVIEW"
    return "MONTHLY_COUNTS_EQUAL_IDENTITIES_UNVERIFIED"


def run(source,dataset,month,through,output):
    pair=(source,dataset)
    if pair not in SOURCE_COUNT_SQL:
        raise ValueError("Unknown source/dataset pair")
    target=validate_output(output)
    start,end=interval(month,through)
    settings=get_settings()
    if ((settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Source count audit requires isolated pilot and ETL disabled")
    query=SOURCE_COUNT_SQL[pair]
    validate_read_query(query)
    pilot=pilot_engine(settings)
    remote=None
    try:
        with pilot.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                # Allow only predeclared projection table identifiers.
                table=PILOT_TABLES[dataset]
                pilot_rows=conn.execute(text(f"""
                    SELECT COUNT(*) FROM {table}
                    WHERE source=:source
                      AND occurred_at >= :start_date
                      AND occurred_at < :end_date
                """),{"source":source,"start_date":start,"end_date":end}).scalar_one()
            finally:
                conn.rollback()
        remote=connect_source(settings,source)
        params={"start_date":start,"end_date":end}
        with read_only_transaction(remote) as conn:
            plan=conn.execute(text("EXPLAIN "+query),params).mappings().all()
            source_plan_guard(plan)
            source_rows=conn.execute(text(query),params).scalar_one()
        source_rows=int(source_rows)
        pilot_rows=int(pilot_rows)
        data=dict(month=month,source=source,dataset=dataset,
                  window_start=start.isoformat(sep=" "),
                  window_end_exclusive=end.isoformat(sep=" "),
                  source_rows=source_rows,pilot_rows=pilot_rows,
                  difference_pilot_minus_source=pilot_rows-source_rows,
                  assessment=assess(source_rows,pilot_rows),
                  source_plan_access="|".join(str(p.get("type")) for p in plan),
                  source_plan_key="|".join(str(p.get("key")) for p in plan),
                  identity_verified="False",coverage_certified="False")
        # Deliberately aggregate-only CSV (no personal identities or amounts).
        with target.open("w",newline="",encoding="utf-8-sig") as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(data)
        print(f"phase_c_source_count=True source={source} dataset={dataset} "
              f"month={month} source_rows={source_rows} pilot_rows={pilot_rows} "
              f"assessment={data['assessment']} "
              "source_read_only=True source_writes=False pilot_writes=False "
              "identity_verified=False coverage_certified=False",flush=True)
        print(f"files_created={target.name} private_export=True",flush=True)
        return data
    finally:
        if remote is not None:
            remote.dispose()
        pilot.dispose()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",required=True,choices=("BOLIVIA","CHILE"))
    p.add_argument("--dataset",required=True,choices=("remittance","payment"))
    p.add_argument("--month",required=True)
    p.add_argument("--through",type=date.fromisoformat,required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    run(a.source,a.dataset,a.month,a.through,a.output)


if __name__=="__main__":
    main()
