"""Synthetic tests for bounded December targeted lookup."""
from datetime import datetime
from types import SimpleNamespace
from scripts.pilot_december_lookup_2025 import missing_january_payment_codes


def rem(source,code,operation_type,id):
    return SimpleNamespace(source_record_id=id,source=source,code=code,
       operation_type=operation_type,status="PAID",amount=1,currency="USD",
       occurred_at=datetime(2026,1,10))


def pay(source,code,operation_type,id,month=1):
    return SimpleNamespace(source_record_id=id,source=source,code=code,
       operation_type=operation_type,amount=1,currency="USD",
       occurred_at=datetime(2026,month,11))


def test_targets_only_unpaired_january_payments():
    targets=missing_january_payment_codes(
        [rem("BOLIVIA","paired",16,1)],
        [pay("CHILE","paired",3,2), pay("CHILE","older",3,3),
         pay("BOLIVIA","other",4,4),pay("CHILE","feb",3,5,2)])
    assert targets["BOLIVIA"]=={"older"}
    assert targets["CHILE"]=={"other"}
