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


def classify_operation(source: str, dataset: str, operation_type: int | None) -> str:
    if operation_type is None:
        return "UNKNOWN"
    lookup = REMITTANCE_KIND if dataset == "remittance" else PAYMENT_KIND if dataset == "payment" else {}
    return lookup.get(source, {}).get(operation_type, "UNKNOWN")
