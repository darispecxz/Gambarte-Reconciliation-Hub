from scripts.pilot_monthly_counts_safe_2026 import CHECKS,classify,collect
def test_count_checks_continue_after_blocked_plan():
    observed=[]
    def fake(source,dataset,month,count):
        observed.append((source,dataset,month))
        if source=="CHILE" and dataset=="remittance":
            return {"counted":False,"status":"COUNT_PLAN_BLOCKED"}
        return {"counted":True,"status":"COUNT_MATCH_NOT_CERTIFIED",
                "source_count":10,"pilot_rows_scanned":10}
    rows=collect(fake)
    assert len(observed)==10
    assert len(rows)==10
    assert sum(x["status"]=="BLOCKED_UNSAFE_COUNT_PLAN" for x in rows)==2
    assert sum(x["status"]=="COUNT_MATCH_NOT_CERTIFIED" for x in rows)==8
def test_exception_continues():
    def fake(source,dataset,month,count):
        if source=="BOLIVIA" and month=="2026-01" and dataset=="payment":
            raise RuntimeError("connect failed")
        return {"counted":True,"status":"COUNT_MATCH_NOT_CERTIFIED"}
    rows=collect(fake)
    assert len(rows)==10
    assert sum(x["status"]=="ERROR" for x in rows)==1
