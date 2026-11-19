"""Risk-free rate from CCIL (Clearing Corporation of India): the 10-year central government
benchmark yield, published daily. Falls back to config/macro.json if CCIL is unreachable."""
from __future__ import annotations

import re

import requests

CCIL_URL = "https://www.ccilindia.com/tenorwise-indicative-yields"
RF_MIN, RF_MAX = 0.03, 0.15  # anything outside this is a parsing error, not a market move

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def fetch_ccil(timeout: int = 20) -> str:
    resp = requests.get(CCIL_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_ccil_10y(html: str):
    """Return (yield as a decimal, date 'YYYY-MM-DD', security name) or None.

    Picks the 9Y-10Y central government security (" GS "), never a state bond ("SGS")."""
    for row in _ROW.findall(html):
        cells = [re.sub(r"<[^>]+>|\s+", " ", c).strip() for c in _CELL.findall(row)]
        if len(cells) < 4:
            continue
        date, tenor, security, ytm = cells[:4]
        if tenor.upper() != "9Y-10Y" or " GS " not in f" {security.upper()} " or "SGS" in security.upper():
            continue
        try:
            return float(ytm) / 100, date[:10], security
        except ValueError:
            return None
    return None


def live_macro(macro: dict, fetch=fetch_ccil) -> tuple[dict, str]:
    """Copy of `macro` with rf from CCIL when available. Returns (macro, source description)."""
    out = dict(macro)
    try:
        parsed = parse_ccil_10y(fetch())
    except Exception as exc:  # network / HTTP errors: fall back, never fail the run
        parsed = None
        reason = f"{type(exc).__name__}"
    else:
        reason = "no 10Y row"
    if parsed and RF_MIN <= parsed[0] <= RF_MAX:
        rf, as_of, security = parsed
        out["rf"], out["rf_as_of"] = round(rf, 6), as_of
        return out, f"CCIL 10Y G-sec ({security}, {as_of})"
    if parsed:
        reason = f"implausible yield {parsed[0]:.4f}"
    return out, f"config/macro.json (updated {macro['updated_on']}; CCIL unavailable: {reason})"
