from scripts.pilot_monthly_readiness_2026 import adjacent,requirements,evaluate
def test_february_needs_january_and_march_payment():
    assert adjacent("2026-02")==("2026-01","2026-02","2026-03")
    req=requirements("2026-02")
    assert len(req)==10
    assert ("2026-03","NEXT_MONTH_PAYMENTS","CHILE","payment") in req
    assert ("2026-03","NEXT_MONTH_PAYMENTS","CHILE","remittance") not in req
def test_unstarted_month_is_blocked():
    result,status=evaluate("2026-02",[])
    assert len(result)==10
    assert status=="BLOCKED_INCOMPLETE_PILOT"
    assert all(r["coverage_certified"]=="false" for r in result)
def test_exhausted_is_not_certification():
    progress=[{"month_key":m,"source":s,"dataset":d,"rows_seen":4,
       "pages_seen":1,"scan_exhausted":True} for m,_,s,d in requirements("2026-02")]
    result,status=evaluate("2026-02",progress)
    assert status=="READY_FOR_MANUAL_COVERAGE_VALIDATION"
    assert all(r["coverage_certified"]=="false" for r in result)
