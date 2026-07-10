import streamlit as st
import ccxt
import pandas as pd
import plotly.express as px
from supabase import create_client, Client

# 1. PAGE CONFIGURATION
st.set_page_config(page_title="My Crypto Trading Journal", page_icon="📈", layout="wide")

# 2. PASSWORD PROTECTION
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct:
        return True

    st.title("🔒 Private Trading Journal")
    password_input = st.text_input("Enter Access Password", type="password")
    correct_password = st.secrets.get("JOURNAL_PASSWORD", "vibe_coding_2026")

    if st.button("Unlock Journal"):
        if password_input == correct_password:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("😕 Incorrect password. Try again.")
    return False

if not check_password():
    st.stop()

# 3. INITIALIZE SUPABASE CLIENT
@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = get_supabase_client()

# 4. OKX ENGINE - FETCH TRADES & ACTIVE POSITIONS
def fetch_okx_data():
    sync_status = "Sync Initiated"
    positions_df = pd.DataFrame()
    
    try:
        exchange = ccxt.myokx({
            'apiKey': st.secrets["OKX_API_KEY"],
            'secret': st.secrets["OKX_SECRET"],
            'password': st.secrets["OKX_PASSPHRASE"],
            'options': {'defaultType': 'swap'}
        })
        
        # --- PARSE LIVE OPEN POSITIONS ---
        try:
            raw_positions = exchange.fetch_positions(symbols=None, params={})
            pos_list = []
            for p in raw_positions:
                # Filter out positions with 0 contract sizes
                if float(p.get('contracts', 0)) != 0:
                    pos_list.append({
                        "Symbol": p['symbol'],
                        "Side": p['side'].upper(),
                        "Leverage": f"{p.get('leverage', 1)}x",
                        "Contracts/Size": p['contracts'],
                        "Entry Price": p['entryPrice'],
                        "Mark Price": p.get('markPrice', p.get('liquidationPrice', 0)),
                        "Unrealized PnL ($)": float(p.get('unrealizedPnl', 0)),
                        "Collateral Type": p.get('initialMarginByClass', 'USDT')
                    })
            if pos_list:
                positions_df = pd.DataFrame(pos_list)
        except Exception as pos_err:
            st.warning(f"Could not load open positions: {pos_err}")

        # --- PARSE & SYNC CLOSED HISTORY ---
        thirty_days_ago = exchange.milliseconds() - (30 * 24 * 60 * 60 * 1000)
        trades = exchange.fetch_my_trades(symbol=None, since=thirty_days_ago, limit=100, params={'tradeType': 'FUTURES'})
        
        if not trades:
            sync_status = "No recent executions found on OKX server inside the 30-day window."
            return sync_status, positions_df

        new_records_count = 0
        for t in trades:
            trade_id = str(t['id'])
            existing = supabase.table("trading_journal").select("id").eq("id", trade_id).execute()
            
            if len(existing.data) == 0:
                cost = t.get('cost', 0) if t.get('cost', 0) > 0 else (t['price'] * t['amount'])
                trade_data = {
                    "id": trade_id,
                    "trade_date": t['datetime'],
                    "symbol": t['symbol'],
                    "side": t['side'].upper(),
                    "price": float(t['price']),
                    "amount": float(t['amount']),
                    "cost": float(cost),
                    "fee": float(t.get('fee', {}).get('cost', 0))
                }
                supabase.table("trading_journal").insert(trade_data).execute()
                new_records_count += 1
                
        sync_status = f"Sync Complete! Added {new_records_count} new entries to database vault."
    except Exception as e:
        sync_status = f"Sync Gateway Error: {str(e)}"
        
    return sync_status, positions_df

# 5. RETRIEVE VAULT DATA
def load_journal_from_db():
    try:
        response = supabase.table("trading_journal").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error reading database vault: {e}")
        return pd.DataFrame()

# 6. DASHBOARD GENERATION
st.title("📊 Personal Crypto Trading Command")
st.markdown("Automated metrics syncing with OKX and logging permanently to your Supabase vault.")

# Compute Sync
sync_status, open_positions_df = fetch_okx_data()
history_df = load_journal_from_db()

# --- SECTION A: LIVE ACTIVE POSITIONS RISK WINDOW ---
st.markdown("## 🚨 Live Floating Positions")
if open_positions_df.empty:
    st.info("🟢 No active open positions floating on OKX right now.")
else:
    # Highlight the current floating PnL across active risk exposure
    total_float_pnl = open_positions_df["Unrealized PnL ($)"].sum()
    if total_float_pnl >= 0:
        st.success(f"**Total Floating Equity Drift:** +${total_float_pnl:,.2f}")
    else:
        st.error(f"**Total Floating Equity Drift:** -${abs(total_float_pnl):,.2f}")
        
    st.dataframe(open_positions_df, use_container_width=True, hide_index=True)

st.markdown("---")

# --- SECTION B: HISTORIC VAULT ANALYTICS ---
st.markdown("## 🗄️ Vault Metrics (Historical Data)")

if history_df.empty:
    st.info("Your permanent database vault is currently empty.")
    st.warning(f"Sync Feedback: {sync_status}")
else:
    st.toast(sync_status, icon="🔄")
    
    # Metrics Panel
    col1, col2, col3 = st.columns(3)
    total_trades = len(history_df)
    total_volume = history_df['cost'].sum()
    total_fees = history_df['fee'].sum()
    
    col1.metric("Lifetime Logged Executions", total_trades)
    col2.metric("Total Traded Volume", f"${total_volume:,.2f}")
    col3.metric("Accumulated Fees", f"${total_fees:,.2f}")

    # Charts 
    left, right = st.columns(2)
    with left:
        fig_bar = px.bar(history_df, x="symbol", y="cost", color="side", title="Historical Volume per Asset Node")
        st.plotly_chart(fig_bar, use_container_width=True)
    with right:
        fig_scatter = px.scatter(history_df, x="trade_date", y="price", color="symbol", size="amount", title="Historic Execution Distribution")
        st.plotly_chart(fig_scatter, use_container_width=True)

    # Detailed Ledger Table
    st.subheader("📝 Historic Trade Ledger Table")
    display_df = history_df.rename(columns={
        "trade_date": "Date/Time",
        "symbol": "Contract Symbol",
        "side": "Order Side",
        "price": "Execution Price",
        "amount": "Size/Contracts",
        "cost": "Total Cost ($)",
        "fee": "Trading Fee ($)"
    })
    st.dataframe(display_df.sort_values(by="Date/Time", ascending=False), use_container_width=True, hide_index=True)
