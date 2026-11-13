"""Source-backed product/modality labels; not accounting classification.

Use only the operation IDs confirmed by the historical C# POC and PHP
source. Payment subtype for Chile remains unspecified beyond type number.
"""


REMITTANCE_KIND = {
    "BOLIVIA": {4: "LEGACY_REMITTANCE", 16: "INTERNATIONAL_GIRO"},
    "CHILE": {
        3: "REMITTANCE",
        5: "BANK_DEPOSIT",
        6: "BANK_DEPOSIT",
        8: "BANK_LOAN",
    },
}

PAYMENT_KIND = {
    "BOLIVIA": {4: "CASH_WINDOW", 7: "BANK_DEPOSIT"},
    "CHILE": {3: "LEGACY_TYPE_3", 5: "LEGACY_TYPE_5",
              6: "LEGACY_TYPE_6", 8: "LEGACY_TYPE_8"},
}

# Confirmed operational delivery pairs. These constrain code-based matching;
# they do not imply accounting equivalence or amount/FX validation.
DESTINATION_PAYMENT_TYPES = {
    ("BOLIVIA", "CHILE", 4): frozenset({3, 5, 6, 8}),
    ("BOLIVIA", "CHILE", 16): frozenset({3, 5, 6, 8}),
    ("CHILE", "BOLIVIA", 3): frozenset({4}),
    ("CHILE", "BOLIVIA", 5): frozenset({7}),
    ("CHILE", "BOLIVIA", 6): frozenset({7}),
    ("CHILE", "BOLIVIA", 8): frozenset({7}),
}


def classify_operation(source: str, dataset: str, operation_type: int | None) -> str:
    if operation_type is None:
        return "UNKNOWN"
    lookup = REMITTANCE_KIND if dataset == "remittance" else PAYMENT_KIND if dataset == "payment" else {}
    return lookup.get(source, {}).get(operation_type, "UNKNOWN")


def allowed_destination_payment_types(origin: str, destination: str,
                                      operation_type: int | None):
    """Return approved payment types, or None when the pairing is unverified."""
    return DESTINATION_PAYMENT_TYPES.get((origin, destination, operation_type))
