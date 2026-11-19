"""Tests for the six deferred minor issues."""
import json
import threading
from datetime import datetime, timezone

import numpy as np
import pytest

from conftest import make_bank_bundle, make_bundle
from pipeline.build import build_record
from pipeline.run import run_all, write_outputs
from valuation_engine import compute_valuation, simulate_values

MACRO = {"rf": 0.07, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}
NOW = datetime(2026, 11, 19, 16, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("make", [make_bundle, make_bank_bundle])
def test_monte_carlo_matches_engine_without_noise(make):
    val = compute_valuation(make(), terminal_g=0.05)
    sims = simulate_values(val, terminal_g=0.05, n=20, seed=1, noise=0.0)
    assert np.allclose(sims, val["intrinsic_price"], rtol=1e-9)


def test_monte_carlo_spread_with_noise():
    val = compute_valuation(make_bundle(), terminal_g=0.05)
    sims = simulate_values(val, terminal_g=0.05, n=2000, seed=42)
    assert np.percentile(sims, 10) < val["intrinsic_price"] < np.percentile(sims, 90)


def test_bank_zero_dividend_payout_reported():
    r = compute_valuation(make_bank_bundle(dps=0.0))
    assert r["inputs"]["payout"] == {"value": 0.0, "status": "reported"}
    assert r["payout_ratio_model"] == 0.0


def test_recovers_stocks_after_crashed_swap(tmp_path):
    rec = build_record("ABC.NS", make_bundle(), MACRO, as_of="2026-11-18")
    assert write_outputs([rec], [], tmp_path, NOW, macro=MACRO, sources={})
    (tmp_path / "stocks").rename(tmp_path / ".stocks-old")  # simulate a crash mid-swap
    failures = [{"symbol": f"F{i}.NS", "error": "x"} for i in range(9)]
    assert write_outputs([rec], failures, tmp_path, NOW, macro=MACRO, sources={}) is False
    assert (tmp_path / "stocks" / "ABC.json").exists()
    assert not (tmp_path / ".stocks-old").exists()


def test_run_all_stops_after_consecutive_failures():
    calls = []
    lock = threading.Lock()

    def always_fail(sym):
        with lock:
            calls.append(sym)
        return None, {"symbol": sym, "error": "blocked"}

    targets = [f"S{i}.NS" for i in range(200)]
    records, legacy, failures, aborted = run_all(targets, always_fail, workers=2, max_consecutive_failures=10)
    assert aborted is True
    assert len(calls) < 30
    assert records == [] and len(failures) >= 10


def test_run_all_completes_when_failures_scattered():
    def process(sym):
        n = int(sym[1:-3])
        if n % 3 == 0:
            return None, {"symbol": sym, "error": "x"}
        return ({"symbol": sym}, {"Ticker": sym}), None

    targets = [f"S{i}.NS" for i in range(60)]
    records, legacy, failures, aborted = run_all(targets, process, workers=2, max_consecutive_failures=10)
    assert aborted is False
    assert len(records) + len(failures) == 60
