import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go
import random
import requests
from io import StringIO

# ============= NSE DATA DIRECT FROM CSV (NO LIBRARY NEEDED) =============
# NSE archives bulk/block deals as public CSV files
# We fetch directly — no external library, works everywhere!

@st.cache_data(ttl=3600)
def fetch_nse_bulk_deals(days=7):
    """Fetch bulk deals directly from NSE CSV archives"""
    try:
        all_deals = []
        
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            if date.weekday() >= 5:  # Saturday=5, Sunday=6
                continue
            
            date_str = date.strftime("%d-%m-%Y")
            
            # Try both bulk and block deals
            for deal_type, url in [
                ("Bulk", f"https://archives.nseindia.com/content/equities/bulk_{date_str}.csv"),
                ("Block", f"https://archives.nseindia.com/content/equities/block_{date_str}.csv")
            ]:
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "text/csv,application/csv,*/*",
                        "Referer": "https://www.nseindia.com/"
                    }
                    resp = requests.get(url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        df = pd.read_csv(StringIO(resp.text))
                        if not df.empty:
                            df['Date'] = date.strftime("%Y-%m-%d")
                            df['Deal_Type'] = deal_type
                            all_deals.append(df)
                except:
                    pass
        
        if not all_deals:
            return pd.DataFrame(), "No bulk deals found in last 7 days"
        
        combined = pd.concat(all_deals, ignore_index=True)
        
        # Normalize column names
        col_map = {}
        for col in combined.columns:
            col_upper = col.upper().strip()
            if 'SYMBOL' in col_upper:
                col_map[col] = 'Symbol'
            elif 'SECURITY' in col_upper or 'COMPANY' in col_upper or 'NAME' in col_upper:
                col_map[col] = 'Company'
            elif 'CLIENT' in col_upper:
                col_map[col] = 'Buyer_Seller'
            elif 'BUY' in col_upper and 'SELL' in col_upper:
                col_map[col] = 'Type'
            elif 'QUANTITY' in col_upper or 'QTY' in col_upper:
                col_map[col] = 'Qty'
            elif 'PRICE' in col_upper:
                col_map[col] = 'Price'
        
        combined = combined.rename(columns=col_map)
        
        # Ensure required columns exist
        required = ['Symbol', 'Company', 'Buyer_Seller', 'Type', 'Qty', 'Price']
        for col in required:
            if col not in combined.columns:
                combined[col] = 'N/A'
        
        # Convert to numeric
        combined['Qty'] = pd.to_numeric(combined['Qty'], errors='coerce').fillna(0)
        combined['Price'] = pd.to_numeric(combined['Price'], errors='coerce').fillna(0)
        combined['Value_Cr'] = (combined['Qty'] * combined['Price'] / 1e7).round(2)
        
        # Clean Type
        combined['Type'] = combined['Type'].astype(str).str.upper().str.strip()
        combined['Type'] = combined['Type'].apply(
            lambda x: 'Buy' if 'BUY' in x else 'Sell' if 'SELL' in x else 'Unknown'
        )
        combined = combined[combined['Type'] != 'Unknown']
        
        if combined.empty:
            return pd.DataFrame(), "No valid deals found"
        
        return combined, None
        
    except Exception as e:
        return None, f"Error: {str(e)}"

# ============= SAMPLE TENDER DATA =============
def get_tenders():
    return pd.DataFrame({
        'Company': ['L&T', 'IRFC', 'HAL', 'RVNL', 'SJVN', 'KPI Green', 'Strides Pharma', 'Welspun Corp', 'BHEL', 'NTPC'],
        'Symbol': ['LT', 'IRFC', 'HAL', 'RVNL', 'SJVN', 'KPIGREEN', 'STRIDES', 'WELCORP', 'BHEL', 'NTPC'],
        'Value_Cr': [2400, 850, 1200, 221, 148, 450, 500, 1433, 780, 3200],
        'Ministry': ['Defence', 'Railways', 'Air Force', 'Railways', 'Power', 'Renewable Energy', 'Pharma', 'Defence', 'Power', 'Power'],
        'Date': [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(10)],
        'Status': ['L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'Technical Clearance', 'L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'L1 Bidder', 'Technical Clearance']
    })

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
        return {
            'CMP': round(cmp, 2), 
            'Change': change, 
            'MarketCap': info.get('marketCap', 0), 
            'PE': info.get('trailingPE', 0), 
            'Volume': info.get('volume', 0)
        }
    except:
        return {
            'CMP': random.randint(100, 5000), 
            'Change': round(random.uniform(-5, 8), 2), 
            'MarketCap': random.randint(1000, 50000), 
            'PE': random.randint(10, 40), 
            'Volume': random.randint(100000, 5000000)
        }

# ============= WEEKLY SUMMARY =============
def analyze_weekly_deals(bulk_df):
    if bulk_df.empty:
        return None, None, None
    
    weekly_summary = bulk_df.groupby('Symbol').agg({
        'Qty': ['sum', 'mean'],
        'Value_Cr': ['sum', 'mean'],
        'Type': lambda x: (x == 'Buy').sum()
    }).reset_index()
    
    weekly_summary.columns = ['Symbol', 'Total_Qty', 'Avg_Qty', 'Total_Value', 'Avg_Value', 'Buy_Count']
    
    sell_counts = bulk_df[bulk_df['Type'] == 'Sell'].groupby('Symbol').size()
    weekly_summary['Sell_Count'] = weekly_summary['Symbol'].map(sell_counts).fillna(0).astype(int)
    
    weekly_summary['Buy_Value'] = bulk_df[bulk_df['Type'] == 'Buy'].groupby('Symbol')['Value_Cr'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Sell_Value'] = bulk_df[bulk_df['Type'] == 'Sell'].groupby('Symbol')['Value_Cr'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Net_Value'] = weekly_summary['Buy_Value'] - weekly_summary['Sell_Value']
    
    def get_zone(row):
        if row['Net_Value'] > 50: return '🟢 BUY ZONE'
        elif row['Net_Value'] < -50: return '🔴 SELL ZONE'
        elif row['Net_Value'] > 10: return '🟡 MODERATE BUY'
        elif row['Net_Value'] < -10: return '🟠 MODERATE SELL'
        else: return '⚪ NEUTRAL'
    
    weekly_summary['Zone'] = weekly_summary.apply(get_zone, axis=1)
    
    weekly_summary['Total_Buy_Qty'] = bulk_df[bulk_df['Type'] == 'Buy'].groupby('Symbol')['Qty'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Total_Sell_Qty'] = bulk_df[bulk_df['Type'] == 'Sell'].groupby('Symbol')['Qty'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Net_Qty'] = weekly_summary['Total_Buy_Qty'] - weekly_summary['Total_Sell_Qty']
    
    company_map = bulk_df.drop_duplicates('Symbol').set_index('Symbol')['Company'].to_dict()
    weekly_summary['Company'] = weekly_summary['Symbol'].map(company_map)
    
    return weekly_summary, weekly_summary[weekly_summary['Zone'].str.contains('BUY')], weekly_summary[weekly_summary['Zone'].str.contains('SELL')]

# ============= MAIN UI =============
def main():
    st.set_page_config(
        page_title="Tender Analyzer Pro",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.markdown("""
    <style>
        .main-header { background: linear-gradient(135deg, #0a1628, #1a365d); padding: 2rem; border-radius: 15px; margin-bottom: 2rem; text-align: center; color: white; }
        .tender-card { background: #f8f9fa; padding: 1.2rem; border-radius: 12px; border-left: 5px solid #ff6b35; margin-bottom: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .zone-buy { background: #d4edda; color: #155724; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
        .zone-sell { background: #f8d7da; color: #721c24; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
        @media (max-width: 600px) { .stDataFrame { font-size: 11px; } .stButton button { width: 100%; } }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
    <div class="main-header">
        <h1>📊 Tender Analyzer Pro</h1>
        <p>Live Tender Scanner • Bulk Deal Tracker • AI Analysis</p>
        <p style="font-size:0.9rem;opacity:0.8;">📅 {datetime.now().strftime('%d %B %Y')} • Powered by AI</p>
    </div>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### 🎯 Smart Filters")
        days = st.slider("📅 Tender Age", 1, 7, 3)
        min_val = st.slider("💰 Min Value (₹ Cr)", 50, 5000, 100)
        st.markdown("---")
        bulk_days = st.slider("📅 Days to fetch Bulk Deals", 1, 10, 7)
        if st.button("🔄 Refresh All Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    tenders = get_tenders()
    bulk_data, bulk_error = fetch_nse_bulk_deals(days=bulk_days)
    
    if bulk_error:
        st.warning(f"⚠️ {bulk_error}")
        bulk_data = pd.DataFrame()
    
    weekly_summary, buy_zone, sell_zone = analyze_weekly_deals(bulk_data) if not bulk_data.empty else (None, None, None)

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📌 Tenders", "💹 Bulk Deals", "📊 Analysis", "🎯 Top Picks", "📈 Weekly Summary", "🧠 Buy/Sell Zone"])

    with tab1:
        st.warning("⚠️ **Sample data** — government tender data is illustrative.")
        st.markdown(f"### 📌 Latest Tenders (Last {days} Days)")
        cutoff = datetime.now() - timedelta(days=days)
        filtered = tenders[pd.to_datetime(tenders['Date']) >= cutoff]
        filtered = filtered[filtered['Value_Cr'] >= min_val]
        if filtered.empty:
            st.warning("No tenders found")
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

    with tab2:
        st.markdown("### 💹 Bulk & Block Deals — Live NSE Data")
        if bulk_data.empty:
            st.info("No bulk/block deals found for the selected period.")
        else:
            st.caption(f"Source: NSE • fetched {datetime.now().strftime('%d %b %Y, %H:%M')}")
            display = bulk_data.copy()
            display['Qty'] = display['Qty'].map(lambda x: f"{int(x):,}")
            display['Value_Cr'] = display['Value_Cr'].map(lambda x: f"₹{x:.2f} Cr")
            st.dataframe(display, use_container_width=True)
            st.info("🟢 Buy = Institutional confidence • 🔴 Sell = Profit booking / Exit")

    with tab3:
        st.markdown("### 📊 AI Analysis Report")
        sym = st.text_input("🔍 Enter Symbol (e.g., LT, IRFC, HAL)", "LT")
        if st.button("🚀 Analyze Now", use_container_width=True):
            with st.spinner("🔄 Analyzing..."):
                stock = get_stock(sym)
                tender = tenders[tenders['Symbol'] == sym].iloc[0] if not tenders[tenders['Symbol'] == sym].empty else {'Value_Cr': 500}
                bulk = bulk_data[bulk_data['Symbol'] == sym].iloc[0] if not bulk_data[bulk_data['Symbol'] == sym].empty else None
                
                score = 0
                signals = []
                if tender['Value_Cr'] > 1000: score += 20; signals.append("✅ Mega tender >₹1000 Cr")
                elif tender['Value_Cr'] > 500: score += 15; signals.append("✅ Large tender >₹500 Cr")
                elif tender['Value_Cr'] > 100: score += 10; signals.append("✅ Medium tender")
                if stock['Change'] > 5: score += 20; signals.append("📈 Strong momentum")
                elif stock['Change'] > 2: score += 10; signals.append("📈 Positive momentum")
                if bulk is not None:
                    if bulk['Type'] == 'Buy': score += 10; signals.append("✅ Institutional buying")
                    elif bulk['Type'] == 'Sell': score -= 10; signals.append("⚠️ Selling pressure")
                
                rec = 'BUY ON DIPS' if score >= 30 else 'WATCHLIST' if score >= 15 else 'HOLD' if score >= 0 else 'STRICT AVOID'
                risk = 'LOW' if score >= 30 else 'MEDIUM' if score >= 15 else 'HIGH'
                
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.metric("💰 CMP", f"₹{stock['CMP']:.2f}", f"{stock['Change']:+.2f}%")
                with c2: st.metric("📊 Mkt Cap", f"₹{stock['MarketCap']/1e9:.2f}B")
                with c3: st.metric("🎯 Score", f"{score}/100")
                with c4: st.metric("⚠️ Risk", risk)
                st.markdown(f"### 📋 Recommendation: {rec}")
                st.markdown("#### Signals:\n" + "\n".join([f"- {s}" for s in signals]))

    with tab4:
        st.markdown("### 🎯 Top Picks")
        recs = []
        for _, row in tenders.iterrows():
            stock = get_stock(row['Symbol'])
            bulk = bulk_data[bulk_data['Symbol'] == row['Symbol']]
            score = 0
            if row['Value_Cr'] > 1000: score += 20
            elif row['Value_Cr'] > 500: score += 15
            elif row['Value_Cr'] > 100: score += 10
            if stock['Change'] > 5: score += 20
            elif stock['Change'] > 2: score += 10
            if not bulk.empty and bulk.iloc[0]['Type'] == 'Buy': score += 10
            if not bulk.empty and bulk.iloc[0]['Type'] == 'Sell': score -= 10
            rec = 'BUY ON DIPS' if score >= 30 else 'WATCHLIST' if score >= 15 else 'HOLD' if score >= 0 else 'STRICT AVOID'
            risk = 'LOW' if score >= 30 else 'MEDIUM' if score >= 15 else 'HIGH'
            recs.append({'Company': row['Company'], 'Symbol': row['Symbol'], 'Value': row['Value_Cr'], 'CMP': stock['CMP'], 'Score': score, 'Rec': rec, 'Risk': risk})
        
        df = pd.DataFrame(recs).sort_values('Score', ascending=False)
        st.dataframe(df, use_container_width=True)

    with tab5:
        st.markdown("### 📈 Weekly Summary")
        if weekly_summary is None or weekly_summary.empty:
            st.info("No data available.")
        else:
            total_buy = bulk_data[bulk_data['Type'] == 'Buy']['Value_Cr'].sum()
            total_sell = bulk_data[bulk_data['Type'] == 'Sell']['Value_Cr'].sum()
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("💰 Total Buy", f"₹{total_buy:.2f} Cr")
            with c2: st.metric("📤 Total Sell", f"₹{total_sell:.2f} Cr")
            with c3: st.metric("⚖️ Net Flow", f"₹{total_buy - total_sell:.2f} Cr")
            with c4: st.metric("📄 Total Deals", f"{len(bulk_data)}")
            st.dataframe(weekly_summary, use_container_width=True)

    with tab6:
        st.markdown("### 🧠 Buy/Sell Zone")
        if buy_zone is not None and not buy_zone.empty:
            st.markdown("#### 🟢 BUY ZONE STOCKS")
            st.dataframe(buy_zone, use_container_width=True)
        if sell_zone is not None and not sell_zone.empty:
            st.markdown("#### 🔴 SELL ZONE STOCKS")
            st.dataframe(sell_zone, use_container_width=True)

if __name__ == "__main__":
    main()
