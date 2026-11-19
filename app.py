import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf
from valuation_engine import (
    compute_valuation,
    solve_reverse_valuation,
    compute_dividend_quality,
    build_historical_eps_div_df,
    export_formula_excel,
)

st.set_page_config(page_title="India Valuation & Dividend Workbench", layout="wide")


@st.cache_data(ttl=1800)
def load_daily_screener() -> pd.DataFrame:
    path = "data/daily_screener.csv"
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


@st.cache_data(ttl=3600)
def fetch_bundle(sym: str) -> dict:
    t = yf.Ticker(sym)
    return {
        "info": t.info or {},
        "income": t.financials,
        "balance": t.balance_sheet,
        "cashflow": t.cashflow,
        "dividends": t.dividends,
    }


st.title("India's Open Valuation & Dividend Sustainability Workbench")
st.caption("Reverse DCF Market Expectations • Excess Return for Banks/NBFCs • Dividend Trap Detector • Live-Formula Excel Export")

df_all = load_daily_screener()

st.sidebar.header("1. Margin of Safety & Screener Filters")
mos_pct = st.sidebar.slider("Margin of Safety (MoS %)", 0, 50, 25, 5) / 100

if df_all.empty:
    st.warning("`data/daily_screener.csv` is not generated yet. Run the GitHub Action workflow once to populate the NIFTY 500 screener. Live single-stock deep-dive works right now below.")
    filtered_df = pd.DataFrame()
    ticker_options = ["TCS.NS", "INFY.NS", "ITC.NS", "RELIANCE.NS", "HDFCBANK.NS", "SBIN.NS", "BAJFINANCE.NS"]
else:
    last_upd = df_all["Last Updated (IST)"].iloc[0] if "Last Updated (IST)" in df_all.columns else "Recently"
    st.info(f"Auto-updated weekdays at 4:30 PM IST | Last refresh: **{last_upd}** | Universe: **{len(df_all)} NSE stocks**")

    df_work = df_all.copy()
    mos_col = f"MoS Buy Price ({int(mos_pct*100)}%)"
    df_work[mos_col] = (df_work["Intrinsic Value"] * (1 - mos_pct)).round(2)
    df_work["In MoS Buy Zone"] = df_work["Price"] <= df_work[mos_col]

    sectors = ["All"] + sorted(df_work["Sector"].dropna().unique().tolist())
    sel_sector = st.sidebar.selectbox("Sector", sectors)
    div_classes = ["All", "Compounder", "Stable Payer", "Watchlist", "Yield Trap Risk", "No Dividend"]
    sel_div_cls = st.sidebar.selectbox("Dividend Quality Class", div_classes)
    min_yield = st.sidebar.slider("Min Dividend Yield (%)", 0.0, 10.0, 0.0, 0.25)
    only_mos_zone = st.sidebar.checkbox(f"Only Inside {int(mos_pct*100)}% Margin of Safety Buy Zone", value=False)
    only_pos_gap = st.sidebar.checkbox("Only Low Market Expectations (Expectations Gap > 0%)", value=False)

    filtered_df = df_work.copy()
    if sel_sector != "All":
        filtered_df = filtered_df[filtered_df["Sector"] == sel_sector]
    if sel_div_cls != "All":
        filtered_df = filtered_df[filtered_df["Div Class"] == sel_div_cls]
    filtered_df = filtered_df[filtered_df["Dividend Yield (%)"].fillna(0) >= min_yield]
    if only_mos_zone:
        filtered_df = filtered_df[filtered_df["In MoS Buy Zone"] == True]
    if only_pos_gap:
        filtered_df = filtered_df[filtered_df["Expectations Gap (%)"].fillna(-999) > 0]

    st.subheader("1. NIFTY 500 Market Expectations & Dividend Screener")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Stocks Matching Filters", len(filtered_df))
    p2.metric("In MoS Buy Zone", int(filtered_df["In MoS Buy Zone"].sum()))
    p3.metric("Dividend Compounders", int((filtered_df["Div Class"] == "Compounder").sum()))
    p4.metric("Yield Trap Warnings", int((filtered_df["Div Class"] == "Yield Trap Risk").sum()))

    c1, c2 = st.columns([2, 1])
    with c1:
        sort_by = st.selectbox(
            "Sort Screener By:",
            [
                "Expectations Gap (%)",
                "Dividend Yield (%)",
                "Div Quality Score",
                "Valuation Upside (%)",
                "Annual DPS",
                "Payout Ratio (%)",
                "Trailing EPS",
                "% Below 52W High",
                "Market Cap (Cr)",
            ],
        )
    with c2:
        asc = st.radio("Order:", ["Highest First", "Lowest First"], horizontal=True) == "Lowest First"

    drop_cols = {"Last Updated (IST)", "MoS Buy Price (25%)"}
    display_cols = [c for c in filtered_df.columns if c not in drop_cols]
    filtered_df = filtered_df.sort_values(by=sort_by, ascending=asc, na_position="last").reset_index(drop=True)
    st.dataframe(filtered_df[display_cols], use_container_width=True, height=420)
    ticker_options = filtered_df["Ticker"].tolist() if not filtered_df.empty else df_all["Ticker"].tolist()

# --- Section 2: Live Single-Stock Deep-Dive ---
st.divider()
st.subheader("2. Live Valuation Sandbox & Reverse DCF Deep-Dive")

d1, d2 = st.columns([2, 1])
with d1:
    selected_ticker = st.selectbox("Select stock from screener:", ticker_options)
with d2:
    custom_ticker = st.text_input("Or enter any NSE/Global ticker (e.g., BAJFINANCE.NS, AAPL):", value="").strip().upper()

active_ticker = custom_ticker if custom_ticker else selected_ticker

st.sidebar.divider()
st.sidebar.header("2. Deep-Dive Assumptions")
rf_rate = st.sidebar.slider("Risk-Free Rate (10Y G-Sec %)", 4.0, 10.0, 7.0, 0.1) / 100
erp_rate = st.sidebar.slider("Equity Risk Premium (%)", 3.0, 9.0, 5.5, 0.1) / 100
term_g = st.sidebar.slider("Terminal Growth Rate (%)", 2.0, 7.0, 5.0, 0.25) / 100

with st.spinner(f"Running live valuation engine for {active_ticker}..."):
    bundle = fetch_bundle(active_ticker)
    base_val = compute_valuation(bundle, rf=rf_rate, erp=erp_rate, terminal_g=term_g, mos_pct=mos_pct)

if not base_val.get("valid"):
    st.error(f"Cannot run valuation for {active_ticker}: {base_val.get('reason')}")
    st.stop()

driver_name = "Expected 5Y ROE (%)" if base_val["is_financial"] else "5Y Revenue Growth Rate (%)"
disc_name = "Cost of Equity Ke (%)" if base_val["is_financial"] else "WACC (%)"

min_drv = 4.0 if base_val["is_financial"] else -5.0
default_drv = float(np.clip(round(base_val["driver"] * 100, 1), min_drv, 35.0))
default_disc = float(np.clip(round(base_val["discount_rate"] * 100, 2), 6.0, 28.0))

s1, s2 = st.columns(2)
with s1:
    ov_driver = st.slider(f"Override {driver_name}", min_drv, 35.0, default_drv, 0.5) / 100
with s2:
    ov_disc = st.slider(f"Override {disc_name}", 6.0, 28.0, default_disc, 0.25) / 100

val = compute_valuation(
    bundle,
    rf=rf_rate,
    erp=erp_rate,
    terminal_g=term_g,
    driver_override=ov_driver,
    discount_override=ov_disc,
    mos_pct=mos_pct,
)
if not val.get("valid"):
    st.error(val.get("reason"))
    st.stop()

dq = compute_dividend_quality(bundle, val)
implied_driver = solve_reverse_valuation(bundle, val["discount_rate"], terminal_g=term_g)["implied"]
curr = "₹" if val["currency"] == "INR" else f"{val['currency']} "

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Current Price", f"{curr}{val['price']:,.2f}")
k2.metric(f"{val['model']} Value", f"{curr}{val['intrinsic_price']:,.2f}", f"{val['upside_pct']:+.1f}%")
k3.metric(f"MoS Buy Price ({int(mos_pct*100)}%)", f"{curr}{val['mos_buy_price']:,.2f}")
k4.metric(
    f"Market Implied {val['driver_label']}",
    f"{implied_driver}%" if implied_driver is not None else "N/A",
    f"vs {val['hist_driver']*100:.1f}% Hist" if implied_driver is not None else None,
)
k5.metric("Dividend Quality", f"{dq['score']}/100" if dq["score"] is not None else "N/A", dq["badge"])

if dq["flags"]:
    st.warning(f"Dividend Risk Flags for {active_ticker}: **{', '.join(dq['flags'])}**")

proj = val["projection_df"].copy()
if not val["is_financial"]:
    scale = 1e7 if val["currency"] == "INR" else 1e6
    for c in ["Revenue", "EBIT", "NOPAT", "D&A", "CapEx", "Delta NWC", "FCFF", "PV of FCFF"]:
        proj[c] = (proj[c] / scale).round(2)
else:
    for c in ["Begin BVPS", "Projected EPS", "Projected DPS", "Excess Return", "PV of Excess Return", "End BVPS"]:
        proj[c] = proj[c].round(2)

hist_df = build_historical_eps_div_df(bundle)

tab1, tab2, tab3, tab4 = st.tabs([
    "Projection & Football Field",
    "Sensitivity Matrix",
    "Monte Carlo Simulation",
    "Historical EPS & Dividends",
])

with tab1:
    unit_note = "(Per-Share Excess Return)" if val["is_financial"] else f"({curr} {'Crores' if val['currency']=='INR' else 'Millions'})"
    st.markdown(f"**5-Year Forecast {unit_note}**")
    st.dataframe(proj, use_container_width=True, hide_index=True)

    w52_lo, w52_hi = bundle["info"].get("fiftyTwoWeekLow"), bundle["info"].get("fiftyTwoWeekHigh")
    ff_l, ff_lo, ff_hi = [], [], []
    if w52_lo and w52_hi:
        ff_l.append("52-Week Trading Range"); ff_lo.append(w52_lo); ff_hi.append(w52_hi)
    ff_l.append(f"{val['model']} (±15%)"); ff_lo.append(val["intrinsic_price"] * 0.85); ff_hi.append(val["intrinsic_price"] * 1.15)
    ff_l.append(f"MoS Buy Zone ({int(mos_pct*100)}%)"); ff_lo.append(val["mos_buy_price"] * 0.90); ff_hi.append(val["mos_buy_price"])
    if not df_all.empty and (bundle["info"].get("trailingEps") or 0) > 0:
        med_pe = df_all["P/E"].dropna().median()
        if pd.notna(med_pe):
            pe_v = med_pe * bundle["info"]["trailingEps"]
            ff_l.append("NIFTY Median P/E (±15%)"); ff_lo.append(pe_v * 0.85); ff_hi.append(pe_v * 1.15)

    fig_ff = go.Figure()
    for lbl, lo_v, hi_v in zip(ff_l, ff_lo, ff_hi):
        fig_ff.add_trace(go.Bar(
            y=[lbl], x=[max(hi_v - lo_v, 1.0)], base=[lo_v], orientation="h",
            text=[f"{curr}{lo_v:,.0f} – {curr}{hi_v:,.0f}"], textposition="inside",
        ))
    fig_ff.add_vline(x=val["price"], line_dash="dash", line_color="red", annotation_text=f"CMP: {curr}{val['price']:,.0f}")
    fig_ff.update_layout(title=f"{active_ticker} Football Field Valuation Summary", showlegend=False, height=340)
    st.plotly_chart(fig_ff, use_container_width=True)

with tab2:
    d_steps = [val["discount_rate"] + d for d in (-0.02, -0.01, 0, 0.01, 0.02)]
    g_steps = [term_g + d for d in (-0.01, -0.005, 0, 0.005, 0.01)]
    z = []
    for disc_s in d_steps:
        row_vals = []
        for g_s in g_steps:
            if disc_s <= g_s:
                row_vals.append(np.nan)
            else:
                res_s = compute_valuation(
                    bundle, rf=rf_rate, erp=erp_rate, terminal_g=g_s,
                    driver_override=ov_driver, discount_override=disc_s, mos_pct=mos_pct
                )
                row_vals.append(round(res_s["intrinsic_price"], 2) if res_s.get("valid") else np.nan)
        z.append(row_vals)

    y_prefix = "Ke" if val["is_financial"] else "WACC"
    fig_s = go.Figure(go.Heatmap(
        z=z,
        x=[f"g={g*100:.1f}%" for g in g_steps],
        y=[f"{y_prefix}={d*100:.1f}%" for d in d_steps],
        text=z, texttemplate="%{text}", colorscale="RdYlGn", zmid=val["price"],
    ))
    fig_s.update_layout(title=f"Implied Share Price Sensitivity ({y_prefix} vs Terminal Growth)", height=360)
    st.plotly_chart(fig_s, use_container_width=True)

with tab3:
    rng = np.random.default_rng(42)
    n = 5000
    if val["is_financial"]:
        roes = np.clip(rng.normal(val["driver"], 0.02, n), 0.04, 0.35)
        kes = np.maximum(rng.normal(val["discount_rate"], 0.01, n), term_g + 0.01)
        bv = np.full(n, val["bvps"], dtype=float)
        pv_er = np.zeros(n)
        for yr in range(1, 6):
            er = bv * (roes - kes)
            pv_er += er / ((1 + kes) ** yr)
            bv = bv + (bv * roes) * (1 - val["payout_ratio_model"])
        tv_er = (bv * 0.75 * (roes - kes)) / (kes - term_g)
        sims = val["bvps"] + pv_er + tv_er / ((1 + kes) ** 5)
    else:
        rg = rng.normal(val["driver"], 0.03, n)
        em = np.clip(rng.normal(val["ebit_margin"], 0.02, n), 0.01, 0.65)
        wa = np.maximum(rng.normal(val["discount_rate"], 0.01, n), term_g + 0.01)
        pv_tot, crev = np.zeros(n), np.full(n, val["base_revenue"], dtype=float)
        for yr in range(1, 6):
            prev = crev
            crev = prev * (1 + rg)
            fcff = crev * em * (1 - val["tax_rate"]) + crev * (val["da_pct"] - val["capex_pct"]) - (crev - prev) * val["nwc_pct"]
            pv_tot += fcff / ((1 + wa) ** yr)
        sims = (pv_tot + ((fcff * (1 + term_g)) / (wa - term_g)) / ((1 + wa) ** 5) - (val["total_debt"] - val["cash"])) / val["shares"]

    lo, hi = np.percentile(sims, [1, 99])
    sims = sims[(sims >= lo) & (sims <= hi)]
    p10, med, p90 = np.percentile(sims, [10, 50, 90])
    prob = float(np.mean(sims > val["price"]) * 100)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Bear (P10)", f"{curr}{p10:,.0f}")
    m2.metric("Median Value", f"{curr}{med:,.0f}")
    m3.metric("Bull (P90)", f"{curr}{p90:,.0f}")
    m4.metric("Prob. Undervalued", f"{prob:.1f}%")

    fig_mc = go.Figure(go.Histogram(x=sims, nbinsx=55, marker_color="#4C78A8"))
    fig_mc.add_vline(x=val["price"], line_dash="dash", line_color="red", annotation_text=f"CMP: {curr}{val['price']:,.0f}")
    fig_mc.add_vline(x=med, line_color="green", annotation_text=f"Median: {curr}{med:,.0f}")
    fig_mc.update_layout(height=360, xaxis_title=f"Simulated Share Price ({curr})", yaxis_title="Frequency")
    st.plotly_chart(fig_mc, use_container_width=True)

with tab4:
    if hist_df.empty:
        st.info("No historical EPS or dividend data available.")
    else:
        fig_h = make_subplots(specs=[[{"secondary_y": True}]])
        fig_h.add_trace(go.Bar(x=hist_df["Year"], y=hist_df["EPS"], name="EPS", marker_color="#4C78A8"), secondary_y=False)
        fig_h.add_trace(go.Bar(x=hist_df["Year"], y=hist_df["Annual DPS"], name="Annual DPS", marker_color="#54A24B"), secondary_y=False)
        fig_h.add_trace(go.Scatter(x=hist_df["Year"], y=hist_df["Payout Ratio (%)"], name="Payout Ratio (%)", mode="lines+markers", line=dict(color="#F58518")), secondary_y=True)
        fig_h.update_layout(barmode="group", height=360)
        st.plotly_chart(fig_h, use_container_width=True)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)

st.divider()
excel_bytes = export_formula_excel(filtered_df, val, hist_df, active_ticker, mos_pct=mos_pct)
st.download_button(
    label=f"Download Live-Formula Excel Model for {active_ticker} (.xlsx)",
    data=excel_bytes,
    file_name=f"Live_Model_{active_ticker}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
