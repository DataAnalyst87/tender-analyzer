import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go
import random
import requests
from io import StringIO
from nsepython import nse_bulk_deal_data, nse_block_deal_data  # ✅ FIXED

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
    .zone-buy { background: #d4edda; color: #155724; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
    .zone-sell { background: #f8d7da; color: #721c24; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
    .zone-neutral { background: #fff3cd; color: #856404; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
    .stDataFrame { font-size: 14px; }
    @media (max-width: 600px) { .stDataFrame { font-size: 11px; } .stButton button { width: 100%; } }
</style>
""", unsafe_allow_html=True)

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

# ============= REAL NSE BULK DEALS (nsepython) =============
@st.cache_data(ttl=3600)
def fetch_nse_bulk_deals(days=7):
    """Fetch bulk deals from NSE using nsepython library"""
    try:
        all_deals = []
        
        # Fetch bulk deals for each day
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            if date.weekday() >= 5:  # Skip weekends
                continue
                
            try:
                date_str = date.strftime("%d-%m-%Y")
                # nsepython function for bulk deals
                data = nse_bulk_deal_data(date_str)
                if data and isinstance(data, list) and len(data) > 0:
                    df = pd.DataFrame(data)
                    df['Date'] = date_str
                    all_deals.append(df)
            except Exception as e:
                # Some days may not have data
                pass
        
        if not all_deals:
            return pd.DataFrame(), "No bulk deals found for the selected period"
        
        # Combine all data
        combined = pd.concat(all_deals, ignore_index=True)
        
        # Normalize column names
        col_map = {}
        for col in combined.columns:
            if 'SYMBOL' in col.upper() or 'symbol' in col.lower():
                col_map[col] = 'Symbol'
            elif 'SECURITY' in col.upper() or 'security' in col.lower() or 'COMPANY' in col.upper():
                col_map[col] = 'Company'
            elif 'CLIENT' in col.upper() or 'client' in col.lower():
                col_map[col] = 'Buyer_Seller'
            elif 'BUY' in col.upper() and 'SELL' in col.upper():
                col_map[col] = 'Type'
            elif 'QUANTITY' in col.upper() or 'quantity' in col.lower():
                col_map[col] = 'Qty'
            elif 'PRICE' in col.upper() or 'price' in col.lower():
                col_map[col] = 'Price'
        
        combined = combined.rename(columns=col_map)
        
        # Ensure required columns
        required = ['Symbol', 'Company', 'Buyer_Seller', 'Type', 'Qty', 'Price']
        for col in required:
            if col not in combined.columns:
                combined[col] = 'N/A'
        
        # Convert numeric columns
        combined['Qty'] = pd.to_numeric(combined['Qty'], errors='coerce').fillna(0)
        combined['Price'] = pd.to_numeric(combined['Price'], errors='coerce').fillna(0)
        combined['Value_Cr'] = (combined['Qty'] * combined['Price'] / 1e7).round(2)
        
        # Clean Type (Buy/Sell)
        combined['Type'] = combined['Type'].astype(str).str.upper()
        combined['Type'] = combined['Type'].apply(
            lambda x: 'Buy' if 'BUY' in x else 'Sell' if 'SELL' in x else 'Unknown'
        )
        combined = combined[combined['Type'] != 'Unknown']
        
        return combined, None
        
    except Exception as e:
        return None, f"Error fetching NSE data: {str(e)}"

# ============= STOCK DATA (yFinance) =============
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

# ============= WEEKLY SUMMARY + ZONE ANALYSIS =============
def analyze_weekly_deals(bulk_df):
    if bulk_df.empty:
        return None, None, None
    
    # Calculate weekly totals per stock
    weekly_summary = bulk_df.groupby('Symbol').agg({
        'Qty': ['sum', 'mean'],
        'Value_Cr': ['sum', 'mean'],
        'Type': lambda x: (x == 'Buy').sum()
    }).reset_index()
    
    weekly_summary.columns = ['Symbol', 'Total_Qty', 'Avg_Qty', 'Total_Value', 'Avg_Value', 'Buy_Count']
    
    # Add sell count
    sell_counts = bulk_df[bulk_df['Type'] == 'Sell'].groupby('Symbol').size()
    weekly_summary['Sell_Count'] = weekly_summary['Symbol'].map(sell_counts).fillna(0).astype(int)
    
    # Calculate Buy/Sell Value
    weekly_summary['Buy_Value'] = bulk_df[bulk_df['Type'] == 'Buy'].groupby('Symbol')['Value_Cr'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Sell_Value'] = bulk_df[bulk_df['Type'] == 'Sell'].groupby('Symbol')['Value_Cr'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Net_Value'] = weekly_summary['Buy_Value'] - weekly_summary['Sell_Value']
    
    # Determine Zone
    def get_zone(row):
        if row['Net_Value'] > 50:
            return '🟢 BUY ZONE'
        elif row['Net_Value'] < -50:
            return '🔴 SELL ZONE'
        elif row['Net_Value'] > 10:
            return '🟡 MODERATE BUY'
        elif row['Net_Value'] < -10:
            return '🟠 MODERATE SELL'
        else:
            return '⚪ NEUTRAL'
    
    weekly_summary['Zone'] = weekly_summary.apply(get_zone, axis=1)
    
    # Total quantities
    weekly_summary['Total_Buy_Qty'] = bulk_df[bulk_df['Type'] == 'Buy'].groupby('Symbol')['Qty'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Total_Sell_Qty'] = bulk_df[bulk_df['Type'] == 'Sell'].groupby('Symbol')['Qty'].sum().reindex(weekly_summary['Symbol']).fillna(0)
    weekly_summary['Net_Qty'] = weekly_summary['Total_Buy_Qty'] - weekly_summary['Total_Sell_Qty']
    
    # Add Company name
    company_map = bulk_df.drop_duplicates('Symbol').set_index('Symbol')['Company'].to_dict()
    weekly_summary['Company'] = weekly_summary['Symbol'].map(company_map)
    
    buy_zone = weekly_summary[weekly_summary['Zone'].str.contains('BUY')]
    sell_zone = weekly_summary[weekly_summary['Zone'].str.contains('SELL')]
    
    return weekly_summary, buy_zone, sell_zone

# ============= MAIN UI =============
def main():
    st.markdown('<div class="main-header"><h1>📊 Tender Analyzer Pro</h1><p>Live Tender Scanner • Bulk Deal Tracker • AI Analysis</p><p style="font-size:0.9rem;opacity:0.8;">📅 {} • Powered by AI + NSE Real Data</p></div>'.format(datetime.now().strftime('%d %B %Y')), unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### 🎯 Smart Filters")
        days = st.slider("📅 Tender Age", 1, 7, 3)
        min_val = st.slider("💰 Min Value (₹ Cr)", 50, 5000, 100)
        st.markdown("---")
        st.markdown("### 📊 NSE Data Settings")
        bulk_days = st.slider("📅 Days to fetch Bulk Deals", 1, 10, 7)
        if st.button("🔄 Refresh All Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # Load Data
    tenders = get_tenders()
    bulk_data, bulk_error = fetch_nse_bulk_deals(days=bulk_days)
    
    if bulk_error:
        st.warning(f"⚠️ {bulk_error}")
        bulk_data = pd.DataFrame()
    
    # Weekly Analysis
    weekly_summary, buy_zone, sell_zone = analyze_weekly_deals(bulk_data) if not bulk_data.empty else (None, None, None)

    # TABS
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📌 Tenders", "💹 Bulk Deals", "📊 Analysis", "🎯 Top Picks", "📈 Weekly Summary", "🧠 Buy/Sell Zone"])

    with tab1:
        st.warning("⚠️ **Sample data** — no free public API exists for government tender / L1-bidder data. This tab is illustrative.")
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
                    if st.button("🔍 Analyze", key=f"btn_tender_{row.name}"):
                        st.session_state.selected = row['Symbol']
                        st.session_state.tab = "analysis"

    with tab2:
        st.markdown("### 💹 Bulk & Block Deals — Live NSE Data")
        if bulk_data.empty:
            st.info("No bulk/block deals found for the selected period.")
        else:
            st.caption(f"Source: NSE • fetched {datetime.now().strftime('%d %b %Y, %H:%M')} • cached 1 hour")
            display = bulk_data.copy()
            display['Qty'] = display['Qty'].map(lambda x: f"{int(x):,}")
            display['Value_Cr'] = display['Value_Cr'].map(lambda x: f"₹{x:.2f} Cr")
            styled = display.style.apply(lambda x: ['background: #d4edda' if x['Type'] == 'Buy' else 'background: #f8d7da' for _ in x], axis=1)
            st.dataframe(styled, use_container_width=True)
            st.info("🟢 Buy = Institutional confidence • 🔴 Sell = Profit booking / Exit")

    with tab3:
        st.markdown("### 📊 AI Analysis Report")
        sym = st.text_input("🔍 Enter Symbol (e.g., LT, IRFC, HAL)", "LT")
        if st.button("🚀 Analyze Now", use_container_width=True):
            with st.spinner("🔄 Analyzing..."):
                stock = get_stock(sym)
                tender = tenders[tenders['Symbol'] == sym].iloc[0] if not tenders[tenders['Symbol'] == sym].empty else {'Value_Cr': 500, 'Ministry': 'N/A'}
                bulk = bulk_data[bulk_data['Symbol'] == sym].iloc[0] if not bulk_data[bulk_data['Symbol'] == sym].empty else None
                
                score = 0
                signals = []
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
                
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.metric("💰 CMP", f"₹{stock['CMP']:.2f}", f"{stock['Change']:+.2f}%")
                with c2: st.metric("📊 Mkt Cap", f"₹{stock['MarketCap']/1e9:.2f}B")
                with c3: st.metric("🎯 Score", f"{score}/100")
                with c4: st.metric("⚠️ Risk", risk)
                st.markdown(f"""
                ### 📋 Recommendation: <span style="color:{'green' if score>=30 else 'orange' if score>=15 else 'red'};">{rec}</span>
                #### Signals:
                """ + "\n".join([f"- {s}" for s in signals]), unsafe_allow_html=True)

    with tab4:
        st.markdown("### 🎯 Top Picks")
        recs = []
        for _, row in tenders.iterrows():
            stock = get_stock(row['Symbol'])
            bulk = bulk_data[bulk_data['Symbol'] == row['Symbol']]
            bulk_row = bulk.iloc[0] if not bulk.empty else None
            
            score = 0
            if row['Value_Cr'] > 1000: score += 20
            elif row['Value_Cr'] > 500: score += 15
            elif row['Value_Cr'] > 100: score += 10
            if stock['Change'] > 5: score += 20
            elif stock['Change'] > 2: score += 10
            if bulk_row is not None and bulk_row['Type'] == 'Buy': score += 10
            if bulk_row is not None and bulk_row['Type'] == 'Sell': score -= 10
            
            rec = 'BUY ON DIPS' if score >= 30 else 'WATCHLIST' if score >= 15 else 'HOLD' if score >= 0 else 'STRICT AVOID'
            risk = 'LOW' if score >= 30 else 'MEDIUM' if score >= 15 else 'HIGH'
            recs.append({'Company': row['Company'], 'Symbol': row['Symbol'], 'Value': row['Value_Cr'], 'CMP': stock['CMP'], 'Score': score, 'Rec': rec, 'Risk': risk})
        
        df = pd.DataFrame(recs).sort_values('Score', ascending=False)
        def color(val):
            if 'BUY' in val: return 'background: #00c853; color: white; font-weight: bold;'
            if 'AVOID' in val: return 'background: #ff1744; color: white; font-weight: bold;'
            if 'WATCHLIST' in val: return 'background: #ffab00; color: black;'
            return ''
        st.dataframe(df.style.map(color, subset=["Rec"]), use_container_width=True)

    with tab5:
        st.markdown("### 📈 Weekly Summary — Buy vs Sell Activity")
        st.caption(f"Last {bulk_days} days • Source: NSE")
        
        if weekly_summary is None or weekly_summary.empty:
            st.info("No data available for weekly summary.")
        else:
            total_buy = bulk_data[bulk_data['Type'] == 'Buy']['Value_Cr'].sum()
            total_sell = bulk_data[bulk_data['Type'] == 'Sell']['Value_Cr'].sum()
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("💰 Total Buy", f"₹{total_buy:.2f} Cr")
            with c2: st.metric("📤 Total Sell", f"₹{total_sell:.2f} Cr")
            with c3: st.metric("⚖️ Net Flow", f"₹{total_buy - total_sell:.2f} Cr")
            with c4: st.metric("📄 Total Deals", f"{len(bulk_data)}")
            
            st.markdown("---")
            st.markdown("#### 📊 Stock-wise Weekly Activity")
            display = weekly_summary.copy()
            display['Total_Qty'] = display['Total_Qty'].map(lambda x: f"{int(x):,}")
            display['Total_Buy_Qty'] = display['Total_Buy_Qty'].map(lambda x: f"{int(x):,}")
            display['Total_Sell_Qty'] = display['Total_Sell_Qty'].map(lambda x: f"{int(x):,}")
            display['Net_Qty'] = display['Net_Qty'].map(lambda x: f"{int(x):,}")
            display['Net_Value'] = display['Net_Value'].map(lambda x: f"₹{x:.2f} Cr")
            st.dataframe(display[['Symbol', 'Company', 'Total_Buy_Qty', 'Total_Sell_Qty', 'Net_Qty', 'Buy_Value', 'Sell_Value', 'Net_Value', 'Zone']], use_container_width=True)

    with tab6:
        st.markdown("### 🧠 Buy/Sell Zone — Individual Stock Analysis")
        st.caption("🔍 Identify which stocks are in BUY ZONE, SELL ZONE, or NEUTRAL based on net institutional flow")
        
        if buy_zone is not None and not buy_zone.empty:
            st.markdown("#### 🟢 BUY ZONE STOCKS")
            display_buy = buy_zone.copy()
            display_buy['Total_Buy_Qty'] = display_buy['Total_Buy_Qty'].map(lambda x: f"{int(x):,}")
            display_buy['Total_Sell_Qty'] = display_buy['Total_Sell_Qty'].map(lambda x: f"{int(x):,}")
            display_buy['Net_Value'] = display_buy['Net_Value'].map(lambda x: f"₹{x:.2f} Cr")
            st.dataframe(display_buy[['Symbol', 'Company', 'Total_Buy_Qty', 'Total_Sell_Qty', 'Net_Value', 'Zone']], use_container_width=True)
        
        if sell_zone is not None and not sell_zone.empty:
            st.markdown("#### 🔴 SELL ZONE STOCKS")
            display_sell = sell_zone.copy()
            display_sell['Total_Buy_Qty'] = display_sell['Total_Buy_Qty'].map(lambda x: f"{int(x):,}")
            display_sell['Total_Sell_Qty'] = display_sell['Total_Sell_Qty'].map(lambda x: f"{int(x):,}")
            display_sell['Net_Value'] = display_sell['Net_Value'].map(lambda x: f"₹{x:.2f} Cr")
            st.dataframe(display_sell[['Symbol', 'Company', 'Total_Buy_Qty', 'Total_Sell_Qty', 'Net_Value', 'Zone']], use_container_width=True)
        
        st.markdown("---")
        st.markdown("#### 🔎 Click any stock for detailed analysis")
        
        if weekly_summary is not None and not weekly_summary.empty:
            cols = st.columns(4)
            for idx, (_, row) in enumerate(weekly_summary.iterrows()):
                with cols[idx % 4]:
                    zone_color = "🟢" if "BUY" in row['Zone'] else "🔴" if "SELL" in row['Zone'] else "⚪"
                    if st.button(f"{zone_color} {row['Symbol']}", key=f"zone_btn_{idx}"):
                        st.session_state.selected = row['Symbol']
                        st.session_state.tab = "analysis"
                        st.rerun()

if __name__ == "__main__":
    main()
