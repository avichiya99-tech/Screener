"""Exchange rates for companies that report in a different currency than they trade in."""
from __future__ import annotations

import threading
from functools import lru_cache

_lock = threading.Lock()


@lru_cache(maxsize=16)
def _fx_cached(frm: str, to: str) -> float | None:
    import yfinance as yf
    try:
        hist = yf.Ticker(f"{frm}{to}=X").history(period="5d")
        rate = float(hist["Close"].dropna().iloc[-1])
        return rate if rate > 0 else None
    except Exception:
        return None


def fx_rate(frm: str, to: str) -> float | None:
    """Latest close of frm->to (e.g. USD->INR), or None. Cached for the run; thread-safe."""
    if frm == to:
        return 1.0
    with _lock:
        return _fx_cached(frm, to)
