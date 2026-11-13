"""Phase C: pilot-only inverse payment and internal coverage integrity audit.

Never connects to source databases or certifies coverage. A missing remittance
means absent in isolated pilot, not missing in Bolivia/Chile production.
Local historical checkpoints are not external counts. Incremental updates
make historical rows_seen incomparable with current normalized projections.
"""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from app.core.config import get_settings
from app.domain.operation_types import allowed_destination_payment_types
from app.infrastructure.models import Payment, Remittance, SourceRecord
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_coverage_audit_2026 import validate_output
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker
from scripts.pilot_reconcile import DIRECTIONS

PAYMENT_FIELDS = ("direction","payment_source","payment_code","payment_record_id",
                  "payment_type","payment_date","payment_amount","payment_currency",
                  "assessment","origin_candidates","compatible_origin_candidates",
                  "same_code_payment_candidates","return_reason_present","coverage_certified")
COVERAGE_FIELDS = ("month","source","dataset","pilot_records","missing_code",
                   "missing_date_total_for_pair","historical_rows_seen",
                   "historical_scan_exhausted","recent_scans_finished",
                   "recent_scans_incomplete","assessment",
                   "external_source_count","coverage_certified")
SUMMARY_FIELDS = ("dimension","key","count","coverage_certified")
PAIRS = (("BOLIVIA","remittance"),("BOLIVIA","payment"),
         ("CHILE","remittance"),("CHILE","payment"))


def is_bolivia_return(payment):
    """Nonblank pago.motivo in Bolivia indicates a local return.

    Historical pilot payloads without the field remain unverified.
    Do not export the free-text motive.
    """
    if payment.source != "BOLIVIA":
        return False
    payload = getattr(payment, "payload", None)
    return isinstance(payload, dict) and bool(str(payload.get("return_reason") or "").strip())


def payment_assessment(payment, origin_rows, same_code_payment_count,
                       origin, destination, origin_types):
    possible = [r for r in origin_rows if
                r.source == origin and r.operation_type in origin_types
                and r.code == payment.code]
    matching = [r for r in possible if payment.operation_type in
                (allowed_destination_payment_types(origin,destination,
                                                  r.operation_type) or ())]
    if is_bolivia_return(payment):
        label = "RETURNED_LOCALLY_IN_BOLIVIA"
    elif not possible:
        label = "NO_ORIGIN_IN_PILOT"
    elif not matching:
        label = "PAYMENT_TYPE_NOT_COMPATIBLE_WITH_ORIGIN"
    elif len(matching) > 1 or same_code_payment_count > 1:
        label = "AMBIGUOUS_OR_DUPLICATE_CODE_REVIEW"
    else:
        label = "PROVISIONAL_INVERSE_PAIR"
    return label,len(possible),len(matching)


def inverse_payments(remittances, payments, cutoff):
    """Classify each in-scope payment, including unmatched payments.

    Uses all pilot remittances as potential origins, not only records created
    in 2026, to avoid false orphan labels at the year boundary.
    """
    output = []
    for direction, origin, destination, origin_types in DIRECTIONS:
        pay_rows = [p for p in payments if p.source == destination
                    and p.occurred_at is not None
                    and date(2026,1,1) <= p.occurred_at.date() <= cutoff]
        by_code = Counter(p.code for p in pay_rows)
        rems_by_code = defaultdict(list)
        for r in remittances:
            if r.source == origin and r.operation_type in origin_types:
                rems_by_code[r.code].append(r)
        for p in pay_rows:
            label, origin_count, match_count = payment_assessment(
                p, rems_by_code[p.code], by_code[p.code],
                origin,destination,origin_types)
            if label == "PROVISIONAL_INVERSE_PAIR":
                continue  # Keep exception file focused, report total in summary.
            output.append(dict(
                direction=direction,payment_source=destination,
                payment_code=p.code,payment_record_id=p.source_record_id,
                payment_type=p.operation_type,
                payment_date=p.occurred_at.isoformat(sep=" "),
                payment_amount=str(p.amount) if p.amount is not None else "",
                payment_currency=p.currency or "",assessment=label,
                origin_candidates=origin_count,
                compatible_origin_candidates=match_count,
                same_code_payment_candidates=by_code[p.code],
                return_reason_present=str(is_bolivia_return(p)),
                coverage_certified="False"))
    output.sort(key=lambda r:(r["assessment"],r["direction"],str(r["payment_code"]),
                              str(r["payment_record_id"])))
    return output


def monthly_coverage(remittances,payments,historical,recent,through):
    projections = defaultdict(lambda:dict(pilot_records=0,missing_code=0))
    undated = Counter()
    for dataset, rows in (("remittance",remittances),("payment",payments)):
        for r in rows:
            key=(r.source,dataset)
            if r.occurred_at is None:
                undated[key]+=1
                continue
            if date(2026,1,1) <= r.occurred_at.date() <= through:
                key_month=(r.source,dataset,r.occurred_at.strftime("%Y-%m"))
                projections[key_month]["pilot_records"]+=1
                if not str(r.code or "").strip():
                    projections[key_month]["missing_code"]+=1

    report=[]
    for month in range(1,through.month+1):
        month_key=f"2026-{month:02d}"
        for source,dataset in PAIRS:
            stats=projections[(source,dataset,month_key)]
            cp=historical.get((source,dataset,month_key))
            # A recent-window checkpoint covers a time range, not necessarily
            # a complete calendar month. Never treat it as certification.
            refresh=[r for r in recent if r["source"]==source
                     and r["dataset"]==dataset
                     and r["window_start"].strftime("%Y-%m") <= month_key <=
                         r["as_of_date"].strftime("%Y-%m")]
            complete=sum(bool(r["scan_exhausted"]) for r in refresh)
            incomplete=len(refresh)-complete
            if cp is None:
                assessment="HISTORICAL_CHECKPOINT_MISSING"
            elif not cp["scan_exhausted"]:
                assessment="HISTORICAL_SCAN_INCOMPLETE"
            elif incomplete:
                assessment="RECENT_REFRESH_INCOMPLETE"
            else:
                assessment="LOCAL_ONLY_SOURCE_COUNT_UNVERIFIED"
            if stats["missing_code"] or undated[(source,dataset)]:
                assessment="PILOT_DATA_QUALITY_REVIEW"
            report.append(dict(
                month=month_key,source=source,dataset=dataset,
                pilot_records=stats["pilot_records"],
                missing_code=stats["missing_code"],
                missing_date_total_for_pair=undated[(source,dataset)],
                historical_rows_seen=cp["rows_seen"] if cp else "",
                historical_scan_exhausted=bool(cp["scan_exhausted"]) if cp else "",
                recent_scans_finished=complete,recent_scans_incomplete=incomplete,
                assessment=assessment,external_source_count="NOT_VERIFIED",
                coverage_certified="False"))
    return report


def source_pair_count(remittances,payments,through):
    """Only the known source pairs are candidates; no cross-source certification."""
    summary=Counter()
    for direction,origin,destination,origin_types in DIRECTIONS:
        p=[x for x in payments if x.source==destination
           and x.occurred_at is not None and
           date(2026,1,1)<=x.occurred_at.date()<=through]
        p_counts=Counter(x.code for x in p)
        indexed=defaultdict(list)
        for r in remittances:
            if r.source==origin and r.operation_type in origin_types:
                indexed[r.code].append(r)
        for row in p:
            assessment,_,_=payment_assessment(
                row,indexed[row.code],p_counts[row.code],origin,destination,origin_types)
            summary[("payment_assessment",assessment)]+=1
            summary[("direction",direction)]+=1
    return summary


def table_present(conn,name):
    return bool(conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:name
    """),{"name":name}).scalar_one())


def collect(through):
    settings=get_settings()
    if ((settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Phase C requires the isolated pilot with ETL disabled")
    engine=pilot_engine(settings)
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                remittances=conn.execute(select(
                    Remittance.source_record_id,Remittance.source,Remittance.code,
                    Remittance.operation_type,Remittance.status,Remittance.amount,
                    Remittance.currency,Remittance.occurred_at)).all()
                payments=conn.execute(select(
                    Payment.source_record_id,Payment.source,Payment.code,
                    Payment.operation_type,Payment.amount,Payment.currency,
                    Payment.occurred_at,SourceRecord.payload.label("payload"))
                    .join(SourceRecord,SourceRecord.id==Payment.source_record_id)).all()
                historical={}
                if table_present(conn,"pilot_backfill_progress"):
                    cps=conn.execute(text("""
                        SELECT source,dataset,month_key,rows_seen,scan_exhausted
                        FROM pilot_backfill_progress
                        WHERE month_key BETWEEN '2026-01' AND :through
                    """),{"through":through.strftime("%Y-%m")}).mappings().all()
                    historical={(r["source"],r["dataset"],r["month_key"]):dict(r)
                                for r in cps}
                recent=[]
                if table_present(conn,"pilot_recent_refresh_progress"):
                    cps=conn.execute(text("""
                        SELECT source,dataset,as_of_date,lookback_days,scan_exhausted
                        FROM pilot_recent_refresh_progress
                        WHERE as_of_date <= :through
                    """),{"through":through}).mappings().all()
                    for row in cps:
                        item=dict(row)
                        item["window_start"]=item["as_of_date"]-timedelta(
                            days=item["lookback_days"]-1)
                        recent.append(item)
            finally:
                conn.rollback()
    finally:
        engine.dispose()
    inverse=inverse_payments(remittances,payments,through)
    coverage=monthly_coverage(remittances,payments,historical,recent,through)
    counts=source_pair_count(remittances,payments,through)
    for row in coverage:
        counts[("coverage_assessment",row["assessment"])]+=1
    return inverse,coverage,[
        dict(dimension=k[0],key=k[1],count=v,coverage_certified="False")
        for k,v in sorted(counts.items())
    ]


def write_csv(destination,fields,rows,sensitive=False):
    from scripts.pilot_operation_detail_2026 import safe_csv_value
    with destination.open("w",newline="",encoding="utf-8-sig") as file:
        writer=csv.DictWriter(file,fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {name:safe_csv_value(row.get(name,"")) if sensitive else row.get(name,"")
             for name in fields} for row in rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through",type=date.fromisoformat,required=True)
    parser.add_argument("--output",required=True,
                        help="Exception CSV directly under private /export")
    args=parser.parse_args()
    if not date(2026,1,1)<=args.through<=date.today():
        parser.error("Cutoff must be reached date in 2026")
    detail=validate_output(args.output)
    names=[detail,detail.with_name(detail.stem+"_cobertura.csv"),
           detail.with_name(detail.stem+"_resumen.csv")]
    for dest in names:
        validate_output(str(dest))
    inverse,coverage,summary=collect(args.through)
    write_csv(names[0],PAYMENT_FIELDS,inverse,sensitive=True)
    write_csv(names[1],COVERAGE_FIELDS,coverage)
    write_csv(names[2],SUMMARY_FIELDS,summary)
    counts=Counter(x["assessment"] for x in inverse)
    print(f"phase_c=True reverse_payment_exceptions={len(inverse)} "
          f"exception_counts={dict(sorted(counts.items()))} "
          f"coverage_month_rows={len(coverage)} "
          "source_connections=0 source_writes=False pilot_writes=False "
          "coverage_certified=False",flush=True)
    print("files_created="+",".join(x.name for x in names)+" private_export=True",
          flush=True)


if __name__=="__main__":
    main()
