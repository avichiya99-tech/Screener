import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import pandas as pd
import requests
import yfinance as yf
from valuation_engine import (
    compute_valuation,
    solve_reverse_valuation,
    compute_dividend_quality,
)

IST = timezone(timedelta(hours=5, minutes=30))
os.makedirs("data", exist_ok=True)


def load_nifty500_symbols() -> list[str]:
    """Pulls live NIFTY 500 symbols from NSE, falling back to local CSV."""
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        symbols = df["Symbol"].dropna().str.strip().tolist()
        if len(symbols) >= 100:
            return [f"{s}.NS" for s in symbols]
    except Exception:
        pass

    for fallback in ["data/nifty500_symbols.csv", "MW-NIFTY-500-19-Nov-2026.csv"]:
        if os.path.exists(fallback):
            df = pd.read_csv(fallback)
            df.columns = df.columns.str.strip()
            col = "SYMBOL" if "SYMBOL" in df.columns else "Symbol"
            symbols = df[df[col].str.strip() != "NIFTY 500"][col].dropna().str.strip().tolist()
            return [f"{s}.NS" for s in symbols]
    raise FileNotFoundError("Could not fetch NSE NIFTY 500 list and no fallback CSV found.")


def fetch_with_retry(sym: str, retries: int = 2) -> dict | None:
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            if info.get("currentPrice") or info.get("regularMarketPrice"):
                return {
                    "info": info,
                    "income": t.financials,
                    "balance": t.balance_sheet,
                    "cashflow": t.cashflow,
                    "dividends": t.dividends,
                }
        except Exception:
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    return None


def evaluate_ticker(sym: str, rf: float = 0.07, erp: float = 0.055, term_g: float = 0.05) -> dict | None:
    bundle = fetch_with_retry(sym)
    if not bundle:
        return None

    info = bundle["info"]
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding")
    if not price or not shares:
        return None

    mcap = info.get("marketCap") or (price * shares)
    t_eps = info.get("trailingEps")
    f_eps = info.get("forwardEps")
    dps = info.get("dividendRate") or 0.0
    div_yield = (dps / price * 100) if dps else 0.0
    payout = (dps / t_eps * 100) if (t_eps and t_eps > 0) else None
    pe = (price / t_eps) if (t_eps and t_eps > 0) else None
    w52_hi = info.get("fiftyTwoWeekHigh")
    below_52w = ((price - w52_hi) / w52_hi * 100) if w52_hi else None

    val = compute_valuation(bundle, rf=rf, erp=erp, terminal_g=term_g, mos_pct=0.25)
    dq = compute_dividend_quality(bundle, val)

    implied_driver = None
    expectations_gap = None
    hist_driver_pct = None
    if val.get("valid"):
        hist_driver_pct = round(val["hist_driver"] * 100, 1)
        implied_driver = solve_reverse_valuation(bundle, val["discount_rate"], terminal_g=term_g)
        if implied_driver is not None:
            expectations_gap = round(hist_driver_pct - implied_driver, 1)

    return {
        "Ticker": sym,
        "Company": info.get("shortName", sym),
        "Sector": info.get("sector", "Unknown"),
        "Model": val.get("model", "N/A"),
        "Price": round(price, 2),
        "Market Cap (Cr)": round(mcap / 1e7, 0),
        "Trailing EPS": round(t_eps, 2) if t_eps else None,
        "Forward EPS": round(f_eps, 2) if f_eps else None,
        "P/E": round(pe, 1) if pe else None,
        "Annual DPS": round(dps, 2),
        "Dividend Yield (%)": round(div_yield, 2),
        "Payout Ratio (%)": round(payout, 1) if payout is not None else None,
        "Div Quality Score": dq["score"],
        "Div Class": dq["badge"],
        "Hist Growth/ROE (%)": hist_driver_pct,
        "Mkt Implied Growth/ROE (%)": implied_driver,
        "Expectations Gap (%)": expectations_gap,
        "Intrinsic Value": round(val["intrinsic_price"], 2) if val.get("valid") else None,
        "MoS Buy Price (25%)": round(val["mos_buy_price"], 2) if val.get("valid") else None,
        "Valuation Upside (%)": round(val["upside_pct"], 1) if val.get("valid") else None,
        "% Below 52W High": round(below_52w, 1) if below_52w is not None else None,
        "Flags": ", ".join(dq["flags"]) if dq["flags"] else "OK",
    }


def main():
    symbols = load_nifty500_symbols()
    limit = int(os.environ.get("MAX_STOCKS", "200"))  # Set MAX_STOCKS=0 in workflow for all 500
    target_symbols = symbols[:limit] if limit > 0 else symbols
    print(f"Updating {len(target_symbols)} NIFTY 500 stocks...")

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(evaluate_ticker, s) for s in target_symbols]
        for f in as_completed(futures):
            row = f.result()
            if row:
                results.append(row)

    df = pd.DataFrame(results).sort_values("Market Cap (Cr)", ascending=False)
    df["Last Updated (IST)"] = datetime.now(IST).strftime("%d-%b-%Y %I:%M %p IST")
    df.to_csv("data/daily_screener.csv", index=False)
    print(f"Saved {len(df)} stocks to data/daily_screener.csv")


if __name__ == "__main__":
    main()
