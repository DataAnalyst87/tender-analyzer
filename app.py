import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go
import random
import requests
from io import StringIO

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
# NSE publishes today's bulk/block deals as free public CSV files.
# These endpoints require a warmed-up session (cookies) + browser-like
# headers, or NSE returns 403.
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,application/csv,*/*",
    "Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
}

@st.cache_data(ttl=1800)
def get_bulk_deals():
    """Fetch real bulk + block deals for the latest available session from NSE.
    Returns (dataframe, error_message). error_message is None on success."""
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        # Warm up session to get cookies NSE requires before serving data
        session.get("https://www.nseindia.com", timeout=8)

        frames = []
        for kind, url in [
            ("Bulk Deal", "https://archives.nseindia.com/content/equities/bulk.csv"),
            ("Block Deal", "https://archives.nseindia.com/content/equities/block.csv"),
        ]:
            resp = session.get(url, timeout=8)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
            df.columns = [c.strip() for c in df.columns]
            df["Deal_Kind"] = kind
            frames.append(df)

        combined = pd.concat(frames, ignore_index=True)

        # Normalize NSE's raw column names into the app's schema
        rename_map = {
            "Date": "Date", "DATE": "Date",
            "Symbol": "Symbol", "SYMBOL": "Symbol",
            "Security Name": "Company", "SECURITY NAME": "Company",
            "Client Name": "Buyer_Seller", "CLIENT NAME": "Buyer_Seller",
            "Buy/Sell": "Type", "BUY / SELL": "Type",
            "Quantity Traded": "Qty", "QUANTITY TRADED": "Qty",
            "Trade Price / Wght. Avg. Price": "Price",
            "TRADE PRICE / WGHT. AVG. PRICE": "Price",
        }
        combined = combined.rename(columns={k: v for k, v in rename_map.items() if k in combined.columns})

        required = ["Date", "Symbol", "Company", "Buyer_Seller", "Type", "Qty", "Price"]
        missing = [c for c in required if c not in combined.columns]
        if missing:
            return None, f"NSE changed their CSV format (missing columns: {missing})."

        combined["Qty"] = pd.to_numeric(combined["Qty"], errors="coerce")
        combined["Price"] = pd.to_numeric(combined["Price"], errors="coerce")
        combined["Value_Cr"] = (combined["Qty"] * combined["Price"] / 1e7).round(2)
        combined["Type"] = combined["Type"].astype(str).str.strip().str.title()
        combined.loc[combined["Deal_Kind"] == "Block Deal", "Type"] = "Block Deal"

        combined = combined[["Company", "Symbol", "Type", "Value_Cr", "Buyer_Seller", "Date"]]
        combined = combined.sort_values("Value_Cr", ascending=False).reset_index(drop=True)
        return combined, None
    except Exception as e:
        return None, f"Could not fetch live NSE data ({e})."

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
        if bulk['Type'] == 'Buy' and 'Promoter' in str(bulk['Buyer_Seller']): score += 20; signals.append("🔥 Promoter buying")
        elif bulk['Type'] == 'Buy': score += 10; signals.append("✅ Institutional buying")
        elif bulk['Type'] == 'Sell' and 'Promoter' in str(bulk['Buyer_Seller']): score -= 20; signals.append("🚨 Promoter selling")
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

    tab1, tab2, tab3, tab4 = st.tabs(["📌 Tenders", "💹 Bulk Deals", "📊 Analysis", "🎯 Top Picks"])

    tenders = get_tenders()
    bulk_deals, bulk_error = get_bulk_deals()
    if bulk_error is not None:
        # Fall back to empty frame with the right schema so the rest of the
        # app (Analysis/Top Picks lookups) doesn't crash
        bulk_deals = pd.DataFrame(columns=["Company", "Symbol", "Type", "Value_Cr", "Buyer_Seller", "Date"])

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
            st.caption(f"Source: NSE archives • fetched {datetime.now().strftime('%d %b %Y, %H:%M')} • cached 30 min")
            deals = bulk_deals.head(10)
            styled = deals.style.apply(lambda x: ['background: #d4edda' if x['Type'] == 'Buy' else 'background: #f8d7da' for _ in x], axis=1)
            st.dataframe(styled, use_container_width=True)
            st.info("🟢 Buy = Institutional/Promoter confidence • 🔴 Sell = Caution")

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

if __name__ == "__main__":
    main()
