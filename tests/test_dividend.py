import pandas as pd

from conftest import make_bank_bundle
from valuation_engine import build_historical_eps_div_df, compute_dividend_quality, compute_valuation


def test_fin_dividend_no_double_count():
    # DPS growing 10%/yr for 5 years -> growth component 10; balance-sheet component must be neutral 6.
    dates = pd.to_datetime([f"{y}-07-15" for y in range(2022, 2027)])
    divs = pd.Series([2.0, 2.2, 2.42, 2.662, 2.9282], index=dates)
    b = make_bank_bundle(dividends=divs)
    dq = compute_dividend_quality(b, compute_valuation(b))
    # consistency 30 + coverage 28 + payout 20 + growth 10 + balance sheet 6
    assert dq["score"] == 94


def test_dividends_grouped_by_fiscal_year_and_partial_year_dropped():
    # Indian fiscal year ends March (income columns are dated 31 March).
    dates = pd.to_datetime(["2023-08-01", "2024-07-15", "2025-01-10", "2025-07-20", "2026-08-01"])
    divs = pd.Series([5.0, 3.0, 3.0, 7.0, 2.0], index=dates)
    hist = build_historical_eps_div_df(make_bank_bundle(dividends=divs), today=pd.Timestamp("2026-11-20"))
    dps = dict(zip(hist["Year"], hist["Annual DPS"]))
    assert dps["2024"] == 5.0 and dps["2025"] == 6.0 and dps["2026"] == 7.0
    assert "2027" not in dps  # FY2027 (Apr 2026 - Mar 2027) is not finished yet


def test_partial_year_is_not_a_dividend_cut():
    dates = pd.to_datetime(["2022-07-15", "2023-07-15", "2024-07-15", "2025-07-15", "2026-07-15"])
    divs = pd.Series([10.0, 11.0, 12.0, 13.0, 1.0], index=dates)  # FY2027 has only a small interim so far
    b = make_bank_bundle(dividends=divs)
    dq = compute_dividend_quality(b, compute_valuation(b))
    # FY2023-26 = 10, 11, 12, 13: consistency 30 + coverage 28 + payout 20 + growth 10 + balance sheet 6.
    # Counting the unfinished year as a "cut" would score 74.
    assert dq["score"] == 94
