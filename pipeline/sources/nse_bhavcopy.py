"""Official end-of-day closing prices from NSE's public daily bhavcopy file.

Used as the price of record for valuation (Yahoo's quote is only a fallback) and to
cross-check Yahoo. Only the public archive file is read; no NSE website API is used."""
from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests

BHAV_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}
MAX_LOOKBACK_DAYS = 7  # weekends + market holidays


def fetch_bhavcopy(day: date, timeout: int = 30) -> bytes | None:
    """Zip bytes for `day`, or None when NSE has no file (holiday, weekend, not yet published)."""
    resp = requests.get(BHAV_URL.format(d=day.strftime("%Y%m%d")),
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


def parse_bhavcopy(zip_bytes: bytes) -> dict:
    """{SYMBOL: {"close": float, "date": "YYYY-MM-DD"}} for equity series only."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        df = pd.read_csv(zf.open(name))
    df = df[df["SctySrs"].astype(str).str.strip().isin(EQUITY_SERIES)]
    return {str(r.TckrSymb).strip(): {"close": float(r.ClsPric), "date": str(r.TradDt)[:10]}
            for r in df.itertuples() if pd.notna(r.ClsPric) and r.ClsPric > 0}


def latest_closes(today: date, fetch=fetch_bhavcopy) -> tuple[dict, date | None]:
    """Closes from the most recent trading day on or before `today` (looks back a week)."""
    for back in range(MAX_LOOKBACK_DAYS):
        day = today - timedelta(days=back)
        try:
            blob = fetch(day)
        except Exception:  # network trouble on one day: try the previous one
            blob = None
        if blob:
            closes = parse_bhavcopy(blob)
            if closes:
                return closes, day
    return {}, None
