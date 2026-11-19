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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from pipeline.build import build_record, statements_currency, summary_row
from pipeline.config import load_macro
from pipeline.jsonsafe import to_jsonable
from pipeline.sources.beta import market_history
from pipeline.sources.ccil_rf import live_macro
from pipeline.sources.fx import fx_rate
from pipeline.sources.nse_bhavcopy import latest_closes
from pipeline.sources.yfinance_source import SOURCE_NAME, fetch_bundle

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
NIFTY500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
FALLBACK_SYMBOLS = DATA_DIR / "nifty500_symbols.csv"


def clean_symbols(symbols) -> list[str]:
    """Strip blanks and NSE's temporary DUMMY* placeholders (used during index changes)."""
    out = []
    for s in symbols:
        s = str(s).strip() if s is not None else ""
        if s and s.upper() != "NONE" and not s.upper().startswith("DUMMY"):
            out.append(s)
    return out


LISTING_COLUMNS = {"Company Name": "name", "Industry": "industry", "Series": "series"}


def parse_nifty500_listing(csv_text: str) -> tuple[list[str], dict]:
    """(["SYM.NS", ...], {"SYM.NS": {"name", "industry", "series"}}) from NSE's NIFTY 500 CSV.

    Older fallback files have only a Symbol column; the listing is then empty."""
    df = pd.read_csv(io.StringIO(csv_text), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    symbols, listing = [], {}
    for row in df.to_dict(orient="records"):
        kept = clean_symbols([row.get("Symbol")])
        if not kept:
            continue
        sym = f"{kept[0]}.NS"
        symbols.append(sym)
        meta = {key: str(row[col]).strip() for col, key in LISTING_COLUMNS.items()
                if col in row and pd.notna(row[col])}
        if meta:
            listing[sym] = meta
    return symbols, listing


def load_nifty500_symbols() -> tuple[list[str], dict]:
    """Live NIFTY 500 list from NSE; falls back to data/nifty500_symbols.csv (refreshed on each success)."""
    try:
        resp = requests.get(NIFTY500_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        symbols, listing = parse_nifty500_listing(resp.text)
        if len(symbols) >= 100:
            FALLBACK_SYMBOLS.parent.mkdir(parents=True, exist_ok=True)
            FALLBACK_SYMBOLS.write_text(resp.text)
            return symbols, listing
    except Exception as exc:
        print(f"NSE list unavailable ({exc}); using {FALLBACK_SYMBOLS}", file=sys.stderr)
    if FALLBACK_SYMBOLS.exists():
        return parse_nifty500_listing(FALLBACK_SYMBOLS.read_text())
    raise FileNotFoundError("Could not fetch the NIFTY 500 list and no fallback CSV exists.")


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(obj), ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def recover_interrupted_swap(out_dir: Path) -> None:
    """If a previous run crashed mid-swap, put the last good stocks/ back in place."""
    old, cur = Path(out_dir) / ".stocks-old", Path(out_dir) / "stocks"
    if old.exists():
        if cur.exists():
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.replace(old, cur)


def write_outputs(records: list[dict], failures: list[dict], out_dir: Path, now: datetime,
                  min_success: float = 0.6, macro: dict | None = None, sources: dict | None = None) -> bool:
    """Write summary/stocks/meta/history. Writes nothing and returns False if too few tickers succeeded."""
    out_dir = Path(out_dir)
    recover_interrupted_swap(out_dir)
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
        "Verdict": record["verdict"],
        "Confidence": record["confidence"],
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


def _process(symbol: str, macro: dict, as_of: str, closes: dict | None = None, betas: dict | None = None,
             dividends: dict | None = None, listing: dict | None = None):
    res = fetch_bundle(symbol, dividends=(dividends or {}).get(symbol))
    if res.bundle is None:
        return None, {"symbol": symbol, "error": res.error}
    try:
        bundle = res.bundle
        if betas is not None:
            # Our NIFTY 50 beta replaces Yahoo's S&P 500 one; no beta -> engine default 1.0, marked "default".
            bundle = {**bundle, "info": {**bundle["info"], "beta": betas.get(symbol)}}
        fin_ccy, quote_ccy = statements_currency(bundle["info"])
        official = (closes or {}).get(symbol.replace(".NS", ""))
        rec = build_record(symbol, bundle, macro, as_of=as_of, official_price=official,
                           fx_rate=fx_rate(fin_ccy, quote_ccy), listing=(listing or {}).get(symbol))
        return (rec, legacy_row(rec, bundle)), None
    except Exception as exc:  # one bad ticker never stops the run
        return None, {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}


MAX_CONSECUTIVE_FAILURES = 25  # Yahoo is blocking us: stop instead of grinding through retries


def run_all(targets: list[str], process, workers: int = 4,
            max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES):
    """Run `process(symbol) -> (ok, fail)` over targets. Returns (records, legacy, failures, aborted).

    Aborts early (cancelling queued work) after `max_consecutive_failures` failures in a row.
    """
    stop = threading.Event()
    lock = threading.Lock()
    streak = [0]
    skipped = object()

    def guarded(sym):
        # The streak is tracked where the work happens, so workers stop picking up
        # new tickers as soon as the limit is hit (not when the main thread catches up).
        if stop.is_set():
            return skipped
        try:
            ok, fail = process(sym)
        except Exception as exc:
            ok, fail = None, {"symbol": sym, "error": f"{type(exc).__name__}: {exc}"}
        with lock:
            streak[0] = streak[0] + 1 if fail else 0
            if streak[0] >= max_consecutive_failures:
                stop.set()
        return ok, fail

    records, legacy, failures = [], [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(guarded, targets):
            if res is skipped:
                continue
            ok, fail = res
            if ok:
                records.append(ok[0])
                legacy.append(ok[1])
            if fail:
                failures.append(fail)
    return records, legacy, failures, stop.is_set()


RETRY_COOLDOWN_SECONDS = 60


def retry_failures(failures: list[dict], process, cooldown: int = RETRY_COOLDOWN_SECONDS,
                   sleep=time.sleep) -> tuple[list, list, list]:
    """Second pass for tickers that failed (mostly Yahoo rate limits): wait, then retry one at a time.

    Returns (records, legacy_rows, still_failing)."""
    if not failures:
        return [], [], []
    sleep(cooldown)
    records, legacy, remaining = [], [], []
    for f in failures:
        try:
            ok, fail = process(f["symbol"])
        except Exception as exc:
            ok, fail = None, {"symbol": f["symbol"], "error": f"{type(exc).__name__}: {exc}"}
        if ok:
            records.append(ok[0])
            legacy.append(ok[1])
        else:
            remaining.append(fail or f)
    return records, legacy, remaining


def main() -> int:
    macro, rf_source = live_macro(load_macro())
    print(f"Risk-free rate {macro['rf']:.4%} from {rf_source}")
    symbols, listing = load_nifty500_symbols()
    limit = int(os.environ.get("MAX_STOCKS", "0"))
    targets = symbols[:limit] if limit > 0 else symbols
    now = datetime.now(timezone.utc)
    as_of = now.astimezone(IST).date().isoformat()
    closes, close_day = latest_closes(now.astimezone(IST).date())
    price_source = (f"NSE official close ({close_day.isoformat()}); yfinance fallback" if closes
                    else "yfinance (unofficial) - NSE bhavcopy unavailable")
    betas, dividends = market_history(targets)
    print(f"Prices: {price_source}. Betas vs NIFTY 50 for {len(betas)}/{len(targets)}. "
          f"Valuing {len(targets)} NIFTY 500 stocks...")

    process = partial(_process, macro=macro, as_of=as_of, closes=closes, betas=betas, dividends=dividends,
                      listing=listing)
    records, legacy, failures, aborted = run_all(targets, process)
    if aborted:
        print(f"Stopped after {MAX_CONSECUTIVE_FAILURES} failures in a row (data source blocking?); "
              f"kept previous data. Last error: {failures[-1]['error']}", file=sys.stderr)
        return 1

    if failures:
        print(f"Retrying {len(failures)} failed tickers after a {RETRY_COOLDOWN_SECONDS}s cooldown...")
        more, more_legacy, failures = retry_failures(failures, process)
        records += more
        legacy += more_legacy
    failures.sort(key=lambda f: f["symbol"])
    sources = {"prices": price_source, "statements": SOURCE_NAME, "universe": "NSE NIFTY 500 list",
               "rf": rf_source, "beta": "2y weekly regression vs NIFTY 50 (^NSEI), Blume-adjusted",
               "fx": "yfinance FX close, for companies reporting in USD"}
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
