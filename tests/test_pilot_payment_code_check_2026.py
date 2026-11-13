"""Synthetic tests for bounded Bolivia payment duplicate candidate search."""
from decimal import Decimal
from scripts.pilot_payment_code_check_2026 import QUERY,read_input,classify
from app.integrations.source import validate_read_query

def test_sql_select_indexed_and_bounded():
    validate_read_query(QUERY)
    assert "FORCE INDEX" in QUERY
    assert "codigo=:code AND id_operacion=:op" in QUERY
    assert "LIMIT 6" in QUERY

def test_one_row_vs_duplicate_vs_limit():
    row={"id_pago":12,"monto":"100"}
    assert classify([row],12,Decimal("100"))[0]=="ONE_PAYMENT_ROW_IN_INDEXED_CODE_TYPE_SCOPE"
    assert classify([row,{"id_pago":13,"monto":"100"}],12,Decimal("100"))[0]=="ADDITIONAL_PAYMENT_ROWS_REVIEW"
    assert classify([row]*6,12,Decimal("100"))[0]=="BOUNDED_RESULT_LIMIT_REVIEW"
    assert classify([{"id_pago":13,"monto":"100"}],12,Decimal("100"))[0]=="EXPECTED_PAYMENT_ABSENT_REVIEW"

def test_amount_changed():
    assert classify([{"id_pago":1,"monto":"99"}],1,Decimal("100"))[0]==(
        "EXPECTED_PAYMENT_AMOUNT_CHANGED_REVIEW")
