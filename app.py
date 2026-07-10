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
@st.cache_data(ttl=300) # Caches data for 5 minutes so it doesn't spam OKX on every click
def fetch_okx_futures_data():
    try:
        # Fetching credentials securely from secrets
        exchange = ccxt.myokx({
            'apiKey': st.secrets["OKX_API_KEY"],
            'secret': st.secrets["OKX_SECRET"],
            'password': st.secrets["OKX_PASSPHRASE"], # OKX requires an API passphrase
            'options': {
                'defaultType': 'swap', # 'swap' fetches perpetual futures in CCXT
            }
        })
        
        # Pull closed positions / orders history (Adjust limit as needed)
        # Note: OKX divides trade data into orders and account bills. 
        # CCXT's fetch_my_trades parses closed order execution histories cleanly.
        trades = exchange.fetch_my_trades(limit=50)
        
        # Parse into a clean DataFrame
        trade_list = []
        for t in trades:
            trade_list.append({
                "Date": pd.to_datetime(t['datetime']),
                "Symbol": t['symbol'],
                "Side": t['side'],
                "Price": t['price'],
                "Amount": t['amount'],
                "Cost": t['cost'],
                "Fee": t.get('fee', {}).get('cost', 0)
            })
            
        return pd.DataFrame(trade_list)
    except Exception as e:
        st.error(f"Error connecting to OKX: {e}")
        return pd.DataFrame()

# 4. DASHBOARD UI
st.title("📊 OKX Futures Trading Journal")
st.markdown("Automated metrics fetched straight from your OKX API.")

# Fetch data
df = fetch_okx_futures_data()

if df.empty:
    st.warning("No recent trade data fetched. Double-check your API keys or execute some trades on OKX!")
else:
    # --- METRICS SECTION ---
    st.subheader("🏁 Performance Snapshot")
    col1, col2, col3, col4 = st.columns(4)
    
    total_trades = len(df)
    # Note: Real accurate PnL tracking generally requires fetching 'bills' from OKX, 
    # but for this initial MVP dashboard, we will calculate total cost/volume.
    total_volume = df['Cost'].sum()
    total_fees = df['Fee'].sum()
    
    col1.metric("Total Executions", total_trades)
    col2.metric("Total Traded Volume", f"${total_volume:,.2f}")
    col3.metric("Total Paid Fees", f"${total_fees:,.2f}")
    col4.metric("Active Sync", "Healthy 🟢")

    st.markdown("---")

    # --- CHARTS SECTION ---
    st.subheader("📈 Analytics & Logs")
    left_chart, right_chart = st.columns(2)
    
    with left_chart:
        st.write("**Traded Volume Distribution by Asset**")
        fig_volume = px.bar(df, x="Symbol", y="Cost", color="Side", title="Volume per Symbol")
        st.plotly_chart(fig_volume, use_container_width=True)
        
    with right_chart:
        st.write("**Activity Timeline**")
        fig_time = px.scatter(df, x="Date", y="Price", color="Symbol", size="Amount", title="Execution Prices Over Time")
        st.plotly_chart(fig_time, use_container_width=True)

    # --- DATA TABLE ---
    st.subheader("📝 Detailed Trade Ledger")
    st.dataframe(df.sort_values(by="Date", ascending=False), use_container_width=True)
