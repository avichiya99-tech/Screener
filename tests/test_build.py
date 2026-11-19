from conftest import make_bank_bundle, make_bundle
from pipeline.build import RECORD_KEYS, SUMMARY_KEYS, build_record, summary_row
from pipeline.sources import yfinance_source

MACRO = {"rf": 0.07, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}


class _EmptyTicker:
    calls = 0

    def __init__(self, sym):
        type(self).calls += 1
        self.info = {}


class _GoodTicker:
    def __init__(self, sym):
        b = make_bundle()
        self.info = b["info"]
        self.financials, self.balance_sheet, self.cashflow = b["income"], b["balance"], b["cashflow"]
        self.dividends = b["dividends"]


def test_empty_info_retried_then_failed(monkeypatch):
    _EmptyTicker.calls = 0
    monkeypatch.setattr(yfinance_source.yf, "Ticker", _EmptyTicker)
    slept = []
    res = yfinance_source.fetch_bundle("ABC.NS", retries=3, sleep=slept.append)
    assert res.bundle is None
    assert res.error == "no price after 4 attempts"
    assert _EmptyTicker.calls == 4
    assert slept == [2, 4, 8]
    assert res.source == "yfinance (unofficial)"


def test_exception_text_reported(monkeypatch):
    def boom(sym):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(yfinance_source.yf, "Ticker", boom)
    res = yfinance_source.fetch_bundle("ABC.NS", retries=1, sleep=lambda s: None)
    assert res.bundle is None and "rate limited" in res.error


def test_good_fetch(monkeypatch):
    monkeypatch.setattr(yfinance_source.yf, "Ticker", _GoodTicker)
    res = yfinance_source.fetch_bundle("ABC.NS", sleep=lambda s: None)
    assert res.error is None
    assert set(res.bundle) == {"info", "income", "balance", "cashflow", "dividends"}


def test_build_record_has_schema_keys():
    rec = build_record("ABC.NS", make_bundle(), MACRO, as_of="2026-11-19")
    assert set(RECORD_KEYS) <= set(rec)
    assert rec["symbol"] == "ABC"
    assert rec["verdict"] in {"Cheap", "Fair", "Expensive", "Not rated"}
    assert rec["confidence"] in {"High", "Medium", "Low"}
    assert set(rec["scenarios"]) == {"bear", "base", "bull"}
    assert rec["implied_driver"]["status"] in {"ok", "above_range", "below_range", "invalid"}
    assert isinstance(rec["projection"], list) and len(rec["projection"]) == 10


def test_build_record_bank():
    rec = build_record("BANK.NS", make_bank_bundle(), MACRO, as_of="2026-11-19")
    assert rec["model"] == "Excess Return (Fin)"
    assert rec["driver_label"] == "ROE"


def test_build_record_without_price_raises():
    import pytest

    from pipeline.build import RecordError

    with pytest.raises(RecordError, match="price"):
        build_record("ABC.NS", make_bundle(drop=("currentPrice",)), MACRO, as_of="2026-11-19")


def test_build_record_unvaluable_stock_is_not_rated():
    rec = build_record("ABC.NS", make_bundle(drop=("Total Revenue",)), MACRO, as_of="2026-11-19")
    assert rec["verdict"] == "Not rated"
    assert rec["scenarios"] == {"bear": None, "base": None, "bull": None}
    assert rec["not_meaningful_reason"] == "Missing positive revenue data"
    assert rec["confidence"] == "Low"


def test_summary_row_subset():
    rec = build_record("ABC.NS", make_bundle(), MACRO, as_of="2026-11-19")
    row = summary_row(rec)
    assert list(row) == list(SUMMARY_KEYS)
    assert row["dividend_badge"] == rec["dividend"]["badge"]
    assert row["implied_driver"] == rec["implied_driver"]["value"]
