import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

# 1. PAGE SETUP
st.set_page_config(page_title="AlphaQuant Trading Dashboard", page_icon="⚡", layout="wide")

# 2. GOOGLE OAUTH SECURITY GATE
if not st.user.is_logged_in:
    st.title("🔒 AlphaQuant Workspace Secure Gate")
    st.markdown("This private server requires localized authentication.")
    
    # Renders a sleek Google Auth Single Sign-On button
    st.button("Log in with Google", on_click=st.login, icon="🔑")
    st.stop()

# --- Authorization Access Check ---
# To make sure NO ONE ELSE with a random Google account can view your data,
# we verify that the logged-in email matches your specific personal email address!
MY_ALLOWED_EMAIL = "your_actual_gmail_address@gmail.com" # 👈 Paste your exact Gmail here

if st.user.email != MY_ALLOWED_EMAIL:
    st.error("🚫 Access Denied: This Google account is not whitelisted for this system vault.")
    st.button("Log out & Switch Accounts", on_click=st.logout)
    st.stop()

# Sidebar User interface element
st.sidebar.markdown(f"**👤 Authenticated as:** \n`{st.user.email}`")
st.sidebar.button("Secure Log Out", on_click=st.logout, type="primary")
# 3. DATA ENGINE (REAL VS MOCK SIMULATION FOR PREVIEW)
st.sidebar.title("⚙️ Control Panel")
mode = st.sidebar.radio("Data Engine Mode", ["🔮 Preview Simulation Mode", "🔗 Live OKX + Supabase Sync"])

def get_mock_data():
    """Generates 40 realistic closed trades across BTC and ETH for visual preview."""
    np.random.seed(42)
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']
    sides = ['LONG', 'SHORT']
    days = pd.date_range(end=pd.Timestamp.now(), periods=40, freq='D')
    
    mock_list = []
    for i, date in enumerate(days):
        sym = np.random.choice(symbols)
        side = np.random.choice(sides)
        entry = date - pd.Timedelta(hours=int(np.random.randint(1, 48))) # Holding time between 1 and 48 hours
        
        # Simulating random PnL distribution skewed slightly positive
        net_pnl = float(np.random.normal(loc=45, scale=250))
        fees = float(np.random.uniform(2, 15))
        gross_pnl = net_pnl + fees
        
        mock_list.append({
            "id": f"sim_{i}",
            "symbol": sym,
            "side": side,
            "entry_date": entry,
            "exit_date": date,
            "avg_entry_price": 65000 if 'BTC' in sym else 3400,
            "avg_exit_price": 65200 if 'BTC' in sym else 3420,
            "amount": float(np.random.uniform(0.1, 2)),
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl
        })
    df = pd.DataFrame(mock_list)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    df['exit_date'] = pd.to_datetime(df['exit_date'])
    return df

if mode == "🔮 Preview Simulation Mode":
    df = get_mock_data()
    st.sidebar.success("Displaying sample performance metrics!")
else:
    # Here your code would execute the live Supabase query we did in Phase 3
    # components linking to the 'advanced_journal' table
    st.sidebar.info("Waiting for real trades in advanced_journal table...")
    df = pd.DataFrame()

# 4. MATHS ENGINE (Calculating your advanced metrics)
if not df.empty:
    # Sort chronologically to plot structural growth metrics
    df = df.sort_values(by="exit_date").reset_index(drop=True)
    
    # Core Mathematical Variables
    wins = df[df['net_pnl'] > 0]
    losses = df[df['net_pnl'] <= 0]
    
    total_trades = len(df)
    win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0
    
    total_gross_profits = wins['net_pnl'].sum()
    total_gross_losses = abs(losses['net_pnl'].sum())
    profit_factor = total_gross_profits / total_gross_losses if total_gross_losses > 0 else total_gross_profits
    
    avg_win = wins['net_pnl'].mean() if not wins.empty else 0
    avg_loss = losses['net_pnl'].mean() if not losses.empty else 0
    
    # Expected Value (EV) = (Win% * AvgWin) + (Loss% * AvgLoss)
    expected_value = ((win_rate/100) * avg_win) + ((1 - (win_rate/100)) * avg_loss)
    
    # Holding Time (Minutes -> Hours Conversion)
    df['holding_time_hours'] = (df['exit_date'] - df['entry_date']).dt.total_seconds() / 3600
    avg_holding_time = df['holding_time_hours'].mean()

    # Cumulative calculations for line trends
    df['cumulative_pnl'] = df['net_pnl'].cumsum()
    
    # Dynamic Running Profit Factor Over Time
    running_pf = []
    for i in range(1, len(df) + 1):
        sub_df = df.iloc[:i]
        w = sub_df[sub_df['net_pnl'] > 0]['net_pnl'].sum()
        l = abs(sub_df[sub_df['net_pnl'] <= 0]['net_pnl'].sum())
        running_pf.append(w / l if l > 0 else w)
    df['running_profit_factor'] = running_pf

    # Day of Week Mapping
    df['day_of_week'] = df['exit_date'].dt.day_name()
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    pnl_by_day = df.groupby('day_of_week')['net_pnl'].sum().reindex(day_order).reset_index()

    # --- MAIN RENDER ---
    st.title("⚡ AlphaQuant Advanced Analytics Workspace")
    st.markdown("Deep-dive algorithmic performance telemetry.")

    # 📊 EXECUTIVE STATUS PANEL
    st.markdown("### 🏁 Core Vital Statistics")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Win Rate", f"{win_rate:.2f}%", help="Percentage of trades that closed positive.")
    m2.metric("Profit Factor", f"{profit_factor:.2f}x", help="Ratio of gross profits to gross losses. Above 1.0 means profitable.")
    m3.metric("Expected Value (EV)", f"${expected_value:.2f}", help="Expected returns per single trade distribution execution.")
    m4.metric("Avg Holding Time", f"{avg_holding_time:.1f} Hours", help="Average time spent resting inside active contracts.")
    m5.metric("Net Account PnL", f"${df['net_pnl'].sum():,.2f}")

    st.markdown("---")

    # 📈 ROW 1 CHARTS: EQUITY CURVE & PROFIT FACTOR
    st.markdown("### 📊 Capital Growth Vectors")
    c1, c2 = st.columns(2)
    
    with c1:
        st.write("**The Account Equity Curve (Cumulative Net PnL)**")
        fig_equity = px.line(df, x="exit_date", y="cumulative_pnl", title="Chronological Account Value Scaling ($)", markers=True)
        fig_equity.update_traces(line_color="#00FFCC", line_width=2)
        st.plotly_chart(fig_equity, use_container_width=True)
        
    with c2:
        st.write("**Running Profit Factor Incline**")
        fig_pf = px.line(df, x="exit_date", y="running_profit_factor", title="System Health Factor Decay Trend", markers=True)
        fig_pf.add_hline(y=1.0, line_dash="dash", line_color="red", annotation_text="Breakeven Threshold")
        fig_pf.update_traces(line_color="#FFCC00")
        st.plotly_chart(fig_pf, use_container_width=True)

    st.markdown("---")

    # 📊 ROW 2 CHARTS: WIN RATE BY ASSET & DAYS OF WEEK
    st.markdown("### 📊 Behavioral & Asset Efficiency")
    c3, c4 = st.columns(2)
    
    with c3:
        st.write("**Win Rate Stratification by Contract Token**")
        # Compute win rate per unique ticker string
        symbol_stats = df.groupby('symbol').apply(
            lambda x: (len(x[x['net_pnl'] > 0]) / len(x)) * 100
        ).reset_index(name='Win Rate (%)')
        fig_sym_win = px.bar(symbol_stats, x='symbol', y='Win Rate (%)', text_auto='.1f', title="Win Rate % per Asset Matrix", color='Win Rate (%)', color_continuous_scale='Bluered')
        fig_sym_win.add_hline(y=50.0, line_dash="dot", line_color="white")
        st.plotly_chart(fig_sym_win, use_container_width=True)
        
    with c4:
        st.write("**Profit Accumulation by Trading Day**")
        fig_day = px.bar(pnl_by_day, x='day_of_week', y='net_pnl', title="Net Profit Distribution Across Calendar Week", color='net_pnl', color_continuous_scale='Viridis')
        st.plotly_chart(fig_day, use_container_width=True)

    st.markdown("---")

    # 📊 ROW 3 CHARTS: EXPECTED VALUE DISTRIBUTION
    st.markdown("### 🎯 Mathematical Value Mapping")
    c5, c6 = st.columns(2)
    
    with c5:
        st.write("**Rolling Mathematical Expected Value (EV)**")
        # Calculate running EV sequence
        running_ev = []
        for i in range(5, len(df) + 1): # Start at 5 trades for viable sample sizing
            sub = df.iloc[:i]
            w_r = len(sub[sub['net_pnl'] > 0]) / len(sub)
            a_w = sub[sub['net_pnl'] > 0]['net_pnl'].mean() if len(sub[sub['net_pnl'] > 0]) > 0 else 0
            a_l = sub[sub['net_pnl'] <= 0]['net_pnl'].mean() if len(sub[sub['net_pnl'] <= 0]) > 0 else 0
            running_ev.append((w_r * a_w) + ((1 - w_r) * a_l))
        
        fig_ev = px.area(x=df['exit_date'].iloc[4:], y=running_ev, title="Edge Stability Trend ($ Value Expectancy per Execution)")
        fig_ev.update_traces(line_color="#A100FF")
        st.plotly_chart(fig_ev, use_container_width=True)
        
    with c6:
        st.write("**Position Hold Duration Spectrum**")
        fig_hist = px.histogram(df, x="holding_time_hours", color="side", barmode="overlay", title="Trade Lifetime Profile (Hours spent inside contracts)")
        st.plotly_chart(fig_hist, use_container_width=True)

else:
    st.info("The application workspace is loaded. Select Simulation Mode or supply database data nodes.")
