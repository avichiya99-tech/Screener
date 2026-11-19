"""Turn one fetched bundle into the per-stock record the site reads."""
from __future__ import annotations

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
    "verdict", "confidence", "meaningful", "not_meaningful_reason",
    "scenarios", "upside_pct", "mos_buy_price",
    "implied_driver", "hist_driver", "driver_label",
    "inputs", "projection", "dividend", "eps_dps_history", "pe", "as_of",
)

SUMMARY_KEYS = (
    "symbol", "name", "sector", "price", "market_cap_cr", "verdict", "confidence", "upside_pct",
    "pe", "dividend_badge", "dividend_yield_pct", "implied_driver", "hist_driver",
)


class RecordError(ValueError):
    """The stock can't be shown at all (e.g. no price)."""


def _pct(x):
    return None if x is None else round(x * 100, 1)


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def build_record(symbol: str, bundle: dict, macro: dict, as_of: str | None = None) -> dict:
    info = bundle.get("info") or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding")
    if not price or price <= 0:
        raise RecordError("missing price")

    sc = compute_scenarios(bundle, macro)
    val = sc["base_result"]
    valid = bool(val.get("valid"))
    meaningful = bool(val.get("meaningful")) if valid else False
    reason = val.get("not_meaningful_reason") if valid else val.get("reason")

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
        "name": info.get("shortName") or symbol,
        "sector": info.get("sector") or "Unknown",
        "model": val.get("model", "N/A"),
        "price": _r(price),
        "market_cap_cr": _r(mcap / 1e7, 0) if mcap else None,
        "w52_high": _r(info.get("fiftyTwoWeekHigh")),
        "w52_low": _r(info.get("fiftyTwoWeekLow")),
        "verdict": verdict(price, sc, meaningful),
        "confidence": confidence(val.get("inputs", {}), meaningful),
        "meaningful": meaningful,
        "not_meaningful_reason": reason,
        "scenarios": {k: _r(sc[k]) for k in ("bear", "base", "bull")},
        "upside_pct": _r(val.get("upside_pct"), 1) if valid else None,
        "mos_buy_price": _r(val.get("mos_buy_price")) if valid else None,
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
    return {k: flat[k] for k in SUMMARY_KEYS}
