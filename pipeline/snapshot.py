"""Nightly snapshots of the exact inputs each stock was valued on.

The Streamlit app reads these instead of calling Yahoo from Streamlit Cloud, whose shared IPs
Yahoo rate-limits. Layout under data/bundles/:
  <SYMBOL>.json  statements + dividends (rarely change, so git history stays small)
  info.json      {SYMBOL: price, shares, beta, ...} for every stock (changes nightly)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline.build import statements_currency

# Everything the engine and the app read from `info`; Yahoo's other ~150 fields are dropped.
INFO_KEYS = (
    "beta", "bookValue", "currency", "currentPrice", "dividendRate", "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow", "financialCurrency", "forwardEps", "marketCap", "returnOnEquity",
    "sector", "sharesOutstanding", "shortName", "trailingEps",
)
STATEMENTS = ("income", "balance", "cashflow")


def _base(symbol: str) -> str:
    return symbol.upper().replace(".NS", "").replace(".BO", "")


def valuation_bundle(bundle: dict, price: float, fx_rate: float | None) -> dict:
    """The bundle as valued: official price, statements in the trading currency, slim info."""
    info = {k: v for k, v in (bundle.get("info") or {}).items() if k in INFO_KEYS}
    out = {**bundle, "info": {**info, "currentPrice": price}}
    fin_ccy, quote_ccy = statements_currency(info)
    if fin_ccy != quote_ccy and fx_rate:
        for k in STATEMENTS:
            if out.get(k) is not None:
                out[k] = out[k] * fx_rate
        out["info"]["financialCurrency"] = quote_ccy
    return out


def _frame_to_json(df):
    if df is None or df.empty:
        return None
    df = df.astype(float)
    return {"index": [str(i) for i in df.index],
            "columns": [pd.Timestamp(c).strftime("%Y-%m-%d") for c in df.columns],
            "data": [[None if pd.isna(v) else float(v) for v in row] for row in df.to_numpy()]}


def _frame_from_json(obj):
    if not obj:
        return pd.DataFrame()
    return pd.DataFrame(obj["data"], index=obj["index"], columns=pd.to_datetime(obj["columns"]), dtype=float)


def _series_to_json(s):
    if s is None or len(s) == 0:
        return {"index": [], "data": []}
    return {"index": [pd.Timestamp(i).strftime("%Y-%m-%d") for i in s.index], "data": [float(v) for v in s]}


def _series_from_json(obj):
    return pd.Series(obj["data"], index=pd.to_datetime(obj["index"]), dtype=float)


def _clean(v):
    return None if isinstance(v, float) and pd.isna(v) else v


def write_snapshots(snapshots: dict, out_dir) -> None:
    """Write tonight's snapshots; info.json is merged so stocks that failed tonight keep yesterday's."""
    folder = Path(out_dir) / "bundles"
    folder.mkdir(parents=True, exist_ok=True)
    info_path = folder / "info.json"
    try:
        all_info = json.loads(info_path.read_text())
    except (OSError, ValueError):
        all_info = {}
    for symbol, b in snapshots.items():
        sym = _base(symbol)
        body = {k: _frame_to_json(b.get(k)) for k in STATEMENTS}
        body["dividends"] = _series_to_json(b.get("dividends"))
        (folder / f"{sym}.json").write_text(json.dumps(body, sort_keys=True, separators=(",", ":")))
        all_info[sym] = {k: _clean(v) for k, v in b["info"].items()}
    info_path.write_text(json.dumps(all_info, sort_keys=True, separators=(",", ":")))


def load_snapshot(symbol: str, out_dir) -> dict | None:
    folder = Path(out_dir) / "bundles"
    sym = _base(symbol)
    try:
        body = json.loads((folder / f"{sym}.json").read_text())
        info = json.loads((folder / "info.json").read_text())[sym]
    except (OSError, ValueError, KeyError):
        return None
    bundle = {k: _frame_from_json(body.get(k)) for k in STATEMENTS}
    bundle["dividends"] = _series_from_json(body["dividends"])
    bundle["info"] = info
    return bundle


def get_bundle(symbol: str, out_dir, live) -> tuple[dict | None, str, str | None]:
    """(bundle, source, error). NIFTY 500 stocks come from last night's snapshot; anything else
    is fetched live with `live(symbol)`, and a Yahoo failure becomes a message, not a crash."""
    snap = load_snapshot(symbol, out_dir) if symbol.upper().endswith((".NS", ".BO")) or "." not in symbol else None
    if snap is not None:
        return snap, "nightly snapshot (NSE close)", None
    try:
        return live(symbol), "Yahoo Finance (live)", None
    except Exception as exc:
        name = type(exc).__name__
        if "RateLimit" in name or "Too Many Requests" in str(exc):
            msg = ("Yahoo Finance is rate-limiting this server right now, so live data for "
                   f"{symbol} is unavailable. Try again in a few minutes, or pick a NIFTY 500 stock "
                   "from the list (those use last night's saved data).")
        else:
            msg = f"Could not fetch {symbol} from Yahoo Finance ({name})."
        return None, "Yahoo Finance (live)", msg
