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


def fetch_bundle(symbol: str, retries: int = 3, sleep=time.sleep, dividends=None) -> FetchResult:
    """Fetch one ticker. Empty info / no price counts as a failure and is retried (2s, 4s, 8s...).

    Pass `dividends` (from the batch download) to skip the per-ticker dividend request."""
    attempts = retries + 1
    last_error = f"no price after {attempts} attempts"
    for attempt in range(attempts):
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            if info.get("currentPrice") or info.get("regularMarketPrice"):
                income = t.financials
                # yfinance swallows statement-endpoint errors and returns an empty frame:
                # treat that as a failed attempt so throttling can't masquerade as success.
                if income is not None and not income.empty:
                    return FetchResult(symbol, {
                        "info": info,
                        "income": income,
                        "balance": t.balance_sheet,
                        "cashflow": t.cashflow,
                        "dividends": t.dividends if dividends is None else dividends,
                    }, None)
                last_error = f"no financial statements after {attempts} attempts"
            else:
                last_error = f"no price after {attempts} attempts"
        except Exception as exc:  # network errors, Yahoo schema changes, throttling
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            sleep(2 ** (attempt + 1))
    return FetchResult(symbol, None, last_error)
