# Plan: Free, stable, simple valuation site for Indian traders/investors

## Context
Existing project: `avichiya99-tech/Screener` (Streamlit + yfinance, NIFTY 500, daily CSV via GitHub Actions).
Engine already has FCFF DCF, residual-income model for financials, reverse DCF, sensitivity grid, Monte Carlo,
football field, dividend-quality score, Excel export. (Source read via GitHub raw files; the live Streamlit app is behind a login.)

Goal (user's words): usable by every day trader/investor "at will", simplified, easy-to-understand graphs,
stable and relevant data, free. User approved changing code AND sources. Chosen approach: **rebuild as a static site**
fed by a nightly pipeline. Streamlit retires; the Python engine is kept and reused.

Problems to fix on the way:
- yfinance is unofficial, fails silently, ~5 yrs history, and is research-use only -> not a safe base for a public product.
- Defaults (12% margin, beta 1.0, 14% ROE) silently drive valuations.
- Flat 5-yr growth from a 2-point CAGR, fixed rf/ERP/terminal growth, no scenarios, bank "fade" keeps 75% of spread forever,
  dividend score double-counts growth for financials, reverse solver can return false roots.

## Biggest risk (decide in Phase 0, before building UI)
No source found that is both free AND clearly redistributable for Indian fundamentals.
- NSE bhavcopy/EOD prices: public files, but corporate-data docs say redistribution needs NSE Data & Analytics licence. Terms unverified.
- NSE/BSE XBRL result filings: public filings, access terms for third parties unstated.
- NSE Data & Analytics free tier: ~20 calls/day, 1 yr history (too small for 500 stocks daily).
- Screener.in scraping: likely ToS conflict. Do not use.
- yfinance: keep only as flagged gap-filler, and show "unofficial source" in the UI.
Phase 0 = read the actual ToS of NSE, BSE, RBI/CCIL (G-sec), and pick the sources. If fundamentals cannot be legally
redistributed, fallback: site shows computed outputs (verdict, fair-value range, ratios) rather than raw statements.

## Phases
**0. Data spike (no UI yet).** Verify per source: availability, fields, history depth, terms. Write `docs/data-sources.md`.
Prototype fetching 20 stocks end to end (price, 5+ yrs annual statements, shareholding, 10Y G-sec yield).

**1. Pipeline (Python, GitHub Actions nightly).** Reuse `valuation_engine.py`, `update_data.py`.
- Per-ticker fetch with retries, an explicit failure log, never abort the run on one ticker.
- Full NIFTY 500 (remove 200 default cap), universe list from NSE with local fallback.
- Output versioned JSON: `data/summary.json` (screener rows) + `data/stocks/<SYM>.json` (detail) + `data/meta.json`
  (as-of date, source per field, failures). Keep history so a track-record page is possible.
- Data-quality layer: every input tagged real / estimated / defaulted -> confidence score (High/Med/Low) per stock.
  "DCF not meaningful" for cyclicals, loss-makers, too-short history.

**2. Engine fixes (reuse, don't rewrite).** Growth fade to terminal, bear/base/bull scenarios,
rf from live 10Y G-sec, terminal growth capped by long-run nominal GDP view, fix bank spread persistence,
fix dividend-score double count, reverse solver validity checks. Add unit tests with known fixtures.

**3. Static site (my call: Astro or Next.js static export, Cloudflare Pages/GitHub Pages, free).**
Mobile-first, reads only the JSON files. Screens:
- Home/screener: search box, 3 presets ("Cheap + quality", "Dividend compounders", "Avoid: yield traps"), sortable table with a Cheap/Fair/Expensive chip and confidence badge.
- Stock page, one screen: verdict + fair-value range + one "price vs fair value (bear/base/bull)" bar; plain-English "what the market is pricing in" (reverse DCF); 3 small charts (price vs fair value, earnings/dividend trend, quality scores). Everything else under "Details" (projection, sensitivity grid, Monte Carlo run client-side).
- Methodology + data-source + disclaimer page (not investment advice; as-of date always visible).
- Track record page (past fair values vs later price) once history accrues.

**4. Later/optional:** watchlist in browser localStorage, Excel export, alerts.

## Critical files
- Reuse/modify: `valuation_engine.py`, `update_data.py`, `.github/workflows/daily_update.yml`, `requirements.txt`, `data/`
- New: `site/` (frontend), `pipeline/` (fetchers, quality layer), `tests/`, `docs/data-sources.md`
- Retire: `app.py` (Streamlit) after site parity.

## Verification
- Phase 0: 20-stock prototype matches filings/screener-style sanity numbers for 5 hand-checked companies.
- Engine: pytest fixtures (known inputs -> known value), reverse DCF round-trips to market price, bank model sanity.
- Pipeline: dry run on full NIFTY 500; failure log lists missing tickers; run completes with partial failures.
- Site: build locally, open in browser at desktop and 375px width, check each screen, Lighthouse performance, no console errors.
- Compare outputs of old vs new engine on 20 stocks and explain differences.

## Open items for builder / user
- Final data sources and licence outcome (Phase 0).
- Hosting choice (Cloudflare Pages vs GitHub Pages) and custom domain.
- Scope of first release: recommend Phases 0-3 with ~20 curated stocks first, then full NIFTY 500.
