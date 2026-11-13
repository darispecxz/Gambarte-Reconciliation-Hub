"""Offline Phase C controls: inverse payee audit and coverage uncertainty."""
from datetime import date,datetime
from types import SimpleNamespace

from scripts.pilot_phase_c_integrity_2026 import (
    inverse_payments,monthly_coverage,payment_assessment,source_pair_count,
)


def row(source,code,op,day,record_id=1,amount=100,currency="BOB"):
    return SimpleNamespace(source=source,code=code,operation_type=op,
        occurred_at=datetime.fromisoformat(day) if day else None,
        source_record_id=record_id,amount=amount,currency=currency,status="PAID")


def test_inverse_missing_is_pilot_only_not_production_claim():
    payments=[row("BOLIVIA","4321",4,"2026-11-13 09:00:00")]
    result=inverse_payments([],payments,date(2026,11,13))
    assert len(result)==1
    assert result[0]["assessment"]=="NO_ORIGIN_IN_PILOT"
    assert result[0]["coverage_certified"]=="False"


def test_inverse_pair_skips_known_valid_payment():
    rems=[row("CHILE","4321",3,"2026-11-12 09:00:00")]
    pays=[row("BOLIVIA","4321",4,"2026-11-13 09:00:00")]
    assert inverse_payments(rems,pays,date(2026,11,13)) == []
    stats=source_pair_count(rems,pays,date(2026,11,13))
    assert stats[("payment_assessment","PROVISIONAL_INVERSE_PAIR")]==1


def test_inverse_type_incompatible_is_not_mislabeled_missing_origin():
    rems=[row("CHILE","4321",5,"2026-11-12 09:00:00")]
    pays=[row("BOLIVIA","4321",4,"2026-11-13 09:00:00")]
    result=inverse_payments(rems,pays,date(2026,11,13))
    assert result[0]["assessment"]=="PAYMENT_TYPE_NOT_COMPATIBLE_WITH_ORIGIN"


def test_inverse_duplicate_payment_is_reviewed():
    rems=[row("CHILE","4321",3,"2026-11-12 09:00:00")]
    pays=[row("BOLIVIA","4321",4,"2026-11-13 09:00:00",1),
          row("BOLIVIA","4321",4,"2026-11-13 10:00:00",2)]
    results=inverse_payments(rems,pays,date(2026,11,13))
    assert len(results)==2
    assert all(x["assessment"]=="AMBIGUOUS_OR_DUPLICATE_CODE_REVIEW"
               for x in results)


def test_cross_year_remittance_can_match_2026_payment():
    rems=[row("CHILE","4321",3,"2025-12-30 10:00:00")]
    pays=[row("BOLIVIA","4321",4,"2026-01-02 09:00:00")]
    assert inverse_payments(rems,pays,date(2026,11,13))==[]


def test_coverage_does_not_certify_even_when_historical_checkpoint_exhausted():
    cp={("BOLIVIA","payment","2026-11"):
        {"scan_exhausted":True,"rows_seen":1}}
    payments=[row("BOLIVIA","123",4,"2026-11-13 09:00:00")]
    lines=monthly_coverage([],payments,cp,[],date(2026,11,13))
    result=next(x for x in lines if x["source"]=="BOLIVIA"
                and x["dataset"]=="payment" and x["month"]=="2026-11")
    assert result["assessment"]=="LOCAL_ONLY_SOURCE_COUNT_UNVERIFIED"
    assert result["external_source_count"]=="NOT_VERIFIED"
    assert result["coverage_certified"]=="False"


def test_missing_historical_checkpoint_has_explicit_status():
    result=monthly_coverage([],[],{},[],date(2026,1,2))
    assert len(result)==4
    assert all(x["assessment"]=="HISTORICAL_CHECKPOINT_MISSING" for x in result)
