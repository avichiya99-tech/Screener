import pandas as pd

from conftest import make_bank_bundle
from valuation_engine import compute_dividend_quality, compute_valuation


def test_fin_dividend_no_double_count():
    # DPS growing 10%/yr for 5 years -> growth component 10; balance-sheet component must be neutral 6.
    dates = pd.to_datetime([f"{y}-07-15" for y in range(2022, 2027)])
    divs = pd.Series([2.0, 2.2, 2.42, 2.662, 2.9282], index=dates)
    b = make_bank_bundle(dividends=divs)
    dq = compute_dividend_quality(b, compute_valuation(b))
    # consistency 30 + coverage 28 + payout 20 + growth 10 + balance sheet 6
    assert dq["score"] == 94
