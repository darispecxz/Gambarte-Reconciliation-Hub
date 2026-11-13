"""Phase C: bounded source lookup of pilot payments lacking a remittance.

Reads the isolated pilot to select up to 25 distinct payment codes, then
performs a separate indexed, READ ONLY, EXPLAIN-guarded source lookup for
each code in the opposite country. This first phase deliberately DOES NOT
import found remittances: findings must be reviewed first, particularly
cross-year records. All results remain preliminary and private.
"""
import argparse
import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.integrations.source import SQL, read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine, source_plan_guard
from scripts.pilot_coverage_audit_2026 import validate_output
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.pilot_phase_c_integrity_2026 import collect
from scripts.preflight_source import inspect_page

FIELDS=("direction","payment_code","payment_source","origin_source",
        "payment_records_in_pilot","source_lookup_status",
        "origin_rows_found","origin_rows_2025","origin_rows_2026",
        "origin_rows_other_years","origin_types_found",
        "source_explain_access","source_explain_key","coverage_certified")
PAGE_LIMIT=50
MAX_CODES=25
SOURCE_FOR_DIRECTION={"BO_TO_CL":"BOLIVIA","CL_TO_BO":"CHILE"}
# Only adapt the already-reviewed projection of remittance source tables.
DATE_CLAUSE="(r.fec_crea_remesa >= :cutoff OR r.fec_mod_remesa >= :cutoff)"


def validate_code(code):
    value=str(code)
    if not re.fullmatch(r"[1-9][0-9]{0,17}",value):
        raise ValueError("Lookup requires positive 1..18-digit source code")
    return value


def targeted_sql(source):
    if source not in ("BOLIVIA","CHILE"):
        raise ValueError("Unknown source")
    base=SQL[(source,"remittance")]
    if base.count(DATE_CLAUSE)!=1:
        raise RuntimeError("Source remittance SQL changed; review required")
    query=base.replace(DATE_CLAUSE,"r.codigo = :code")
    validate_read_query(query)
    return query


def candidates(exceptions,max_codes):
    if not 1 <= max_codes <= MAX_CODES:
        raise ValueError("Maximum of 25 codes per manual invocation")
    grouped={}
    for item in exceptions:
        if item["assessment"]!="NO_ORIGIN_IN_PILOT":
            continue
        code=validate_code(item["payment_code"])
        key=(item["direction"],code)
        if key not in grouped:
            grouped[key]=dict(direction=item["direction"],payment_code=code,
                              payment_source=item["payment_source"],
                              payment_records_in_pilot=0)
        grouped[key]["payment_records_in_pilot"]+=1
    # Deterministic order, fail rather than silently truncate.
    result=sorted(grouped.values(),key=lambda x:(x["direction"],int(x["payment_code"])))
    if len(result)>max_codes:
        raise RuntimeError(
            f"{len(result)} distinct cases exceed --max-codes={max_codes}. "
            "Use a larger cap up to 25 or investigate subsets explicitly.")
    return result


def classify_source_rows(rows,code):
    # No normalization or persistence; source data stays read-only.
    if len(rows)>=PAGE_LIMIT:
        raise RuntimeError("Reached 50 source records per code; refusing partial result")
    years=Counter()
    types=set()
    for row in rows:
        if str(row["code"]).strip()!=code:
            raise RuntimeError("Source returned different code than requested")
        dt=row.get("occurred_at")
        years[dt.year if dt else 0]+=1
        types.add(str(row["operation_type"]))
    return dict(origin_rows_found=len(rows),
                origin_rows_2025=years[2025],origin_rows_2026=years[2026],
                origin_rows_other_years=len(rows)-years[2025]-years[2026],
                origin_types_found="|".join(sorted(types)))


def lookup_cases(cases,settings):
    results=[]
    engines={}
    try:
        for case in cases:
            origin=SOURCE_FOR_DIRECTION[case["direction"]]
            if origin not in engines:
                engines[origin]=connect_source(settings,origin)
            params=dict(code=case["payment_code"],last_id=0,last_op=0,
                        last_code=0,last_dest=0,lim=PAGE_LIMIT)
            query=targeted_sql(origin)
            result=dict(case,origin_source=origin,source_lookup_status="NOT_EXECUTED",
                        origin_rows_found="",origin_rows_2025="",
                        origin_rows_2026="",origin_rows_other_years="",
                        origin_types_found="",source_explain_access="",
                        source_explain_key="",coverage_certified="False")
            try:
                with read_only_transaction(engines[origin]) as conn:
                    plan=conn.execute(text("EXPLAIN "+query),params).mappings().all()
                    source_plan_guard(plan)
                    raw=conn.execute(text(query),params).mappings().all()
                    inspect_page(origin,"remittance",raw)
                    summary=classify_source_rows(raw,case["payment_code"])
                result.update(summary)
                result["source_explain_access"]="|".join(str(p.get("type")) for p in plan)
                result["source_explain_key"]="|".join(str(p.get("key")) for p in plan)
                result["source_lookup_status"]=(
                    "ORIGIN_FOUND_IN_SOURCE" if raw else "NO_ORIGIN_FOUND_BY_CODE")
            except (RuntimeError,ValueError) as exc:
                # All rejected plans remain unexecuted. Do not bypass.
                result["source_lookup_status"]=(
                    "LOOKUP_BLOCKED_OR_INCONCLUSIVE")
                result["source_explain_access"]=type(exc).__name__
            results.append(result)
            print(f"checked={len(results)}/{len(cases)} "
                  f"origin={origin} status={result['source_lookup_status']} "
                  "source_writes=False",flush=True)
    finally:
        for engine in engines.values():
            engine.dispose()
    return results


def run(through,output,max_codes=25):
    if not date(2026,1,1)<=through<=date.today():
        raise ValueError("Cutoff must be a reached date in 2026")
    destination=validate_output(output)
    settings=get_settings()
    if ((settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Only isolated pilot and disabled ETL allowed")
    # collect() validates marker, performs read-only pilot transaction,
    # and generates exceptions without modifying anything.
    exceptions,_,_=collect(through)
    lookup=candidates(exceptions,max_codes)
    print(f"candidate_codes={len(lookup)} source_access=READ_ONLY "
          f"max_per_code={PAGE_LIMIT} coverage_certified=False",flush=True)
    results=lookup_cases(lookup,settings)
    with destination.open("w",newline="",encoding="utf-8-sig") as file:
        writer=csv.DictWriter(file,fieldnames=FIELDS)
        writer.writeheader()
        from scripts.pilot_operation_detail_2026 import safe_csv_value
        writer.writerows({k:safe_csv_value(r.get(k,"")) for k in FIELDS}
                         for r in results)
    statuses=Counter(r["source_lookup_status"] for r in results)
    print(f"phase_c_source_lookup=True results={dict(sorted(statuses.items()))} "
          f"report={destination.name} source_writes=False pilot_writes=False "
          "coverage_certified=False",flush=True)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--through",required=True,type=date.fromisoformat)
    p.add_argument("--output",required=True)
    p.add_argument("--max-codes",type=int,default=25)
    args=p.parse_args()
    run(args.through,args.output,args.max_codes)


if __name__=="__main__":
    main()
