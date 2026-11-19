# India Valuation Screener

A free, nightly valuation of every NIFTY 500 stock: a **Cheap / Fair / Expensive / Not rated** verdict, a bear–base–bull fair-value range, and a confidence badge that says how much of the input data was reported rather than guessed.

## How it values a stock
- **Companies:** 10-year free-cash-flow DCF. Revenue growth is held for 5 years, then fades to long-run growth. Cyclical sectors use average margins across the years available.
- **Banks, NBFCs, insurers:** 3-stage excess-return model. ROE is held for 5 years, then fades to a stable ROE that keeps half of today's edge over the cost of equity.
- **Verdict:** Cheap below the bear value, Expensive above the bull value, otherwise Fair. "Not rated" always comes with a reason (loss-making, short history, volatile cyclical, too sensitive to assumptions).

## Data
| Input | Source |
|---|---|
| Price used for valuation | NSE official closing price (public daily bhavcopy) |
| Risk-free rate | CCIL 10-year government bond yield, fetched nightly |
| Beta | Our regression against the NIFTY 50 (2 years, weekly, Blume-adjusted) |
| Financial statements, dividends | Yahoo Finance via `yfinance` (unofficial), with automatic data checks |

See `docs/data-sources.md` for the licence review. The site shows computed outputs only. Not investment advice.

## Layout
- `valuation_engine.py`: the models, scenarios, reverse DCF, Monte Carlo, dividend score and Excel export
- `pipeline/`: the nightly job (`python update_data.py`); writes `data/summary.json`, `data/stocks/<SYM>.json`, `data/meta.json`, `data/history/`
- `app.py`: Streamlit workbench (`streamlit run app.py`)
- `.github/workflows/daily_update.yml`: runs tests, then the pipeline, every weekday at 7:00 PM IST

## Develop
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
MAX_STOCKS=20 .venv/bin/python update_data.py   # quick run on 20 stocks
```
