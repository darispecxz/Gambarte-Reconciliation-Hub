"""Run monthly source count checks independently; never bypass EXPLAIN safety.

Blocked scans are reported as blocked and subsequent checks continue.
Only source SELECTs with accepted plans, and read-only pilot checkpoints.
"""
import argparse
import csv
from pathlib import Path
from scripts.pilot_month_count import run as count_run
from scripts.pilot_operation_detail_2026 import safe_csv_value
from scripts.management_report_2026 import EXPORT_DIR


CHECKS=(
    ("BOLIVIA","remittance","2026-01"),
    ("BOLIVIA","payment","2026-01"),
    ("CHILE","remittance","2026-01"),
    ("CHILE","payment","2026-01"),
    ("BOLIVIA","remittance","2026-02"),
    ("BOLIVIA","payment","2026-02"),
    ("CHILE","remittance","2026-02"),
    ("CHILE","payment","2026-02"),
    ("BOLIVIA","payment","2026-03"),
    ("CHILE","payment","2026-03"),
)
FIELDS=("source","dataset","month","status","source_count","pilot_rows_scanned","message")
def validate_csv_export_path(path):
    """Permit only a regular CSV destination directly inside the private /export mount."""
    output = Path(path)
    if (not output.is_absolute()
            or output.parent != EXPORT_DIR
            or output.suffix.lower() != ".csv"):
        raise ValueError("Output must be a CSV file directly under /export")
    if not EXPORT_DIR.is_dir():
        raise RuntimeError("Mount a private local export directory at /export")
    if output.is_symlink():
        raise ValueError("Symlink output blocked")
    if output.parent.resolve(strict=True) != EXPORT_DIR.resolve(strict=True):
        raise ValueError("Output mount resolves outside approved directory")
    return output

def classify(result):
    if not result.get("counted"):
        return ("BLOCKED_UNSAFE_COUNT_PLAN" if result.get("status")=="COUNT_PLAN_BLOCKED"
                else "NOT_EXECUTED")
    return result.get("status","UNKNOWN")
def collect(executor=count_run):
    results=[]
    for source,dataset,month in CHECKS:
        print(f"checking={source}/{dataset}/{month}",flush=True)
        try:
            value=executor(source,dataset,month,count=True)
            status=classify(value)
            results.append(dict(source=source,dataset=dataset,month=month,
                status=status,source_count=value.get("source_count",""),
                pilot_rows_scanned=value.get("pilot_rows_scanned",""),
                message=("Skipped: unindexed or costly EXPLAIN" if status=="BLOCKED_UNSAFE_COUNT_PLAN" else "")))
        except Exception as exc:
            # Continue with independent sources; never mark errors as count matches.
            results.append(dict(source=source,dataset=dataset,month=month,
                status="ERROR",source_count="",pilot_rows_scanned="",
                message=type(exc).__name__))
        print(f"check_result={results[-1]['status']}",flush=True)
    return results
def write(path,rows):
    output=validate_csv_export_path(path)
    with output.open("w",encoding="utf-8-sig",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:writer.writerow({key:safe_csv_value(row.get(key,"")) for key in FIELDS})
    return output
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    rows=collect()
    target=write(args.output,rows)
    matched=sum(r["status"]=="COUNT_MATCH_NOT_CERTIFIED" for r in rows)
    blocked=sum(r["status"]=="BLOCKED_UNSAFE_COUNT_PLAN" for r in rows)
    issues=sum(r["status"] not in ("COUNT_MATCH_NOT_CERTIFIED","BLOCKED_UNSAFE_COUNT_PLAN") for r in rows)
    print(f"matched={matched} blocked={blocked} issues={issues} checked={len(rows)}")
    print(f"report={target.name} coverage_certified=False source_writes=False")
    if issues: raise SystemExit(2)
    # Blocked plans are recognized incomplete evidence, not success.
    if blocked: raise SystemExit(3)
if __name__=="__main__":main()
