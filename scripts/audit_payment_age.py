"""Bounded, read-only exploratory cross-border payment-age audit.

Run manually inside the API container; NEVER enables source ETL, writes data
to source databases, or persists client codes. Only aggregate counts printed.
This is a sample audit, not proof of absence / completeness.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime
import os

import pymysql


DIRECTIONS = (
    ("BO_TO_CL", "CHILE", "BOLIVIA", (3, 5, 6, 8), (4, 16), "remesa"),
    ("CL_TO_BO", "BOLIVIA", "CHILE", (4, 7), (3, 5, 6, 8), "tmp_reporte_remesa"),
)


def connect_readonly(country: str):
    prefix = country + "_DB_"
    return pymysql.connect(
        host=os.environ[prefix + "HOST"],
        port=int(os.environ.get(prefix + "PORT", "3306")),
        user=os.environ[prefix + "USER"],
        password=os.environ[prefix + "PASSWORD"],
        database=os.environ[prefix + "NAME"],
        connect_timeout=10, read_timeout=30,
        autocommit=False,
    )


def summarize(payment_rows, origin_by_code):
    """Classify one bounded sample of payments without exposing any identifiers."""
    totals = Counter()
    for code, paid_at in payment_rows:
        totals["sampled_payments"] += 1
        origins = origin_by_code.get(str(code), [])
        if not origins:
            totals["origin_not_found_in_selected_types"] += 1
            continue
        if len(origins) > 1:
            totals["ambiguous_origin_code"] += 1
            continue
        created_at = origins[0]
        if not isinstance(created_at, datetime) or not isinstance(paid_at, datetime):
            totals["unknown_dates"] += 1
            continue
        lag = (paid_at - created_at).total_seconds() / 86400
        if lag < -1:
            totals["origin_created_after_payment"] += 1
        elif lag > 30:
            totals["paid_more_than_30_days_after_origin"] += 1
            # Detailed bands help size the initial import window without
            # reporting any individual code or customer information.
            if lag > 90:
                totals["paid_more_than_90_days_after_origin"] += 1
            elif lag > 60:
                totals["paid_between_60_and_90_days_after_origin"] += 1
            else:
                totals["paid_between_30_and_60_days_after_origin"] += 1
            totals["max_lag_days"] = max(totals["max_lag_days"], round(lag, 2))
        elif lag > 7:
            totals["paid_between_7_and_30_days_after_origin"] += 1
        else:
            totals["paid_within_7_days_or_clock_skew"] += 1
    return totals


def fetch_payment_sample(connection, types, days, limit):
    marks = ",".join(["%s"] * len(types))
    query = (
        "SELECT p.codigo,p.fec_crea_pago FROM pago p "
        f"WHERE p.id_operacion IN ({marks}) "
        "AND p.fec_crea_pago >= NOW() - INTERVAL %s DAY "
        "ORDER BY p.fec_crea_pago DESC,p.id_pago DESC LIMIT %s"
    )
    with connection.cursor() as cursor:
        cursor.execute(query, (*types, days, limit))
        return cursor.fetchall()


def fetch_origins(connection, table, types, codes):
    marks = ",".join(["%s"] * len(types))
    grouped = defaultdict(list)
    # Bounded by sample size, query chunks and a per-chunk result ceiling.
    # If duplicate density is exceptional, abort rather than undercount.
    with connection.cursor() as cursor:
        for offset in range(0, len(codes), 20):
            chunk = codes[offset:offset + 20]
            placeholders = ",".join(["%s"] * len(chunk))
            query = (
                f"SELECT codigo,fec_crea_remesa FROM {table} "
                f"WHERE id_operacion IN ({marks}) "
                f"AND codigo IN ({placeholders}) LIMIT 201"
            )
            cursor.execute(query, (*types, *chunk))
            rows = cursor.fetchall()
            if len(rows) > 200:
                raise RuntimeError(
                    "Too many remittances for one code batch; "
                    "cannot classify this sample without ambiguity"
                )
            for code, created_at in rows:
                grouped[str(code)].append(created_at)
    return grouped


def audit_one(direction, connections, days, limit):
    name, pay_country, origin_country, payment_types, origin_types, origin_table = direction
    payment_rows = fetch_payment_sample(
        connections[pay_country], payment_types, days, limit
    )
    codes = sorted({str(code) for code, _ in payment_rows if code is not None})
    origins = fetch_origins(connections[origin_country], origin_table, origin_types, codes) if codes else {}
    result = summarize(payment_rows, origins)
    print(f"\n{name} | payment_country={pay_country} | sample_limit={limit} | days={days}")
    print(f"sample_is_capped={len(payment_rows) == limit}")
    for key in (
        "sampled_payments", "paid_more_than_30_days_after_origin",
        "paid_between_30_and_60_days_after_origin",
        "paid_between_60_and_90_days_after_origin",
        "paid_more_than_90_days_after_origin", "max_lag_days",
        "paid_between_7_and_30_days_after_origin",
        "paid_within_7_days_or_clock_skew", "origin_not_found_in_selected_types",
        "ambiguous_origin_code", "unknown_dates", "origin_created_after_payment",
    ):
        print(f"{key}={result[key]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--sample", type=int, default=150)
    args = parser.parse_args()
    if not 1 <= args.days <= 30 or not 1 <= args.sample <= 250:
        parser.error("--days must be 1..30 and --sample 1..250")

    # Separate read-only transactions, always rolled back. No DB writes.
    with ExitStack() as stack:
        connections = {}
        try:
            for country in ("BOLIVIA", "CHILE"):
                connection = connect_readonly(country)
                stack.callback(connection.close)
                with connection.cursor() as cursor:
                    cursor.execute("START TRANSACTION READ ONLY")
                connections[country] = connection
            for direction in DIRECTIONS:
                audit_one(direction, connections, args.days, args.sample)
        finally:
            for connection in connections.values():
                connection.rollback()
    print("\nNOTES: Sample only. Missing origin is not proof of loss.")
    print("Dates are source-local and not normalized across countries.")
    print("Do not enable ETL based on this diagnostic alone.")


if __name__ == "__main__":
    main()
