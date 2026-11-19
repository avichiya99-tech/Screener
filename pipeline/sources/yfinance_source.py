"""yfinance adapter: the only module that talks to Yahoo. Failures are reported, never dropped."""
from __future__ import annotations

import time
from dataclasses import dataclass

import yfinance as yf

SOURCE_NAME = "yfinance (unofficial)"


@dataclass
class FetchResult:
    symbol: str
    bundle: dict | None
    error: str | None
    source: str = SOURCE_NAME


def fetch_bundle(symbol: str, retries: int = 3, sleep=time.sleep) -> FetchResult:
    """Fetch one ticker. Empty info / no price counts as a failure and is retried (2s, 4s, 8s...)."""
    attempts = retries + 1
    last_error = f"no price after {attempts} attempts"
    for attempt in range(attempts):
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            if info.get("currentPrice") or info.get("regularMarketPrice"):
                return FetchResult(symbol, {
                    "info": info,
                    "income": t.financials,
                    "balance": t.balance_sheet,
                    "cashflow": t.cashflow,
                    "dividends": t.dividends,
                }, None)
            last_error = f"no price after {attempts} attempts"
        except Exception as exc:  # network errors, Yahoo schema changes, throttling
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            sleep(2 ** (attempt + 1))
    return FetchResult(symbol, None, last_error)
