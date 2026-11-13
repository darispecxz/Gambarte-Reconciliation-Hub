from decimal import Decimal
from scripts.pilot_january_integrity_offline_2026 import CLP_LIMIT
def test_clp_tolerance():
    assert CLP_LIMIT == Decimal("10")
    assert abs(Decimal("-10"))<=CLP_LIMIT
    assert abs(Decimal("10.001"))>CLP_LIMIT
