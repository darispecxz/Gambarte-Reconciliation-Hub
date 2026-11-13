"""Seven permitted business currency routes; NOT certified FX or settlement."""
ALLOWED_CURRENCY_ROUTES = {
    "BO_TO_CL": frozenset({
        ("BOB", "CLP"), ("BOB", "USD"), ("USD", "USD"), ("USD", "CLP"),
    }),
    "CL_TO_BO": frozenset({
        ("CLP", "BOB"), ("USD", "BOB"), ("BOB", "BOB"),
    }),
}


def classify_currency_route(direction, origin_currency, payment_currency,
                            origin_source=None, payment_source=None):
    """Validate approved business route without implying accounting equivalence."""
    if direction not in ALLOWED_CURRENCY_ROUTES:
        return "UNKNOWN_DIRECTION_REVIEW"
    source, destination = (("BOLIVIA", "CHILE") if direction == "BO_TO_CL"
                           else ("CHILE", "BOLIVIA"))
    if ((origin_source and origin_source != source)
            or (payment_source and payment_source != destination)):
        return "DIRECTION_SOURCE_CONFLICT_REVIEW"
    origin = (origin_currency or "").strip().upper()
    payment = (payment_currency or "").strip().upper()
    if not origin or not payment:
        return "CURRENCY_DATA_INCOMPLETE"
    if (origin, payment) in ALLOWED_CURRENCY_ROUTES[direction]:
        return "VALID_CURRENCY_ROUTE_FINANCIAL_PENDING"
    return "UNEXPECTED_CURRENCY_ROUTE_REVIEW"
