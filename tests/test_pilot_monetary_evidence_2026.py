"""Synthetic monetary audit: FX ratios are never treated as verified FX."""
from scripts.pilot_monetary_evidence_2026 import monetary_classification,build


def row(origin="BOB",destination="CLP",a="373.61",b="39"):
    return dict(direction="BO_TO_CL",cohort="JANUARY_ORIGIN",
        as_of_status="PAID_BY_CUTOFF",code="X",origin_source="BOLIVIA",
        payment_source="CHILE",origin_currency=origin,payment_currency=destination,
        origin_amount=a,payment_amount=b,origin_key="1",payment_key="2",
        origin_date="",payment_date="")


def test_fx_not_certified_even_if_ratio_looks_stable():
    flag,ratio,note=monetary_classification(row())
    assert flag=="FX_SEMANTICS_UNVERIFIED"
    assert ratio=="0.104387"
    assert "No inferir FX" in note


def test_same_currency_equality_not_settlement():
    assert monetary_classification(row("USD","USD","100","100"))[0]=="SAME_CURRENCY_EQUAL_NOT_SETTLED"


def test_same_currency_difference():
    assert monetary_classification(row("BOB","BOB","100","99"))[0]=="SAME_CURRENCY_AMOUNT_DIFFERENCE"


def test_missing_payment():
    item=row()
    item["payment_key"]=""
    assert monetary_classification(item)[0]=="NO_MATCHED_PAYMENT"


def test_grouping_keeps_directions_and_cohorts():
    items,summary,groups=build([row(),row(),row("BOB","USD")])
    assert summary["FX_SEMANTICS_UNVERIFIED"]==3
    assert len(groups)==2
    assert sorted(g["count"] for g in groups)==[1,2]


def test_negative_and_invalid_review():
    assert monetary_classification(row(a="-10"))[0]=="NONPOSITIVE_AMOUNT_REVIEW"
    assert monetary_classification(row(a="not-number"))[0]=="MONETARY_DATA_INVALID"
