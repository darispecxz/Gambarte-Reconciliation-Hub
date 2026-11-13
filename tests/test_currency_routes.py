"""Currency route policy is distinct from monetary certification."""
from app.domain.currency_routes import ALLOWED_CURRENCY_ROUTES, classify_currency_route
from scripts.pilot_monetary_evidence_2026 import build


def test_six_authorized_pairs():
    assert sum(len(routes) for routes in ALLOWED_CURRENCY_ROUTES.values()) == 6
    for direction, pairs in ALLOWED_CURRENCY_ROUTES.items():
        for origin, payment in pairs:
            assert classify_currency_route(direction, origin, payment) == (
                "VALID_CURRENCY_ROUTE_FINANCIAL_PENDING")


def test_chilean_origin_bob_projection_is_not_auto_invalid():
    assert classify_currency_route("CL_TO_BO","BOB","BOB","CHILE","BOLIVIA") == (
        "CHILE_ORIGIN_CURRENCY_FIELD_UNVERIFIED")


def test_unexpected_and_direction_conflict():
    assert classify_currency_route("BO_TO_CL","EUR","CLP") == "UNEXPECTED_CURRENCY_ROUTE_REVIEW"
    assert classify_currency_route("BO_TO_CL","BOB","CLP","CHILE","BOLIVIA") == (
        "DIRECTION_SOURCE_CONFLICT_REVIEW")


def test_valid_pair_never_claims_financial_match():
    row=dict(direction="BO_TO_CL",cohort="JANUARY_ORIGIN",code="x",
        origin_source="BOLIVIA",payment_source="CHILE",
        origin_currency="BOB",payment_currency="CLP",
        origin_amount="1000",payment_amount="100",
        origin_key="1",payment_key="2",origin_date="",payment_date="")
    result,_,_=build([row])
    assert result[0]["money_flag"]=="FX_SEMANTICS_UNVERIFIED"
    assert result[0]["currency_route_status"]=="VALID_CURRENCY_ROUTE_FINANCIAL_PENDING"
    assert result[0]["financial_status"]=="FINANCIAL_VALIDATION_PENDING"
