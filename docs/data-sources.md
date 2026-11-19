# Data sources review (Phase 0)

Reviewed on 2026-11-19. This is not legal advice. It records what each source's own documents say, so the project can choose sources knowingly.

## Findings

| Source | What we'd use it for | Reachable by script? | What its terms say | Status |
|---|---|---|---|---|
| NSE archives: `ind_nifty500list.csv` | NIFTY 500 universe (symbol list) | Yes, HTTP 200 with a browser user-agent | Covered by NSE Data Sharing & Usage Policy (below) | unclear (a list of index members is low-risk; attribute to NSE) |
| NSE archives: daily CM bhavcopy (`BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip`) | Official end-of-day prices | Yes, HTTP 200 (~200 KB/day) | Policy defines "Market Data" to include "end of day data, historical data ... and corporate data". Clause 6.1: "NSE is the sole owner of the Market Data". Clause 7.3: no redistribution "except as agreed in the Relevant Agreement". Clause 8.3: NSE Data "may also consider introducing reduced fee arrangements or waivers for Non-Commercial Users". | not-allowed to republish without an NSE Data agreement |
| NSE / BSE XBRL financial results ("Integrated Filing – Financials") | Statements (P&L, balance sheet, cash flow) | NSE pages time out / need cookies, BSE returns 403 to scripts | NSE counts "corporate data" as Market Data (same policy). BSE terms could not be retrieved (403). | not-allowed / unclear |
| NSE Data & Analytics free API tier | Official fundamentals | Needs sign-up | ~20 calls/day, 1 year history (per vendor comparison, not verified) | too small for 500 stocks nightly |
| FBIL / CCIL 10Y G-sec yield | Risk-free rate | fbil.org.in reachable | Not reviewed in detail. Benchmark is published daily. Third-party trackers put the 10Y around 6.7–6.8% in March 2026 (not verified for November). | use as a manually checked number in `config/macro.json`, citing FBIL |
| yfinance (Yahoo Finance) | Prices + statements today | Yes | Yahoo Developer API terms 1.7.4: may not "derive income from the use or provision of the Yahoo APIs" without permission. 2.2 restricts disclosure to third parties. yfinance README: research/educational use. | unclear for a public site; acceptable only for a free, non-commercial site that shows computed outputs, clearly labelled unofficial |
| Screener.in | — | — | Scraping not permitted by spec | not used |

Sources: [NSE Data Sharing & Usage Policy (PDF)](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing%26Usage_Policy.pdf), [NSE Terms of Use](https://www.nseindia.com/nse-terms-of-use), [NSE data policy page](https://www.nseindia.com/static/market-data/nse-data-policy), [Yahoo Developer API Terms](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html), [CCIL tenor-wise yields](https://www.ccilindia.com/tenorwise-indicative-yields), [vendor comparison of Indian data APIs](https://tapetide.com/compare/best-api-indian-stock-market-data).

## Recommendation

| Field group | Chosen source | Fallback | Status |
|---|---|---|---|
| Prices (EOD) | yfinance, labelled "unofficial" | NSE bhavcopy for internal cross-checks only (not republished) | unclear |
| Statements | yfinance, used only as model inputs | none | unclear → spec fallback applies |
| Shareholding / pledging | not in Plan 1 | — | deferred |
| Risk-free rate | `config/macro.json`, checked monthly against FBIL | 7.0% default, marked `default` | ok |

Because the statements row is not `licensed-ok`, the spec's fallback applies. **The site shows computed outputs** (verdict, fair-value range, ratios, scores), not raw financial statements. The site credits data sources and states it is a free, non-commercial, educational tool, not investment advice.

**The route to fully official data** is to write to NSE Data & Analytics asking for a non-commercial waiver under policy clause 8.3. This is the user's decision.

## User decision (2026-11-20)
The user asked for "the most reliable and professional" sources. Within the free, non-commercial constraint, that is:

| Field | Source now | Why it's the most reliable available | Fallback |
|---|---|---|---|
| Price used for valuation | **NSE official closing price**, from NSE's public daily bhavcopy file (`pipeline/sources/nse_bhavcopy.py`) | The exchange's own settlement close. Yahoo is only cross-checked against it; a gap above 3% is flagged and drops confidence to Low. | yfinance quote, labelled unofficial |
| Risk-free rate | **CCIL 10Y central G-sec benchmark**, fetched every night (`pipeline/sources/ccil_rf.py`) | CCIL is the clearing house for Indian government bonds. State bonds (SGS) are excluded. | `config/macro.json` (7.28%, 2026-11-20) |
| Beta | **Our own regression vs NIFTY 50**: 2 years of weekly returns, Blume-adjusted (`pipeline/sources/beta.py`) | Yahoo's beta for Indian stocks is measured against the US S&P 500 (TCS 0.08, Infosys 0.02), which is meaningless for India. | 1.0, marked `default` |
| Statements | yfinance, converted to rupees when a company reports in USD (Infosys) | No free official alternative can be read by a script (see below). Guarded by automatic data checks. | — |
| Data checks | price vs NSE close, share count vs market cap, results older than 18 months | Any failed check shows the reason and drops confidence to Low. | — |

**Not used, on purpose:** NSE's website APIs (corporate filings, XBRL). They sit behind bot protection that requires harvesting session cookies, and NSE's policy forbids that kind of access. Getting past it would be unauthorized access, so the pipeline only reads NSE's public archive file.

**The route to official statements** is still a licence from NSE Data & Analytics (or a non-commercial waiver under clause 8.3), or a paid licensed vendor. When one is in place, it plugs in as another adapter in `pipeline/sources/` without changing the engine.
