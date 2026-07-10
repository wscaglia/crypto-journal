import streamlit as st
import ccxt
import pandas as pd
import plotly.express as px

# 1. PAGE CONFIGURATION
st.set_page_config(page_title="My Crypto Trading Journal", page_icon="📈", layout="wide")

# 2. PASSWORD PROTECTION
def check_password():
    """Returns True if the user had the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.title("🔒 Private Trading Journal")
    password_input = st.text_input("Enter Access Password", type="password")
    
    # In production, we fetch this from Streamlit Secrets
    correct_password = st.secrets.get("JOURNAL_PASSWORD", "vibe_coding_2026")

    if st.button("Unlock Journal"):
        if password_input == correct_password:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("😕 Incorrect password. Try again.")
    return False

# Stop app execution if the password isn't matched yet
if not check_password():
    st.stop()

# 3. OKX API CONNECTOR
@st.cache_data(ttl=60) # Refreshes every 60 seconds
def fetch_okx_futures_data():
    try:
        exchange = ccxt.myokx({
            'apiKey': st.secrets["OKX_API_KEY"],
            'secret': st.secrets["OKX_SECRET"],
            'password': st.secrets["OKX_PASSPHRASE"],
            'options': {
                'defaultType': 'swap', # Targets Perpetuals/Futures
            }
        })
        
        # Explicitly ask OKX for the last 100 actual executions
        # We pass tradeType='FUTURES' inside params for OKX Unified Accounts
        trades = exchange.fetch_my_trades(symbol=None, since=None, limit=100, params={'tradeType': 'FUTURES'})
        
        if not trades:
            return pd.DataFrame(), None
            
        trade_list = []
        for t in trades:
            # Calculate an estimated cost/volume if not provided directly
            cost = t.get('cost', 0) if t.get('cost', 0) > 0 else (t['price'] * t['amount'])
            
            trade_list.append({
                "Date": pd.to_datetime(t['datetime']),
                "Symbol": t['symbol'],
                "Side": t['side'].upper(),
                "Price": t['price'],
                "Amount": t['amount'],
                "Cost": cost,
                "Fee": t.get('fee', {}).get('cost', 0)
            })
        return pd.DataFrame(trade_list), None
        
    except Exception as e:
        return pd.DataFrame(), str(e)

# 4. DASHBOARD UI
st.title("📊 OKX Futures Trading Journal")
st.markdown("Automated metrics fetched straight from your OKX API.")

df, error_msg = fetch_okx_futures_data()

if not df.empty:
    st.subheader("🏁 Performance Snapshot")
    col1, col2, col3 = st.columns(3)
    
    total_records = len(df)
    
    # If we parsed a ledger, we can find total PnL changes
    if "Amount/PnL" in df.columns:
        # Filter out rows that represent changes in asset balances (Realized PnL or Fees)
        net_change = df["Amount/PnL"].sum()
        col1.metric("Net Change (PnL & Fees)", f"${net_change:,.4f}")
    
    col2.metric("Total Records Found", total_records)
    col3.metric("Active Sync", "Healthy 🟢")

    st.markdown("---")

    st.subheader("📈 History Log")
    
    # Simple Chart
    if "Amount/PnL" in df.columns:
        fig_pnl = px.line(df.sort_values(by="Date"), x="Date", y="Amount/PnL", title="Account Balance Adjustments / PnL Over Time")
        st.plotly_chart(fig_pnl, use_container_width=True)

    st.subheader("📝 Detailed Ledger Table")
    st.dataframe(df.sort_values(by="Date", ascending=False), use_container_width=True)
    
    # --- DATA TABLE ---
    st.subheader("📝 Detailed Trade Ledger")
    st.dataframe(df.sort_values(by="Date", ascending=False), use_container_width=True)
