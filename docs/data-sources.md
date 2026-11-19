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

## User decision
_Pending. To be recorded after review._
