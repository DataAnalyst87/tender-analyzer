import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go

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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(12px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes shimmer {
        0% { background-position: -400px 0; }
        100% { background-position: 400px 0; }
    }
    @keyframes pulseGlow {
        0%, 100% { box-shadow: 0 0 0 rgba(26,54,93,0.0); }
        50% { box-shadow: 0 0 18px rgba(26,54,93,0.25); }
    }

    .main-header {
        background: linear-gradient(135deg, #0a1628 0%, #1a365d 55%, #2b4f81 100%);
        padding: 2.2rem; border-radius: 18px; margin-bottom: 1.6rem; text-align: center;
        color: white; animation: fadeInUp 0.6s ease-out, pulseGlow 6s ease-in-out infinite;
        box-shadow: 0 8px 24px rgba(10,22,40,0.35);
    }
    .main-header h1 { letter-spacing: 0.5px; font-weight: 800; }

    .tender-card {
        background: #ffffff; padding: 1.3rem; border-radius: 14px;
        border-left: 5px solid #ff6b35; margin-bottom: 1rem;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        animation: fadeInUp 0.45s ease-out;
    }
    .tender-card:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(0,0,0,0.12); }

    .buy-tag { color: #00c853; font-weight: 700; }
    .sell-tag { color: #ff1744; font-weight: 700; }

    .metric-box {
        background: white; padding: 1.2rem; border-radius: 14px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06); text-align: center;
        border-top: 4px solid #1a365d; transition: transform 0.2s ease;
        animation: fadeInUp 0.5s ease-out;
    }
    .metric-box:hover { transform: translateY(-2px); }

    /* Streamlit's own metric widgets get a subtle card treatment + entrance */
    div[data-testid="stMetric"] {
        background: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
        border: 1px solid #e7ecf3; border-radius: 14px; padding: 0.9rem 1rem;
        box-shadow: 0 2px 8px rgba(20,30,60,0.05);
        animation: fadeInUp 0.5s ease-out; transition: box-shadow 0.2s ease, transform 0.2s ease;
    }
    div[data-testid="stMetric"]:hover { box-shadow: 0 6px 16px rgba(20,30,60,0.10); transform: translateY(-2px); }

    /* Tabs: smoother active-state transition */
    button[data-baseweb="tab"] { transition: color 0.2s ease, border-color 0.2s ease; }

    /* DataFrames fade in */
    div[data-testid="stDataFrame"] { animation: fadeInUp 0.4s ease-out; border-radius: 10px; overflow: hidden; }

    /* Buttons: gradient + lift */
    .stButton button, .stDownloadButton button {
        background: linear-gradient(135deg, #1a365d, #2b4f81);
        color: white; border: none; border-radius: 10px; font-weight: 600;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .stButton button:hover, .stDownloadButton button:hover {
        transform: translateY(-2px); box-shadow: 0 6px 16px rgba(26,54,93,0.35);
    }

    /* Score badge pills — used via st.markdown for consistent green/amber/red look */
    .score-pill {
        display: inline-block; padding: 0.25rem 0.75rem; border-radius: 999px;
        font-weight: 700; font-size: 0.85rem; animation: fadeInUp 0.4s ease-out;
    }
    .score-high { background: #d4edda; color: #0a5c2e; }
    .score-mid  { background: #fff3cd; color: #7a5c00; }
    .score-low  { background: #f8d7da; color: #7a1224; }

    @media (max-width: 600px) { .stDataFrame { font-size: 11px; } .stButton button { width: 100%; } }
</style>
""", unsafe_allow_html=True)

# ============= REAL DATA: ORDER/TENDER-WIN ANNOUNCEMENTS =============
# There's no free API for government CPPP/GeM tender awards, but listed
# companies are legally required to notify the stock exchange the moment
# they win a material order/contract/tender. NSE publishes these as
# "corporate announcements" — free, official, and genuinely real. We fetch
# them and keyword-filter for order/tender/contract-win language.
TENDER_KEYWORDS = [
    "order", "tender", "contract", "l1 bidder", "letter of intent", " loi ",
    "awarded", "bags order", "wins order", "work order", "purchase order",
    "loa ", "letter of award",
]

def _find_col(df, candidates):
    for c in df.columns:
        lc = c.lower()
        if any(cand in lc for cand in candidates):
            return c
    return None

@st.cache_data(ttl=1800)
def get_tender_win_announcements(days_back=7):
    """Real NSE corporate announcements that look like order/tender wins.
    Returns (dataframe, error_message). Empty dataframe + no error means
    the search worked but genuinely found nothing — never fabricated."""
    try:
        from nse import NSE
        import tempfile
        to_d = datetime.now()
        from_d = to_d - timedelta(days=days_back)
        with NSE(download_folder=tempfile.gettempdir()) as nse_client:
            records = nse_client.announcements(index="equities", from_date=from_d, to_date=to_d)
    except Exception as e:
        return None, f"Could not fetch NSE announcements ({e})."

    if not records:
        return pd.DataFrame(columns=["Date", "Symbol", "Company", "Announcement"]), None

    df = pd.DataFrame(records)
    symbol_col = _find_col(df, ["symbol"])
    company_col = _find_col(df, ["sm_name", "company", "companyname"])
    desc_col = _find_col(df, ["desc", "subject", "attchmnttext"])
    date_col = _find_col(df, ["an_dt", "date", "dt"])

    if desc_col is None:
        return None, "NSE changed their announcements format (couldn't find a description field)."

    text = df[desc_col].astype(str).str.lower()
    mask = text.apply(lambda t: any(k in t for k in TENDER_KEYWORDS))
    hits = df[mask].copy()
    if hits.empty:
        return pd.DataFrame(columns=["Date", "Symbol", "Company", "Announcement"]), None

    out = pd.DataFrame({
        "Date": hits[date_col] if date_col else "",
        "Symbol": hits[symbol_col] if symbol_col else "",
        "Company": hits[company_col] if company_col else (hits[symbol_col] if symbol_col else ""),
        "Announcement": hits[desc_col],
    })
    return out.reset_index(drop=True), None

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
    """Real yfinance data only. Returns (data_dict_or_None, error_message)."""
    try:
        ticker = yf.Ticker(symbol + ".NS")
        info = ticker.info
        hist = ticker.history(period="5d")
        if hist.empty and not info.get('currentPrice'):
            return None, f"No live price data found for {symbol}."
        cmp = hist['Close'].iloc[-1] if not hist.empty else info.get('currentPrice', 0)
        prev = hist['Close'].iloc[-2] if len(hist) > 1 else cmp
        change = round(((cmp - prev) / prev) * 100, 2) if prev > 0 else 0
        return {
            'CMP': round(cmp, 2), 'Change': change,
            'MarketCap': info.get('marketCap', 0), 'PE': info.get('trailingPE', 0),
            'ROE': info.get('returnOnEquity'), 'DebtToEquity': info.get('debtToEquity'),
            'ProfitMargin': info.get('profitMargins'), 'Sector': info.get('sector', 'N/A'),
        }, None
    except Exception as e:
        return None, f"Could not fetch stock data for {symbol} ({e})."

# ============= AI ANALYSIS =============
def score_pill_html(score, max_score=100):
    pct = (score / max_score) * 100 if max_score else 0
    cls = "score-high" if pct >= 70 else ("score-mid" if pct >= 50 else "score-low")
    return f'<span class="score-pill {cls}">{score}/{max_score}</span>'

def analyze(has_recent_tender, stock, bulk):
    score = 0; signals = []
    if has_recent_tender:
        score += 15; signals.append("✅ Recent order/tender-win announcement (NSE, confirmed)")
    if stock['Change'] > 5: score += 20; signals.append("📈 Strong momentum")
    elif stock['Change'] > 2: score += 10; signals.append("📈 Positive momentum")
    if bulk is not None:
        if bulk['Type'].startswith('Buy') and 'Promoter' in str(bulk['Buyer_Seller']): score += 20; signals.append("🔥 Promoter buying")
        elif bulk['Type'].startswith('Buy'): score += 10; signals.append("✅ Institutional buying")
        elif bulk['Type'].startswith('Sell') and 'Promoter' in str(bulk['Buyer_Seller']): score -= 20; signals.append("🚨 Promoter selling")
    rec = 'BUY ON DIPS' if score >= 30 else 'WATCHLIST' if score >= 15 else 'HOLD' if score >= 0 else 'STRICT AVOID'
    risk = 'LOW' if score >= 30 else 'MEDIUM' if score >= 15 else 'HIGH'
    return {'Score': score, 'Signals': signals, 'Recommendation': rec, 'Risk': risk}

@st.cache_data(ttl=1800)
def get_financial_trend(symbol):
    """Real quarterly revenue/net-profit trend from NSE's own filings.
    Returns (list of {period, revenue_cr, net_profit_cr}, error_message)."""
    try:
        from nse import NSE
        import tempfile
        with NSE(download_folder=tempfile.gettempdir()) as nse_client:
            data = nse_client.results_comparison(symbol)
        rows = data.get("resCmpData", []) if isinstance(data, dict) else []
        if not rows:
            return [], "No financial results data found."
        out = []
        for row in rows:
            try:
                out.append({
                    "period": row.get("re_to_dt", "N/A"),
                    "revenue_cr": round(float(row.get("re_total_inc", 0)) / 100, 1),
                    "net_profit_cr": round(float(row.get("re_net_profit", 0)) / 100, 1),
                })
            except (TypeError, ValueError):
                continue
        return out, None
    except Exception as e:
        return [], f"Could not fetch financial results ({e})."

@st.cache_data(ttl=1800)
def get_shareholding_snapshot(symbol):
    """Real, latest-quarter shareholding pattern as filed with NSE (Promoter/
    Public breakdown at minimum; other categories included as NSE reports
    them — field names aren't force-mapped to avoid mislabeling)."""
    try:
        from nse import NSE
        import tempfile
        with NSE(download_folder=tempfile.gettempdir()) as nse_client:
            data = nse_client.shareholding(symbol)
        records = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
        if not records:
            return None, "No shareholding pattern data found."
        latest = records[0]
        return latest, None
    except Exception as e:
        return None, f"Could not fetch shareholding pattern ({e})."

@st.cache_data(ttl=1800)
def get_post_tender_buying(symbol, tender_date_str):
    """Real bulk/block deal buying for this symbol from the tender-win date
    through today, using the same NSE deals pipeline as the rest of the app."""
    try:
        tender_date = pd.to_datetime(tender_date_str, format="%d-%b-%Y", errors="coerce")
        if pd.isna(tender_date):
            tender_date = pd.to_datetime(tender_date_str, errors="coerce")
        if pd.isna(tender_date):
            return pd.DataFrame(), "Could not parse tender announcement date."
        from_d = tender_date.date()
        to_d = datetime.now().date()
        if from_d > to_d:
            return pd.DataFrame(), None
        df, err = fetch_nse_deals_range(str(from_d), str(to_d))
        if err:
            return pd.DataFrame(), err
        if df.empty:
            return df, None
        return df[df["Symbol"].str.upper() == symbol.upper()].copy(), None
    except Exception as e:
        return pd.DataFrame(), f"Could not check post-tender deals ({e})."

def compute_fundamental_score(stock, fin_trend):
    """Score 0-100 from real, verifiable signals only. Returns (score, notes)."""
    score = 0
    notes = []
    if stock.get("Change") is not None:
        if stock["Change"] > 3: score += 15; notes.append("Positive price momentum")
        elif stock["Change"] < -3: notes.append("Negative price momentum")
    roe = stock.get("ROE")
    if roe is not None:
        if roe > 0.15: score += 20; notes.append(f"Healthy ROE ({roe*100:.1f}%)")
        elif roe > 0: score += 10; notes.append(f"Positive ROE ({roe*100:.1f}%)")
        else: notes.append(f"Negative ROE ({roe*100:.1f}%)")
    d2e = stock.get("DebtToEquity")
    if d2e is not None:
        if d2e < 50: score += 15; notes.append(f"Low debt (D/E {d2e:.0f})")
        elif d2e < 150: score += 5; notes.append(f"Moderate debt (D/E {d2e:.0f})")
        else: notes.append(f"High debt (D/E {d2e:.0f})")
    pm = stock.get("ProfitMargin")
    if pm is not None:
        if pm > 0.1: score += 15; notes.append(f"Solid profit margin ({pm*100:.1f}%)")
        elif pm > 0: score += 5; notes.append(f"Thin profit margin ({pm*100:.1f}%)")
        else: notes.append(f"Negative profit margin ({pm*100:.1f}%)")
    if len(fin_trend) >= 2:
        latest, prev = fin_trend[0], fin_trend[1]
        if latest["net_profit_cr"] > prev["net_profit_cr"] > 0:
            score += 20; notes.append("Net profit grew quarter-on-quarter")
        elif latest["net_profit_cr"] > 0:
            score += 10; notes.append("Profitable, but profit didn't grow QoQ")
        else:
            notes.append("Latest quarter net profit is negative")
    return min(score, 100), notes

# ============= REAL DATA: COMPANY NEWS (free, no key) =============
@st.cache_data(ttl=1800)
def get_company_news(query, max_items=6):
    """Real recent news headlines via Google News RSS — free, no API key.
    Returns (list of {title, link, source, date}, error_message)."""
    try:
        import feedparser
        import urllib.parse
        q = urllib.parse.quote(f"{query} stock India")
        url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
        feed = feedparser.parse(url)
        if not feed.entries:
            return [], None
        items = []
        for e in feed.entries[:max_items]:
            source = ""
            if isinstance(e.get("source"), dict):
                source = e.get("source", {}).get("title", "")
            items.append({
                "title": e.get("title", "Untitled"),
                "link": e.get("link", ""),
                "source": source,
                "date": e.get("published", ""),
            })
        return items, None
    except Exception as ex:
        return [], f"Could not fetch news ({ex})."

# ============= OPTIONAL: AI SYNTHESIS (needs the user's own LLM API key) =============
def get_ai_summary(symbol, company_name, stock, analysis, fin_trend, news_items):
    """Synthesizes the REAL data already gathered above into a plain-English
    paragraph using an LLM. Prefers genuinely free options (Google Gemini,
    then Groq's free open-source Llama models) before paid ones, so this
    works with zero cost for most usage. Requires the deployer's own key in
    Streamlit Cloud's Secrets — nothing is billed on your behalf without
    one. Returns (text_or_None, note)."""
    api_key = None
    provider = None
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key, provider = st.secrets["GEMINI_API_KEY"], "gemini"
        elif "GROQ_API_KEY" in st.secrets:
            api_key, provider = st.secrets["GROQ_API_KEY"], "groq"
        elif "ANTHROPIC_API_KEY" in st.secrets:
            api_key, provider = st.secrets["ANTHROPIC_API_KEY"], "anthropic"
        elif "OPENAI_API_KEY" in st.secrets:
            api_key, provider = st.secrets["OPENAI_API_KEY"], "openai"
    except Exception:
        pass

    if not api_key:
        return None, (
            "AI synthesis is off. To enable it **for free**, add **GEMINI_API_KEY** "
            "(from [Google AI Studio](https://aistudio.google.com/apikey), no credit card needed) "
            "or **GROQ_API_KEY** (from [console.groq.com](https://console.groq.com/keys), also free, "
            "serves open-source Llama models) under your Streamlit Cloud app → Settings → Secrets. "
            "Paid ANTHROPIC_API_KEY / OPENAI_API_KEY also work if you prefer those."
        )

    news_text = "\n".join([f"- {n['title']} ({n['source'] or 'unknown source'}, {n['date']})" for n in news_items[:5]]) or "No recent news found."
    fin_text = "\n".join([f"{f['period']}: Revenue ₹{f['revenue_cr']} Cr, Net Profit ₹{f['net_profit_cr']} Cr" for f in fin_trend[:4]]) or "No financial trend data available."
    prompt = f"""You are a cautious equity-research assistant. Using ONLY the facts listed below — never invent numbers or events — write a concise 4-6 sentence plain-English summary for a retail investor deciding whether to research {company_name} ({symbol}) further. Close with one balanced, non-prescriptive takeaway line. Do not give investment advice or a buy/sell instruction.

STOCK DATA: CMP ₹{stock['CMP']}, day change {stock['Change']}%, Market Cap ₹{stock['MarketCap']/1e7:.0f} Cr, P/E {stock.get('PE')}, ROE {stock.get('ROE')}, Debt/Equity {stock.get('DebtToEquity')}, Profit Margin {stock.get('ProfitMargin')}, Sector {stock.get('Sector')}
COMPOSITE SCORE: {analysis['Score']}/100, Recommendation label: {analysis['Recommendation']}, Risk: {analysis['Risk']}
SIGNALS TRIGGERED: {', '.join(analysis['Signals']) or 'None'}
RECENT QUARTERLY FINANCIALS (NSE filings):
{fin_text}
RECENT NEWS HEADLINES:
{news_text}
"""
    try:
        if provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            resp = model.generate_content(prompt)
            text = resp.text
        elif provider == "groq":
            from groq import Groq
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(model="llama-3.1-8b-instant", max_tokens=400, messages=[{"role": "user", "content": prompt}])
            text = resp.choices[0].message.content
        elif provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(model="claude-sonnet-4-5", max_tokens=400, messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        else:
            import openai
            client = openai.OpenAI(api_key=api_key)
            resp = client.chat.completions.create(model="gpt-4o-mini", max_tokens=400, messages=[{"role": "user", "content": prompt}])
            text = resp.choices[0].message.content
        return text, None
    except Exception as e:
        return None, f"AI synthesis failed ({e})."

# ============= MAIN UI =============
def main():
    st.markdown('<div class="main-header"><h1>📊 Tender Analyzer Pro</h1><p>Live Tender Scanner • Bulk Deal Tracker • AI Analysis</p><p style="font-size:0.9rem;opacity:0.8;">📅 {} • Powered by AI</p></div>'.format(datetime.now().strftime('%d %B %Y')), unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### 🎯 Smart Filters")
        days = st.slider("📅 Search Window (days)", 1, 30, 7, help="How far back to search NSE corporate announcements for order/tender-win language.")
        st.markdown("---")
        if st.button("🔄 Refresh All Data", use_container_width=True):
            st.cache_data.clear(); st.rerun()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📌 Tenders", "💹 Bulk Deals", "📊 Analysis", "🎯 Top Picks", "🧠 Smart Money Tracker", "🏆 Top Tender Picks"])

    tender_hits, tender_err = get_tender_win_announcements(days)
    if tender_err is not None:
        tender_hits = pd.DataFrame(columns=["Date", "Symbol", "Company", "Announcement"])

    bulk_deals, bulk_error, bulk_as_of = get_bulk_deals()
    if bulk_error is not None:
        # Fall back to empty frame with the right schema so the rest of the
        # app (Analysis/Top Picks lookups) doesn't crash
        bulk_deals = pd.DataFrame(columns=["Company", "Symbol", "Type", "Value_Cr", "Qty", "Buyer_Seller", "Date"])

    with st.sidebar:
        st.markdown("---")
        st.markdown("### 📊 Quick Stats (real, from NSE)")
        st.metric("📌 Tender/Order-Win Announcements", f"{len(tender_hits)}", help=f"Last {days} days, listed companies only")
        st.metric("🏢 Companies Involved", f"{tender_hits['Symbol'].nunique() if not tender_hits.empty else 0}")

    with tab1:
        st.caption(
            f"Source: NSE corporate announcements, keyword-matched for order/tender/contract-win language • last {days} days • cached 30 min. "
            "Covers **listed companies only** — CPPP/GeM government tender data has no free public API, so smaller/unlisted awardees won't show here."
        )
        st.markdown(f"### 📌 Confirmed Order/Tender-Win Announcements (Last {days} Days)")
        if tender_err:
            st.error(f"⚠️ {tender_err}")
        elif tender_hits.empty:
            st.info(f"No confirmed order/tender-win announcements found for listed companies in the last {days} days. Try widening the search window in the sidebar.")
        else:
            for _, row in tender_hits.iterrows():
                st.markdown(f"""
                <div class="tender-card">
                    <h4>🏢 {row['Company']} <span style="font-size:0.8rem;color:#666;">({row['Symbol']})</span></h4>
                    <p>{row['Announcement']}</p>
                    <p style="font-size:0.85rem;color:#666;">📅 {row['Date']}</p>
                </div>
                """, unsafe_allow_html=True)

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
        st.markdown("### 📊 AI Company Analysis Report")
        st.caption(
            "Enter any NSE symbol for a full picture: live price + score, real fundamentals (yfinance), "
            "real quarterly financials (NSE filings), real recent news (Google News), and an optional "
            "AI-written synthesis of all of the above."
        )
        sym = st.text_input("🔍 Enter Symbol (e.g., LT, IRFC, HAL)", "LT")
        if st.button("🚀 Analyze Now", use_container_width=True):
            with st.spinner("🔄 Gathering live data…"):
                stock, stock_err = get_stock(sym)
                if stock_err:
                    st.error(f"⚠️ {stock_err}")
                else:
                    has_recent_tender = (not tender_hits.empty) and (sym.upper() in tender_hits['Symbol'].str.upper().values)
                    bulk = bulk_deals[bulk_deals['Symbol'] == sym].iloc[0] if not bulk_deals[bulk_deals['Symbol'] == sym].empty else None
                    analysis = analyze(has_recent_tender, stock, bulk)
                    fin_trend, fin_err = get_financial_trend(sym)
                    news_items, news_err = get_company_news(sym)

                    c1, c2, c3, c4 = st.columns(4)
                    with c1: st.metric("💰 CMP", f"₹{stock['CMP']:.2f}", f"{stock['Change']:+.2f}%")
                    with c2: st.metric("📊 Mkt Cap", f"₹{stock['MarketCap']/1e9:.2f}B")
                    with c3: st.metric("🎯 Score", f"{analysis['Score']}/100")
                    with c4: st.metric("⚠️ Risk", analysis['Risk'])
                    signals_text = "\n".join([f"- {s}" for s in analysis['Signals']]) if analysis['Signals'] else "_No additional signals found._"
                    rec_color = '#0a5c2e' if analysis['Score']>=30 else ('#7a5c00' if analysis['Score']>=15 else '#7a1224')
                    st.markdown(f"""
                    ### 📋 Recommendation: <span style="color:{rec_color};">{analysis['Recommendation']}</span> {score_pill_html(analysis['Score'])}
                    #### Signals:
                    {signals_text}
                    """, unsafe_allow_html=True)

                    st.markdown("---")
                    fc1, fc2 = st.columns(2)
                    with fc1:
                        st.markdown("#### 🧮 Fundamentals (yfinance)")
                        pe = stock.get('PE'); roe = stock.get('ROE'); d2e = stock.get('DebtToEquity'); pm = stock.get('ProfitMargin')
                        st.markdown(f"""
                        - **Sector:** {stock.get('Sector', 'N/A')}
                        - **P/E Ratio:** {f'{pe:.1f}' if pe else 'N/A'}
                        - **ROE:** {f'{roe*100:.1f}%' if roe is not None else 'N/A'}
                        - **Debt/Equity:** {f'{d2e:.0f}' if d2e is not None else 'N/A'}
                        - **Profit Margin:** {f'{pm*100:.1f}%' if pm is not None else 'N/A'}
                        """)
                    with fc2:
                        st.markdown("#### 📈 Quarterly Revenue & Net Profit (NSE, ₹ Cr)")
                        if fin_err or not fin_trend:
                            st.caption(f"⚠️ {fin_err or 'No financial results data found.'}")
                        else:
                            st.dataframe(pd.DataFrame(fin_trend[:4]), use_container_width=True, hide_index=True)

                    st.markdown("---")
                    st.markdown("#### 📰 Recent News")
                    if news_err:
                        st.caption(f"⚠️ {news_err}")
                    elif not news_items:
                        st.info("No recent news found for this symbol.")
                    else:
                        for n in news_items:
                            st.markdown(f"- [{n['title']}]({n['link']})  <span style='color:#888;font-size:0.8rem;'>· {n['source']} · {n['date']}</span>", unsafe_allow_html=True)

                    st.markdown("---")
                    st.markdown("#### 🤖 AI Synthesis")
                    ai_text, ai_note = get_ai_summary(sym, sym, stock, analysis, fin_trend, news_items)
                    if ai_text:
                        st.info(ai_text)
                        st.caption("Generated by an LLM strictly from the real data shown above — not an independent data source.")
                    else:
                        st.warning(f"⚠️ {ai_note}")

    with tab4:
        st.markdown("### 🎯 Top Picks")
        st.caption("Ranked only among companies with a **confirmed** NSE order/tender-win announcement in the search window — no sample/fake entries.")
        if tender_hits.empty:
            st.info(f"No confirmed order/tender-win announcements in the last {days} days, so there's nothing real to rank yet. Try widening the search window in the sidebar.")
        else:
            recs = []
            for symbol in tender_hits['Symbol'].unique():
                stock, stock_err = get_stock(symbol)
                if stock_err or stock is None:
                    continue  # skip symbols we genuinely can't get real prices for
                bulk = bulk_deals[bulk_deals['Symbol'] == symbol]
                a = analyze(True, stock, bulk.iloc[0] if not bulk.empty else None)
                company = tender_hits[tender_hits['Symbol'] == symbol]['Company'].iloc[0]
                recs.append({'Company': company, 'Symbol': symbol, 'CMP': stock['CMP'], 'Score': a['Score'], 'Rec': a['Recommendation'], 'Risk': a['Risk']})
            if not recs:
                st.info("Found tender-win announcements, but couldn't fetch live prices for any of those symbols.")
            else:
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

    with tab6:
        st.markdown("### 🏆 Top Tender Picks — Fundamentally Vetted")
        st.caption(
            "Only companies with a **confirmed** NSE order/tender-win announcement (from the Tenders tab, "
            f"last {days} days) are considered. Each is checked against real yfinance stock ratios and NSE's own "
            "quarterly financial filings before ranking — nothing here is estimated or invented."
        )
        MIN_SCORE = 50
        if tender_hits.empty:
            st.info(f"No confirmed order/tender-win announcements in the last {days} days — nothing to vet yet. Widen the search window in the sidebar.")
        else:
            top_n = st.slider("How many top companies to show", 1, 10, 5, key="top_n_picks")
            candidates = list(tender_hits['Symbol'].unique())
            if len(candidates) > 15:
                st.caption(f"⚠️ {len(candidates)} companies found — evaluating the first 15 to keep load times reasonable.")
                candidates = candidates[:15]

            evaluated = []
            with st.spinner(f"Checking fundamentals for {len(candidates)} companies…"):
                for symbol in candidates:
                    stock, stock_err = get_stock(symbol)
                    if stock_err or stock is None:
                        continue
                    fin_trend, fin_err = get_financial_trend(symbol)
                    score, notes = compute_fundamental_score(stock, fin_trend)
                    company = tender_hits[tender_hits['Symbol'] == symbol]['Company'].iloc[0]
                    tender_date = tender_hits[tender_hits['Symbol'] == symbol]['Date'].iloc[0]
                    evaluated.append({
                        "Symbol": symbol, "Company": company, "Tender Date": tender_date,
                        "CMP": stock["CMP"], "Change %": stock["Change"], "Fundamental Score": score,
                        "notes": notes, "fin_trend": fin_trend, "fin_err": fin_err,
                    })

            qualified = [e for e in evaluated if e["Fundamental Score"] >= MIN_SCORE]

            if not evaluated:
                st.info("Found tender-win announcements, but couldn't fetch real fundamentals for any of those symbols.")
            elif not qualified:
                st.warning(
                    f"⚠️ None of the {len(evaluated)} evaluated companies scored {MIN_SCORE}+ right now. "
                    f"Highest was {max(e['Fundamental Score'] for e in evaluated)}/100 — showing nothing rather than a weak pick."
                )
            else:
                st.success(f"✅ {len(qualified)} of {len(evaluated)} companies scored {MIN_SCORE}+ ")
                qualified.sort(key=lambda x: x["Fundamental Score"], reverse=True)
                top_picks = qualified[:top_n]

                summary_df = pd.DataFrame([{
                    "Rank": i + 1, "Company": e["Company"], "Symbol": e["Symbol"],
                    "Tender Date": e["Tender Date"], "CMP": f"₹{e['CMP']:.2f}",
                    "Change %": f"{e['Change %']:+.2f}%", "Fundamental Score": f"{e['Fundamental Score']}/100",
                } for i, e in enumerate(top_picks)])
                st.dataframe(
                    summary_df.style.map(
                        lambda v: 'background: #d4edda; color: #0a5c2e; font-weight: 600;' if isinstance(v, str) and '/100' in v and int(v.split('/')[0]) >= 70
                        else ('background: #fff3cd; color: #7a5c00; font-weight: 600;' if isinstance(v, str) and '/100' in v else ''),
                        subset=["Fundamental Score"]
                    ),
                    use_container_width=True, hide_index=True
                )

                st.markdown("---")
                st.markdown("#### Detailed breakdown")
                for i, e in enumerate(top_picks):
                    score_emoji = "🟢" if e["Fundamental Score"] >= 70 else "🟡"
                    with st.expander(f"{score_emoji} #{i+1} — {e['Company']} ({e['Symbol']}) — Score {e['Fundamental Score']}/100"):
                        st.markdown(score_pill_html(e["Fundamental Score"]), unsafe_allow_html=True)
                        st.markdown("**Why it ranks here:**")
                        if e["notes"]:
                            for n in e["notes"]:
                                st.markdown(f"- {n}")
                        else:
                            st.markdown("_No real fundamental ratios were available from yfinance for this stock._")

                        st.markdown("**📊 Revenue & Net Profit trend (NSE filings, ₹ Cr):**")
                        if e["fin_err"] or not e["fin_trend"]:
                            st.caption(f"⚠️ {e['fin_err'] or 'No financial results data found.'}")
                        else:
                            fin_df = pd.DataFrame(e["fin_trend"][:5])
                            st.dataframe(fin_df, use_container_width=True, hide_index=True)

                        st.markdown("**🧾 Shareholding pattern (latest quarter, as filed with NSE):**")
                        share_data, share_err = get_shareholding_snapshot(e["Symbol"])
                        if share_err or not share_data:
                            st.caption(f"⚠️ {share_err or 'No shareholding data found.'}")
                        else:
                            skip_keys = {"symbol", "date"}
                            share_rows = [{"Field": k, "Value": v} for k, v in share_data.items() if k.lower() not in skip_keys]
                            st.dataframe(pd.DataFrame(share_rows), use_container_width=True, hide_index=True)
                            st.caption("As disclosed in NSE's official quarterly shareholding filing — fields are shown exactly as NSE reports them, not relabeled, so nothing is guessed.")

                        st.markdown("**💰 Buying activity since the tender-win announcement:**")
                        post_deals, post_err = get_post_tender_buying(e["Symbol"], e["Tender Date"])
                        if post_err:
                            st.caption(f"⚠️ {post_err}")
                        elif post_deals.empty:
                            st.caption("No bulk/block deals recorded for this stock since the announcement.")
                        else:
                            buy_side = post_deals[post_deals["Type"].str.startswith("Buy")]
                            if buy_side.empty:
                                st.caption("No buy-side bulk/block deals since the announcement (some sell-side activity may exist).")
                            else:
                                buyer_summary = buy_side.groupby("Buyer_Seller").agg(
                                    Value_Cr=("Value_Cr", "sum"), Qty=("Qty", "sum")
                                ).reset_index().sort_values("Value_Cr", ascending=False)
                                buyer_summary["Qty"] = buyer_summary["Qty"].map(lambda x: f"{int(x):,}")
                                buyer_summary.columns = ["Buyer", "Value Bought (₹ Cr)", "Quantity"]
                                st.dataframe(buyer_summary, use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
