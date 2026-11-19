import json
from datetime import datetime, timezone

import numpy as np
import pytest

from conftest import make_bundle
from pipeline.build import build_record
from pipeline.jsonsafe import to_jsonable
from pipeline.run import write_outputs

MACRO = {"rf": 0.07, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}
NOW = datetime(2026, 11, 19, 16, 30, tzinfo=timezone.utc)


def _strict_load(path):
    def bad(c):
        raise ValueError(f"non-JSON constant {c}")

    return json.loads(path.read_text(), parse_constant=bad)


def _record(sym):
    rec = build_record(f"{sym}.NS", make_bundle(), MACRO, as_of="2026-11-19")
    return rec


def test_to_jsonable_converts_nan_inf_numpy():
    out = to_jsonable({"a": float("nan"), "b": np.float64(1.5), "c": np.inf, "d": [np.int64(3), -np.inf]})
    assert out == {"a": None, "b": 1.5, "c": None, "d": [3, None]}
    assert type(out["b"]) is float and type(out["d"][0]) is int


def test_nan_becomes_null(tmp_path):
    rec = _record("ABC")
    rec["pe"] = float("nan")
    rec["upside_pct"] = np.float64(1.5)
    rec["price"] = np.inf
    assert write_outputs([rec], [], tmp_path, NOW, min_success=0.0, macro=MACRO, sources={})
    stock = _strict_load(tmp_path / "stocks" / "ABC.json")
    assert stock["pe"] is None and stock["price"] is None and stock["upside_pct"] == 1.5
    for f in tmp_path.rglob("*.json"):
        _strict_load(f)


def test_low_success_writes_nothing(tmp_path):
    (tmp_path / "summary.json").write_text("[\"yesterday\"]")
    failures = [{"symbol": f"F{i}.NS", "error": "boom"} for i in range(9)]
    ok = write_outputs([_record("ABC")], failures, tmp_path, NOW, macro=MACRO, sources={})
    assert ok is False
    assert (tmp_path / "summary.json").read_text() == "[\"yesterday\"]"
    assert not (tmp_path / "stocks").exists()


def test_outputs_written(tmp_path):
    recs = [_record(s) for s in ("ABC", "DEF", "GHI")]
    failures = [{"symbol": "BAD.NS", "error": "no price after 4 attempts"}]
    assert write_outputs(recs, failures, tmp_path, NOW, macro=MACRO, sources={"prices": "yfinance (unofficial)"})
    summary = _strict_load(tmp_path / "summary.json")
    assert len(summary) == 3
    assert (tmp_path / "stocks" / "ABC.json").exists()
    meta = _strict_load(tmp_path / "meta.json")
    assert meta["failures"] == failures
    assert meta["count"] == 3
    assert meta["macro"]["rf"] == 0.07
    assert meta["as_of"].startswith("2026-11-19")
    assert (tmp_path / "history" / "2026-11-19.json").exists()


def test_stale_stock_files_removed(tmp_path):
    write_outputs([_record("OLD"), _record("ABC")], [], tmp_path, NOW, macro=MACRO, sources={})
    write_outputs([_record("ABC")], [], tmp_path, NOW, macro=MACRO, sources={})
    assert not (tmp_path / "stocks" / "OLD.json").exists()
    assert (tmp_path / "stocks" / "ABC.json").exists()


def test_history_kept_across_runs(tmp_path):
    write_outputs([_record("ABC")], [], tmp_path, NOW, macro=MACRO, sources={})
    later = datetime(2026, 11, 20, 16, 30, tzinfo=timezone.utc)
    write_outputs([_record("ABC")], [], tmp_path, later, macro=MACRO, sources={})
    assert (tmp_path / "history" / "2026-11-19.json").exists()
    assert (tmp_path / "history" / "2026-11-20.json").exists()
