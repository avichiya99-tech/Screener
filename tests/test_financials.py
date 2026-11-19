import json

from conftest import make_bank_bundle, make_bundle
from valuation_engine import compute_valuation
from pipeline.config import load_macro


def test_bank_roe_equals_ke_gives_book_value():
    b = make_bank_bundle()
    ke = 0.07 + 1.0 * 0.055
    r = compute_valuation(b, driver_override=ke, discount_override=ke)
    assert abs(r["intrinsic_price"] - r["bvps"]) < 1e-6


def test_bank_terminal_uses_persistence():
    r = compute_valuation(make_bank_bundle())
    assert r["terminal_method"] == "persistence_0.7"
    # Persistence fade must value the spread less than the old "75% forever" terminal.
    disc, roe = r["discount_rate"], r["driver"]
    end_bv = r["projection_df"]["End BVPS"].iloc[-1]
    old_pv_tv = end_bv * 0.75 * (roe - disc) / (disc - 0.05) / (1 + disc) ** 5
    assert r["pv_tv_er"] < old_pv_tv


def test_missing_beta_marked_default():
    r = compute_valuation(make_bundle(drop=("beta",)))
    assert r["inputs"]["beta"]["status"] == "default"
    r = compute_valuation(make_bank_bundle(drop=("beta",)))
    assert r["inputs"]["beta"]["status"] == "default"


def test_reported_inputs_marked_reported():
    r = compute_valuation(make_bank_bundle())
    assert r["inputs"]["roe"]["status"] == "reported"
    assert r["inputs"]["bvps"]["status"] == "reported"


def test_negative_book_value_invalid():
    r = compute_valuation(make_bank_bundle(book_value=-5.0))
    assert r["valid"] is False


def test_load_macro(tmp_path):
    p = tmp_path / "macro.json"
    p.write_text(json.dumps({"rf": 0.068, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}))
    m = load_macro(str(p))
    assert m["rf"] == 0.068 and m["updated_on"] == "2026-11-19"


def test_repo_macro_config_has_spec_values():
    m = load_macro()
    assert (m["rf"], m["erp"], m["terminal_g"], m["mos_pct"]) == (0.07, 0.055, 0.05, 0.25)
