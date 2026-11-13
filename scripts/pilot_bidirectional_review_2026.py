"""Bidirectional private audit of month-scoped remittances and payments.

Only uses isolated pilot; source tables are never contacted. A payment with
no matching pilot remittance is NOT a confirmed orphan.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

from app.core.config import get_settings
from app.domain.operation_types import allowed_destination_payment_types
from app.infrastructure.models import Payment, Remittance, SourceRecord
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker
from scripts.pilot_operation_detail_2026 import (
    detail_rows, export_csv, html_report, validate_export_path,
)


def temporal_flag(rem, payment):
    if not rem or not payment or not rem.occurred_at or not payment.occurred_at:
        return "TIME_NOT_COMPARABLE"
    duration = (payment.occurred_at-rem.occurred_at).total_seconds()
    if duration < 0:
        return "PAYMENT_BEFORE_ORIGIN_TIMEZONE_NOT_VALIDATED"
    if duration > 30*86400:
        return "DELAY_OVER_30_DAYS_REVIEW"
    return "TIME_ORDERED_TIMEZONE_NOT_VALIDATED"


def build_rows(remittances, payments, records, through):
    """Keep remittance cases, and add January payments without a unique provisional pair."""
    rows = detail_rows(remittances, payments, through)
    record_map = {item.id: item for item in records}
    remap = {item.source_record_id: item for item in remittances}
    pmap = {item.source_record_id: item for item in payments}
    by_code = defaultdict(list)
    for rem in remittances:
        by_code[(rem.source,rem.code)].append(rem)
    paired = {item["destination_id"] for item in rows
              if item["category"] == "PROVISIONAL_CODE_PAIR" and item["destination_id"] != ""}

    def evidence(record_id):
        value = record_map.get(record_id)
        if value is None:
            return "", ""
        payload = value.payload if isinstance(value.payload,dict) else {}
        currency = payload.get("currency_id")
        return value.source_id, str(currency) if currency is not None else ""

    for row in rows:
        row["record_type"] = "REMITTANCE"
        row["origin_source_key"], row["origin_currency_raw"] = evidence(row["origin_id"])
        row["payment_source_key"], row["payment_currency_raw"] = (
            evidence(row["destination_id"]) if row["destination_id"] != "" else ("","")
        )
        rem = remap.get(row["origin_id"])
        pay = pmap.get(row["destination_id"]) if row["destination_id"] != "" else None
        row["date_flag"] = temporal_flag(rem,pay)
        row["money_flag"] = (
            "NO_PAIRED_PAYMENT" if pay is None else
            "MONEY_DATA_INCOMPLETE" if (not rem or rem.amount is None or pay.amount is None
                                        or not rem.currency or not pay.currency) else
            "CURRENCIES_DIFFER_FX_REVIEW" if rem.currency != pay.currency else
            "SAME_CURRENCY_EQUAL" if rem.amount == pay.amount else
            "SAME_CURRENCY_AMOUNT_DIFFERENCE"
        )

    for pay in payments:
        if (pay.source_record_id in paired or not pay.occurred_at or
                not(date(2026,1,1)<=pay.occurred_at.date()<=through)):
            continue
        origin_country = "BOLIVIA" if pay.source == "CHILE" else "CHILE"
        direction = "BO_TO_CL" if pay.source == "CHILE" else "CL_TO_BO"
        origins = by_code[(origin_country,pay.code)]
        compatible = [
            rem for rem in origins
            if pay.operation_type in (
                allowed_destination_payment_types(
                    rem.source,pay.source,rem.operation_type) or ()
            )
        ]
        if not origins:
            category = "PAYMENT_ORIGIN_NOT_IN_PILOT"
            reason = "No se encontró remesa en los datos disponibles; no implica pago huérfano confirmado"
        elif not compatible:
            category = "PAYMENT_TYPE_REVIEW"
            reason = "Hay remesa por código, pero el tipo de pago no coincide con el contrato provisional"
        elif len(compatible) != 1:
            category = "PAYMENT_AMBIGUOUS_ORIGIN"
            reason = "Más de una remesa compatible; revisar identidad y modalidad"
        elif not compatible[0].occurred_at or not (
            date(2026,1,1)<=compatible[0].occurred_at.date()<=through
        ):
            category = "PAYMENT_ORIGIN_OUTSIDE_PERIOD"
            reason = "Remesa compatible fuera del período; puede corresponder a otro mes o año"
        else:
            category = "PAYMENT_ORIGIN_IN_PERIOD_REVIEW"
            reason = "Remesa compatible, pero no se obtuvo par provisional único"
        rem = compatible[0] if len(compatible)==1 else None
        origin_id = rem.source_record_id if rem else ""
        origin_key, origin_cur_raw = evidence(origin_id)
        pay_key,pay_cur_raw = evidence(pay.source_record_id)
        rows.append(dict(
            direction=direction,category=category,reason=reason,code=pay.code,
            origin_id=origin_id, origin_type=rem.operation_type if rem else "",
            origin_date=rem.occurred_at.isoformat(sep=" ") if rem and rem.occurred_at else "",
            origin_status=rem.status if rem else "",
            origin_amount=str(rem.amount) if rem and rem.amount is not None else "",
            origin_currency=(rem.currency or "") if rem else "",
            destination_id=pay.source_record_id,destination_type=pay.operation_type,
            destination_date=pay.occurred_at.isoformat(sep=" "),
            destination_amount=str(pay.amount) if pay.amount is not None else "",
            destination_currency=pay.currency or "",difference="",
            payment_candidates=1,unexpected_payment_types="",
            record_type="UNPAIRED_PAYMENT",origin_source_key=origin_key,
            origin_currency_raw=origin_cur_raw,payment_source_key=pay_key,
            payment_currency_raw=pay_cur_raw,date_flag=temporal_flag(rem,pay),
            money_flag="NOT_MONETARILY_RECONCILED",
        ))
    rows.sort(key=lambda row:(row["direction"],str(row["code"]),
                              row["record_type"],str(row["origin_id"]),
                              str(row["destination_id"])))
    return rows


def run(through, output):
    if through.year!=2026 or through>date.today():
        raise ValueError("Use a nonfuture date in 2026")
    s=get_settings()
    if ((s.db_host,s.db_name)!=(PILOT_HOST,PILOT_DB)
            or s.enable_source_etl or s.source_mapping_verified):
        raise RuntimeError("Isolated pilot with source ETL disabled required")
    destination=validate_export_path(output)
    csv_path=destination.with_suffix(".csv")
    if csv_path.is_symlink():
        raise ValueError("CSV output must not be a symlink")
    db=create_engine(URL.create("mysql+pymysql",host=s.db_host,port=s.db_port,
        username=s.db_user,password=s.db_password,database=s.db_name,
        query={"charset":"utf8mb4"}),
        connect_args={"connect_timeout":10,"read_timeout":30})
    try:
        with db.connect() as con:
            try:
                con.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(con)
                rems=con.execute(select(
                    Remittance.source_record_id,Remittance.source,Remittance.code,
                    Remittance.operation_type,Remittance.status,Remittance.amount,
                    Remittance.currency,Remittance.occurred_at,
                )).all()
                pays=con.execute(select(
                    Payment.source_record_id,Payment.source,Payment.code,
                    Payment.operation_type,Payment.amount,Payment.currency,
                    Payment.occurred_at,
                )).all()
                records=con.execute(select(
                    SourceRecord.id,SourceRecord.source_id,SourceRecord.payload,
                )).all()
                rows=build_rows(rems,pays,records,through)
            finally:
                con.rollback()
    finally:
        db.dispose()
    # Extend table headers for the new evidence columns in both export formats.
    from scripts import pilot_operation_detail_2026 as detail
    base=detail.COLUMNS
    extra=(
        ("record_type","Tipo fila"),("origin_source_key","Clave original remesa"),
        ("payment_source_key","Clave original pago"),
        ("origin_currency_raw","ID moneda remesa (raw)"),
        ("payment_currency_raw","ID moneda pago (raw)"),
        ("date_flag","Alerta fechas"),("money_flag","Alerta monetaria"),
    )
    detail.COLUMNS = base+extra
    try:
        html=html_report(rows,through)
        # The original KPI counts remittances, not all newly added payment rows.
        html=html.replace("Remesas incluidas</span>","Filas revisadas (remesas + pagos)</span>")
        html=html.replace("Anuladas / devueltas</span>","Pagos sin par provisional</span>")
        html=html.replace("DATA.filter(r=>r.category==='CLOSED_IN_SAMPLE').length",
                          "DATA.filter(r=>r.record_type==='UNPAIRED_PAYMENT').length")
        html=html.replace("Todos los campos", "Todos los campos")
        destination.write_text(html,encoding="utf-8")
        export_csv(csv_path,rows)
    finally:
        detail.COLUMNS=base
    categories=Counter(r["category"] for r in rows)
    print(f"bidirectional_report=True cutoff={through} "
          f"remittance_rows={sum(r['record_type']=='REMITTANCE' for r in rows)} "
          f"unpaired_payment_rows={sum(r['record_type']=='UNPAIRED_PAYMENT' for r in rows)} "
          f"source_read_only=True certified=False")
    for category,count in sorted(categories.items()):
        print(f"{category}={count}")
    print(f"files_created={destination.name},{csv_path.name}")
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through",required=True,type=date.fromisoformat)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    run(args.through,args.output)


if __name__=="__main__":
    main()
