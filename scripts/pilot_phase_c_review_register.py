"""Phase C: append-only manual review decisions in the isolated pilot.

Never rewrites normalized source records or auto-resolves a reconciliation.
A manual decision is recorded separately from automated classifications.
Source databases are never contacted. All writes require opt-in and guard.
"""
import argparse
import csv
import re
from datetime import date

from sqlalchemy import text

from app.core.config import get_settings
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_coverage_audit_2026 import validate_output
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker

TABLE_NAME = "pilot_phase_c_review_events"
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS pilot_phase_c_review_events (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 direction VARCHAR(10) NOT NULL,
 code VARCHAR(30) NOT NULL,
 payment_source VARCHAR(20) NOT NULL,
 payment_record_id BIGINT NOT NULL,
 classification_snapshot VARCHAR(80) NOT NULL,
 decision VARCHAR(80) NOT NULL,
 reviewer VARCHAR(64) NOT NULL,
 evidence_ref VARCHAR(128) NOT NULL,
 recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 INDEX ix_phase_c_review_target (direction,code,payment_source,payment_record_id,id)
) ENGINE=InnoDB
"""
# These labels do not authorize reversal, balance changes or reconciliation.
DECISIONS = frozenset({
    "CONFIRMED_DUPLICATE_RECORD_CONNECTIVITY",
    "REVIEW_EXCEPTIONAL_PAYMENT_CHANNEL",
    "RETURN_CONFIRMED_OPERATIONS",
    "AWAITING_ACCOUNTING_IMPACT",
    "REVIEW_REOPENED",
})
CLASSIFICATIONS = frozenset({
    "AMBIGUOUS_OR_DUPLICATE_CODE_REVIEW",
    "PAYMENT_TYPE_NOT_COMPATIBLE_WITH_ORIGIN",
    "RETURNED_LOCALLY_IN_BOLIVIA",
    "NO_ORIGIN_IN_PILOT",
})
OUTPUT_FIELDS = ("event_id","direction","code","payment_source","payment_record_id",
                 "classification_snapshot","decision","reviewer","evidence_ref",
                 "recorded_at","coverage_certified")
RECORD_FIELDS = ("direction","code","payment_source","payment_record_id",
                 "classification_snapshot","decision","reviewer","evidence_ref")


def validate_record(values):
    values = dict(values)
    if values["direction"] not in ("BO_TO_CL","CL_TO_BO"):
        raise ValueError("Unknown direction")
    expected = "CHILE" if values["direction"] == "BO_TO_CL" else "BOLIVIA"
    if values["payment_source"] != expected:
        raise ValueError("Payment source/direction mismatch")
    if not re.fullmatch(r"[1-9][0-9]{0,17}",str(values["code"])):
        raise ValueError("Invalid code")
    value = str(values["payment_record_id"])
    if not re.fullmatch(r"[1-9][0-9]{0,17}",value):
        raise ValueError("Invalid payment id")
    values["payment_record_id"] = int(value)
    if values["classification_snapshot"] not in CLASSIFICATIONS:
        raise ValueError("Invalid automatic classification")
    if values["decision"] not in DECISIONS:
        raise ValueError("Invalid manual decision")
    if (values["decision"] == "CONFIRMED_DUPLICATE_RECORD_CONNECTIVITY"
            and values["classification_snapshot"] !=
                "AMBIGUOUS_OR_DUPLICATE_CODE_REVIEW"):
        raise ValueError("Duplicate decision requires ambiguous-payment classification")
    if (values["decision"] == "REVIEW_EXCEPTIONAL_PAYMENT_CHANNEL"
            and values["classification_snapshot"] !=
                "PAYMENT_TYPE_NOT_COMPATIBLE_WITH_ORIGIN"):
        raise ValueError("Channel review requires incompatible-payment classification")
    if (values["decision"] == "RETURN_CONFIRMED_OPERATIONS"
            and values["classification_snapshot"] != "RETURNED_LOCALLY_IN_BOLIVIA"):
        raise ValueError("Return review requires a source-motive return")
    for field in ("reviewer","evidence_ref"):
        content = str(values[field]).strip()
        # Strict tokens/refs only, no arbitrary free-text notes or private details.
        if (not 3 <= len(content) <= (64 if field=="reviewer" else 128)
                or not re.fullmatch(r"[A-Za-z0-9_.:/-]+",content)):
            raise ValueError(f"{field} must be a short, non-sensitive reference")
        values[field] = content
    return values


def current_classification(conn,record):
    from scripts.pilot_phase_c_integrity_2026 import collect
    # This collector uses its own marked, READ ONLY pilot transaction;
    # no production access or mutation is possible.
    exceptions,_,_=collect(date.today())
    matches=[x for x in exceptions
             if x["direction"]==record["direction"]
             and str(x["payment_code"])==str(record["code"])
             and x["payment_source"]==record["payment_source"]
             and int(x["payment_record_id"])==record["payment_record_id"]]
    if len(matches)!=1:
        raise RuntimeError("Payment is not an unambiguous current pilot exception")
    actual=matches[0]["assessment"]
    if actual!=record["classification_snapshot"]:
        raise RuntimeError(f"Stale classification: current={actual}; no event appended")


def pilot_settings():
    s=get_settings()
    if ((s.db_host,s.db_name)!=(PILOT_HOST,PILOT_DB)
            or s.enable_source_etl or s.source_mapping_verified):
        raise RuntimeError("Review register requires marked isolated pilot with ETL disabled")
    return s


def record_event(record,apply=False,acknowledge=False):
    data=validate_record(record)
    if apply and not acknowledge:
        raise ValueError("--apply requires --acknowledge-sensitive-data")
    s=pilot_settings()
    engine=pilot_engine(s)
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
            finally:
                conn.rollback()
        current_classification(None,data)
        if not apply:
            print(f"review_preview=True decision={data['decision']} "
                  "pilot_writes=False source_connections=0 coverage_certified=False")
            return
        with engine.connect() as conn:
            check_marker(conn)
            # DDL only inside isolated pilot, after marker validation.
            conn.execute(text(CREATE_TABLE))
            conn.commit()
        with engine.begin() as conn:
            check_marker(conn)
            conn.execute(text("""
                INSERT INTO pilot_phase_c_review_events
                (direction,code,payment_source,payment_record_id,
                 classification_snapshot,decision,reviewer,evidence_ref)
                VALUES (:direction,:code,:payment_source,:payment_record_id,
                        :classification_snapshot,:decision,:reviewer,:evidence_ref)
            """),data)
        print(f"review_event_appended=True decision={data['decision']} "
              "pilot_writes=True source_connections=0 source_writes=False "
              "coverage_certified=False")
    finally:
        engine.dispose()


def export_events(output):
    target=validate_output(output)
    engine=pilot_engine(pilot_settings())
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                present=conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table_name
                """),{"table_name":TABLE_NAME}).scalar_one()
                rows=(conn.execute(text("""
                    SELECT id AS event_id,direction,code,payment_source,
                           payment_record_id,classification_snapshot,decision,
                           reviewer,evidence_ref,recorded_at
                    FROM pilot_phase_c_review_events ORDER BY id
                """)).mappings().all() if present else [])
            finally:
                conn.rollback()
    finally:
        engine.dispose()
    from scripts.pilot_operation_detail_2026 import safe_csv_value
    with target.open("w",newline="",encoding="utf-8-sig") as stream:
        writer=csv.DictWriter(stream,fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key:safe_csv_value(
                "False" if key=="coverage_certified" else row.get(key,""))
                for key in OUTPUT_FIELDS})
    print(f"review_events_exported={len(rows)} report={target.name} "
          "source_connections=0 pilot_writes=False coverage_certified=False")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest="command",required=True)
    entry=commands.add_parser("record")
    for flag in RECORD_FIELDS:
        entry.add_argument("--"+flag.replace("_","-"),required=True)
    entry.add_argument("--apply",action="store_true")
    entry.add_argument("--acknowledge-sensitive-data",action="store_true")
    exp=commands.add_parser("export")
    exp.add_argument("--output",required=True)
    args=p.parse_args()
    if args.command=="export":
        export_events(args.output)
    else:
        record_event({key:getattr(args,key) for key in RECORD_FIELDS},
                     args.apply,args.acknowledge_sensitive_data)


if __name__=="__main__":
    main()
