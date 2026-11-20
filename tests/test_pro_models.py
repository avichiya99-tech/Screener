"""Professional-grade bank model (3-stage excess return) and data-driven cyclical handling."""
import numpy as np
import pytest

from conftest import make_bank_bundle, make_bundle
from valuation_engine import (
    CYCLICAL_GROWTH_CAP,
    MAX_TERMINAL_SPREAD,
    TERMINAL_SPREAD_SHARE,
    compute_valuation,
    simulate_values,
)

KE = 0.07 + 1.0 * 0.055  # beta 1.0 in the fixtures


# ---------------------------------------------------------------- banks
def test_bank_stable_roe_keeps_half_the_spread():
    r = compute_valuation(make_bank_bundle(roe=0.16))
    assert r["terminal_method"] == "stable_roe"
    assert r["stable_roe"] == pytest.approx(KE + TERMINAL_SPREAD_SHARE * (0.16 - KE))


def test_bank_stable_spread_is_capped():
    r = compute_valuation(make_bank_bundle(roe=0.30))
    assert r["stable_roe"] == pytest.approx(KE + MAX_TERMINAL_SPREAD)


def test_bank_projection_10_years_fading_to_stable_roe():
    r = compute_valuation(make_bank_bundle(roe=0.18))
    proj = r["projection_df"]
    assert len(proj) == 10
    assert list(proj["ROE"][:5]) == pytest.approx([0.18] * 5)
    assert proj["ROE"].iloc[-1] == pytest.approx(r["stable_roe"])
    assert all(np.diff(proj["ROE"]) <= 1e-12)  # never rises


def test_bank_terminal_is_gordon_on_stable_spread():
    r = compute_valuation(make_bank_bundle(roe=0.18), terminal_g=0.05)
    end_bv = r["projection_df"]["End BVPS"].iloc[-1]
    expected_tv = end_bv * (r["stable_roe"] - r["discount_rate"]) / (r["discount_rate"] - 0.05)
    assert r["tv_er"] == pytest.approx(expected_tv)


def test_bank_value_between_book_and_no_fade_ceiling(monkeypatch):
    """A good bank is worth more than book but less than if its ROE lasted forever."""
    import valuation_engine as ve
    b = make_bank_bundle(roe=0.18, book_value=200.0)
    r = compute_valuation(b, terminal_g=0.05)
    monkeypatch.setattr(ve, "TERMINAL_SPREAD_SHARE", 1.0)
    monkeypatch.setattr(ve, "MAX_TERMINAL_SPREAD", 1.0)
    ceiling = compute_valuation(b, terminal_g=0.05)["intrinsic_price"]  # ROE never fades
    assert 200.0 < r["intrinsic_price"] < ceiling


def test_bank_roe_below_ke_valued_below_book():
    r = compute_valuation(make_bank_bundle(roe=0.10))
    assert r["intrinsic_price"] < r["bvps"]


def test_bank_monte_carlo_matches_engine():
    val = compute_valuation(make_bank_bundle(roe=0.19))
    sims = simulate_values(val, terminal_g=0.05, n=10, seed=3, noise=0.0)
    assert np.allclose(sims, val["intrinsic_price"], rtol=1e-9)


# ---------------------------------------------------------------- cyclicals
def test_stable_margin_cyclical_sector_is_rated_on_normalized_margin():
    # Asian Paints-like: "Basic Materials" label, but steady margins
    r = compute_valuation(make_bundle(sector="Basic Materials",
                                      revenue=(1200, 1100, 1000, 900), ebit=(204, 176, 170, 144)))
    assert r["meaningful"] is True
    assert r["margin_method"] == "normalized"
    yearly = [204 / 1200, 176 / 1100, 170 / 1000, 144 / 900]
    assert r["ebit_margin"] == pytest.approx(np.mean(yearly))


def test_volatile_cyclical_not_rated():
    r = compute_valuation(make_bundle(sector="Energy",
                                      revenue=(1200, 1100, 1000, 900), ebit=(300, 60, 250, 20)))
    assert r["meaningful"] is False
    assert "Cyclical" in r["not_meaningful_reason"]


def test_cyclical_with_loss_year_not_rated():
    r = compute_valuation(make_bundle(sector="Basic Materials",
                                      revenue=(1200, 1100, 1000, 900), ebit=(180, 165, -10, 135)))
    assert r["meaningful"] is False
    assert "Cyclical" in r["not_meaningful_reason"]


def test_cyclical_boom_growth_is_not_extrapolated():
    # NMDC-like: iron-ore upcycle lifts revenue ~20%/yr for 3 years. That is price, not a
    # growth trend, so the model must not carry it forward for 5 years.
    r = compute_valuation(make_bundle(sector="Basic Materials",
                                      revenue=(1730, 1440, 1200, 1000), ebit=(660, 550, 455, 380)))
    assert r["hist_driver"] == pytest.approx(0.2, abs=0.01)  # history still shown as it was
    assert r["driver"] == pytest.approx(CYCLICAL_GROWTH_CAP)
    assert r["inputs"]["revenue_growth"] == {"value": CYCLICAL_GROWTH_CAP, "status": "estimated"}


def test_non_cyclical_growth_is_not_capped_at_cyclical_cap():
    r = compute_valuation(make_bundle(revenue=(1730, 1440, 1200, 1000), ebit=(260, 216, 180, 150)))
    assert r["driver"] == pytest.approx(0.2, abs=0.01)


def test_non_cyclical_uses_latest_margin():
    r = compute_valuation(make_bundle(revenue=(1200, 1100, 1000, 900), ebit=(240, 165, 150, 135)))
    assert r["margin_method"] == "latest"
    assert r["ebit_margin"] == pytest.approx(240 / 1200)
