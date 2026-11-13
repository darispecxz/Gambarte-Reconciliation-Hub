"""Synthetic operation detail tests; never use real client data."""
import csv
from datetime import date,datetime
from decimal import Decimal
from types import SimpleNamespace

from scripts.pilot_operation_detail_2026 import detail_rows,export_csv,html_report,safe_csv_value


def r(source,code,typ,status="PAID",amount="100",currency="BOB",id=1,month=1):
    return SimpleNamespace(source=source,code=code,operation_type=typ,
                           status=status,amount=Decimal(amount),currency=currency,
                           source_record_id=id,occurred_at=datetime(2026,month,10))


def test_detail_classification_matches_existing_summary_counts():
    rems=[r("BOLIVIA","A",16,id=101),
          r("BOLIVIA","B",16,id=102),
          r("CHILE","C",3,"CANCELLED",id=103)]
    pays=[r("CHILE","A",3,id=201)]
    rows=detail_rows(rems,pays,date(2026,1,31))
    by_code={x["code"]:x for x in rows}
    assert by_code["A"]["category"]=="PROVISIONAL_CODE_PAIR"
    assert by_code["A"]["destination_id"]==201
    assert by_code["A"]["difference"]=="0"
    assert by_code["B"]["category"]=="NO_PAYMENT_IN_SAMPLE"
    assert by_code["C"]["category"]=="CLOSED_IN_SAMPLE"


def test_different_currencies_do_not_compute_difference():
    rows=detail_rows([r("BOLIVIA","A",16,"PAID","500","BOB")],
                     [r("CHILE","A",3,"RECORDED","100","USD")],date(2026,1,31))
    assert rows[0]["difference"]==""
    assert "monedas distintas" in rows[0]["reason"]


def test_ambiguous_does_not_assign_payment():
    rems=[r("BOLIVIA","A",16,id=1),r("BOLIVIA","A",16,id=2)]
    pay=[r("CHILE","A",3,id=3)]
    rows=detail_rows(rems,pay,date(2026,1,31))
    assert len(rows)==2
    assert all(x["category"]=="MANUAL_REVIEW_AMBIGUOUS_CODE" for x in rows)
    assert all(x["destination_id"]=="" for x in rows)


def test_csv_injection_guard(tmp_path):
    assert safe_csv_value("=2+2").startswith("'")
    assert safe_csv_value("  @SUM(A1)").startswith("'")
    assert safe_csv_value("-123").startswith("'")
    rows=detail_rows([r("BOLIVIA","=HYPERLINK(1)",16)],[],date(2026,1,31))
    dest=tmp_path/"detail.csv"
    export_csv(dest,rows)
    with dest.open(encoding="utf-8-sig",newline="") as f:
        parsed=list(csv.reader(f))
    assert parsed[1][3].startswith("'=")


def test_html_escapes_script_and_is_provisional():
    rows=detail_rows([r("BOLIVIA","</script><script>alert(1)",16)],
                     [],date(2026,1,31))
    html=html_report(rows,date(2026,1,31))
    assert "</script><script>alert(1)" not in html
    assert "NO CERTIFICADO" in html
    assert "Exportar filtrado" in html


def test_future_payments_in_pilot_are_eligible_but_unproven():
    rows=detail_rows([r("BOLIVIA","A",16,id=1)],
                     [r("CHILE","A",3,id=2,month=2)],date(2026,1,31))
    assert rows[0]["category"]=="PROVISIONAL_CODE_PAIR"
