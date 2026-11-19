"""Shared test helpers: a synthetic, yfinance-shaped data bundle."""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CR = 1e7  # 1 crore


def _frame(rows: dict[str, list[float] | None], years: int) -> pd.DataFrame:
    cols = [pd.Timestamp(f"{2026 - i}-03-31") for i in range(years)]
    data = {}
    for label, vals in rows.items():
        if vals is None:
            continue
        padded = list(vals) + [float("nan")] * (years - len(vals))
        data[label] = padded[:years]
    return pd.DataFrame.from_dict(data, orient="index", columns=cols)


def make_bundle(
    *,
    sector: str = "Industrials",
    price: float = 100.0,
    shares: float = 1e8,
    revenue=(1200, 1100, 1000, 900),
    ebit=(180, 165, 150, 135),
    pretax=None,
    tax=None,
    da=(40, 38, 36, 34),
    capex=(60, 55, 50, 45),
    debt: float = 200.0,
    cash: float = 50.0,
    beta: float | None = 1.0,
    book_value: float | None = None,
    roe: float | None = None,
    dps: float = 0.0,
    trailing_eps: float | None = None,
    dividends: pd.Series | None = None,
    drop: tuple = (),
) -> dict:
    """Build a yfinance-shaped bundle. Statement lists are newest first, in crores."""
    revenue = list(revenue)
    ebit = list(ebit)
    years = max(len(revenue), 1)
    interest = [debt * 0.08] * len(ebit)
    if pretax is None:
        pretax = [e - i for e, i in zip(ebit, interest)]
    if tax is None:
        tax = [p * 0.25 for p in pretax]
    net_income = [p - t for p, t in zip(pretax, tax)]

    def cr(vals):
        return [v * CR for v in vals]

    income_rows = {
        "Total Revenue": cr(revenue),
        "EBIT": cr(ebit),
        "Pretax Income": cr(pretax),
        "Tax Provision": cr(tax),
        "Interest Expense": cr(interest),
        "Net Income": cr(net_income),
        "Diluted EPS": [n * CR / shares for n in net_income],
    }
    cash_rows = {
        "Depreciation And Amortization": cr(da),
        "Capital Expenditure": [-v * CR for v in capex],
        "Free Cash Flow": [(n + d - c) * CR for n, d, c in zip(net_income, da, capex)],
        "Cash Dividends Paid": [-dps * shares] * len(revenue),
    }
    equity = (book_value * shares) if book_value is not None else 800 * CR
    bal_rows = {
        "Total Debt": [debt * CR],
        "Cash And Cash Equivalents": [cash * CR],
        "Stockholders Equity": [equity],
    }
    for key in drop:
        income_rows.pop(key, None)
        cash_rows.pop(key, None)
        bal_rows.pop(key, None)

    info = {
        "currentPrice": price,
        "sharesOutstanding": shares,
        "marketCap": price * shares,
        "beta": beta,
        "sector": sector,
        "shortName": "TEST CO",
        "currency": "INR",
        "dividendRate": dps,
        "trailingEps": trailing_eps if trailing_eps is not None else net_income[0] * CR / shares,
        "fiftyTwoWeekHigh": price * 1.2,
        "fiftyTwoWeekLow": price * 0.8,
    }
    if book_value is not None:
        info["bookValue"] = book_value
    if roe is not None:
        info["returnOnEquity"] = roe
    for key in drop:
        info.pop(key, None)

    return {
        "info": info,
        "income": _frame(income_rows, years),
        "balance": _frame(bal_rows, 1),
        "cashflow": _frame(cash_rows, years),
        "dividends": dividends if dividends is not None else pd.Series(dtype=float),
    }


def make_bank_bundle(**kw) -> dict:
    defaults = dict(sector="Financial Services", book_value=200.0, roe=0.16, dps=4.0, trailing_eps=32.0)
    defaults.update(kw)
    return make_bundle(**defaults)


@pytest.fixture
def bundle():
    return make_bundle()


@pytest.fixture
def bank_bundle():
    return make_bank_bundle()
