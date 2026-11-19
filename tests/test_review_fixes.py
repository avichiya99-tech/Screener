"""Regression tests for the final-review findings (Important #1-#5)."""
import json
from datetime import datetime, timezone

import pandas as pd

from conftest import make_bank_bundle, make_bundle
from pipeline.build import build_record
from pipeline.run import write_outputs
from pipeline.sources import yfinance_source
from valuation_engine import compute_scenarios, compute_valuation

MACRO = {"rf": 0.07, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}
NOW = datetime(2026, 11, 19, 16, 30, tzinfo=timezone.utc)


class _NoStatementsTicker:
    """Quote endpoint works, statements endpoint throttled: yfinance returns empty frames silently."""
    calls = 0

    def __init__(self, sym):
        type(self).calls += 1
        self.info = make_bundle()["info"]
        self.financials = self.balance_sheet = self.cashflow = pd.DataFrame()
        self.dividends = pd.Series(dtype=float)


def test_empty_statements_count_as_failure(monkeypatch):  # Important #1
    _NoStatementsTicker.calls = 0
    monkeypatch.setattr(yfinance_source.yf, "Ticker", _NoStatementsTicker)
    res = yfinance_source.fetch_bundle("ABC.NS", retries=2, sleep=lambda s: None)
    assert res.bundle is None
    assert "statements" in res.error
    assert _NoStatementsTicker.calls == 3


def test_not_meaningful_publishes_no_fair_values():  # Important #2
    rec = build_record("ABC.NS", make_bundle(revenue=[1100, 1000], ebit=[165, 150], da=[38, 36], capex=[55, 50]),
                       MACRO, as_of="2026-11-19")
    assert rec["verdict"] == "Not rated"
    assert rec["scenarios"] == {"bear": None, "base": None, "bull": None}
    assert rec["upside_pct"] is None and rec["mos_buy_price"] is None


def test_bank_short_history_not_meaningful():  # Important #3
    r = compute_valuation(make_bank_bundle(revenue=(1200,), ebit=(180,), da=(40,), capex=(60,)))
    assert r["meaningful"] is False
    assert "3 years" in r["not_meaningful_reason"]


def test_loss_making_bank_not_meaningful():  # Important #3
    r = compute_valuation(make_bank_bundle(roe=-0.05))
    assert r["meaningful"] is False
    assert "Loss-making" in r["not_meaningful_reason"]


def test_unstable_scenarios_not_rated_with_reason():  # Important #4
    b = make_bundle(debt=8000.0, beta=0.4)  # WACC ~6.4%, close to 5% terminal growth
    assert compute_scenarios(b, MACRO)["unstable_reason"] is not None
    rec = build_record("ABC.NS", b, MACRO, as_of="2026-11-19")
    assert rec["verdict"] == "Not rated"
    assert rec["not_meaningful_reason"]
    assert rec["scenarios"]["bear"] is None


def test_clean_scenarios_stable():  # Important #4
    s = compute_scenarios(make_bundle(), MACRO)
    assert s["unstable_reason"] is None
    assert s["bear"] > 0


def test_every_not_rated_has_reason():  # Important #4
    for b in (make_bundle(), make_bundle(sector="Energy"), make_bundle(debt=8000.0, beta=0.4),
              make_bundle(drop=("Total Revenue",)), make_bank_bundle()):
        rec = build_record("ABC.NS", b, MACRO, as_of="2026-11-19")
        if rec["verdict"] == "Not rated":
            assert rec["not_meaningful_reason"], rec


def test_failed_ticker_carried_forward_as_stale(tmp_path):  # Important #5
    rec = build_record("ABC.NS", make_bundle(), MACRO, as_of="2026-11-18")
    other = build_record("DEF.NS", make_bundle(), MACRO, as_of="2026-11-18")
    assert write_outputs([rec, other], [], tmp_path, NOW, macro=MACRO, sources={})
    other2 = dict(other, as_of="2026-11-19")
    assert write_outputs([other2], [{"symbol": "ABC.NS", "error": "boom"}], tmp_path, NOW,
                         min_success=0.5, macro=MACRO, sources={})
    stale = json.loads((tmp_path / "stocks" / "ABC.json").read_text())
    assert stale["stale_since"] == "2026-11-18"
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert {r["symbol"] for r in summary} == {"ABC", "DEF"}
    assert next(r for r in summary if r["symbol"] == "ABC")["stale_since"] == "2026-11-18"
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["count"] == 1 and meta["stale"] == ["ABC"]
