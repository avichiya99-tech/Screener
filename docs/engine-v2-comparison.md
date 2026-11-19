# Engine v2 vs v1: top 20 NIFTY 500 stocks by market cap

The run used live yfinance data on 2026-11-19, with the same macro inputs as v1 (rf 7%, ERP 5.5%, terminal growth 5%). The "old value" column is from the committed `data/daily_screener.csv` (v1 engine, same day). Values are per share, in ₹.

| Stock | Model | Price | Old value | New base (bear–bull) | Change | Growth/ROE old→new % | Verdict | Confidence |
|---|---|--:|--:|--:|--:|--|--|--|
| BHARTIARTL | DCF | 2,144 | 2,103 | 2,584 (1,163–5,276) | +23% | 14.9→15.3 | Fair | Medium |
| BAJFINANCE | Bank/NBFC | 1,093 | 770 | 366 (287–465) | -52% | 19.0→19.0 | Expensive | High |
| ADANIPORTS | DCF | 1,917 | 2,943 | 4,478 (2,218–8,659) | +52% | 22.9→25.0 | Cheap | Medium |
| AXISBANK | Bank/NBFC | 1,381 | 1,678 | 1,025 (779–1,338) | -39% | 13.9→13.9 | Expensive | High |
| ADANIPOWER | DCF | 210 | 136 | 153 (58–326) | +12% | 12.5→12.1 | Fair | High |
| ADANIENT | DCF | 2,703 | -703 | -703 (-888–-416) | +0% | -5.0→1.4 | Not rated (Cyclical) | Low |
| HCLTECH | DCF | 1,333 | 2,187 | 2,272 (1,272–4,111) | +4% | 8.7→8.3 | Fair | High |
| ETERNAL | DCF | 367 | 24 | 40 (18–79) | +67% | 25.0→25.0 | Expensive | Medium |
| BAJAJFINSV | Bank/NBFC | 1,885 | 1,412 | 789 (602–1,025) | -44% | 15.2→15.2 | Expensive | High |
| BAJAJ-AUTO | DCF | 10,817 | 14,638 | 21,842 (11,971–38,384) | +49% | 19.5→22.6 | Cheap | High |
| DIVISLAB | DCF | 11,178 | 1,154 | 1,372 (520–2,913) | +19% | 11.0→12.3 | Expensive | Medium |
| BEL | DCF | 404 | 299 | 361 (194–666) | +21% | 15.5→15.9 | Fair | High |
| ASIANPAINT | DCF | 2,595 | 917 | 964 (503–1,817) | +5% | 1.1→2.9 | Not rated (Cyclical) | Low |
| COALINDIA | DCF | 392 | 1,500 | 924 (489–1,745) | -38% | 9.3→0.1 | Not rated (Cyclical) | Low |
| ADANIGREEN | DCF | 1,425 | 207 | 463 (-3–1,209) | +124% | 16.6→18.6 | Expensive | Medium |
| DMART | DCF | 3,500 | -93 | -62 (-273–308) | -33% | 17.1→16.8 | Not rated (Model value is negative) | Low |
| EICHERMOT | DCF | 8,058 | 7,840 | 8,076 (4,306–14,970) | +3% | 17.5→14.5 | Fair | High |
| GRASIM | DCF | 3,111 | 2,039 | 2,848 (-1,397–16,692) | +40% | 14.3→13.6 | Not rated (Cyclical) | Low |
| DLF | DCF | 768 | 333 | 340 (187–613) | +2% | 11.3→10.0 | Expensive | High |
| ADANIENSOL | DCF | 1,473 | 235 | 479 (-118–1,530) | +104% | 25.0→25.0 | Fair | Medium |

**Verdict spread:** 6 Fair, 7 Expensive, 2 Cheap, 5 Not rated. No bucket exceeds 80%, so the scenario widths are not retuned.

## Why values moved more than 30%

| Change | Stocks | Cause |
|---|---|---|
| Banks/NBFCs −39% to −52% | BAJFINANCE, AXISBANK, BAJAJFINSV | Intended fix. v1 kept 75% of the ROE-over-cost-of-equity spread *forever*. v2 lets it fade 30% a year (persistence 0.7). See open question 1. |
| High growers +49% to +124% | ADANIPORTS, BAJAJ-AUTO, ADANIGREEN, ADANIENSOL, ETERNAL | 10 explicit years: years 6–10 fade from the growth driver to 5%, instead of jumping to 5% after year 5. Growth companies get more credit for years 6–10. ADANIPORTS/BAJAJ-AUTO growth also moved (median YoY vs endpoint CAGR). |
| GRASIM +40%, COALINDIA −38% | — | Growth estimate changed (COALINDIA 9.3% → 0.1% median YoY). Both are now Not rated as cyclical anyway. |
| DMART −33% | — | Both versions give a *negative* value. v2 now shows Not rated instead of a negative "intrinsic value". |

## Open questions for review (before Plan 2)

1. **Every financial is "Expensive"** (all 4 of 4 here, High confidence). The 0.7 persistence fade is harsh for franchises like Bajaj Finance that have sustained high ROE for years. Options:
   - keep 0.7 (conservative)
   - use 0.8–0.85 for banks with ≥5 years of ROE above cost of equity
   - show banks as "Not rated" until there is a better model
2. **Sector-level "cyclical" flag is too blunt.** Yahoo classifies Asian Paints and Grasim as "Basic Materials", so they are now Not rated, even though paints are not a commodity business. A better rule: flag only when EBIT margin swings widely over the available history (for example, the standard deviation of margins is above 5 percentage points).
3. **Suspicious data, not model, results:**
   - DIVISLAB (value ₹1,372 vs price ₹11,178, a debt-free company)
   - DMART (negative value; Yahoo's debt likely includes store lease liabilities and capex is high)

   These show the limit of yfinance statements. The confidence badge does not catch them, because the inputs are "reported", just not representative. A data cross-check (Plan 2 or a follow-up) should flag stocks whose value is under 20% of price with High confidence for manual review.
