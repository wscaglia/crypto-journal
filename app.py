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

# 4. SYNC DATA FROM OKX TO SUPABASE
def sync_okx_to_database():
    try:
        # Initialize OKX connection via CCXT
        exchange = ccxt.myokx({
            'apiKey': st.secrets["OKX_API_KEY"],
            'secret': st.secrets["OKX_SECRET"],
            'password': st.secrets["OKX_PASSPHRASE"],
            'options': {
                'defaultType': 'swap', # Focus on Futures/Perpetuals (.UM)
            }
        })
        
        # Pull the last 100 executions from OKX
        trades = exchange.fetch_my_trades(symbol=None, since=None, limit=100, params={'tradeType': 'FUTURES'})
        
        if not trades:
            return "No recent executions found on OKX server."

        new_records_count = 0
        
        for t in trades:
            trade_id = str(t['id'])
            
            # Check if this specific execution is already saved in Supabase
            existing = supabase.table("trading_journal").select("id").eq("id", trade_id).execute()
            
            if len(existing.data) == 0:
                cost = t.get('cost', 0) if t.get('cost', 0) > 0 else (t['price'] * t['amount'])
                
                # Format record structure matching our PostgreSQL columns
                trade_data = {
                    "id": trade_id,
                    "trade_date": t['datetime'], # CCXT ISO timestamp
                    "symbol": t['symbol'],
                    "side": t['side'].upper(),
                    "price": float(t['price']),
                    "amount": float(t['amount']),
                    "cost": float(cost),
                    "fee": float(t.get('fee', {}).get('cost', 0))
                }
                
                # Insert safely into database
                supabase.table("trading_journal").insert(trade_data).execute()
                new_records_count += 1
                
        return f"Sync complete! Found and stored {new_records_count} new executions."
    except Exception as e:
        return f"Sync Warning/Error: {str(e)}"

# 5. FETCH ENTIRE JOURNAL HISTORY FROM DATABASE
def load_journal_from_db():
    try:
        response = supabase.table("trading_journal").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading database ledger: {e}")
        return pd.DataFrame()

# 6. APP EXECUTION & UI RENDER
st.title("📊 Permanent Futures Trading Journal")
st.markdown("Your data is safe here. Syncing automatically with OKX and saving forever.")

# Run sync process silently
sync_status = sync_okx_to_database()

# Load all historic records from the database vault
df = load_journal_from_db()

if df.empty:
    st.info("Your database vault is currently empty.")
    st.warning(f"Status from sync attempt: {sync_status}")
    st.markdown("If you recently opened trades in the last few hours and they aren't appearing, double-check that your order fills were generated under a Live Unified Trading Account on OKX.")
else:
    # Top toast alert showing the sync results
    st.toast(sync_status, icon="🔄")

    # --- METRICS PANEL ---
    st.subheader("🏁 Performance Snapshot")
    col1, col2, col3 = st.columns(3)
    
    total_trades = len(df)
    total_volume = df['cost'].sum()
    total_fees = df['fee'].sum()
    
    col1.metric("Lifetime Logged Executions", total_trades)
    col2.metric("Total Traded Volume", f"${total_volume:,.2f}")
    col3.metric("Accumulated Fees", f"${total_fees:,.2f}")

    st.markdown("---")

    # --- CHARTS ---
    st.subheader("📈 Visual Analytics")
    left, right = st.columns(2)
    
    with left:
        st.write("**Executions by Asset**")
        fig_bar = px.bar(df, x="symbol", y="cost", color="side", title="Volume per Asset Node")
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with right:
        st.write("**Trading Activity Timeline**")
        fig_scatter = px.scatter(df, x="trade_date", y="price", color="symbol", size="amount", title="Execution Distribution")
        st.plotly_chart(fig_scatter, use_container_width=True)

    # --- DATA MATRIX ---
    st.subheader("📝 Historic Trade Ledger Vault")
    # Clean up column visual names for presentation mapping
    display_df = df.rename(columns={
        "trade_date": "Date/Time",
        "symbol": "Contract Symbol",
        "side": "Order Side",
        "price": "Execution Price",
        "amount": "Size/Contracts",
        "cost": "Total Cost ($)",
        "fee": "Trading Fee ($)"
    })
    st.dataframe(display_df.sort_values(by="Date/Time", ascending=False), use_container_width=True)
