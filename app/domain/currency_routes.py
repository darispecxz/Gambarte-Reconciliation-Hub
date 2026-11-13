"""Six permitted business currency routes; NOT certified field mappings or FX."""
ALLOWED_CURRENCY_ROUTES = {
    "BO_TO_CL": frozenset({("BOB", "CLP"), ("BOB", "USD"), ("USD", "USD"), ("USD", "CLP")}),
    "CL_TO_BO": frozenset({("CLP", "BOB"), ("USD", "BOB")}),
}


def classify_currency_route(direction, origin_currency, payment_currency,
                            origin_source=None, payment_source=None):
    """Validate operational pair without inferring payout unit or financial settlement."""
    if direction not in ALLOWED_CURRENCY_ROUTES:
        return "UNKNOWN_DIRECTION_REVIEW"
    source, destination = (("BOLIVIA", "CHILE") if direction == "BO_TO_CL"
                           else ("CHILE", "BOLIVIA"))
    if (origin_source and origin_source != source
            or payment_source and payment_source != destination):
        return "DIRECTION_SOURCE_CONFLICT_REVIEW"
    origin = (origin_currency or "").strip().upper()
    payment = (payment_currency or "").strip().upper()
    if not origin or not payment:
        return "CURRENCY_DATA_INCOMPLETE"
    # Chile consolidated view may denote payout (BOB), not sending unit.
    # Never call this an invalid business route without the original send unit.
    if direction == "CL_TO_BO" and origin == "BOB":
        return "CHILE_ORIGIN_CURRENCY_FIELD_UNVERIFIED"
    if (origin, payment) in ALLOWED_CURRENCY_ROUTES[direction]:
        return "VALID_CURRENCY_ROUTE_FINANCIAL_PENDING"
    return "UNEXPECTED_CURRENCY_ROUTE_REVIEW"
