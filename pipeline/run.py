"""Nightly pipeline: fetch NIFTY 500, value each stock, write JSON for the site.

Run: python update_data.py   (MAX_STOCKS=20 for a quick smoke run; default 0 = all)
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from pipeline.build import build_record, summary_row
from pipeline.config import load_macro
from pipeline.jsonsafe import to_jsonable
from pipeline.sources.yfinance_source import SOURCE_NAME, fetch_bundle

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
NIFTY500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
FALLBACK_SYMBOLS = DATA_DIR / "nifty500_symbols.csv"


def load_nifty500_symbols() -> list[str]:
    """Live NIFTY 500 list from NSE; falls back to data/nifty500_symbols.csv (refreshed on each success)."""
    try:
        resp = requests.get(NIFTY500_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        symbols = df["Symbol"].dropna().str.strip().tolist()
        if len(symbols) >= 100:
            FALLBACK_SYMBOLS.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"Symbol": symbols}).to_csv(FALLBACK_SYMBOLS, index=False)
            return [f"{s}.NS" for s in symbols]
    except Exception as exc:
        print(f"NSE list unavailable ({exc}); using {FALLBACK_SYMBOLS}", file=sys.stderr)
    if FALLBACK_SYMBOLS.exists():
        df = pd.read_csv(FALLBACK_SYMBOLS)
        return [f"{s.strip()}.NS" for s in df["Symbol"].dropna()]
    raise FileNotFoundError("Could not fetch the NIFTY 500 list and no fallback CSV exists.")


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(obj), ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def write_outputs(records: list[dict], failures: list[dict], out_dir: Path, now: datetime,
                  min_success: float = 0.6, macro: dict | None = None, sources: dict | None = None) -> bool:
    """Write summary/stocks/meta/history. Writes nothing and returns False if too few tickers succeeded."""
    out_dir = Path(out_dir)
    total = len(records) + len(failures)
    if total == 0 or len(records) / total < min_success:
        return False

    now_ist = now.astimezone(IST)
    fresh_count = len(records)
    # Carry yesterday's page forward for tickers that failed tonight, flagged as stale,
    # so a one-night Yahoo hiccup never makes a stock vanish from the site.
    fresh = {r["symbol"] for r in records}
    stale = []
    for f in failures:
        sym = f["symbol"].replace(".NS", "").replace(".BO", "")
        prev_path = out_dir / "stocks" / f"{sym}.json"
        if sym in fresh or not prev_path.exists():
            continue
        try:
            prev = json.loads(prev_path.read_text())
        except (OSError, ValueError):
            continue
        prev["stale_since"] = prev.get("stale_since") or prev.get("as_of")
        stale.append(prev)
    records = sorted(list(records) + stale, key=lambda r: r.get("market_cap_cr") or 0, reverse=True)
    summary = [summary_row(r) for r in records]
    meta = {
        "as_of": now_ist.isoformat(timespec="minutes"),
        "count": fresh_count,
        "stale": sorted(r["symbol"] for r in stale),
        "failures": failures,
        "sources": sources or {},
        "macro": macro or {},
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=out_dir))
    try:
        _dump(staging / "summary.json", summary)
        _dump(staging / "meta.json", meta)
        for rec in records:
            _dump(staging / "stocks" / f"{rec['symbol']}.json", rec)

        # Swap in: stocks dir first, then the small files.
        old = out_dir / ".stocks-old"
        if old.exists():
            shutil.rmtree(old)
        if (out_dir / "stocks").exists():
            os.replace(out_dir / "stocks", old)
        os.replace(staging / "stocks", out_dir / "stocks")
        shutil.rmtree(old, ignore_errors=True)
        os.replace(staging / "summary.json", out_dir / "summary.json")
        os.replace(staging / "meta.json", out_dir / "meta.json")
        _dump(out_dir / "history" / f"{now_ist.date().isoformat()}.json", summary)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return True


def legacy_row(record: dict, bundle: dict) -> dict:
    """Old daily_screener.csv columns, so the Streamlit app keeps working until the site replaces it."""
    info = bundle.get("info") or {}
    price = record["price"]
    t_eps, dps = info.get("trailingEps"), info.get("dividendRate") or 0.0
    w52 = info.get("fiftyTwoWeekHigh")
    return {
        "Ticker": record["symbol"] + ".NS",
        "Company": record["name"],
        "Sector": record["sector"],
        "Model": record["model"],
        "Price": price,
        "Market Cap (Cr)": record["market_cap_cr"],
        "Trailing EPS": round(t_eps, 2) if t_eps else None,
        "Forward EPS": round(info["forwardEps"], 2) if info.get("forwardEps") else None,
        "P/E": record["pe"],
        "Annual DPS": round(dps, 2),
        "Dividend Yield (%)": record["dividend"]["yield_pct"],
        "Payout Ratio (%)": round(dps / t_eps * 100, 1) if (t_eps and t_eps > 0) else None,
        "Div Quality Score": record["dividend"]["score"],
        "Div Class": record["dividend"]["badge"],
        "Hist Growth/ROE (%)": record["hist_driver"],
        "Mkt Implied Growth/ROE (%)": record["implied_driver"]["value"],
        "Expectations Gap (%)": (round(record["hist_driver"] - record["implied_driver"]["value"], 1)
                                 if record["hist_driver"] is not None and record["implied_driver"]["value"] is not None else None),
        "Intrinsic Value": record["scenarios"]["base"],
        "MoS Buy Price (25%)": record["mos_buy_price"],
        "Valuation Upside (%)": record["upside_pct"],
        "% Below 52W High": round((price - w52) / w52 * 100, 1) if (w52 and price) else None,
        "Flags": ", ".join(record["dividend"]["flags"]) or "OK",
    }


def _process(symbol: str, macro: dict, as_of: str):
    res = fetch_bundle(symbol)
    if res.bundle is None:
        return None, {"symbol": symbol, "error": res.error}
    try:
        rec = build_record(symbol, res.bundle, macro, as_of=as_of)
        return (rec, legacy_row(rec, res.bundle)), None
    except Exception as exc:  # one bad ticker never stops the run
        return None, {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    macro = load_macro()
    symbols = load_nifty500_symbols()
    limit = int(os.environ.get("MAX_STOCKS", "0"))
    targets = symbols[:limit] if limit > 0 else symbols
    now = datetime.now(timezone.utc)
    as_of = now.astimezone(IST).date().isoformat()
    print(f"Valuing {len(targets)} NIFTY 500 stocks...")

    records, legacy, failures = [], [], []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_process, s, macro, as_of): s for s in targets}
        for fut in as_completed(futures):
            try:
                ok, fail = fut.result()
            except Exception as exc:
                ok, fail = None, {"symbol": futures[fut], "error": f"{type(exc).__name__}: {exc}"}
            if ok:
                records.append(ok[0])
                legacy.append(ok[1])
            if fail:
                failures.append(fail)

    failures.sort(key=lambda f: f["symbol"])
    sources = {"prices": SOURCE_NAME, "statements": SOURCE_NAME, "universe": "NSE NIFTY 500 list",
               "rf": f"config/macro.json (updated {macro['updated_on']})"}
    if not write_outputs(records, failures, DATA_DIR, now, macro=macro, sources=sources):
        print(f"Only {len(records)}/{len(targets)} succeeded; kept previous data.", file=sys.stderr)
        return 1

    df = pd.DataFrame(legacy).sort_values("Market Cap (Cr)", ascending=False)
    df["Last Updated (IST)"] = now.astimezone(IST).strftime("%d-%b-%Y %I:%M %p IST")
    df.to_csv(DATA_DIR / "daily_screener.csv", index=False)
    print(f"Wrote {len(records)} stocks; {len(failures)} failures logged in data/meta.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
