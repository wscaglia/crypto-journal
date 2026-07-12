import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import ccxt
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
    df = pd.DataFrame(mock_list)
    df['entry_date'] = pd.to_datetime(df['entry_date'])
    df['exit_date'] = pd.to_datetime(df['exit_date'])
    return df

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

        # --- C. DEEP-SWEEP COMPLETED ORDERS (WEBHOOK ORDER ROUTER EXTRACTION) ---
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
    live_balances = {"USDT": 10500.0, "USDC": 1250.0}
    sync_status = "Simulation Cache Verified"
    st.sidebar.success("Displaying analytical performance models!")
else:
    sync_status, open_positions_df, live_balances = fetch_live_account_and_sync()
    df = load_history_from_db()

# 5. MATHEMATICS & METRICS COMPILER
if not df.empty:
    df = df.sort_values(by="exit_date").reset_index(drop=True)
    
    # Stratified Performance Segments
    wins = df[df['net_pnl'] > 0]
    losses = df[df['net_pnl'] <= 0]
    
    total_trades = len(df)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
    
    # Financial Sums
    sum_rewards = wins['net_pnl'].sum()
    sum_losses = losses['net_pnl'].sum() # Negative value representing absolute loss scale
    
    total_gross_profits = sum_rewards
    total_gross_losses = abs(sum_losses)
    profit_factor = total_gross_profits / total_gross_losses if total_gross_losses > 0 else total_gross_profits
    
    avg_win = wins['net_pnl'].mean() if not wins.empty else 0
    avg_loss = abs(losses['net_pnl'].mean()) if not losses.empty else 1
    
    # Average Risk:Reward Ratio (Calculated based on Average Reward Size vs Average Risk Size)
    avg_risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
    
    expected_value = ((win_rate / 100) * avg_win) + ((1 - (win_rate / 100)) * (avg_loss * -1))
    
    # Compute Durations
    df['holding_time_hours'] = (df['exit_date'] - df['entry_date']).dt.total_seconds() / 3600
    avg_holding_time = df['holding_time_hours'].mean()
    
    # Long vs Short Directional Ratio Compilation
    longs_count = len(df[df['side'] == 'LONG'])
    shorts_count = len(df[df['side'] == 'SHORT'])
    long_pct = (longs_count / total_trades) * 100 if total_trades > 0 else 0
    short_pct = (shorts_count / total_trades) * 100 if total_trades > 0 else 0
    
    # Cumulative Curves
    df['cumulative_pnl'] = df['net_pnl'].cumsum()
    
    running_pf = []
    for i in range(1, len(df) + 1):
        sub = df.iloc[:i]
        w_sum = sub[sub['net_pnl'] > 0]['net_pnl'].sum()
        l_sum = abs(sub[sub['net_pnl'] <= 0]['net_pnl'].sum())
        running_pf.append(w_sum / l_sum if l_sum > 0 else w_sum)
    df['running_profit_factor'] = running_pf

    # Day-of-Week Distribution Layout Matrix
    df['day_of_week'] = df['exit_date'].dt.day_name()
    day_order = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    
    # Compile metrics per day for the Trading Calendar table
    calendar_metrics = []
    for day in day_order:
        day_df = df[df['day_of_week'] == day]
        if not day_df.empty:
            day_pnl = day_df['net_pnl'].sum()
            day_volume = len(day_df)
            day_wins = len(day_df[day_df['net_pnl'] > 0])
            day_wr = (day_wins / day_volume) * 100
        else:
            day_pnl, day_volume, day_wr = 0.0, 0, 0.0
            
        calendar_metrics.append({
            "Calendar Day": day,
            "Total Closed Trades": day_volume,
            "Win Rate (%)": f"{day_wr:.1f}%",
            "Net Session Performance ($)": day_pnl
        })
    calendar_table_df = pd.DataFrame(calendar_metrics)

# 6. APP RENDERING LAYOUT
st.title("⚡ AlphaQuant Advanced Analytics Workspace")
st.markdown("Deep-dive algorithmic performance telemetry and live margin risk mapping.")

# --- LIVE WALLET BALANCE DIAGNOSTIC CARD ---
st.markdown("## 💰 Live Account Balances")
if live_balances:
    cols = st.columns(len(live_balances))
    for idx, (asset, amount) in enumerate(live_balances.items()):
        cols[idx].metric(f"Total Asset Balance ({asset})", f"{amount:,.4f}")
else:
    st.warning("⚠️ No asset wallet balances returned from the endpoint check. Verify account margin distribution layers.")

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
        st.toast(sync_status, icon="🔄")

    # PRIMARY PERFORMANCE MATRIX BLOCKS
    st.markdown("### 📊 Primary Metric Matrix Blocks")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Win Rate", f"{win_rate:.2f}%", help="Percentage of trades executed that closed net positive.")
    m2.metric("Profit Factor", f"{profit_factor:.2f}x", help="Gross Profits divided by Gross Losses.")
    m3.metric("Avg Risk:Reward Ratio", f"1 : {avg_risk_reward:.2f}", help="Average gross win payout size vs average gross loss sizing scale.")
    m4.metric("Avg Holding Time", f"{avg_holding_time:.2f} Hours", help="The mean operational lifespan resting inside an active contract.")
    m5.metric("Net Vault PnL", f"${df['net_pnl'].sum():,.2f}")

    # SECONDARY COMPILER MATRIX BLOCKS
    st.markdown("### 📐 Distribution & Volume Stratification")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Sum up of Rewards (Gross Profit)", f"+${sum_rewards:,.2f}")
    s2.metric("Sum up of Losses (Gross Loss)", f"-${abs(sum_losses):,.2f}")
    s3.metric("Winners vs Losses Count", f"{win_count} Wins / {loss_count} Losses", help="Total raw trade count broken into winners vs negative closures.")
    s4.metric("Longs vs Shorts Ratio", f"{long_pct:.1f}% L / {short_pct:.1f}% S", help="Percentage balance layout between buy orders and short entries.")

    st.markdown("---")

    # ROW 1 CHARTS: UPGRADED AREA GROWTH CURVES & STABILITY DECAY
    st.markdown("### 📈 Capital Growth Vectors")
    c1, c2 = st.columns(2)
    with c1:
        st.write("**The Account Equity Curve (Cumulative Net PnL)**")
        # 🚨 UPGRADED: Line chart replaced with a visual Area Chart filling the equity progression
        fig_equity = px.area(df, x="exit_date", y="cumulative_pnl", title="Chronological Account Value Scaling ($)")
        fig_equity.update_traces(line_color="#00FFCC", fillcolor="rgba(0, 255, 204, 0.15)", line_width=2)
        st.plotly_chart(fig_equity, use_container_width=True)
    with c2:
        st.write("**Running Profit Factor Trend**")
        fig_pf = px.line(df, x="exit_date", y="running_profit_factor", title="System Health Factor Decay Progression", markers=True)
        fig_pf.add_hline(y=1.0, line_dash="dash", line_color="red", annotation_text="Breakeven Vector")
        fig_pf.update_traces(line_color="#FFCC00")
        st.plotly_chart(fig_pf, use_container_width=True)

    st.markdown("---")

    # ROW 2: ASSET MAP & TRADING CALENDAR LAYOUT MATRIX
    st.markdown("### 📅 Temporal & Asset Matrix Mapping")
    c3, c4 = st.columns(2)
    with c3:
        st.write("**Win Rate Stratification by Contract Token**")
        symbol_stats = df.groupby('symbol').apply(
            lambda x: (len(x[x['net_pnl'] > 0]) / len(x)) * 100 if len(x) > 0 else 0
        ).reset_index(name='Win Rate (%)')
        fig_sym_win = px.bar(symbol_stats, x='symbol', y='Win Rate (%)', text_auto='.1f', title="Win Rate % per Asset Matrix", color='Win Rate (%)', color_continuous_scale='Bluered')
        fig_sym_win.add_hline(y=50.0, line_dash="dot", line_color="white")
        st.plotly_chart(fig_sym_win, use_container_width=True)
    with c4:
        st.write("**📅 Weekly Trading Calendar Performance Grid**")
        # 🚨 INSTALLED: Real grid matrix table mapping session metrics out from Sunday through Saturday
        st.dataframe(
            calendar_table_df,
            use_container_width=True,
            hide_index=True
        )

    st.markdown("---")

    # ROW 3 CHARTS: MATHEMATICAL EXPECTANCY & SPECTRUM
    st.markdown("### 🎯 Mathematical Value Mapping")
    c5, c6 = st.columns(2)
    with c5:
        st.write("**Rolling Mathematical Expected Value (EV)**")
        running_ev = []
        for i in range(2, len(df) + 1):
            sub = df.iloc[:i]
            sub_w = sub[sub['net_pnl'] > 0]
            sub_l = sub[sub['net_pnl'] <= 0]
            w_r = len(sub_w) / len(sub)
            a_w = sub_w['net_pnl'].mean() if not sub_w.empty else 0
            a_l = abs(sub_l['net_pnl'].mean()) if not sub_l.empty else 0
            running_ev.append((w_r * a_w) + ((1 - w_r) * (a_l * -1)))
        
        fig_ev = px.area(x=df['exit_date'].iloc[1:], y=running_ev, title="Edge Stability Trend ($ Value Expectancy per Execution)")
        fig_ev.update_traces(line_color="#A100FF", fillcolor="rgba(161, 0, 255, 0.15)")
        st.plotly_chart(fig_ev, use_container_width=True)
    with c6:
        st.write("**Position Hold Duration Spectrum**")
        fig_hist = px.histogram(df, x="holding_time_hours", color="side", barmode="overlay", title="Trade Lifetime Profile (Hours Spent Inside Contracts)")
        st.plotly_chart(fig_hist, use_container_width=True)

    # HISTORIC LEDGER DATA GRID
    st.markdown("---")
    st.subheader("📝 Historic Trade Ledger Vault Records")
    display_df = df.rename(columns={
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
