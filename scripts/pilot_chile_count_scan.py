"""Independent, resumable Chile 2026 monthly count using PRIMARY keyset pages.

Reads only key columns from source under READ ONLY, never runs unindexed
COUNT(*). Stores an isolated count checkpoint in pilot DB after each page.
A matching count is provisional, not a certified historical snapshot.
Run one dataset/month at a time. No background scheduler.
"""
import argparse
from time import perf_counter, sleep

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import (
    month_window, source_plan_guard, pilot_engine, checkpoint_params,
    read_checkpoint,
)
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source

SQL = {
    "payment": """
        SELECT p.id_pago AS source_pk, p.id_operacion AS operation_type
        FROM pago p FORCE INDEX (PRIMARY)
        WHERE p.id_operacion IN (3,5,6,8)
          AND p.fec_crea_pago >= :from_date AND p.fec_crea_pago < :to_date
          AND (p.id_pago > :last_id OR
               (p.id_pago = :last_id AND p.id_operacion > :last_op))
        ORDER BY p.id_pago,p.id_operacion LIMIT :lim
    """,
    "remittance": """
        SELECT r.id_operacion AS operation_type, r.codigo AS code,
               r.id_destino AS cursor_destination
        FROM tmp_reporte_remesa r FORCE INDEX (PRIMARY)
        WHERE r.id_operacion IN (3,5,6,8)
          AND r.fec_crea_remesa >= :from_date AND r.fec_crea_remesa < :to_date
          AND (r.id_operacion > :last_op
               OR (r.id_operacion = :last_op AND r.codigo > :last_code)
               OR (r.id_operacion = :last_op AND r.codigo = :last_code
                   AND r.id_destino > :last_dest))
        ORDER BY r.id_operacion,r.codigo,r.id_destino LIMIT :lim
    """,
}
DDL = """
CREATE TABLE IF NOT EXISTS pilot_chile_count_progress (
  dataset VARCHAR(20) NOT NULL, month_key CHAR(7) NOT NULL,
  last_id BIGINT NOT NULL DEFAULT 0, last_op INTEGER NOT NULL DEFAULT 0,
  last_code BIGINT NOT NULL DEFAULT 0, last_dest INTEGER NOT NULL DEFAULT 0,
  rows_counted BIGINT NOT NULL DEFAULT 0, pages_counted BIGINT NOT NULL DEFAULT 0,
  scan_exhausted BOOLEAN NOT NULL DEFAULT FALSE,
  changed_at DATETIME NOT NULL,
  PRIMARY KEY(dataset,month_key)
) ENGINE=InnoDB
"""
SELECT = text("""
SELECT last_id,last_op,last_code,last_dest,rows_counted,pages_counted,scan_exhausted
FROM pilot_chile_count_progress WHERE dataset=:dataset AND month_key=:month_key
""")
LOCK = text(str(SELECT) + " FOR UPDATE")
INSERT = text("""
INSERT INTO pilot_chile_count_progress
(dataset,month_key,last_id,last_op,last_code,last_dest,
 rows_counted,pages_counted,scan_exhausted,changed_at)
VALUES (:dataset,:month_key,0,0,0,0,0,0,0,UTC_TIMESTAMP())
""")
UPDATE = text("""
UPDATE pilot_chile_count_progress SET
last_id=:last_id,last_op=:last_op,last_code=:last_code,last_dest=:last_dest,
rows_counted=rows_counted+:batch_count,pages_counted=pages_counted+1,
scan_exhausted=:exhausted,changed_at=UTC_TIMESTAMP()
WHERE dataset=:dataset AND month_key=:month_key
""")
ZERO = dict(last_id=0,last_op=0,last_code=0,last_dest=0,
            rows_counted=0,pages_counted=0,scan_exhausted=False)


def validate_request(settings, dataset, month, limit, pages, apply, ack, pause):
    month_window(month)
    if dataset not in SQL:
        raise ValueError("Only Chile payment/remittance supported")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL and source mapping must remain disabled")
    if (settings.db_host,settings.db_name) != (PILOT_HOST,PILOT_DB):
        raise RuntimeError("Refusing non-isolated pilot")
    if not 1 <= limit <= 50 or not 1 <= pages <= 10 or not 0 <= pause <= 30:
        raise ValueError("Safety cap: 50 rows/page, 10 pages/run, pause 0..30s")
    if apply and not ack:
        raise ValueError("Writing count checkpoints needs --acknowledge-sensitive-data")


def key(dataset, row):
    if dataset == "payment":
        return (int(row["source_pk"]), int(row["operation_type"]))
    return (int(row["operation_type"]), int(row["code"]),
            int(row["cursor_destination"]))


def advance(dataset, row, state):
    next_state = dict(state)
    if dataset == "payment":
        next_state.update(last_id=int(row["source_pk"]),
                          last_op=int(row["operation_type"]))
    else:
        next_state.update(last_op=int(row["operation_type"]),
                          last_code=int(row["code"]),
                          last_dest=int(row["cursor_destination"]))
    return next_state


def compare(count_progress, import_progress):
    if not import_progress or not import_progress.get("scan_exhausted"):
        return "IMPORT_SCAN_INCOMPLETE"
    if not count_progress.get("scan_exhausted"):
        return "COUNT_SCAN_IN_PROGRESS"
    if int(count_progress["rows_counted"]) != int(import_progress["rows_seen"]):
        return "COUNT_MISMATCH_REVIEW_REQUIRED"
    return "COUNT_MATCH_NOT_CERTIFIED"


def run(dataset, month, limit=50, pages=2, apply=False,
        acknowledge=False, pause_seconds=2):
    s=get_settings()
    validate_request(s,dataset,month,limit,pages,apply,acknowledge,pause_seconds)
    from_date,to_date=month_window(month)
    sql=SQL[dataset]
    validate_read_query(sql)
    identity={"dataset":dataset,"month_key":month}
    import_identity=checkpoint_params("CHILE",dataset,month)
    pilot=pilot_engine(s)
    source=None
    try:
        with pilot.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                table_names={r[0] for r in conn.execute(text("""
                    SELECT TABLE_NAME FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE()
                      AND TABLE_NAME IN ('pilot_backfill_progress','pilot_chile_count_progress')
                """)).all()}
                if "pilot_backfill_progress" not in table_names:
                    raise RuntimeError("Existing pilot import checkpoint table missing")
                imported=read_checkpoint(conn,import_identity)
                state=(dict(conn.execute(SELECT,identity).mappings().first() or ZERO)
                       if "pilot_chile_count_progress" in table_names else dict(ZERO))
            finally:
                conn.rollback()
        if not imported["scan_exhausted"]:
            raise RuntimeError("Finish the pilot import before verifying Chile counts")
        if state["scan_exhausted"]:
            status=compare(state,imported)
            print(f"month={month} source=CHILE dataset={dataset} "
                  f"counted={state['rows_counted']} imported_rows={imported['rows_seen']} "
                  f"comparison={status}")
            if status != "COUNT_MATCH_NOT_CERTIFIED":
                raise RuntimeError(status)
            return {"status":status,"rows_counted":state["rows_counted"]}
        source=connect_source(s,"CHILE")
        for page_no in range(pages if apply else 1):
            params={**state,"from_date":from_date,"to_date":to_date,"lim":limit}
            with read_only_transaction(source) as conn:
                plan=conn.execute(text("EXPLAIN "+sql),params).mappings().all()
                print("chile_keyset_explain="+",".join(
                    f"{r.get('type')}/{r.get('key')}/{r.get('rows')}" for r in plan),
                    flush=True)
                source_plan_guard(plan)
                tick=perf_counter()
                rows=conn.execute(text(sql),params).mappings().all()
                elapsed=perf_counter()-tick
            keys=[key(dataset,row) for row in rows]
            previous=((state["last_id"],state["last_op"]) if dataset=="payment"
                      else (state["last_op"],state["last_code"],state["last_dest"]))
            if keys != sorted(set(keys)) or (keys and keys[0] <= previous):
                raise RuntimeError("Count scan cursor duplicated or regressed")
            next_state=advance(dataset,rows[-1],state) if rows else dict(state)
            exhausted=len(rows)<limit
            print(f"month={month} dataset={dataset} counted_page={len(rows)} "
                  f"elapsed_seconds={elapsed:.3f} scan_exhausted={exhausted} "
                  f"pilot_checkpoint_write={apply}")
            if not apply:
                print("dry_run=True no_count_checkpoint_written=True")
                return {"status":"DRY_RUN","rows_read":len(rows)}
            if "pilot_chile_count_progress" not in table_names:
                with pilot.begin() as conn:
                    check_marker(conn)
                    conn.execute(text(DDL))
                table_names.add("pilot_chile_count_progress")
            with Session(pilot) as session:
                with session.begin():
                    check_marker(session.connection())
                    existing=session.execute(LOCK,identity).mappings().first()
                    if existing is None:
                        if state != ZERO:
                            raise RuntimeError("Missing count checkpoint during resume")
                        session.execute(INSERT,identity)
                        existing=session.execute(LOCK,identity).mappings().one()
                    if any(int(existing[k])!=int(state[k]) for k in
                           ("last_id","last_op","last_code","last_dest",
                            "rows_counted","pages_counted","scan_exhausted")):
                        raise RuntimeError("Concurrent count scan detected")
                    session.execute(UPDATE,{**identity,**next_state,
                                            "batch_count":len(rows),
                                            "exhausted":int(exhausted)})
            state={**next_state,"rows_counted":int(state["rows_counted"])+len(rows),
                   "pages_counted":int(state["pages_counted"])+1,
                   "scan_exhausted":exhausted}
            if exhausted:
                status=compare(state,imported)
                print(f"month={month} source=CHILE dataset={dataset} "
                      f"counted={state['rows_counted']} imported_rows={imported['rows_seen']} "
                      f"comparison={status} coverage_certified=False")
                if status != "COUNT_MATCH_NOT_CERTIFIED":
                    raise RuntimeError(status)
                return {"status":status,"rows_counted":state["rows_counted"]}
            if page_no+1 < pages:
                sleep(pause_seconds)
        print(f"count_scan_paused=True month={month} dataset={dataset} "
              f"rows_counted={state['rows_counted']} resume_with_same_command=True")
        return {"status":"COUNT_SCAN_IN_PROGRESS","rows_counted":state["rows_counted"]}
    finally:
        if source is not None:
            source.dispose()
        pilot.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",required=True,choices=("payment","remittance"))
    parser.add_argument("--month",required=True)
    parser.add_argument("--limit",type=int,default=50)
    parser.add_argument("--pages",type=int,default=2)
    parser.add_argument("--pause-seconds",type=float,default=2)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--acknowledge-sensitive-data",action="store_true")
    args=parser.parse_args()
    run(args.dataset,args.month,args.limit,args.pages,args.apply,
        args.acknowledge_sensitive_data,args.pause_seconds)


if __name__=="__main__":
    main()
