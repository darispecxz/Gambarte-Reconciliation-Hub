"""Currency route policy is separate from monetary and settlement certification."""
from app.domain.currency_routes import ALLOWED_CURRENCY_ROUTES, classify_currency_route
from scripts.pilot_monetary_evidence_2026 import build


def test_seven_authorized_pairs():
    assert sum(len(routes) for routes in ALLOWED_CURRENCY_ROUTES.values()) == 7
    assert len(ALLOWED_CURRENCY_ROUTES["BO_TO_CL"]) == 4
    assert len(ALLOWED_CURRENCY_ROUTES["CL_TO_BO"]) == 3
    for direction, pairs in ALLOWED_CURRENCY_ROUTES.items():
        for origin, payment in pairs:
            assert classify_currency_route(direction, origin, payment) == (
                "VALID_CURRENCY_ROUTE_FINANCIAL_PENDING")


def test_chilean_bob_bob_is_permitted_but_not_financially_certified():
    row=dict(direction="CL_TO_BO",cohort="JANUARY_ORIGIN",code="x",
        origin_source="CHILE",payment_source="BOLIVIA",
        origin_currency="BOB",payment_currency="BOB",
        origin_amount="100",payment_amount="100",
        origin_key="1",payment_key="2",origin_date="",payment_date="")
    result,_,_=build([row])
    assert result[0]["currency_route_status"]=="VALID_CURRENCY_ROUTE_FINANCIAL_PENDING"
    assert result[0]["money_flag"]=="SAME_CURRENCY_EQUAL_NOT_SETTLED"
    assert result[0]["financial_status"]=="FINANCIAL_VALIDATION_PENDING"


def test_unexpected_and_direction_conflict():
    assert classify_currency_route("BO_TO_CL","EUR","CLP") == "UNEXPECTED_CURRENCY_ROUTE_REVIEW"
    assert classify_currency_route("BO_TO_CL","BOB","CLP","CHILE","BOLIVIA") == (
        "DIRECTION_SOURCE_CONFLICT_REVIEW")


def test_valid_fx_pair_does_not_claim_financial_match():
    row=dict(direction="BO_TO_CL",cohort="JANUARY_ORIGIN",code="x",
        origin_source="BOLIVIA",payment_source="CHILE",
        origin_currency="BOB",payment_currency="CLP",
        origin_amount="1000",payment_amount="100",
        origin_key="1",payment_key="2",origin_date="",payment_date="")
    result,_,_=build([row])
    assert result[0]["money_flag"]=="FX_SEMANTICS_UNVERIFIED"
    assert result[0]["currency_route_status"]=="VALID_CURRENCY_ROUTE_FINANCIAL_PENDING"
    assert result[0]["financial_status"]=="FINANCIAL_VALIDATION_PENDING"
