from decimal import Decimal
import pytest
from app.domain.reconciliation import Remittance, Payment, decimal_amount, reconcile
from app.integrations.source import map_status
from app.infrastructure.ingestion import safe

def test_money_exact():
    assert decimal_amount("0.1")+decimal_amount("0.2")==Decimal("0.3")
    with pytest.raises(TypeError):
        decimal_amount(0.1)

def test_missing_paid_payment():
    assert reconcile(Remittance("A","PAID",Decimal("100"),"USD"),[])[0].category=="PAID_WITHOUT_PAYMENT"

def test_pending_not_missing():
    assert reconcile(Remittance("A","PENDING",Decimal("100"),"USD"),[])==[]

def test_duplicate_payment():
    p=Payment("A",Decimal("100"),"USD")
    assert reconcile(Remittance("A","PAID",Decimal("100"),"USD"),[p,p])[0].category=="MULTIPLE_PAYMENTS"

def test_mismatch_in_matching_currency():
    p=Payment("A",Decimal("99"),"USD")
    assert reconcile(Remittance("A","PAID",Decimal("100"),"USD"),[p])[0].category=="AMOUNT_MISMATCH"

def test_no_mismatch_without_conversion_rule():
    p=Payment("A",Decimal("700"),"BOB")
    assert reconcile(Remittance("A","PAID",Decimal("100"),"USD"),[p])==[]

def test_chile_status_and_serialization():
    assert map_status("CHILE",7)=="PROCESSING"
    assert safe({"money":Decimal("10.50")})=={"money":"10.50"}
