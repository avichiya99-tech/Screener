# Engine + Nightly Pipeline Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the valuation engine and daily job into a trustworthy nightly pipeline that writes clean JSON (verdict, bear/base/bull range, confidence, provenance) for a static site to read.

**Architecture:** Keep `valuation_engine.py` as the single valuation module and fix it in place. A new `pipeline/` package fetches data through a source adapter (yfinance today, swappable after the Phase 0 source review), runs the engine, and writes `data/summary.json`, `data/stocks/<SYM>.json`, `data/meta.json`, and a dated history snapshot. A GitHub Action runs it nightly. Plan 2 (static site) consumes only those JSON files.

**Tech Stack:** Python 3.11, pandas, numpy, scipy, yfinance, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-19-static-valuation-site-design.md`

## Global Constraints
- Python 3.11 (matches the workflow). Local machine has only 3.9, so Task 0 sets up 3.11. The code already uses `X | None` syntax.
- Macro inputs live in `config/macro.json` and are never hardcoded in the engine: `rf` 0.07, `erp` 0.055, `terminal_g` 0.05, `mos_pct` 0.25, plus `updated_on`. These are the spec's current values; Phase 0 may replace `rf` with a live 10Y G-sec yield.
- Every engine input is tagged `"reported" | "estimated" | "default"`. Nothing is defaulted silently.
- The JSON must be valid for browsers: NaN and ±inf are written as `null`.
- Do not use screener.in scraping. yfinance-sourced data is marked `"source": "yfinance (unofficial)"` in `meta.json`.
- Universe: the full NIFTY 500 (`MAX_STOCKS` default `0`).
- `export_formula_excel` and `app.py` stay working until Plan 2 retires Streamlit. Update their call sites only where a signature changes.

## Review Focus
1. **A run where most tickers fail** (Yahoo throttling) must not overwrite yesterday's good data. If fewer than 60% of tickers succeed, write nothing and exit non-zero. Tested in Task 6.
2. **NaN, inf, or numpy types in output** must still produce JSON that `json.loads` accepts with `allow_nan` off. Tested in Task 6.
3. **yfinance returns an empty `info` dict without raising.** This must be retried and then logged as a failure, not dropped. Tested in Task 5.
4. **A new listing with fewer than 3 years of statements** must get `meaningful: False` with a reason, not a number. Tested in Task 3.
5. **Negative equity or negative book value** must return invalid with a reason. Tested in Task 2 (bank) and Task 3 (non-financial, negative equity value is allowed but flagged `Low` confidence).

## File map
- Modify `valuation_engine.py`: provenance, growth estimate, 10-year fade DCF, scenarios, verdict, bank persistence, dividend-score fix, reverse solver.
- Create `config/macro.json`, `pipeline/__init__.py`, `pipeline/config.py`, `pipeline/sources/yfinance_source.py`, `pipeline/build.py` (per-ticker record), `pipeline/run.py` (orchestration and writing), `pipeline/jsonsafe.py`.
- Create `tests/conftest.py` (synthetic bundle builder) and `tests/test_*.py`.
- Move `daily_update.yml` to `.github/workflows/daily_update.yml`. The file at the repo root is ignored by GitHub, so the daily job is not running today.
- Turn `update_data.py` into a thin shim that calls `pipeline.run.main()`.
- Modify `app.py` at lines 164-174 (the reverse-solver call site).
- Create `docs/data-sources.md` (Task 1).

---

### Task 0: Python 3.11 env + test harness

**Files:** Create `requirements-dev.txt` (`pytest`), `tests/conftest.py`, `pytest.ini`.

**Interfaces:** Produces `make_bundle(...)` in `tests/conftest.py`.
- Signature: `make_bundle(*, sector="Industrials", price=100.0, shares=1e8, revenue=[1200,1100,1000,900], ebit=[180,165,150,135], pretax=None, tax=None, da=[40,38,36,34], capex=[60,55,50,45], debt=2000.0, cash=500.0, beta=1.0, book_value=None, roe=None, dps=0.0, trailing_eps=None, dividends=None, drop=()) -> dict`
- Lists are newest first, in absolute units (crore-scale numbers multiplied by 1e7 inside).
- It returns the yfinance-shaped bundle `{"info","income","balance","cashflow","dividends"}`, with DataFrames indexed by label and columns as year-end Timestamps (newest first).
- `drop` is a tuple of info keys or statement labels to omit. Use it to simulate missing data.

- [ ] Step 1: Install Python 3.11. Use `brew install python@3.11`, and ask the user before installing. Create `.venv` and run `pip install -r requirements.txt -r requirements-dev.txt`.
- [ ] Step 2: Write `tests/test_smoke.py::test_current_engine_values_fixture`. It asserts that `compute_valuation(make_bundle())["valid"] is True` and that `intrinsic_price > 0`.
- [ ] Step 3: Run `.venv/bin/pytest -q`. Expected: 1 passed. This confirms the fixture matches the current engine before anything changes.
- [ ] Step 4: Commit `chore: add pytest harness and synthetic bundle fixture`.

### Task 1: Phase 0 data-source review (research, no code)

**Files:** Create `docs/data-sources.md`.

- [ ] Step 1: For each candidate source, record availability, fields, history depth, update time, and the exact wording of its terms on automated access and redistribution, with links:
  - NSE EOD price files and the NIFTY 500 list
  - NSE/BSE XBRL financial results ("Integrated Filing – Financials")
  - NSE shareholding pattern
  - RBI/CCIL 10Y G-sec yield
  - yfinance
- [ ] Step 2: Fetch one EOD price file and one XBRL result for RELIANCE and TCS by hand. Note the formats and any blocking (cookies, rate limits).
- [ ] Step 3: Write a recommendation table with one row per field group: prices, statements, shareholding, rf. Each row gives the chosen source, the fallback, and the status `licensed-ok | unclear | not-allowed`.
- [ ] Step 4: **Stop and show the user the table.** Any `unclear` or `not-allowed` row for statements triggers the spec's fallback: the site shows computed outputs, not raw statements. Record their decision in the doc.
- [ ] Step 5: Commit `docs: data source review`.

The remaining tasks do not depend on this outcome. The source adapter in Task 5 isolates it.

### Task 2: Macro config, provenance, financials-model fixes

**Files:** Create `config/macro.json` and `pipeline/config.py`. Modify `valuation_engine.py:232-348`. Test: `tests/test_financials.py`.

**Interfaces:**
- Produces `load_macro(path="config/macro.json") -> dict` with keys `rf, erp, terminal_g, mos_pct, updated_on`.
- Produces `Inputs` in `valuation_engine.py`: a small class with `.set(name, value, status)` and `.as_dict() -> {name: {"value": float, "status": str}}`.
- `compute_valuation(...)` keeps its signature. Its result gains `"inputs"` (from `Inputs.as_dict()`).
- Financials: replace the "75% of spread forever" terminal with an Ohlson persistence fade, constant `ER_PERSISTENCE = 0.7`: `pv_tv_er = (curr_bv*(roe-disc)) / (1 + disc - ER_PERSISTENCE) / (1+disc)**5`. `terminal_g` is no longer used for banks. Note this in the result as `"terminal_method": "persistence_0.7"`.
- Status rules: `beta` is `default` when missing. ROE is `reported` from info, `estimated` from NI/BV, `default` when 0.14 is used. Any value changed by `np.clip` becomes `estimated`. Payout follows the same pattern.

- [ ] Step 1: Write the failing tests.
  - `test_bank_roe_equals_ke_gives_book_value`: set ROE equal to Ke via `driver_override=ke` and `discount_override=ke`. Assert `abs(intrinsic - bvps) < 1e-6`.
  - `test_bank_terminal_uses_persistence`: assert that `result["terminal_method"] == "persistence_0.7"`.
  - `test_missing_beta_marked_default`: assert that `result["inputs"]["beta"]["status"] == "default"`.
  - `test_negative_book_value_invalid`: with `book_value=-5` and negative equity, assert `valid is False`.
- [ ] Step 2: Run `pytest tests/test_financials.py -v`. Expected: FAIL (no `inputs` key, old terminal).
- [ ] Step 3: Implement. Add `Inputs`, record statuses in both models, change the bank terminal, and add `load_macro`. Also update the Excel bank bridge formula at `valuation_engine.py:702` and its label "(25% Fade)" to the persistence formula `=(F21*($B$6-$B$8))/(1+$B$8-0.7)`.
- [ ] Step 4: Run `pytest -q`. Expected: all pass.
- [ ] Step 5: Commit `fix: bank terminal fade, input provenance, macro config`.

### Task 3: Non-financial DCF: robust growth, 10-year fade, meaningfulness

**Files:** Modify `valuation_engine.py:33-46` and `:350-451`. Test: `tests/test_dcf.py`.

**Interfaces:**
- Replace `get_historical_cagr` with `historical_growth(df, labels, default=0.08) -> tuple[float, int, str]`, returning (growth, years_of_history, status).
  - Growth is the **median of year-on-year growth rates**, clipped to [-0.05, 0.25].
  - Status is `reported` when there are at least 3 YoY points, `estimated` when there are 1-2, and `default` otherwise.
- Projection: 10 years. Years 1-5 grow at `rev_g`. Years 6-10 fade linearly from `rev_g` to `terminal_g`, so year-10 growth equals `terminal_g`. Gordon terminal value on year-10 FCFF. `projection_df` has 10 rows.
- Result gains `"meaningful": bool` and `"not_meaningful_reason": str | None`. It is False when any of these hold:
  - latest EBIT ≤ 0: "Loss-making: DCF not meaningful"
  - revenue years < 3: "Less than 3 years of history"
  - sector in `CYCLICAL_SECTORS = {"Basic Materials", "Energy"}`: "Cyclical: earnings swing with commodity prices"
- The value is still computed so the Details view can show it.
- Excel export stays a 5-year model. Add a one-line docstring note that it differs from the site model. Plan 2 may update it.

- [ ] Step 1: Write the failing tests.
  - `test_growth_median_ignores_one_bad_year`: revenue `[1210,1100,1000,500]` (one bad base year). Assert growth ≈ 0.10, ±0.005. The old endpoint CAGR gives about 0.34, which clips to 0.25.
  - `test_projection_has_10_years_and_fades_to_terminal`: assert 10 rows, and that year-10 revenue / year-9 revenue − 1 ≈ `terminal_g`.
  - `test_loss_maker_not_meaningful`: with ebit negative, assert `meaningful is False` and that the reason contains "Loss-making".
  - `test_short_history_not_meaningful`: with `revenue=[1100,1000]`, assert `meaningful is False`.
  - `test_cyclical_not_meaningful`: with `sector="Energy"`, assert `meaningful is False`.
- [ ] Step 2: Run `pytest tests/test_dcf.py -v`. Expected: FAIL.
- [ ] Step 3: Implement.
- [ ] Step 4: Run `pytest -q`. Expected: all pass.
- [ ] Step 5: Commit `feat: median growth, 10y fade DCF, not-meaningful flags`.

### Task 4: Scenarios, verdict, confidence, reverse solver, dividend fix

**Files:** Modify `valuation_engine.py` (new functions after `compute_valuation`, `:191-192`, `:454-479`) and `app.py:164-174`. Test: `tests/test_scenarios.py`, `tests/test_dividend.py`.

**Interfaces:**
- `compute_scenarios(bundle, macro: dict) -> dict` returns `{"bear": float|None, "base": float|None, "bull": float|None, "base_result": dict}`, with per-share values.
  - Non-financials: bear uses growth − 0.04, EBIT margin × 0.85, and discount + 0.01. Bull uses growth + 0.04, margin × 1.10, and discount − 0.01. The base is unchanged.
  - Financials: ROE ∓ 0.03 and Ke ± 0.01.
  - This requires `compute_valuation` to accept `margin_override: float | None = None`.
- `verdict(price, scenarios, meaningful) -> str`:
  - "Not rated" if not meaningful or any scenario value is None
  - "Cheap" if price < bear
  - "Expensive" if price > bull
  - otherwise "Fair"
- `confidence(inputs: dict, meaningful: bool) -> str`:
  - "Low" if not meaningful or 2 or more key inputs are `default`
  - "Medium" if 1 key input is `default` or 2 or more are `estimated`
  - otherwise "High"
  - Key inputs for non-financials: revenue_growth, ebit_margin, tax_rate, beta, da_pct, capex_pct. For financials: roe, beta, payout, bvps.
- `solve_reverse_valuation(bundle, discount_rate, terminal_g) -> dict` returns `{"implied": float|None, "status": "ok"|"above_range"|"below_range"|"invalid"}`, with `implied` in %.
  - Scan drivers from -0.25 to 0.70 in steps of 0.05, skipping invalid points (no more `0.0` fake diffs).
  - Run brentq on the first valid sign-change bracket.
  - Use `above_range` if the price is above the value at 0.70 and `below_range` if below the value at -0.25.
  - Update `app.py:164` to use `["implied"]`, and `update_data`/pipeline likewise.
- Dividend score for financials: `bs_pts = 6` (neutral) instead of `bs_pts = growth_pts`.

- [ ] Step 1: Write the failing tests.
  - `test_scenarios_ordered`: assert `bear < base < bull` for the default bundle and for a bank bundle.
  - `test_verdict_bands`: verdict with price below bear is "Cheap", price above bull is "Expensive", in between is "Fair", and `meaningful=False` gives "Not rated".
  - `test_confidence_low_with_two_defaults`: use `drop=("beta","Tax Provision")` plus a short revenue history, and assert "Low".
  - `test_confidence_high_clean_bundle`: assert "High".
  - `test_reverse_round_trip`: re-run `compute_valuation` with `driver_override=implied/100`. Assert that `intrinsic_price` is within 0.5% of price.
  - `test_reverse_reports_above_range`: with price = 1e6, assert `status == "above_range"` and `implied is None`.
  - `test_fin_dividend_no_double_count`: for a bank with DPS growth ≥ 8%, assert the balance-sheet component is 6 by checking the total score equals the expected sum.
- [ ] Step 2: Run the tests. Expected: FAIL.
- [ ] Step 3: Implement.
- [ ] Step 4: Run `pytest -q`. Expected: all pass.
- [ ] Step 5: Commit `feat: scenarios, verdict, confidence; fix reverse solver and dividend score`.

### Task 5: Source adapter with honest failures

**Files:** Create `pipeline/sources/yfinance_source.py` and `pipeline/build.py`. Test: `tests/test_build.py` (monkeypatched, no network).

**Interfaces:**
- `FetchResult` dataclass: `symbol: str, bundle: dict | None, error: str | None, source: str`.
- `fetch_bundle(symbol: str, retries: int = 3, sleep=time.sleep) -> FetchResult`.
  - Empty `info` or a missing price counts as a failure and is retried.
  - Backoff is 2, 4, then 8 seconds.
  - After the final attempt, return `error="no price after N attempts"` or the exception text.
- `build_record(symbol: str, bundle: dict, macro: dict) -> dict` returns the per-stock detail record (schema below). The summary row is its subset `summary_row(record) -> dict`.
- Record fields:
  - identity: `symbol, name, sector, model, price, market_cap_cr, w52_high, w52_low`
  - verdict: `verdict, confidence, meaningful, not_meaningful_reason`
  - scenarios: `scenarios {bear, base, bull}`, `upside_pct` (base), `mos_buy_price`
  - reverse DCF: `implied_driver {value, status}`, `hist_driver`, `driver_label`
  - inputs: `inputs` (provenance dict)
  - per-share data: `projection` (list of dicts), `dividend {score, badge, flags, yield_pct}`, `eps_dps_history` (list of dicts), `pe`
  - context: `as_of`
- `summary_row` keeps `symbol, name, sector, price, market_cap_cr, verdict, confidence, upside_pct, pe, dividend.badge, dividend.yield_pct, implied_driver.value, hist_driver`.

- [ ] Step 1: Write the failing tests.
  - `test_empty_info_retried_then_failed`: a fake `yf.Ticker` always returns `info={}`. Assert `error` is set, the fetch was attempted 4 times, and `sleep` was called with [2,4,8].
  - `test_build_record_has_schema_keys`: run `build_record` on `make_bundle()`. Assert every key in the schema list above is present.
  - `test_summary_row_subset`.
- [ ] Step 2: Run the tests. Expected: FAIL.
- [ ] Step 3: Implement. `build_record` is the only place that combines `compute_scenarios`, `verdict`, `confidence`, `solve_reverse_valuation`, `compute_dividend_quality`, and `build_historical_eps_div_df`.
- [ ] Step 4: Run `pytest -q`. Expected: all pass.
- [ ] Step 5: Commit `feat: source adapter and per-stock record builder`.

### Task 6: Orchestrator, JSON writing, workflow

**Files:** Create `pipeline/jsonsafe.py` and `pipeline/run.py`. Replace the body of `update_data.py` with `from pipeline.run import main; main()`. Move the workflow to `.github/workflows/daily_update.yml`. Test: `tests/test_run.py`.

**Interfaces:**
- `to_jsonable(obj) -> obj` converts numpy scalars to Python, converts NaN/inf to None, and converts DataFrames to records.
- `write_outputs(records: list[dict], failures: list[dict], out_dir: Path, now: datetime, min_success: float = 0.6) -> bool`
  - Writes `summary.json`, `stocks/<SYM>.json` (symbol without `.NS`), `meta.json` (`as_of`, `count`, `failures`, `sources`, `macro`), and `history/<YYYY-MM-DD>.json`.
  - Writes atomically: build in a temp dir, then swap.
  - Returns False and writes nothing if `success / total < min_success`.
- `main()`:
  - Loads the universe with the existing `load_nifty500_symbols` (moved into `pipeline/run.py`; drop the dated fallback filename and keep `data/nifty500_symbols.csv`).
  - Sets `MAX_STOCKS` default `0`, and uses 4 workers.
  - Wraps each ticker in try/except so one crash becomes a failure entry.
  - Also writes the legacy `data/daily_screener.csv` with its old columns, so `app.py` keeps working until Plan 2.
  - Exits 1 when `write_outputs` returns False.
- Workflow:
  - schedule: same cron
  - `MAX_STOCKS: "0"`
  - `git add data/` instead of the single CSV
  - a step `pytest -q` before the run

- [ ] Step 1: Write the failing tests.
  - `test_nan_becomes_null`: a record containing `float("nan")`, `np.float64(1.5)`, and `np.inf` produces output files that `json.loads(..., parse_constant=raise)` accepts, with `null` in place of NaN/inf.
  - `test_low_success_writes_nothing`: 1 record and 9 failures. Assert the function returns False and leaves `out_dir` unchanged.
  - `test_outputs_written`: 3 records. Assert `summary.json` has 3 rows, `stocks/ABC.json` exists, `meta.json["failures"]` lists the failures, and the history file is named by date.
- [ ] Step 2: Run the tests. Expected: FAIL.
- [ ] Step 3: Implement.
- [ ] Step 4: Run `pytest -q`. Expected: all pass.
- [ ] Step 5: Run a live smoke test, `MAX_STOCKS=20 .venv/bin/python update_data.py`. Expected: at least 12 records written, `data/meta.json` lists any failures, and every file opens with `python -c "import json,glob;[json.load(open(f)) for f in glob.glob('data/**/*.json',recursive=True)]"`.
- [ ] Step 6: Commit `feat: nightly JSON pipeline with failure log and workflow`.

### Task 7: Old-vs-new comparison (verification)

- [ ] Step 1: For 20 large caps, export old intrinsic value (from `git show HEAD~N:data/daily_screener.csv`) next to new base, bear, bull, verdict, and confidence into `docs/engine-v2-comparison.md`. Explain every change above 30%.
- [ ] Step 2: Check the verdict distribution across the 20. If more than 80% land in one bucket, report it to the user before Plan 2. It means the scenario widths need tuning.
- [ ] Step 3: Commit `docs: engine v2 comparison`.

---

**Plan 2 (static site)** gets written after Task 7. Its input is the JSON schema fixed in Task 5 and Task 6.
