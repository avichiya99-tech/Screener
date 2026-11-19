"""Batch price history: beta against the NIFTY 50 (computed by us) and dividend history.

Yahoo's `beta` for Indian stocks is measured against the US S&P 500, which makes it close to
zero for most of them (TCS 0.08, Infosys 0.02 in Nov 2026). Professional practice for India is a
regression on the local index: here 2 years of weekly returns vs ^NSEI, Blume-adjusted
(0.67 x raw + 0.33 x 1.0, the Bloomberg convention)."""
from __future__ import annotations

import numpy as np
import pandas as pd

MARKET = "^NSEI"
MIN_WEEKS = 52
BLUME_WEIGHT = 0.67


def regression_beta(stock_close: pd.Series, market_close: pd.Series, min_obs: int = MIN_WEEKS) -> float | None:
    """Blume-adjusted OLS beta of weekly returns, or None with fewer than `min_obs` weeks."""
    df = pd.concat([stock_close, market_close], axis=1).astype(float)
    rets = df.pct_change(fill_method=None).dropna()
    if len(rets) < min_obs:
        return None
    s, m = rets.iloc[:, 0].to_numpy(), rets.iloc[:, 1].to_numpy()
    var = np.var(m, ddof=1)
    if var <= 0:
        return None
    raw = np.cov(s, m, ddof=1)[0, 1] / var
    return float(BLUME_WEIGHT * raw + (1 - BLUME_WEIGHT))


BETA_WEEKS = 105  # 2 years of weekly closes -> 104 weekly returns


def market_history(symbols: list[str], download=None, chunk: int = 100) -> tuple[dict, dict]:
    """One batch download per `chunk` symbols: 6 years of weekly prices with dividends.

    Returns ({symbol: adjusted beta}, {symbol: dividend Series}). Replaces one dividend request
    per stock with a handful of batch requests. Never raises: missing symbols are just absent."""
    if download is None:
        import yfinance as yf
        download = yf.download
    betas, dividends = {}, {}
    for i in range(0, len(symbols), chunk):
        batch = list(symbols[i:i + chunk])
        try:
            data = download(batch + [MARKET], period="6y", interval="1wk",
                            auto_adjust=True, actions=True, progress=False)
            closes = data["Close"]
        except Exception:
            continue
        divs = data["Dividends"] if "Dividends" in data else None
        if MARKET not in closes:
            continue
        market = closes[MARKET].iloc[-BETA_WEEKS:]
        for sym in batch:
            if sym not in closes:
                continue
            b = regression_beta(closes[sym].iloc[-BETA_WEEKS:], market)
            if b is not None and np.isfinite(b):
                betas[sym] = round(b, 4)
            if divs is not None and sym in divs:
                d = divs[sym]
                dividends[sym] = d[d > 0]
    return betas, dividends


def compute_betas(symbols: list[str], download=None, chunk: int = 100) -> dict:
    """{symbol: adjusted beta} vs NIFTY 50 (2 years of weekly returns)."""
    return market_history(symbols, download=download, chunk=chunk)[0]
