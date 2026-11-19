from valuation_engine import compute_valuation
from conftest import make_bundle


def test_current_engine_values_fixture():
    r = compute_valuation(make_bundle())
    assert r["valid"] is True
    assert r["intrinsic_price"] > 0
