"""Nightly snapshots let the app value NIFTY 500 stocks without calling Yahoo from Streamlit Cloud."""
import json

import pandas as pd
import pytest

from conftest import make_bundle
from pipeline import run
from pipeline.snapshot import get_bundle, load_snapshot, valuation_bundle, write_snapshots
from pipeline.sources.yfinance_source import FetchResult
from valuation_engine import compute_valuation

MACRO = {"rf": 0.068, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}


def _divs():
    return pd.Series([2.0, 2.5], index=pd.to_datetime(["2024-07-15", "2025-07-15"]))


def test_snapshot_round_trip_gives_same_valuation(tmp_path):
    b = valuation_bundle(make_bundle(dividends=_divs()), price=100.0, fx_rate=None)
    write_snapshots({"ABC": b}, tmp_path)
    loaded = load_snapshot("ABC.NS", tmp_path)
    assert compute_valuation(loaded)["intrinsic_price"] == pytest.approx(compute_valuation(b)["intrinsic_price"])
    assert list(loaded["income"].columns) == list(b["income"].columns)  # newest-first order kept
    assert loaded["dividends"].tolist() == [2.0, 2.5]


def test_snapshot_info_is_slim_and_uses_official_price(tmp_path):
    raw = make_bundle()
    raw["info"]["longBusinessSummary"] = "x" * 5000
    write_snapshots({"ABC": valuation_bundle(raw, price=123.4, fx_rate=None)}, tmp_path)
    info = json.loads((tmp_path / "bundles" / "info.json").read_text())["ABC"]
    assert info["currentPrice"] == 123.4
    assert "longBusinessSummary" not in info


def test_snapshot_converts_foreign_currency_statements():
    raw = make_bundle()
    raw["info"].update(financialCurrency="USD", currency="INR")
    b = valuation_bundle(raw, price=100.0, fx_rate=80.0)
    assert b["info"]["financialCurrency"] == "INR"
    assert b["income"].iloc[0, 0] == pytest.approx(raw["income"].iloc[0, 0] * 80.0)


def test_info_merges_with_previous_night(tmp_path):
    write_snapshots({"ABC": valuation_bundle(make_bundle(), price=100.0, fx_rate=None)}, tmp_path)
    write_snapshots({"XYZ": valuation_bundle(make_bundle(), price=50.0, fx_rate=None)}, tmp_path)
    assert load_snapshot("ABC.NS", tmp_path) is not None  # a stock that failed tonight keeps its snapshot
    assert load_snapshot("XYZ", tmp_path)["info"]["currentPrice"] == 50.0


def test_missing_snapshot_returns_none(tmp_path):
    assert load_snapshot("NOPE.NS", tmp_path) is None


def test_get_bundle_prefers_snapshot_over_live(tmp_path):
    write_snapshots({"ABC": valuation_bundle(make_bundle(), price=100.0, fx_rate=None)}, tmp_path)

    def live(sym):
        raise AssertionError("must not call Yahoo for a stock we have a snapshot of")

    bundle, source, error = get_bundle("ABC.NS", tmp_path, live)
    assert bundle is not None and error is None and "nightly" in source


def test_get_bundle_reports_live_failure_instead_of_raising(tmp_path):
    class YFRateLimitError(Exception):
        pass

    def live(sym):
        raise YFRateLimitError("Too Many Requests")

    bundle, source, error = get_bundle("AAPL", tmp_path, live)
    assert bundle is None
    assert "rate" in error.lower() or "busy" in error.lower()


def test_process_records_snapshot(monkeypatch):
    monkeypatch.setattr(run, "fetch_bundle", lambda sym, dividends=None: FetchResult(sym, make_bundle(), None))
    snaps = {}
    ok, fail = run._process("ABC.NS", MACRO, "2026-11-20", closes={"ABC": {"close": 101.0, "date": "2026-11-19"}},
                            snapshots=snaps)
    assert fail is None
    assert snaps["ABC"]["info"]["currentPrice"] == 101.0
