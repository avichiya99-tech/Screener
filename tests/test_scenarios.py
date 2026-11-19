import pytest

from conftest import make_bank_bundle, make_bundle
from valuation_engine import (
    compute_scenarios,
    compute_valuation,
    confidence,
    solve_reverse_valuation,
    verdict,
)

MACRO = {"rf": 0.07, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25}


@pytest.mark.parametrize("make", [make_bundle, make_bank_bundle])
def test_scenarios_ordered(make):
    s = compute_scenarios(make(), MACRO)
    assert s["bear"] < s["base"] < s["bull"]
    assert s["base"] == pytest.approx(s["base_result"]["intrinsic_price"])


def test_scenarios_none_when_invalid():
    s = compute_scenarios(make_bundle(drop=("currentPrice",)), MACRO)
    assert (s["bear"], s["base"], s["bull"]) == (None, None, None)


def test_verdict_bands():
    sc = {"bear": 80.0, "base": 100.0, "bull": 130.0}
    assert verdict(70.0, sc, True) == "Cheap"
    assert verdict(140.0, sc, True) == "Expensive"
    assert verdict(100.0, sc, True) == "Fair"
    assert verdict(70.0, sc, False) == "Not rated"
    assert verdict(70.0, {"bear": None, "base": 100.0, "bull": 130.0}, True) == "Not rated"


def test_negative_model_value_not_rated_and_low():
    # Debt far above what the cash flows can support -> negative equity value per share.
    r = compute_valuation(make_bundle(debt=50000.0))
    assert r["intrinsic_price"] < 0
    assert r["meaningful"] is False
    assert "negative" in r["not_meaningful_reason"].lower()
    assert confidence(r["inputs"], r["meaningful"]) == "Low"
    s = compute_scenarios(make_bundle(debt=50000.0), MACRO)
    assert verdict(100.0, s, r["meaningful"]) == "Not rated"


def test_confidence_low_with_two_defaults():
    r = compute_valuation(make_bundle(drop=("beta", "Tax Provision")))
    assert confidence(r["inputs"], r["meaningful"]) == "Low"


def test_confidence_medium_with_one_default():
    r = compute_valuation(make_bundle(drop=("beta",)))
    assert confidence(r["inputs"], r["meaningful"]) == "Medium"


def test_confidence_high_clean_bundle():
    r = compute_valuation(make_bundle())
    assert confidence(r["inputs"], r["meaningful"]) == "High"


def test_confidence_low_when_not_meaningful():
    r = compute_valuation(make_bundle(sector="Energy"))
    assert confidence(r["inputs"], r["meaningful"]) == "Low"


@pytest.mark.parametrize("make", [make_bundle, make_bank_bundle])
def test_reverse_round_trip(make):
    base = compute_valuation(make())
    price = round(base["intrinsic_price"] * 0.8, 2)
    b = make(price=price)
    disc = compute_valuation(b)["discount_rate"]
    rev = solve_reverse_valuation(b, disc, terminal_g=0.05)
    assert rev["status"] == "ok"
    r = compute_valuation(b, driver_override=rev["implied"] / 100, discount_override=disc, terminal_g=0.05)
    assert r["intrinsic_price"] == pytest.approx(price, rel=0.005)


def test_reverse_reports_above_range():
    b = make_bundle(price=1e6)
    rev = solve_reverse_valuation(b, compute_valuation(b)["discount_rate"], terminal_g=0.05)
    assert rev == {"implied": None, "status": "above_range"}


def test_reverse_reports_below_range():
    b = make_bundle(price=0.01)
    rev = solve_reverse_valuation(b, compute_valuation(b)["discount_rate"], terminal_g=0.05)
    assert rev == {"implied": None, "status": "below_range"}


def test_reverse_invalid_bundle():
    b = make_bundle(drop=("currentPrice",))
    assert solve_reverse_valuation(b, 0.11, terminal_g=0.05)["status"] == "invalid"
