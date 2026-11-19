"""Official-source adapters: CCIL risk-free rate and NSE bhavcopy price check."""
import pytest

from pipeline.sources.ccil_rf import live_macro, parse_ccil_10y

CCIL_HTML = """
<table><tr><th>Date</th><th>Tenor Bucket</th><th>Security</th><th>YTM (%)</th></tr>
<tr><td align="left">2026-11-19 00:00:00.0</td><td align="left">4Y-5Y</td>
    <td align="left">6.53% GS 2031</td><td align="left">7.1409</td></tr>
<tr><td align="left">2026-11-19 00:00:00.0</td><td align="left">9Y-10Y</td>
    <td align="left">6.94% GS 2036</td><td align="left">7.2752</td></tr>
<tr><td align="left">2026-11-19 00:00:00.0</td><td align="left">10Y</td>
    <td align="left">7.82% GUJARAT SGS 2036</td><td align="left">7.82</td></tr>
</table>
"""

MACRO = {"rf": 0.07, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}


def test_parse_picks_central_govt_10y_not_state_bond():
    assert parse_ccil_10y(CCIL_HTML) == (pytest.approx(0.072752), "2026-11-19", "6.94% GS 2036")


def test_parse_returns_none_when_table_missing():
    assert parse_ccil_10y("<html>maintenance</html>") is None


def test_live_macro_uses_ccil_when_available():
    macro, source = live_macro(MACRO, fetch=lambda: CCIL_HTML)
    assert macro["rf"] == pytest.approx(0.072752)
    assert macro["rf_as_of"] == "2026-11-19"
    assert "CCIL" in source
    assert MACRO["rf"] == 0.07  # config dict not mutated


def test_live_macro_falls_back_to_config_on_error():
    def boom():
        raise OSError("down")
    macro, source = live_macro(MACRO, fetch=boom)
    assert macro["rf"] == 0.07
    assert "config/macro.json" in source


def test_live_macro_rejects_implausible_yield():
    bad = CCIL_HTML.replace("7.2752", "72.752")
    macro, source = live_macro(MACRO, fetch=lambda: bad)
    assert macro["rf"] == 0.07


# ---------------------------------------------------------------- NSE bhavcopy + data checks
import io
import zipfile
from datetime import date

from conftest import make_bundle
from pipeline.build import build_record
from pipeline.sources.nse_bhavcopy import latest_closes, parse_bhavcopy

BHAV_CSV = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,ClsPric\n"
    "2026-11-19,2026-11-19,CM,NSE,STK,1,INE021A01026,ASIANPAINT,EQ,2595.40\n"
    "2026-11-19,2026-11-19,CM,NSE,STK,2,IN0020200104,SGBJUN28,GB,13039.87\n"
    "2026-11-19,2026-11-19,CM,NSE,STK,3,INE000X00000,SMALLCO,BE,12.50\n"
)


def _zip(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bhav.csv", csv_text)
    return buf.getvalue()


def test_parse_bhavcopy_keeps_equity_series_only():
    closes = parse_bhavcopy(_zip(BHAV_CSV))
    assert closes == {"ASIANPAINT": {"close": 2595.40, "date": "2026-11-19"},
                      "SMALLCO": {"close": 12.50, "date": "2026-11-19"}}


def test_latest_closes_walks_back_over_holidays():
    seen = []

    def fetch(d):
        seen.append(d)
        return _zip(BHAV_CSV) if d == date(2026, 11, 19) else None  # 21st/20th: no file

    closes, day = latest_closes(date(2026, 11, 21), fetch=fetch)
    assert day == date(2026, 11, 19) and "ASIANPAINT" in closes
    assert seen == [date(2026, 11, 21), date(2026, 11, 20), date(2026, 11, 19)]


def test_latest_closes_gives_up_after_a_week():
    closes, day = latest_closes(date(2026, 11, 21), fetch=lambda d: None)
    assert closes == {} and day is None


def test_record_uses_official_close():
    rec = build_record("ABC.NS", make_bundle(price=100.0), MACRO, as_of="2026-11-19",
                       official_price={"close": 101.0, "date": "2026-11-19"})
    assert rec["price"] == 101.0
    assert "NSE" in rec["price_source"]
    assert rec["data_checks"] == []


def test_price_mismatch_flagged_and_low_confidence():
    rec = build_record("ABC.NS", make_bundle(price=100.0), MACRO, as_of="2026-11-19",
                       official_price={"close": 120.0, "date": "2026-11-19"})
    assert any("NSE close" in c for c in rec["data_checks"])
    assert rec["confidence"] == "Low"


def test_without_official_price_source_is_yfinance():
    rec = build_record("ABC.NS", make_bundle(), MACRO, as_of="2026-11-19")
    assert rec["price_source"].startswith("yfinance")


def test_share_count_mismatch_flagged():
    b = make_bundle(price=100.0)
    b["info"]["marketCap"] = 100.0 * b["info"]["sharesOutstanding"] * 2
    rec = build_record("ABC.NS", b, MACRO, as_of="2026-11-19")
    assert any("share count" in c.lower() for c in rec["data_checks"])
    assert rec["confidence"] == "Low"


def test_stale_statements_flagged():
    rec = build_record("ABC.NS", make_bundle(), MACRO, as_of="2028-01-15")  # results dated 2026-03-31
    assert any("older than 18 months" in c for c in rec["data_checks"])


# ---------------------------------------------------------------- beta vs NIFTY 50, currency
import numpy as np
import pandas as pd

from pipeline.build import RecordError
from pipeline.sources.beta import compute_betas, regression_beta


def _prices(returns):
    return pd.Series(100 * np.cumprod(1 + np.asarray(returns)))


def test_regression_beta_is_blume_adjusted():
    rng = np.random.default_rng(0)
    mkt = rng.normal(0.002, 0.02, 104)
    beta = regression_beta(_prices(1.5 * mkt), _prices(mkt))
    assert beta == pytest.approx(0.67 * 1.5 + 0.33, abs=1e-6)


def test_regression_beta_needs_a_year_of_weeks():
    mkt = np.full(30, 0.01)
    assert regression_beta(_prices(mkt), _prices(mkt)) is None


def test_compute_betas_uses_nifty_and_skips_missing():
    rng = np.random.default_rng(1)
    mkt = rng.normal(0.002, 0.02, 104)
    closes = pd.DataFrame({"^NSEI": _prices(mkt), "AAA.NS": _prices(0.8 * mkt), "BBB.NS": np.nan})

    def fake_download(tickers, **kw):
        assert "^NSEI" in tickers
        return {"Close": closes[[t for t in tickers if t in closes]]}

    betas = compute_betas(["AAA.NS", "BBB.NS"], download=fake_download)
    assert betas["AAA.NS"] == pytest.approx(0.67 * 0.8 + 0.33, abs=1e-6)
    assert "BBB.NS" not in betas


def test_usd_statements_converted_to_inr():
    b = make_bundle()
    inr = build_record("ABC.NS", b, MACRO, as_of="2026-11-19")
    usd = make_bundle()
    for k in ("income", "balance", "cashflow"):
        usd[k] = usd[k] / 90.0
    usd["info"]["financialCurrency"] = "USD"
    rec = build_record("ABC.NS", usd, MACRO, as_of="2026-11-19", fx_rate=90.0)
    assert rec["scenarios"]["base"] == pytest.approx(inr["scenarios"]["base"], rel=1e-6)


def test_foreign_statements_without_rate_rejected():
    b = make_bundle()
    b["info"]["financialCurrency"] = "USD"
    with pytest.raises(RecordError):
        build_record("ABC.NS", b, MACRO, as_of="2026-11-19")


# ---------------------------------------------------------------- one batch download for beta + dividends
from pipeline.sources import yfinance_source
from pipeline.sources.beta import market_history


def test_market_history_returns_betas_on_last_two_years_and_dividends():
    rng = np.random.default_rng(2)
    mkt = rng.normal(0.002, 0.02, 312)  # 6 years of weeks
    stock = np.concatenate([3.0 * mkt[:208], 0.8 * mkt[208:]])  # beta changed 2 years ago
    idx = pd.date_range("2020-11-22", periods=312, freq="W")
    closes = pd.DataFrame({"^NSEI": _prices(mkt).to_numpy(), "AAA.NS": _prices(stock).to_numpy()}, index=idx)
    divs = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    divs.iloc[100, 1], divs.iloc[200, 1] = 4.0, 5.0
    seen = {}

    def fake_download(tickers, **kw):
        seen.update(kw)
        return {"Close": closes[tickers], "Dividends": divs[tickers]}

    betas, dividends = market_history(["AAA.NS"], download=fake_download)
    assert seen["actions"] is True and seen["period"] == "6y"
    assert betas["AAA.NS"] == pytest.approx(0.67 * 0.8 + 0.33, abs=0.02)
    assert list(dividends["AAA.NS"]) == [4.0, 5.0]


def test_fetch_bundle_skips_dividend_request_when_given(monkeypatch):
    class T:
        def __init__(self, sym):
            b = make_bundle()
            self.info, self.financials = b["info"], b["income"]
            self.balance_sheet, self.cashflow = b["balance"], b["cashflow"]

        @property
        def dividends(self):
            raise AssertionError("per-ticker dividend request should be skipped")

    monkeypatch.setattr(yfinance_source.yf, "Ticker", T)
    given = pd.Series([1.0], index=pd.to_datetime(["2025-07-01"]))
    res = yfinance_source.fetch_bundle("ABC.NS", dividends=given)
    assert res.error is None and res.bundle["dividends"] is given
