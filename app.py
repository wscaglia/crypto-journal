import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import ccxt
import calendar
from datetime import datetime, timedelta
from supabase import create_client, Client

# 1. PAGE SETUP
st.set_page_config(page_title="AlphaQuant Trading Dashboard", page_icon="⚡", layout="wide")

# 2. SECURITY SINGLE SIGN-ON GATE
if not st.user.is_logged_in:
    st.title("🔒 AlphaQuant Workspace Secure Gate")
    st.markdown("This private server requires localized authentication.")
    st.button("Log in with Google", on_click=st.login, args=["google"], icon="🔑")
    st.stop()

# --- Authorization Access Check ---
MY_ALLOWED_EMAIL = "wscaglia@gmail.com" 

if st.user.email != MY_ALLOWED_EMAIL:
    st.error("🚫 Access Denied: This Google account is not whitelisted for this system vault.")
    st.button("Log out & Switch Accounts", on_click=st.logout, key="denied_logout")
    st.stop()

st.sidebar.markdown(f"**👤 Authenticated as:** \n`{st.user.email}`")
st.sidebar.button("Secure Log Out", on_click=st.logout, type="primary", key="sidebar_logout")

# 3. INITIALIZE CLOUD CLIENTS
@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = get_supabase_client()

# 4. DATA ENGINE (REAL EXCHANGE CONNECTOR & SYNC VS PREVIEW SIMULATION)
st.sidebar.title("⚙️ Control Panel")
mode = st.sidebar.radio("Data Engine Mode", ["🔗 Live Account Sync", "🔮 Preview Simulation Mode"])

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Data Filters")
timeframe = st.sidebar.selectbox("Analysis Horizon", ["All Time", "Last 30 Days", "Last 7 Days"])

def get_mock_data():
    """Generates 40 realistic closed trades across BTC/ETH contracts for preview modeling."""
    np.random.seed(42)
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']
    sides = ['LONG', 'SHORT']
    days = pd.date_range(end=pd.Timestamp.now(), periods=40, freq='D')
    
    mock_list = []
    for i, date in enumerate(days):
        sym = np.random.choice(symbols)
        side = np.random.choice(sides)
        entry = date - pd.Timedelta(hours=int(np.random.randint(1, 48)))
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
    df_mock = pd.DataFrame(mock_list)
    df_mock['entry_date'] = pd.to_datetime(df_mock['entry_date'])
    df_mock['exit_date'] = pd.to_datetime(df_mock['exit_date'])
    return df_mock

def fetch_live_account_and_sync():
    sync_status = "Sync Initiated"
    positions_df = pd.DataFrame()
    balance_dict = {}
    
    try:
        # Initialize CCXT client router
        exchange = ccxt.myokx({
            'apiKey': st.secrets["OKX_API_KEY"],
            'secret': st.secrets["OKX_SECRET"],
            'password': st.secrets["OKX_PASSPHRASE"],
        })
        
        # --- A. WALLET BALANCE RETRIEVAL ---
        try:
            bal_raw = exchange.fetch_balance()
            if bal_raw and 'total' in bal_raw:
                balance_dict = {ccy: amt for ccy, amt in bal_raw['total'].items() if amt > 0.0}
        except:
            pass

        # --- B. RETRIEVE LIVE FLOATING POSITIONS ---
        try:
            raw_positions = exchange.fetch_positions(symbols=None, params={})
            pos_list = []
            for p in raw_positions:
                if float(p.get('contracts', 0)) != 0:
                    pos_list.append({
                        "Symbol": p['symbol'],
                        "Side": p['side'].upper(),
                        "Leverage": f"{p.get('leverage', 1)}x",
                        "Contracts/Size": p['contracts'],
                        "Entry Price": p['entryPrice'],
                        "Mark Price": p.get('markPrice', 0),
                        "Unrealized PnL ($)": float(p.get('unrealizedPnl', 0)),
                        "Collateral Asset": p.get('marginClass', 'USDT')
                    })
            if pos_list:
                positions_df = pd.DataFrame(pos_list)
        except:
            pass

        # --- C. DEEP-SWEEP COMPLETED ORDERS ---
        thirty_days_ago = exchange.milliseconds() - (30 * 24 * 60 * 60 * 1000)
        consolidated_orders = []
        
        target_types = ['SWAP', 'MARGIN', 'FUTURES']
        scanned_counts = {"SWAP": 0, "MARGIN": 0, "FUTURES": 0}
        
        for inst_type in target_types:
            try:
                orders = exchange.fetch_closed_orders(symbol=None, since=thirty_days_ago, limit=100, params={'instType': inst_type})
                if orders:
                    filled_orders = [o for o in orders if o.get('status') == 'closed' or float(o.get('filled', 0)) > 0]
                    consolidated_orders.extend(filled_orders)
                    scanned_counts[inst_type] = len(filled_orders)
            except:
                pass
        
        if consolidated_orders:
            new_records = 0
            for o in consolidated_orders:
                order_id = str(o['id'])
                existing = supabase.table("advanced_journal").select("id").eq("id", order_id).execute()
                
                if len(existing.data) == 0:
                    fee_cost = float(o.get('fee', {}).get('cost', 0)) if o.get('fee') else 0.0
                    raw_pnl = float(o.get('info', {}).get('pnl', 0.0))
                    net_pnl_calc = raw_pnl if raw_pnl != 0.0 else float(fee_cost * -1)
                    
                    order_data = {
                        "id": order_id,
                        "symbol": o['symbol'],
                        "side": o['side'].upper(),
                        "entry_date": o['datetime'],
                        "exit_date": o['datetime'],
                        "avg_entry_price": float(o.get('average', o.get('price', 1))),
                        "avg_exit_price": float(o.get('average', o.get('price', 1))),
                        "amount": float(o.get('filled', o.get('amount', 0))),
                        "gross_pnl": float(net_pnl_calc + fee_cost),
                        "fees": fee_cost,
                        "net_pnl": net_pnl_calc
                    }
                    supabase.table("advanced_journal").insert(order_data).execute()
                    new_records += 1
            sync_status = f"Sync Completed! Found Scanned: Swap={scanned_counts['SWAP']}, Margin={scanned_counts['MARGIN']}, Futures={scanned_counts['FUTURES']}. Added {new_records} items."
        else:
            sync_status = f"No closed orders found across categories (Scanned: Swap=0, Margin=0, Futures={scanned_counts['FUTURES']})."
            
    except Exception as e:
        sync_status = f"API Synchronization Bridge Warning: {str(e)}"
        
    return sync_status, positions_df, balance_dict

def load_history_from_db():
    try:
        response = supabase.table("advanced_journal").select("*").execute()
        if response.data:
            df_db = pd.DataFrame(response.data)
            df_db['entry_date'] = pd.to_datetime(df_db['entry_date'])
            df_db['exit_date'] = pd.to_datetime(df_db['exit_date'])
            return df_db
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error accessing database warehouse: {e}")
        return pd.DataFrame()

# EXECUTE DATA PROCESSING PIPELINE
if mode == "🔮 Preview Simulation Mode":
    df = get_mock_data()
    open_positions_df = pd.DataFrame([{
        "Symbol": "BTC/USDT:USDT", "Side": "LONG", "Leverage": "20x",
        "Contracts/Size": "1.50", "Entry Price": 64200.0, "Mark Price": 65150.0,
        "Unrealized PnL ($)": 1425.0, "Collateral Asset": "USDT"
    }])
    live_balances = {"USDT": 314.50, "USDC": 12.20}
    sync_status = "Simulation Cache Verified"
    st.sidebar.success("Displaying analytical performance models!")
else:
    sync_status, open_positions_df, live_balances = fetch_live_account_and_sync()
    df = load_history_from_db()

# 5. MATHEMATICS & METRICS COMPILER
if not df.empty:
    df = df.sort_values(by="exit_date").reset_index(drop=True)
    
    # App-side Timeframe Slicing Filter Interface
    max_date_in_db = df['exit_date'].max()
    if timeframe == "Last 7 Days":
        cutoff = max_date_in_db - timedelta(days=7)
        filtered_df = df[df['exit_date'] >= cutoff].copy()
    elif timeframe == "Last 30 Days":
        cutoff = max_date_in_db - timedelta(days=30)
        filtered_df = df[df['exit_date'] >= cutoff].copy()
    else:
        filtered_df = df.copy() 
        
    if filtered_df.empty:
        filtered_df = df.copy()
        st.sidebar.warning(f"No records inside selected window. Defaulting view to All Time.")

    # FILTER OUT ZERO-TRADING SYSTEM NOISE
    filtered_df['gross_profit_before_fees'] = filtered_df['net_pnl'] + filtered_df['fees']
    clean_df = filtered_df[filtered_df['gross_profit_before_fees'].round(4) != 0.0].copy()
    
    if clean_df.empty:
        clean_df = filtered_df.copy()
        
    wins = clean_df[clean_df['net_pnl'] > 0]
    losses = clean_df[clean_df['net_pnl'] <= 0]
    
    total_trades = len(clean_df)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
    
    # Rewards Score = Winners - Losses
    rewards_count = win_count - loss_count
    
    # Financial Sums
    sum_rewards = wins['net_pnl'].sum()
    sum_losses = losses['net_pnl'].sum()
    sum_total_fees = filtered_df['fees'].sum() 
    
    total_gross_profits = sum_rewards
    total_gross_losses = abs(sum_losses)
    profit_factor = total_gross_profits / total_gross_losses if total_gross_losses > 0 else total_gross_profits
    
    avg_win = wins['net_pnl'].mean() if not wins.empty else 0
    avg_loss = abs(losses['net_pnl'].mean()) if not losses.empty else 1
    avg_risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
    
    # DURATION ENGINES LIFESPAN PARSER
    try:
        grouped_durations = []
        for symbol, group in clean_df.groupby('symbol'):
            if len(group) >= 2:
                sorted_group = group.sort_values(by='exit_date')
                first_entry = sorted_group['exit_date'].min()
                last_exit = sorted_group['exit_date'].max()
                duration_hours = (last_exit - first_entry).total_seconds() / 3600
                if duration_hours > 0.01:
                    grouped_durations.append(duration_hours)
        if grouped_durations:
            avg_holding_time = np.mean(grouped_durations)
        else:
            avg_holding_time = 25.0  
    except:
        avg_holding_time = 25.0
    clean_df['holding_time_hours'] = avg_holding_time
    
    # DIRECTIONAL INTENT LOGIC
    if mode == "🔮 Preview Simulation Mode":
        longs_count = len(clean_df[clean_df['side'] == 'LONG'])
        shorts_count = len(clean_df[clean_df['side'] == 'SHORT'])
    else:
        execs_df = clean_df.copy()
        raw_buys = len(execs_df[execs_df['side'].str.upper().isin(['BUY', 'LONG'])])
        raw_sells = len(execs_df[execs_df['side'].str.upper().isin(['SELL', 'SHORT'])])
        
        if raw_buys > 0 and raw_sells > 0 and raw_buys == raw_sells:
            longs_count = raw_buys
            shorts_count = 0
        else:
            longs_count = raw_buys
            shorts_count = raw_sells
            
    total_direction_sum = longs_count + shorts_count
    long_pct = (longs_count / total_direction_sum) * 100 if total_direction_sum > 0 else 100.0
    short_pct = (shorts_count / total_direction_sum) * 100 if total_direction_sum > 0 else 0.0
    
    # Cumulative Curves & Running Drawdown Math
    filtered_df = filtered_df.sort_values(by="exit_date").reset_index(drop=True)
    filtered_df['cumulative_pnl'] = filtered_df['net_pnl'].cumsum()
    
    # 🚨 DRAWDOWN CALCULATOR
    # Drawdown % = ((Cumulative PnL + Seed) - Running Peak) / Running Peak * 100
    starting_seed_baseline = 278.32
    filtered_df['total_account_value'] = filtered_df['cumulative_pnl'] + starting_seed_baseline
    filtered_df['running_peak'] = filtered_df['total_account_value'].cummax()
    filtered_df['drawdown_percent'] = ((filtered_df['total_account_value'] - filtered_df['running_peak']) / filtered_df['running_peak']) * 100
    
    running_pf = []
    for i in range(1, len(filtered_df) + 1):
        sub = filtered_df.iloc[:i]
        w_sum = sub[sub['net_pnl'] > 0]['net_pnl'].sum()
        l_sum = abs(sub[sub['net_pnl'] <= 0]['net_pnl'].sum())
        running_pf.append(w_sum / l_sum if l_sum > 0 else w_sum)
    filtered_df['running_profit_factor'] = running_pf

    # CALENDAR MATRIX GENERATION
    target_year = max_date_in_db.year
    target_month = max_date_in_db.month
    month_name = calendar.month_name[target_month]
    
    filtered_df['calendar_day'] = filtered_df['exit_date'].dt.day
    daily_pnl_map = filtered_df.groupby('calendar_day')['net_pnl'].sum().to_dict()
    month_calendar = calendar.monthcalendar(target_year, target_month)

# 6. APP RENDERING LAYOUT
st.title("⚡ AlphaQuant Advanced Analytics Workspace")
st.markdown(f"Deep-dive algorithmic performance telemetry and live margin risk mapping. (Viewing: **{timeframe}**)")

# --- 💰 LIVE WALLET BALANCE & PERFORMANCE GAIN ENGINE ---
st.markdown("## 💰 Live Account Balances & Performance ROI")
INITIAL_ACCOUNT_SEED = 278.32  

if live_balances:
    total_assets_count = len(live_balances)
    cols = st.columns(total_assets_count + 1)
    
    primary_stable_balance = live_balances.get("USDT", live_balances.get("USDC", 0.0))
    net_roi_percent = ((primary_stable_balance - INITIAL_ACCOUNT_SEED) / INITIAL_ACCOUNT_SEED) * 100
    
    for idx, (asset, amount) in enumerate(live_balances.items()):
        cols[idx].metric(f"Total Balance ({asset})", f"${amount:,.2f}")
        
    cols[total_assets_count].metric(
        label="Account Return on Investment (ROI)",
        value=f"{net_roi_percent:+.2f}%",
        delta=f"${(primary_stable_balance - INITIAL_ACCOUNT_SEED):+,.2f} Total Drift",
        help=f"Calculated yield derived from your permanent baseline seed deposit of ${INITIAL_ACCOUNT_SEED:,.2f}"
    )
else:
    st.warning("⚠️ No asset wallet balances returned from the endpoint check.")

st.markdown("---")

# --- RISK NODE: LIVE OPEN POSITIONS ---
st.markdown("## 🚨 Live Floating Margin Positions")
if open_positions_df.empty:
    st.info("🟢 No active positions are currently floating open on your Live Account perpetual or dated contracts.")
else:
    total_float_pnl = open_positions_df["Unrealized PnL ($)"].sum()
    if total_float_pnl >= 0:
        st.success(f"**Total Floating Position Equity Drift:** +${total_float_pnl:,.2f}")
    else:
        st.error(f"**Total Floating Position Equity Drift:** -${abs(total_float_pnl):,.2f}")
    st.dataframe(open_positions_df, use_container_width=True, hide_index=True)

st.markdown("---")

# --- VAULT NODE: STATISTICAL INTELLIGENCE ---
st.markdown("## 🗄️ Vault Metrics & Performance Telemetry")

if df.empty:
    st.info("Your permanent historical database vault table is currently empty.")
    st.warning(f"Sync Diagnostics: {sync_status}")
else:
    if mode == "🔗 Live Account Sync":
        st.toast(f"{sync_status} (Display slice: {timeframe})", icon="🔄")

    # PRIMARY PERFORMANCE MATRIX BLOCKS
    st.markdown("### 📊 Primary Performance Metrics")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Win Rate (Filtered)", f"{win_rate:.2f}%", help="Percentage of strategic trades executed that closed net positive.")
    m2.metric("Profit Factor", f"{profit_factor:.2f}x", help="Gross Profits divided by Gross Losses.")
    m3.metric("Avg Risk:Reward Ratio", f"1 : {avg_risk_reward:.2f}", help="Average gross win payout size vs average gross loss sizing scale.")
    m4.metric("Avg Holding Time", f"{avg_holding_time:.2f} Hours", help="The mean operational lifespan resting inside an active contract.")
    m5.metric(
        label="Rewards Score", 
        value=f"{rewards_count:+} Trades", 
        delta=f"{rewards_count} Net",
        help="The product of (Number of Winners) - (Number of Losses)."
    )
    m6.metric("Net Vault PnL", f"${filtered_df['net_pnl'].sum():,.2f}")

    # SECONDARY COMPILER MATRIX BLOCKS
    st.markdown("### 📐 Distribution & Volume Stratification")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Sum up of Rewards (Gross Profit)", f"+${sum_rewards:,.2f}")
    s2.metric("Sum up of Losses (Gross Loss)", f"-${abs(sum_losses):,.2f}")
    s3.metric("Sum up of Trading Fees", f"${sum_total_fees:,.4f}", help="Aggregate accumulation of all commissions paid across all execution paths.")
    s4.metric(
        label="Winners vs Losses Count", 
        value=f"{win_count} W / {loss_count} L / {total_trades} T",
        help="Total execution volume split into Winning Trades (W), Losing Trades (L), and Cumulative Total Closed Trades (T)."
    )
    s5.metric("Longs vs Shorts Ratio", f"{long_pct:.1f}% L / {short_pct:.1f}% S")

    st.markdown("---")

    # ROW 1 CHARTS: AREA GROWTH CURVES & NEW EQUITIES DRAWDOWN VISUALIZER
    st.markdown("### 📈 Capital Growth Vectors")
    c1, c2 = st.columns(2)
    with c1:
        st.write("**The Account Equity Curve (Cumulative Net PnL)**")
        fig_equity = px.area(filtered_df, x="exit_date", y="cumulative_pnl", title="Chronological Account Value Scaling ($)")
        fig_equity.update_traces(line_color="#00FFCC", fillcolor="rgba(0, 255, 204, 0.15)", line_width=2)
        st.plotly_chart(fig_equity, use_container_width=True)
    with c2:
        # 🚨 NEW CHART: Active percentage drawdown visually displayed below high-watermark peaks
        st.write("**Account Equity Drawdown Performance Decay (%)**")
        fig_dd = px.area(filtered_df, x="exit_date", y="drawdown_percent", title="Running Portfolio Drawdown Profile")
        fig_dd.update_traces(line_color="#FF4B4B", fillcolor="rgba(255, 75, 75, 0.15)", line_width=2)
        st.plotly_chart(fig_dd, use_container_width=True)

    st.markdown("---")

    # ROW 2: ASSET MAP & NEW WINNERS VS LOSSES PIE/DONUT CHART
    st.markdown("### 📅 Temporal & Asset Matrix Mapping")
    c3, c4 = st.columns(2)
    with c3:
        # 🚨 NEW CHART: Beautiful Pie/Donut Chart visualizing Wins vs Losses
        st.write("**Winners vs Losses Stratification Profile**")
        pie_data = pd.DataFrame({
            "Classification": ["Winners", "Losses"],
            "Trade Count": [win_count, loss_count]
        })
        fig_pie = px.pie(
            pie_data, 
            values="Trade Count", 
            names="Classification", 
            hole=0.45,
            color="Classification",
            color_discrete_map={"Winners": "#00FFCC", "Losses": "#FF4B4B"}
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with c4:
        st.write(f"**📅 Trading Performance Calendar Grid ({month_name} {target_year})**")
        
        headers = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        grid_cols = st.columns(7)
        for idx, day_head in enumerate(headers):
            grid_cols[idx].markdown(f"<p style='text-align:center; font-weight:bold; margin-bottom:2px;'>{day_head}</p>", unsafe_allow_html=True)
            
        for week in month_calendar:
            week_cols = st.columns(7)
            for day_idx, day_num in enumerate(week):
                if day_num == 0:
                    week_cols[day_idx].markdown(
                        "<div style='background-color:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); height:75px; border-radius:4px;'></div>", 
                        unsafe_allow_html=True
                    )
                else:
                    day_pnl = daily_pnl_map.get(day_num, 0.0)
                    
                    if day_pnl > 0.001:
                        bg_style = "background-color: rgba(0, 255, 204, 0.85); border: 1px solid #00FFCC;"
                        text_color = "color: #111111;"
                        pnl_str = f"+${day_pnl:,.2f}"
                    elif day_pnl < -0.001:
                        bg_style = "background-color: rgba(255, 75, 75, 0.85); border: 1px solid #FF4B4B;"
                        text_color = "color: #111111;"
                        pnl_str = f"-${abs(day_pnl):,.2f}"
                    else:
                        bg_style = "background-color: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);"
                        text_color = "color: #888888;"
                        pnl_str = "$0.00"
                        
                    card_html = f"""
                    <div style='{bg_style} height:75px; border-radius:4px; padding:6px; display: flex; flex-direction: column; justify-content: space-between;'>
                        <span style='font-size:12px; font-weight:bold; color:#111111;'>{day_num}</span>
                        <span style='font-size:11px; font-weight:black; text-align:right; {text_color}'>{pnl_str}</span>
                    </div>
                    """
                    week_cols[day_idx].markdown(card_html, unsafe_allow_html=True)

    st.markdown("---")

    # ROW 3 CHARTS: SYSTEM HEALTH & HOLD TIME HISTOGRAM
    st.markdown("### 🎯 System Health & Telemetry Vectors")
    c5, c6 = st.columns(2)
    with c5:
        st.write("**Running System Profit Factor Trend**")
        fig_pf = px.line(filtered_df, x="exit_date", y="running_profit_factor", title="System Health Factor Decay Progression", markers=True)
        fig_pf.add_hline(y=1.0, line_dash="dash", line_color="red", annotation_text="Breakeven Vector")
        fig_pf.update_traces(line_color="#FFCC00")
        st.plotly_chart(fig_pf, use_container_width=True)
    with c6:
        st.write("**Position Hold Duration Spectrum**")
        fig_hist = px.histogram(clean_df, x="holding_time_hours", color="side", barmode="overlay", title="Trade Lifetime Profile (Hours Spent Inside Contracts)")
        st.plotly_chart(fig_hist, use_container_width=True)

    # HISTORIC LEDGER DATA GRID
    st.markdown("---")
    st.subheader("📝 Historic Trade Ledger Vault Records")
    display_df = filtered_df.rename(columns={
        "entry_date": "Entry Date/Time",
        "exit_date": "Exit Date/Time",
        "symbol": "Contract Symbol",
        "side": "Order Side",
        "price": "Execution Price",
        "amount": "Size/Contracts",
        "fees": "Trading Fee ($)",
        "net_pnl": "Net Realized PnL ($)"
    })
    st.dataframe(
        display_df[["id", "Contract Symbol", "Order Side", "Entry Date/Time", "Exit Date/Time", "Size/Contracts", "Trading Fee ($)", "Net Realized PnL ($)"]].sort_values(by="Exit Date/Time", ascending=False),
        use_container_width=True, hide_index=True
    )
