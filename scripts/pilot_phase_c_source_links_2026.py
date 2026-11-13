"""Phase C local ingestion integrity: SourceRecord to normalized projection.

Aggregates only, isolated pilot read-only, no source connections. Checks
distinct source records, missing projections, duplicated projections and
projection rows lacking their source evidence. Never certifies source coverage.
"""
import argparse
import csv
from datetime import date
from sqlalchemy import text

from app.core.config import get_settings
from scripts.pilot_backfill_2026 import pilot_engine
from scripts.pilot_coverage_audit_2026 import validate_output
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker

FIELDS=("source","dataset","source_records","projections","source_without_projection",
        "projection_without_source","multiple_projections_per_source",
        "assessment","coverage_certified")
PAIRS=(("BOLIVIA","remittance"),("BOLIVIA","payment"),
       ("CHILE","remittance"),("CHILE","payment"))
TABLES={"remittance":"remittances","payment":"payments"}


def assess(source_count,projection_count,missing_projection,
           missing_source,duplicates):
    return ("LOCAL_LINK_INTEGRITY_REVIEW"
            if missing_projection or missing_source or duplicates
            or source_count!=projection_count else
            "LOCAL_LINK_COUNTS_MATCH_NOT_CERTIFIED")


def collect():
    s=get_settings()
    if ((s.db_host,s.db_name)!=(PILOT_HOST,PILOT_DB)
            or s.enable_source_etl or s.source_mapping_verified):
        raise RuntimeError("Only isolated pilot with source ETL disabled")
    engine=pilot_engine(s)
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(conn)
                result=[]
                for source,dataset in PAIRS:
                    # All table identifiers are fixed literals from TABLES.
                    table=TABLES[dataset]
                    counts=conn.execute(text(f"""
                        SELECT
                          (SELECT COUNT(*) FROM source_records sr
                           WHERE sr.source=:source AND sr.dataset=:dataset)
                             AS source_records,
                          (SELECT COUNT(*) FROM {table} p
                           WHERE p.source=:source) AS projections,
                          (SELECT COUNT(*) FROM source_records sr
                           LEFT JOIN {table} p ON p.source_record_id=sr.id
                           WHERE sr.source=:source AND sr.dataset=:dataset
                             AND p.id IS NULL) AS missing_projection,
                          (SELECT COUNT(*) FROM {table} p
                           LEFT JOIN source_records sr ON sr.id=p.source_record_id
                           WHERE p.source=:source AND
                             (sr.id IS NULL OR sr.source<>:source
                              OR sr.dataset<>:dataset)) AS missing_source,
                          (SELECT COUNT(*) FROM (
                             SELECT p.source_record_id
                             FROM {table} p WHERE p.source=:source
                             GROUP BY p.source_record_id HAVING COUNT(*)>1
                           ) duplicates) AS duplicate_projection
                    """),{"source":source,"dataset":dataset}).mappings().one()
                    sr=int(counts["source_records"])
                    proj=int(counts["projections"])
                    no_proj=int(counts["missing_projection"])
                    no_src=int(counts["missing_source"])
                    dup=int(counts["duplicate_projection"])
                    result.append(dict(source=source,dataset=dataset,
                        source_records=sr,projections=proj,
                        source_without_projection=no_proj,
                        projection_without_source=no_src,
                        multiple_projections_per_source=dup,
                        assessment=assess(sr,proj,no_proj,no_src,dup),
                        coverage_certified="False"))
                return result
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    dest=validate_output(args.output)
    rows=collect()
    with dest.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"local_integrity_pairs={len(rows)} "
          f"pairs_requiring_review={sum(x['assessment']=='LOCAL_LINK_INTEGRITY_REVIEW' for x in rows)} "
          "source_connections=0 source_writes=False pilot_writes=False "
          "coverage_certified=False",flush=True)
    print(f"files_created={dest.name} private_export=True",flush=True)


if __name__=="__main__":
    main()
