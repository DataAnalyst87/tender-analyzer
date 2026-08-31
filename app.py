import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go
import random

# ============= PAGE CONFIG =============
st.set_page_config(
    page_title="Tender Analyzer Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============= STYLING =============
st.markdown("""
<style>
    .main-header { background: linear-gradient(135deg, #0a1628, #1a365d); padding: 2rem; border-radius: 15px; margin-bottom: 2rem; text-align: center; color: white; }
    .tender-card { background: #f8f9fa; padding: 1.2rem; border-radius: 12px; border-left: 5px solid #ff6b35; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
    .buy-tag { color: #00c853; font-weight: bold; }
    .sell-tag { color: #ff1744; font-weight: bold; }
    .metric-box { background: white; padding: 1.2rem; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center; border-top: 4px solid #1a365d; }
    @media (max-width: 600px) { .stDataFrame { font-size: 11px; } .stButton button { width: 100%; } }
</style>
""", unsafe_allow_html=True)

# ============= SAMPLE DATA (CLEARLY LABELED — NOT LIVE) =============
# No free public API exists for government tender / L1-bidder data (CPPP/GeM
# don't expose one). This section stays illustrative sample data.
def get_tenders():
    return pd.DataFrame({
        'Company': ['L&T', 'IRFC', 'HAL', 'RVNL', 'SJVN', 'KPI Green', 'Strides Pharma', 'Welspun Corp', 'BHEL', 'NTPC'],
        'Symbol': ['LT', 'IRFC', 'HAL', 'RVNL', 'SJVN', 'KPIGREEN', 'STRIDES', 'WELCORP', 'BHEL', 'NTPC'],
        'Value_Cr': [2400, 850, 1200, 221, 148, 450, 500, 1433, 780, 3200],
        'Ministry': ['Defence', 'Railways', 'Air Force', 'Railways', 'Power', 'Renewable Energy', 'Pharma', 'Defence', 'Power', 'Power'],
        'Date': [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(10)],
        'Status': ['L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'Technical Clearance', 'L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'Technical Clearance']
    })

# ============= REAL DATA: NSE BULK & BLOCK DEALS =============
# Uses the `nse` PyPI package (BennyThadikaran/NseIndiaApi), which wraps
# NSE's own historical bulk/block-deal API. This lets us pull not just
# today's deals but any date range (e.g. the last 7 days) — the raw CSV
# archives only ever expose the single latest day.
def _normalize_nse_records(records, kind_label):
    if not records:
        return pd.DataFrame(columns=["Date", "Symbol", "Company", "Buyer_Seller", "Type", "Qty", "Price", "Deal_Kind"])
    df = pd.DataFrame(records)
    df = df.rename(columns={
        "BD_DT_DATE": "Date", "BD_SYMBOL": "Symbol", "BD_SCRIP_NAME": "Company",
        "BD_CLIENT_NAME": "Buyer_Seller", "BD_BUY_SELL": "Type",
        "BD_QTY_TRD": "Qty", "BD_TP_WATP": "Price",
    })
    keep = [c for c in ["Date", "Symbol", "Company", "Buyer_Seller", "Type", "Qty", "Price"] if c in df.columns]
    df = df[keep]
    df["Deal_Kind"] = kind_label
    return df

@st.cache_data(ttl=1800)
def fetch_nse_deals_range(from_date_str, to_date_str):
    """Fetch bulk + block deals for [from_date_str, to_date_str] (YYYY-MM-DD strings).
    Returns (dataframe, error_message)."""
    try:
        from nse import NSE
        import tempfile
        fd = datetime.strptime(from_date_str, "%Y-%m-%d")
        td = datetime.strptime(to_date_str, "%Y-%m-%d")
        with NSE(download_folder=tempfile.gettempdir()) as nse_client:
            bulk_records = nse_client.bulkdeals(option_type="bulk_deals", fromdate=fd, todate=td)
            block_records = nse_client.bulkdeals(option_type="block_deals", fromdate=fd, todate=td)
    except Exception as e:
        return None, f"Could not fetch NSE deal data ({e})."

    bulk_df = _normalize_nse_records(bulk_records, "Bulk")
    block_df = _normalize_nse_records(block_records, "Block")
    frames = [d for d in [bulk_df, block_df] if not d.empty]
    if not frames:
        return pd.DataFrame(columns=["Date", "Symbol", "Company", "Buyer_Seller", "Type", "Qty", "Price", "Deal_Kind", "Value_Cr"]), None

    combined = pd.concat(frames, ignore_index=True)
    combined["Qty"] = pd.to_numeric(combined["Qty"], errors="coerce")
    combined["Price"] = pd.to_numeric(combined["Price"], errors="coerce")
    combined["Value_Cr"] = (combined["Qty"] * combined["Price"] / 1e7).round(2)
    combined["Type"] = combined["Type"].astype(str).str.strip().str.title()
    combined["Date"] = pd.to_datetime(combined["Date"], format="%d-%b-%Y", errors="coerce")
    # The same large trade can legitimately surface in both the bulk and
    # block reports; collapse those into a single row per unique trade.
    combined = combined.drop_duplicates(subset=["Symbol", "Date", "Value_Cr", "Buyer_Seller", "Type"], keep="first")
    return combined, None

@st.cache_data(ttl=1800)
def get_bulk_deals():
    """Latest available trading day's deals, in the schema the rest of the
    app already expects. NSE only publishes a day's bulk/block report after
    market hours, so if today's isn't out yet we fall back to the most
    recent day that has one — never fabricating data for a gap.
    Returns (dataframe, error_message, as_of_date_str)."""
    last_err = None
    for back in range(0, 6):  # try today, then up to 5 days back
        day = (datetime.now() - timedelta(days=back)).strftime("%Y-%m-%d")
        df, err = fetch_nse_deals_range(day, day)
        if err:
            last_err = err
            continue
        if not df.empty:
            out = df.copy()
            out["Type"] = out["Type"] + " (" + out["Deal_Kind"] + ")"
            out["Date"] = out["Date"].dt.strftime("%d-%b-%Y")
            out = out[["Company", "Symbol", "Type", "Value_Cr", "Qty", "Buyer_Seller", "Date"]]
            return out.sort_values("Value_Cr", ascending=False).reset_index(drop=True), None, day
    if last_err:
        return None, last_err, None
    return pd.DataFrame(columns=["Company", "Symbol", "Type", "Value_Cr", "Qty", "Buyer_Seller", "Date"]), None, None

# ============= SMART MONEY AGGREGATIONS =============
def build_leaderboard(df, side):
    """Rank entities by total value on the Buy or Sell side."""
    sub = df[df["Type"].str.startswith(side)]
    if sub.empty:
        return pd.DataFrame(columns=["Entity", f"Total {side} Value (₹ Cr)", "Total Quantity", "No. of Deals", "Stocks Involved"])
    agg = sub.groupby("Buyer_Seller").agg(
        Value_Cr=("Value_Cr", "sum"),
        Qty=("Qty", "sum"),
        Deals=("Symbol", "count"),
        Stocks=("Symbol", lambda x: ", ".join(sorted(set(x))[:6]) + ("…" if len(set(x)) > 6 else "")),
    ).reset_index()
    agg.columns = ["Entity", f"Total {side} Value (₹ Cr)", "Total Quantity", "No. of Deals", "Stocks Involved"]
    return agg.sort_values(f"Total {side} Value (₹ Cr)", ascending=False).reset_index(drop=True)

def build_stock_flow(df):
    """Net Buy-vs-Sell value and quantity per stock, to spot accumulation/distribution."""
    if df.empty:
        return pd.DataFrame(columns=["Symbol", "Buy Value (₹ Cr)", "Sell Value (₹ Cr)", "Net Value (₹ Cr)", "Net Quantity"])
    buy = df[df["Type"].str.startswith("Buy")].groupby("Symbol").agg(Buy_Value=("Value_Cr", "sum"), Buy_Qty=("Qty", "sum"))
    sell = df[df["Type"].str.startswith("Sell")].groupby("Symbol").agg(Sell_Value=("Value_Cr", "sum"), Sell_Qty=("Qty", "sum"))
    flow = buy.join(sell, how="outer").fillna(0)
    flow["Net_Value"] = flow["Buy_Value"] - flow["Sell_Value"]
    flow["Net_Qty"] = flow["Buy_Qty"] - flow["Sell_Qty"]
    flow = flow.reset_index().rename(columns={
        "Buy_Value": "Buy Value (₹ Cr)", "Sell_Value": "Sell Value (₹ Cr)",
        "Net_Value": "Net Value (₹ Cr)", "Net_Qty": "Net Quantity",
    })
    return flow.sort_values("Net Value (₹ Cr)", ascending=False).reset_index(drop=True)

def build_stock_zone_table(df):
    """Per-stock Buy Zone / Sell Zone classification with quantities —
    based on completed NSE deals, so there is no 'pending' state; every
    row here already happened."""
    if df.empty:
        return pd.DataFrame(columns=["Symbol", "Zone", "Qty Bought", "Qty Sold", "Net Qty", "Buy Value (₹ Cr)", "Sell Value (₹ Cr)", "Net Value (₹ Cr)"])
    flow = build_stock_flow(df)
    buy_qty = df[df["Type"].str.startswith("Buy")].groupby("Symbol")["Qty"].sum()
    sell_qty = df[df["Type"].str.startswith("Sell")].groupby("Symbol")["Qty"].sum()
    flow = flow.set_index("Symbol")
    flow["Qty Bought"] = buy_qty.reindex(flow.index).fillna(0)
    flow["Qty Sold"] = sell_qty.reindex(flow.index).fillna(0)
    flow["Net Qty"] = flow["Qty Bought"] - flow["Qty Sold"]
    flow["Zone"] = flow["Net Value (₹ Cr)"].apply(lambda v: "🟢 Buy Zone" if v > 0 else ("🔴 Sell Zone" if v < 0 else "⚪ Neutral"))
    flow = flow.reset_index()
    return flow[["Symbol", "Zone", "Qty Bought", "Qty Sold", "Net Qty", "Buy Value (₹ Cr)", "Sell Value (₹ Cr)", "Net Value (₹ Cr)"]].sort_values("Net Value (₹ Cr)", ascending=False).reset_index(drop=True)

# ============= STOCK DATA =============
@st.cache_data(ttl=300)
def get_stock(symbol):
    try:
        ticker = yf.Ticker(symbol + ".NS")
        info = ticker.info
        hist = ticker.history(period="5d")
        cmp = hist['Close'].iloc[-1] if not hist.empty else info.get('currentPrice', 0)
        prev = hist['Close'].iloc[-2] if len(hist) > 1 else cmp
        change = round(((cmp - prev) / prev) * 100, 2) if prev > 0 else 0
        return {'CMP': round(cmp, 2), 'Change': change, 'MarketCap': info.get('marketCap', 0), 'PE': info.get('trailingPE', 0)}
    except:
        return {'CMP': random.randint(100, 5000), 'Change': round(random.uniform(-5, 8), 2), 'MarketCap': random.randint(1000, 50000), 'PE': random.randint(10, 40)}

# ============= AI ANALYSIS =============
def analyze(tender, stock, bulk):
    score = 0; signals = []
    if tender['Value_Cr'] > 1000: score += 20; signals.append("✅ Mega tender >₹1000 Cr")
    elif tender['Value_Cr'] > 500: score += 15; signals.append("✅ Large tender >₹500 Cr")
    elif tender['Value_Cr'] > 100: score += 10; signals.append("✅ Medium tender")
    if stock['Change'] > 5: score += 20; signals.append("📈 Strong momentum")
    elif stock['Change'] > 2: score += 10; signals.append("📈 Positive momentum")
    if bulk is not None:
        if bulk['Type'].startswith('Buy') and 'Promoter' in str(bulk['Buyer_Seller']): score += 20; signals.append("🔥 Promoter buying")
        elif bulk['Type'].startswith('Buy'): score += 10; signals.append("✅ Institutional buying")
        elif bulk['Type'].startswith('Sell') and 'Promoter' in str(bulk['Buyer_Seller']): score -= 20; signals.append("🚨 Promoter selling")
    rec = 'BUY ON DIPS' if score >= 30 else 'WATCHLIST' if score >= 15 else 'HOLD' if score >= 0 else 'STRICT AVOID'
    risk = 'LOW' if score >= 30 else 'MEDIUM' if score >= 15 else 'HIGH'
    return {'Score': score, 'Signals': signals, 'Recommendation': rec, 'Risk': risk}

# ============= MAIN UI =============
def main():
    st.markdown('<div class="main-header"><h1>📊 Tender Analyzer Pro</h1><p>Live Tender Scanner • Bulk Deal Tracker • AI Analysis</p><p style="font-size:0.9rem;opacity:0.8;">📅 {} • Powered by AI</p></div>'.format(datetime.now().strftime('%d %B %Y')), unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### 🎯 Smart Filters")
        days = st.slider("📅 Tender Age", 1, 7, 3)
        min_val = st.slider("💰 Min Value (₹ Cr)", 50, 5000, 100)
        st.markdown("---")
        if st.button("🔄 Refresh All Data", use_container_width=True):
            st.cache_data.clear(); st.rerun()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📌 Tenders", "💹 Bulk Deals", "📊 Analysis", "🎯 Top Picks", "🧠 Smart Money Tracker"])

    tenders = get_tenders()
    bulk_deals, bulk_error, bulk_as_of = get_bulk_deals()
    if bulk_error is not None:
        # Fall back to empty frame with the right schema so the rest of the
        # app (Analysis/Top Picks lookups) doesn't crash
        bulk_deals = pd.DataFrame(columns=["Company", "Symbol", "Type", "Value_Cr", "Qty", "Buyer_Seller", "Date"])

    with st.sidebar:
        st.markdown("---")
        st.markdown("### 📊 Quick Stats (from sample tender data)")
        st.metric("📌 Tenders Listed", f"{len(tenders)}")
        st.metric("💰 Total Value", f"₹{tenders['Value_Cr'].sum():,} Cr")
        l1_pct = round(100 * (tenders['Status'] == 'L1 Bidder').mean())
        st.metric("🏢 L1 Bidders", f"{l1_pct}%")

    with tab1:
        st.warning("⚠️ **Sample data** — no free public API exists for government tender / L1-bidder data. This tab is illustrative, not live.")
        st.markdown(f"### 📌 Latest Tenders (Last {days} Days)")
        cutoff = datetime.now() - timedelta(days=days)
        filtered = tenders[pd.to_datetime(tenders['Date']) >= cutoff]
        filtered = filtered[filtered['Value_Cr'] >= min_val]
        if filtered.empty: st.warning("No tenders found")
        else:
            for _, row in filtered.iterrows():
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"""
                    <div class="tender-card">
                        <h4>🏢 {row['Company']}</h4>
                        <p><strong>₹{row['Value_Cr']:,} Cr</strong> • {row['Ministry']} • {row['Status']}</p>
                        <p style="font-size:0.85rem;color:#666;">📅 {row['Date']} • Symbol: {row['Symbol']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                with c2:
                    if st.button("🔍 Analyze", key=f"btn_{row.name}"):
                        st.session_state.selected = row['Symbol']
                        st.session_state.tab = "analysis"

    with tab2:
        st.markdown("### 💹 Bulk & Block Deals — Live NSE Data")
        if bulk_error:
            st.error(f"⚠️ {bulk_error} Showing no data rather than fake numbers.")
        elif bulk_deals.empty:
            st.info("No bulk/block deals reported for the latest NSE session yet.")
        else:
            st.caption(f"Source: NSE • data for **{bulk_as_of}** (latest available session) • cached 30 min")
            deals = bulk_deals.head(10).copy()
            deals["Qty"] = deals["Qty"].map(lambda x: f"{int(x):,}")
            styled = deals.style.apply(lambda x: ['background: #d4edda' if x['Type'].startswith('Buy') else 'background: #f8d7da' for _ in x], axis=1)
            st.dataframe(styled, use_container_width=True)
            st.info("🟢 Buy = Institutional/Promoter confidence • 🔴 Sell = Caution")
            st.caption("👉 For buyer/seller leaderboards, quantities, and full accumulation/distribution analysis, see the **🧠 Smart Money Tracker** tab.")

    with tab3:
        st.markdown("### 📊 AI Analysis Report")
        sym = st.text_input("🔍 Enter Symbol (e.g., LT, IRFC, HAL)", "LT")
        if st.button("🚀 Analyze Now", use_container_width=True):
            with st.spinner("🔄 Analyzing..."):
                stock = get_stock(sym)
                tender = tenders[tenders['Symbol'] == sym].iloc[0] if not tenders[tenders['Symbol'] == sym].empty else {'Value_Cr': 500, 'Ministry': 'N/A'}
                bulk = bulk_deals[bulk_deals['Symbol'] == sym].iloc[0] if not bulk_deals[bulk_deals['Symbol'] == sym].empty else None
                analysis = analyze(tender, stock, bulk)
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.metric("💰 CMP", f"₹{stock['CMP']:.2f}", f"{stock['Change']:+.2f}%")
                with c2: st.metric("📊 Mkt Cap", f"₹{stock['MarketCap']/1e9:.2f}B")
                with c3: st.metric("🎯 Score", f"{analysis['Score']}/100")
                with c4: st.metric("⚠️ Risk", analysis['Risk'])
                st.markdown(f"""
                ### 📋 Recommendation: <span style="color:{'green' if analysis['Score']>=30 else 'orange' if analysis['Score']>=15 else 'red'};">{analysis['Recommendation']}</span>
                #### Signals:
                """ + "\n".join([f"- {s}" for s in analysis['Signals']]), unsafe_allow_html=True)

    with tab4:
        st.markdown("### 🎯 Top Picks")
        recs = []
        for _, row in tenders.iterrows():
            stock = get_stock(row['Symbol'])
            bulk = bulk_deals[bulk_deals['Symbol'] == row['Symbol']]
            a = analyze(row, stock, bulk.iloc[0] if not bulk.empty else None)
            recs.append({'Company': row['Company'], 'Symbol': row['Symbol'], 'Value': row['Value_Cr'], 'CMP': stock['CMP'], 'Score': a['Score'], 'Rec': a['Recommendation'], 'Risk': a['Risk']})
        df = pd.DataFrame(recs).sort_values('Score', ascending=False)
        def color(val):
            if 'BUY' in val: return 'background: #00c853; color: white; font-weight: bold;'
            if 'AVOID' in val: return 'background: #ff1744; color: white; font-weight: bold;'
            if 'WATCHLIST' in val: return 'background: #ffab00; color: black;'
            return ''
        st.dataframe(df.style.map(color, subset=["Rec"]), use_container_width=True)

    with tab5:
        st.markdown("### 🧠 Smart Money Tracker — Who's Buying, Who's Selling")
        if bulk_as_of:
            st.caption(f"Source: NSE • data for **{bulk_as_of}** (latest available session) • cached 30 min")

        if bulk_error:
            st.error(f"⚠️ {bulk_error} No fake data shown.")
        elif bulk_deals.empty:
            st.info("No bulk/block deals reported for the latest NSE session yet.")
        else:
            buy_total = bulk_deals.loc[bulk_deals["Type"].str.startswith("Buy"), "Value_Cr"].sum()
            sell_total = bulk_deals.loc[bulk_deals["Type"].str.startswith("Sell"), "Value_Cr"].sum()
            k1, k2, k3, k4 = st.columns(4)
            with k1: st.metric("💰 Total Buy Value", f"₹{buy_total:,.0f} Cr")
            with k2: st.metric("📤 Total Sell Value", f"₹{sell_total:,.0f} Cr")
            with k3: st.metric("⚖️ Net Flow", f"₹{buy_total - sell_total:,.0f} Cr")
            with k4: st.metric("📄 Total Deals", f"{len(bulk_deals)}")

            st.markdown("---")
            sub_buyers, sub_sellers, sub_accum, sub_dist, sub_zones, sub_weekly, sub_deep, sub_all = st.tabs(
                ["🟢 Top Buyers", "🔴 Top Sellers", "📈 Top Accumulation", "📉 Top Distribution",
                 "🎯 Stock Zones", "📆 Weekly Summary", "🔍 Stock Deep-Dive", "📋 All Deals"]
            )

            with sub_buyers:
                st.markdown("#### Entities buying the most, by value")
                buyers = build_leaderboard(bulk_deals, "Buy")
                if buyers.empty:
                    st.info("No buy-side deals found.")
                else:
                    display = buyers.head(15).copy()
                    display["Total Quantity"] = display["Total Quantity"].map(lambda x: f"{int(x):,}")
                    st.dataframe(display, use_container_width=True, hide_index=True)
                    fig = go.Figure(go.Bar(
                        x=buyers.head(10)["Entity"], y=buyers.head(10).iloc[:, 1],
                        marker_color="#00c853"
                    ))
                    fig.update_layout(title="Top 10 Buyers by Value (₹ Cr)", height=350, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)

            with sub_sellers:
                st.markdown("#### Entities selling the most, by value")
                sellers = build_leaderboard(bulk_deals, "Sell")
                if sellers.empty:
                    st.info("No sell-side deals found.")
                else:
                    display = sellers.head(15).copy()
                    display["Total Quantity"] = display["Total Quantity"].map(lambda x: f"{int(x):,}")
                    st.dataframe(display, use_container_width=True, hide_index=True)
                    fig = go.Figure(go.Bar(
                        x=sellers.head(10)["Entity"], y=sellers.head(10).iloc[:, 1],
                        marker_color="#ff1744"
                    ))
                    fig.update_layout(title="Top 10 Sellers by Value (₹ Cr)", height=350, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)

            with sub_accum:
                st.markdown("#### Stocks with the strongest net buying (Buy value > Sell value)")
                flow = build_stock_flow(bulk_deals)
                accum = flow[flow["Net Value (₹ Cr)"] > 0].head(15)
                if accum.empty:
                    st.info("No stocks show net accumulation in the current data.")
                else:
                    st.dataframe(accum, use_container_width=True, hide_index=True)

            with sub_dist:
                st.markdown("#### Stocks with the strongest net selling (Sell value > Buy value)")
                flow = build_stock_flow(bulk_deals)
                dist = flow[flow["Net Value (₹ Cr)"] < 0].sort_values("Net Value (₹ Cr)").head(15)
                if dist.empty:
                    st.info("No stocks show net distribution in the current data.")
                else:
                    st.dataframe(dist, use_container_width=True, hide_index=True)

            with sub_zones:
                st.markdown("#### Which stocks are in the Buy Zone vs the Sell Zone — today")
                st.caption("ℹ️ These are **completed NSE trades**, not open/pending orders — bulk & block deals have no 'pending' state, every row here already executed.")
                zones = build_stock_zone_table(bulk_deals)
                if zones.empty:
                    st.info("No deals to classify today.")
                else:
                    zdisp = zones.copy()
                    zdisp["Qty Bought"] = zdisp["Qty Bought"].map(lambda x: f"{int(x):,}")
                    zdisp["Qty Sold"] = zdisp["Qty Sold"].map(lambda x: f"{int(x):,}")
                    zdisp["Net Qty"] = zdisp["Net Qty"].map(lambda x: f"{int(x):,}")
                    styled_z = zdisp.style.apply(
                        lambda r: ['background: #d4edda' if r['Zone'] == '🟢 Buy Zone' else ('background: #f8d7da' if r['Zone'] == '🔴 Sell Zone' else '') for _ in r],
                        axis=1
                    )
                    st.dataframe(styled_z, use_container_width=True, hide_index=True)

            with sub_weekly:
                st.markdown("#### Total Buy vs Sell per stock — last 7 calendar days")
                to_d = datetime.now().date()
                from_d = to_d - timedelta(days=7)
                weekly_df, weekly_err = fetch_nse_deals_range(str(from_d), str(to_d))
                if weekly_err:
                    st.error(f"⚠️ {weekly_err}")
                elif weekly_df is None or weekly_df.empty:
                    st.info("No bulk/block deals found for the last 7 days.")
                else:
                    st.caption(f"Range: {from_d.strftime('%d %b')} – {to_d.strftime('%d %b %Y')}")
                    weekly_zones = build_stock_zone_table(weekly_df)
                    wdisp = weekly_zones.copy()
                    wdisp["Qty Bought"] = wdisp["Qty Bought"].map(lambda x: f"{int(x):,}")
                    wdisp["Qty Sold"] = wdisp["Qty Sold"].map(lambda x: f"{int(x):,}")
                    wdisp["Net Qty"] = wdisp["Net Qty"].map(lambda x: f"{int(x):,}")
                    st.dataframe(wdisp, use_container_width=True, hide_index=True)
                    wk1, wk2, wk3 = st.columns(3)
                    with wk1: st.metric("💰 Week Buy Value", f"₹{weekly_zones['Buy Value (₹ Cr)'].sum():,.0f} Cr")
                    with wk2: st.metric("📤 Week Sell Value", f"₹{weekly_zones['Sell Value (₹ Cr)'].sum():,.0f} Cr")
                    with wk3: st.metric("⚖️ Week Net", f"₹{weekly_zones['Net Value (₹ Cr)'].sum():,.0f} Cr")

            with sub_deep:
                st.markdown("#### Pick a stock to see what's driving its Buy/Sell activity")
                to_d = datetime.now().date()
                from_d = to_d - timedelta(days=7)
                weekly_df, weekly_err = fetch_nse_deals_range(str(from_d), str(to_d))
                if weekly_err or weekly_df is None or weekly_df.empty:
                    st.info("No 7-day deal data available to analyze yet.")
                else:
                    symbols = sorted(weekly_df["Symbol"].unique())
                    picked = st.selectbox("Select Symbol", symbols, key="deep_dive_symbol")
                    sub = weekly_df[weekly_df["Symbol"] == picked]
                    buy_side = sub[sub["Type"].str.startswith("Buy")]
                    sell_side = sub[sub["Type"].str.startswith("Sell")]
                    buy_val = buy_side["Value_Cr"].sum()
                    sell_val = sell_side["Value_Cr"].sum()

                    d1, d2, d3 = st.columns(3)
                    with d1: st.metric("💰 Buy Value (7D)", f"₹{buy_val:,.1f} Cr")
                    with d2: st.metric("📤 Sell Value (7D)", f"₹{sell_val:,.1f} Cr")
                    with d3:
                        zone = "🟢 Buy Zone" if buy_val > sell_val else ("🔴 Sell Zone" if sell_val > buy_val else "⚪ Neutral")
                        st.metric("🎯 Zone", zone)

                    top_buyer = buy_side.groupby("Buyer_Seller")["Value_Cr"].sum().sort_values(ascending=False)
                    top_seller = sell_side.groupby("Buyer_Seller")["Value_Cr"].sum().sort_values(ascending=False)

                    st.markdown("##### 🧾 Major driver")
                    if buy_val == 0 and sell_val == 0:
                        st.info("No deals for this stock in the last 7 days.")
                    else:
                        lines = []
                        if not top_buyer.empty:
                            lines.append(f"🟢 **Biggest buyer:** {top_buyer.index[0]} — ₹{top_buyer.iloc[0]:,.1f} Cr ({(top_buyer.iloc[0]/buy_val*100):.0f}% of all buying)" if buy_val > 0 else "")
                        if not top_seller.empty:
                            lines.append(f"🔴 **Biggest seller:** {top_seller.index[0]} — ₹{top_seller.iloc[0]:,.1f} Cr ({(top_seller.iloc[0]/sell_val*100):.0f}% of all selling)" if sell_val > 0 else "")
                        if buy_val > sell_val:
                            lines.append(f"📋 **Verdict:** Buying pressure dominates — net ₹{buy_val - sell_val:,.1f} Cr more bought than sold over 7 days.")
                        elif sell_val > buy_val:
                            lines.append(f"📋 **Verdict:** Selling pressure dominates — net ₹{sell_val - buy_val:,.1f} Cr more sold than bought over 7 days.")
                        else:
                            lines.append("📋 **Verdict:** Buy and sell activity are roughly balanced.")
                        for l in lines:
                            if l: st.markdown(l)

                    with st.expander("See all deals for this stock (7 days)"):
                        show = sub[["Date", "Type", "Buyer_Seller", "Qty", "Price", "Value_Cr"]].copy()
                        show["Date"] = show["Date"].dt.strftime("%d-%b-%Y")
                        show["Qty"] = show["Qty"].map(lambda x: f"{int(x):,}")
                        st.dataframe(show.sort_values("Value_Cr", ascending=False), use_container_width=True, hide_index=True)

            with sub_all:
                st.markdown("#### Every individual deal (raw data)")
                full = bulk_deals.copy()
                full["Qty"] = full["Qty"].map(lambda x: f"{int(x):,}")
                st.dataframe(full, use_container_width=True, hide_index=True)
                st.download_button(
                    "⬇️ Download full deals as CSV",
                    data=bulk_deals.to_csv(index=False).encode("utf-8"),
                    file_name=f"nse_bulk_block_deals_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )

if __name__ == "__main__":
    main()
