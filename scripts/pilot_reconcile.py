"""Read-only provisional operational classification of the isolated pilot.

No MATCHED, PAYMENT_MISSING, persisted result, coverage or amount comparison.
Country/type direction is a pilot hypothesis, not an approved source contract.
"""
from collections import Counter, defaultdict

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

from app.core.config import get_settings
from app.domain.matching import CLOSED, NONPAID
from app.domain.operation_types import allowed_destination_payment_types
from app.infrastructure.models import Payment, Remittance
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker


DIRECTIONS = (
    ("BO_TO_CL", "BOLIVIA", "CHILE", {4, 16}),
    ("CL_TO_BO", "CHILE", "BOLIVIA", {3, 5, 6, 8}),
)


def classify(status, origin_count, payments, metadata_complete):
    if origin_count > 1 or len(payments) > 1:
        return "MANUAL_REVIEW_AMBIGUOUS_CODE"
    if payments:
        if status in CLOSED:
            return "MANUAL_REVIEW_CLOSED_WITH_PAYMENT"
        if status in NONPAID:
            return "MANUAL_REVIEW_STATUS_WITH_PAYMENT"
        if status != "PAID" or not metadata_complete:
            return "INSUFFICIENT_DATA"
        return "PROVISIONAL_CODE_PAIR"
    if status in CLOSED:
        return "CLOSED_IN_SAMPLE"
    if status in NONPAID:
        return "PENDING_IN_SAMPLE"
    return "NO_PAYMENT_IN_SAMPLE" if status == "PAID" else "INSUFFICIENT_DATA"


def summarize(remittances, payments):
    totals = {}
    for direction, origin, destination, origin_types in DIRECTIONS:
        origin_rows = [row for row in remittances
                       if row.source == origin and row.operation_type in origin_types]
        payout_rows = [row for row in payments
                       if row.source == destination]
        origin_by_code = defaultdict(list)
        payment_by_code = defaultdict(list)
        for row in origin_rows:
            origin_by_code[row.code].append(row)
        for row in payout_rows:
            payment_by_code[row.code].append(row)
        counts = Counter()
        for row in origin_rows:
            all_candidates = payment_by_code[row.code]
            allowed = allowed_destination_payment_types(
                origin, destination, row.operation_type
            )
            if allowed is None:
                counts["INSUFFICIENT_UNVERIFIED_PAYMENT_MAPPING"] += 1
                continue
            candidates = [payment for payment in all_candidates
                          if payment.operation_type in allowed]
            unexpected = [payment for payment in all_candidates
                          if payment.operation_type not in allowed]
            if unexpected:
                counts["MANUAL_REVIEW_UNEXPECTED_PAYMENT_TYPE"] += 1
                continue
            metadata_complete = (row.amount is not None and bool(row.currency)
                                 and all(p.amount is not None and p.currency
                                         for p in candidates))
            counts[classify(row.status, len(origin_by_code[row.code]),
                            candidates, metadata_complete)] += 1
        totals[direction] = {"origins": len(origin_rows),
                             "payments_in_sample": len(payout_rows),
                             "categories": counts}
    return totals


def run():
    settings = get_settings()
    if ((settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Provisional run requires isolated pilot and disabled ETL")
    engine = create_engine(URL.create(
        "mysql+pymysql", host=settings.db_host, port=settings.db_port,
        username=settings.db_user, password=settings.db_password,
        database=settings.db_name, query={"charset": "utf8mb4"},
    ), connect_args={"connect_timeout": 10, "read_timeout": 30})
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(connection)
                remittances = connection.execute(select(
                    Remittance.source, Remittance.code, Remittance.operation_type,
                    Remittance.status, Remittance.amount, Remittance.currency,
                )).all()
                payments = connection.execute(select(
                    Payment.source, Payment.code, Payment.operation_type,
                    Payment.amount, Payment.currency,
                )).all()
                totals = summarize(remittances, payments)
            finally:
                connection.rollback()
    finally:
        engine.dispose()
    for direction, result in totals.items():
        print(f"direction={direction} origins={result['origins']} "
              f"payments_in_sample={result['payments_in_sample']}")
        for category, count in sorted(result["categories"].items()):
            print(f"{category}={count}")
    print("read_only=True persisted=False matched_certified=False "
          "payment_missing_claim=False amounts_compared=False")
    return totals


if __name__ == "__main__":
    run()
