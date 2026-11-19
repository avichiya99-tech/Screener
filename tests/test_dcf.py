import pandas as pd

from conftest import make_bundle
from valuation_engine import compute_valuation, historical_growth


def test_growth_median_ignores_one_bad_year():
    b = make_bundle(revenue=[1210, 1100, 1000, 500], ebit=[180, 165, 150, 75])
    g, years, status = historical_growth(b["income"], ["Total Revenue"])
    assert abs(g - 0.10) <= 0.005
    assert years == 4
    assert status == "reported"


def test_growth_status_default_without_history():
    g, years, status = historical_growth(pd.DataFrame(), ["Total Revenue"], default=0.08)
    assert (g, years, status) == (0.08, 0, "default")


def test_projection_has_10_years_and_fades_to_terminal():
    r = compute_valuation(make_bundle(), terminal_g=0.05)
    proj = r["projection_df"]
    assert len(proj) == 10
    rev = proj["Revenue"].tolist()
    assert abs(rev[9] / rev[8] - 1 - 0.05) < 1e-9
    assert abs(rev[4] / rev[3] - 1 - r["driver"]) < 1e-9


def test_revenue_growth_provenance_recorded():
    r = compute_valuation(make_bundle())
    assert r["inputs"]["revenue_growth"]["status"] == "reported"


def test_clean_company_is_meaningful():
    r = compute_valuation(make_bundle())
    assert r["meaningful"] is True and r["not_meaningful_reason"] is None


def test_loss_maker_not_meaningful():
    r = compute_valuation(make_bundle(ebit=[-20, 10, 30, 40]))
    assert r["meaningful"] is False
    assert "Loss-making" in r["not_meaningful_reason"]


def test_short_history_not_meaningful():
    r = compute_valuation(make_bundle(revenue=[1100, 1000], ebit=[165, 150], da=[38, 36], capex=[55, 50]))
    assert r["meaningful"] is False
    assert "3 years" in r["not_meaningful_reason"]


def test_cyclical_not_meaningful():
    # volatile margins in a commodity sector (stable ones are rated on normalized margins)
    r = compute_valuation(make_bundle(sector="Energy", ebit=(300, 60, 250, 20)))
    assert r["meaningful"] is False
    assert "Cyclical" in r["not_meaningful_reason"]
