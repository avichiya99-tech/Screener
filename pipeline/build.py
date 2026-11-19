"""Turn one fetched bundle into the per-stock record the site reads."""
from __future__ import annotations

import pandas as pd

from valuation_engine import (
    build_historical_eps_div_df,
    compute_dividend_quality,
    compute_scenarios,
    confidence,
    solve_reverse_valuation,
    verdict,
)

RECORD_KEYS = (
    "symbol", "name", "sector", "model", "price", "market_cap_cr", "w52_high", "w52_low",
    "verdict", "confidence", "price_source", "data_checks", "meaningful", "not_meaningful_reason",
    "scenarios", "upside_pct", "mos_buy_price",
    "implied_driver", "hist_driver", "driver_label",
    "inputs", "projection", "dividend", "eps_dps_history", "pe", "as_of",
)

SUMMARY_KEYS = (
    "symbol", "name", "sector", "price", "market_cap_cr", "verdict", "confidence", "upside_pct",
    "pe", "dividend_badge", "dividend_yield_pct", "implied_driver", "hist_driver", "stale_since",
)


class RecordError(ValueError):
    """The stock can't be shown at all (e.g. no price)."""


def _pct(x):
    return None if x is None else round(x * 100, 1)


def _r(x, n=2):
    return None if x is None else round(float(x), n)


# NSE series for REITs (RR) and InvITs (IV): trusts that pass rental/toll cash through as distributions.
# A company FCFF model does not fit them; they are valued on distribution yield and NAV.
TRUST_SERIES = {"RR": "REIT", "IV": "InvIT"}

PRICE_TOLERANCE = 0.03       # Yahoo vs NSE official close
MCAP_TOLERANCE = 0.25        # price x shares vs reported market cap
STALE_RESULTS_DAYS = 548     # ~18 months


def data_checks(info: dict, income, yahoo_price: float, official_price: dict | None, as_of: str | None) -> list[str]:
    """Plain-English warnings when the inputs look unreliable. Any warning drops confidence to Low."""
    checks = []
    if official_price and official_price.get("close"):
        nse = official_price["close"]
        gap = abs(yahoo_price - nse) / nse
        if gap > PRICE_TOLERANCE:
            checks.append(f"Yahoo price differs from NSE close by {gap:.0%}")
    shares, mcap = info.get("sharesOutstanding"), info.get("marketCap")
    if shares and mcap and yahoo_price:
        gap = abs(yahoo_price * shares - mcap) / mcap
        if gap > MCAP_TOLERANCE:
            checks.append(f"Reported share count doesn't match market cap ({gap:.0%} off)")
    if as_of and income is not None and not income.empty:
        latest = pd.to_datetime(pd.Index(income.columns), errors="coerce").max()
        if pd.notna(latest) and (pd.Timestamp(as_of) - latest).days > STALE_RESULTS_DAYS:
            checks.append(f"Latest annual results ({latest.date()}) are older than 18 months")
    return checks


def statements_currency(info: dict) -> tuple[str, str]:
    """(statement currency, quote currency)."""
    quote = info.get("currency") or "INR"
    return (info.get("financialCurrency") or quote), quote


def build_record(symbol: str, bundle: dict, macro: dict, as_of: str | None = None,
                 official_price: dict | None = None, fx_rate: float | None = None,
                 listing: dict | None = None) -> dict:
    """`listing` is the stock's row from NSE's NIFTY 500 file: {"name", "industry", "series"}."""
    listing = listing or {}
    info = bundle.get("info") or {}
    yahoo_price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not yahoo_price or yahoo_price <= 0:
        raise RecordError("missing price")
    fin_ccy, quote_ccy = statements_currency(info)
    if fin_ccy != quote_ccy:
        # e.g. Infosys files in USD but trades in INR: convert statements before valuing.
        if not fx_rate or fx_rate <= 0:
            raise RecordError(f"statements in {fin_ccy}, no {fin_ccy}{quote_ccy} exchange rate")
        bundle = {**bundle, **{k: bundle[k] * fx_rate for k in ("income", "balance", "cashflow")
                               if bundle.get(k) is not None}}
    checks = data_checks(info, bundle.get("income"), yahoo_price, official_price, as_of)
    if official_price and official_price.get("close"):
        # Value on the exchange's official close, not Yahoo's quote.
        price = official_price["close"]
        price_source = f"NSE official close ({official_price.get('date')})"
        info = {**info, "currentPrice": price}
        bundle = {**bundle, "info": info}
    else:
        price = yahoo_price
        price_source = "yfinance (unofficial)"
    shares = info.get("sharesOutstanding")

    sc = compute_scenarios(bundle, macro)
    val = sc["base_result"]
    valid = bool(val.get("valid"))
    meaningful = bool(val.get("meaningful")) if valid else False
    reason = val.get("not_meaningful_reason") if valid else val.get("reason")
    if meaningful and sc.get("unstable_reason"):
        meaningful, reason = False, sc["unstable_reason"]
    trust = TRUST_SERIES.get(listing.get("series"))
    if valid and trust:
        meaningful = False
        reason = f"{trust}: valued on distribution yield and NAV, not a company cash-flow model"
    rated = valid and meaningful  # only rated stocks publish fair values

    implied = {"value": None, "status": "invalid"}
    if valid:
        rev = solve_reverse_valuation(bundle, val["discount_rate"], terminal_g=macro["terminal_g"])
        implied = {"value": rev["implied"], "status": rev["status"]}

    dq = compute_dividend_quality(bundle, val)
    dps = info.get("dividendRate") or 0.0
    t_eps = info.get("trailingEps")
    mcap = info.get("marketCap") or (price * shares if shares else None)
    projection = val["projection_df"].round(4).to_dict(orient="records") if valid else []

    return {
        "symbol": symbol.replace(".NS", "").replace(".BO", ""),
        "name": listing.get("name") or info.get("shortName") or symbol,
        "sector": info.get("sector") or listing.get("industry") or "Unknown",
        "model": val.get("model", "N/A"),
        "price": _r(price),
        "market_cap_cr": _r(mcap / 1e7, 0) if mcap else None,
        "w52_high": _r(info.get("fiftyTwoWeekHigh")),
        "w52_low": _r(info.get("fiftyTwoWeekLow")),
        "verdict": verdict(price, sc, meaningful),
        "confidence": "Low" if checks else confidence(val.get("inputs", {}), meaningful),
        "price_source": price_source,
        "data_checks": checks,
        "meaningful": meaningful,
        "not_meaningful_reason": reason,
        "scenarios": {k: (_r(sc[k]) if rated else None) for k in ("bear", "base", "bull")},
        "upside_pct": _r(val.get("upside_pct"), 1) if rated else None,
        "mos_buy_price": _r(val.get("mos_buy_price")) if rated else None,
        "implied_driver": implied,
        "hist_driver": _pct(val.get("hist_driver")) if valid else None,
        "driver_label": val.get("driver_label"),
        "inputs": val.get("inputs", {}),
        "projection": projection,
        "dividend": {
            "score": dq["score"],
            "badge": dq["badge"],
            "flags": dq["flags"],
            "yield_pct": _r(dps / price * 100) if dps else 0.0,
        },
        "eps_dps_history": build_historical_eps_div_df(bundle).to_dict(orient="records"),
        "pe": _r(price / t_eps, 1) if (t_eps and t_eps > 0) else None,
        "as_of": as_of,
    }


def summary_row(record: dict) -> dict:
    flat = dict(record)
    flat["dividend_badge"] = record["dividend"]["badge"]
    flat["dividend_yield_pct"] = record["dividend"]["yield_pct"]
    flat["implied_driver"] = record["implied_driver"]["value"]
    flat.setdefault("stale_since", None)
    return {k: flat[k] for k in SUMMARY_KEYS}
