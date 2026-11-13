"""Read-only December 2025 to January 2026 targeted operation evidence.

No import into pilot, no write to source. Uses only January unpaired
payments detected by existing pilot matching, 25-code maximum, and short
December source lookups protected by EXPLAIN. Creates private HTML/CSV.
The result is provisional operational evidence, not financial certification.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.core.config import get_settings
from app.domain.operation_types import allowed_destination_payment_types
from app.infrastructure.models import Remittance, Payment, SourceRecord
from app.integrations.source import normalize, read_only_transaction, validate_read_query
from scripts.pilot_backfill_2026 import pilot_engine, source_plan_guard
from scripts.pilot_december_lookup_2025 import missing_january_payment_codes
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker, connect_source
from scripts.pilot_operation_detail_2026 import (
    COLUMNS, export_csv, html_report, validate_export_path, detail_rows,
)

DECEMBER_SQL = {
    "BOLIVIA": """SELECT r.id_remesa AS source_pk, r.codigo AS code,
        r.id_operacion AS operation_type, r.estado AS status_code,
        r.monto AS amount, r.mon_rec AS currency_id,
        r.fec_crea_remesa AS occurred_at, r.fec_mod_remesa AS updated_at
        FROM remesa r WHERE r.codigo = :code AND r.id_operacion IN (4,16)
          AND r.fec_crea_remesa >= :from_date AND r.fec_crea_remesa < :to_date
        LIMIT 5""",
    "CHILE": """SELECT r.id_remesa AS source_pk, r.codigo AS code,
        r.id_destino AS cursor_destination,
        r.id_operacion AS operation_type, r.estado AS status_code,
        r.envio AS amount, r.moneda AS currency_id,
        r.fec_crea_remesa AS occurred_at, r.fec_mod_remesa AS updated_at
        FROM tmp_reporte_remesa r FORCE INDEX (PRIMARY)
        WHERE r.codigo = :code AND r.id_operacion IN (3,5,6,8)
          AND r.fec_crea_remesa >= :from_date AND r.fec_crea_remesa < :to_date
        LIMIT 5""",
}
EXTRA = (
    ("record_type", "Tipo fila"),
    ("origin_source_key", "Clave real remesa diciembre"),
    ("payment_source_key", "Clave real pago enero"),
    ("origin_currency_raw", "Moneda diciembre ID raw"),
    ("payment_currency_raw", "Moneda enero ID raw"),
    ("date_flag", "Alerta horario"),
    ("money_flag", "Alerta importes"),
    ("origin_utc", "Fecha origen UTC"),
    ("payment_utc", "Fecha pago UTC"),
    ("elapsed_hours", "Horas transcurridas reales"),
    ("origin_month", "Mes remesa"),
    ("payment_month", "Mes pago"),
)
ZONES = {"BOLIVIA": "America/La_Paz", "CHILE": "America/Santiago"}


def datetime_in_utc(source, value):
    if value is None:
        return None
    if source not in ZONES:
        raise ValueError("Unknown source timezone")
    # Source timestamps are assumed to be country-local naive DATETIME.
    if value.tzinfo is not None:
        raise ValueError("Expected naive country-local source datetime")
    local = value.replace(tzinfo=ZoneInfo(ZONES[source]))
    return local.astimezone(timezone.utc)


def compare_time(origin_source, sent, payment_source, paid):
    if not sent or not paid:
        return "TIME_NOT_COMPARABLE", "", "", ""
    a = datetime_in_utc(origin_source, sent)
    b = datetime_in_utc(payment_source, paid)
    elapsed = (b-a).total_seconds()/3600
    flag = ("PAYMENT_BEFORE_ORIGIN_AFTER_TZ" if elapsed < 0 else
            "DELAY_OVER_30_DAYS_REVIEW" if elapsed > 30*24 else
            "TIME_ORDERED_AFTER_TZ")
    return flag, a.isoformat(), b.isoformat(), f"{elapsed:.2f}"


def classify_candidate(origin_source, payment, candidates):
    """Only one compatible December source remittance can be provisional."""
    accepted = [
        candidate for candidate in candidates
        if payment.operation_type in (
            allowed_destination_payment_types(
                origin_source, payment.source, candidate.operation_type) or ()
        )
    ]
    if len(candidates) >= 5:
        return "MANUAL_REVIEW_CANDIDATE_LIMIT", None
    if not candidates:
        return "PAYMENT_ORIGIN_NOT_FOUND_DECEMBER", None
    if len(accepted) != 1 or len(candidates) != 1:
        return "MANUAL_REVIEW_ORIGIN_TYPE_OR_DUPLICATE", None
    candidate = accepted[0]
    if candidate.status != "PAID":
        return "MANUAL_REVIEW_ORIGIN_STATUS", candidate
    flag, _, _, _ = compare_time(
        origin_source, candidate.occurred_at, payment.source, payment.occurred_at
    )
    if flag in ("PAYMENT_BEFORE_ORIGIN_AFTER_TZ", "TIME_NOT_COMPARABLE"):
        return "MANUAL_REVIEW_DATE", candidate
    if candidate.amount is None or payment.amount is None or not (
        candidate.currency and payment.currency
    ):
        return "MANUAL_REVIEW_INCOMPLETE_AMOUNT", candidate
    if candidate.currency == payment.currency and (
        Decimal(candidate.amount) != Decimal(payment.amount)
    ):
        return "MANUAL_REVIEW_AMOUNT_DIFFERENCE", candidate
    return "CROSS_MONTH_PROVISIONAL_PAIR", candidate


def make_report_row(payment, origin_source, candidates, original_key=""):
    category, candidate = classify_candidate(origin_source, payment, candidates)
    flag, utc_origin, utc_payment, elapsed = compare_time(
        origin_source, candidate.occurred_at if candidate else None,
        payment.source, payment.occurred_at
    )
    money_flag = (
        "NO_COMPARABLE_ORIGIN" if not candidate else
        "MONEY_DATA_INCOMPLETE" if (
            candidate.amount is None or payment.amount is None
            or not candidate.currency or not payment.currency
        ) else
        "FX_REVIEW_DIFFERENT_CURRENCIES" if candidate.currency != payment.currency else
        "SAME_CURRENCY_EQUAL" if candidate.amount == payment.amount else
        "SAME_CURRENCY_DIFFERENCE_REVIEW"
    )
    reasons = {
        "CROSS_MONTH_PROVISIONAL_PAIR": "Código, tipo, estado y cronología compatibles; verificar titularidad y liquidación",
        "MANUAL_REVIEW_CANDIDATE_LIMIT": "La consulta alcanzó el límite de candidatos",
        "PAYMENT_ORIGIN_NOT_FOUND_DECEMBER": "No existe candidato en la ventana revisada",
        "MANUAL_REVIEW_ORIGIN_TYPE_OR_DUPLICATE": "Tipo incompatible o más de una remesa",
        "MANUAL_REVIEW_ORIGIN_STATUS": "Estado del origen no es PAID",
        "MANUAL_REVIEW_DATE": "Fecha real inconsistente después de normalizar zonas",
        "MANUAL_REVIEW_INCOMPLETE_AMOUNT": "Importe o moneda insuficientes",
        "MANUAL_REVIEW_AMOUNT_DIFFERENCE": "Diferencia aun con misma moneda",
    }
    reason = reasons[category]
    if money_flag == "FX_REVIEW_DIFFERENT_CURRENCIES":
        reason += "; diferencia de moneda sin equivalencia FX verificada"
    return dict(
        direction="BO_TO_CL" if origin_source=="BOLIVIA" else "CL_TO_BO",
        category=category,reason=reason,code=payment.code,
        origin_id="",origin_type=candidate.operation_type if candidate else "",
        origin_date=candidate.occurred_at.isoformat(sep=" ") if candidate and candidate.occurred_at else "",
        origin_status=candidate.status if candidate else "",
        origin_amount=str(candidate.amount) if candidate and candidate.amount is not None else "",
        origin_currency=candidate.currency or "" if candidate else "",
        destination_id=payment.source_record_id,
        destination_type=payment.operation_type,
        destination_date=payment.occurred_at.isoformat(sep=" ") if payment.occurred_at else "",
        destination_amount=str(payment.amount) if payment.amount is not None else "",
        destination_currency=payment.currency or "",
        difference=(
            str(candidate.amount-payment.amount)
            if candidate and candidate.currency and candidate.currency==payment.currency
            and candidate.amount is not None and payment.amount is not None else ""
        ),
        payment_candidates=len(candidates),unexpected_payment_types="",
        record_type="DEC2025_TO_JAN2026_PAYMENT",
        origin_source_key=candidate.source_id if candidate else "",
        payment_source_key=original_key,
        origin_currency_raw=(
            str(candidate.raw.get("currency_id"))
            if candidate and candidate.raw.get("currency_id") is not None else ""
        ),
        payment_currency_raw="",date_flag=flag,money_flag=money_flag,
        origin_utc=utc_origin,payment_utc=utc_payment,
        elapsed_hours=elapsed,origin_month="2025-12",payment_month="2026-01",
    )


def run(output):
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Pilot DB only")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Source ETL and mapping must remain disabled")
    destination=validate_export_path(output)
    csv_path=destination.with_suffix(".csv")
    if csv_path.is_symlink():
        raise ValueError("CSV path cannot be symlink")
    pilot=pilot_engine(settings)
    try:
        with pilot.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                rems=con.execute(select(
                    Remittance.source_record_id,Remittance.source,Remittance.code,
                    Remittance.operation_type,Remittance.status,Remittance.amount,
                    Remittance.currency,Remittance.occurred_at)).all()
                pays=con.execute(select(
                    Payment.source_record_id,Payment.source,Payment.code,
                    Payment.operation_type,Payment.amount,Payment.currency,
                    Payment.occurred_at)).all()
                meta=con.execute(select(SourceRecord.id,SourceRecord.source_id)).all()
            finally:
                con.rollback()
    finally:
        pilot.dispose()
    targets=missing_january_payment_codes(rems,pays)
    paired={r["destination_id"] for r in detail_rows(rems,pays,date(2026,1,31))
            if r["category"]=="PROVISIONAL_CODE_PAIR" and r["destination_id"]!=""}
    ids=dict(meta)
    to_check=defaultdict(list)
    for p in pays:
        if (p.source_record_id in paired or p.occurred_at is None or
                not(datetime(2026,1,1)<=p.occurred_at<datetime(2026,2,1))):
            continue
        country="BOLIVIA" if p.source=="CHILE" else "CHILE"
        if p.code in targets[country]:
            to_check[country].append(p)
    if sum(len(v) for v in to_check.values())>25:
        raise RuntimeError("Too many payment rows for bounded audit")
    rows=[]
    for country,payments in to_check.items():
        sql=DECEMBER_SQL[country]
        validate_read_query(sql)
        engine=connect_source(settings,country)
        try:
            for pay in payments:
                params=dict(code=pay.code,from_date=datetime(2025,12,1),
                            to_date=datetime(2026,1,1))
                with read_only_transaction(engine) as con:
                    plan=con.execute(text("EXPLAIN "+sql),params).mappings().all()
                    source_plan_guard(plan)
                    raw=con.execute(text(sql),params).mappings().all()
                candidates=[normalize(country,"remittance",dict(item)) for item in raw]
                rows.append(make_report_row(pay,country,candidates,ids.get(pay.source_record_id,"")))
        finally:
            engine.dispose()
    rows.sort(key=lambda r:(r["direction"],r["code"],str(r["destination_id"])))
    from scripts import pilot_operation_detail_2026 as detail
    original=detail.COLUMNS
    detail.COLUMNS=original+EXTRA
    try:
        html=html_report(rows,date(2026,1,31))
        html=html.replace(
            "Detalle de conciliación por operación",
            "Cruce dirigido diciembre 2025 → enero 2026"
        ).replace(
            "Desde 01/01/2026 hasta 31/01/2026",
            "Remesas de diciembre 2025 y pagos de enero 2026"
        ).replace("Remesas incluidas</span>","Pagos revisados</span>")
        # First KPI is DATA.length; remaining labels are expressly provisional.
        html=html.replace("Pares provisionales</span>","Pares provisionales diciembre-enero</span>")
        html=html.replace("Sin pago en registros</span>","Revisión manual</span>")
        html=html.replace("Anuladas / devueltas</span>","Sin remesa candidata</span>")
        html=html.replace(
            "DATA.filter(r=>r.category==='PROVISIONAL_CODE_PAIR').length",
            "DATA.filter(r=>r.category==='CROSS_MONTH_PROVISIONAL_PAIR').length"
        ).replace(
            "DATA.filter(r=>r.category==='NO_PAYMENT_IN_SAMPLE').length",
            "DATA.filter(r=>r.category.startsWith('MANUAL_REVIEW')).length"
        ).replace(
            "DATA.filter(r=>r.category==='CLOSED_IN_SAMPLE').length",
            "DATA.filter(r=>r.category==='PAYMENT_ORIGIN_NOT_FOUND_DECEMBER').length"
        )
        destination.write_text(html,encoding="utf-8")
        export_csv(csv_path,rows)
    finally:
        detail.COLUMNS=original
    counts=Counter(r["category"] for r in rows)
    print(f"december_detail=True checked={len(rows)} source_read_only=True "
          "pilot_writes=False certified=False")
    for key,count in sorted(counts.items()):
        print(f"{key}={count}")
    print(f"files_created={destination.name},{csv_path.name} private_export=True")
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    run(parser.parse_args().output)


if __name__=="__main__":
    main()
