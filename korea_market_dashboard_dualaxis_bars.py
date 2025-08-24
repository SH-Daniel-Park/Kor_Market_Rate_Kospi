
# korea_market_dashboard_dualaxis_bars_custom.py
# Streamlit app: Dual-axis — Left lines (KOSPI, USD/KRW), Right BARS (US Fed Funds, BOK Base Rate)
# Customizable bar thickness/spacing, value labels, and fixed right-axis range.
# Distutils-free (no pandas_datareader). Robust FRED loader with API/CSV fallback.
# Run: streamlit run korea_market_dashboard_dualaxis_bars_custom.py

import io
import math
import datetime as dt
from dateutil.relativedelta import relativedelta
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FuncFormatter
from matplotlib.dates import date2num
import streamlit as st
import requests

st.set_page_config(page_title="Korea Market Dashboard (Bars w/ Controls)", layout="wide")

st.title("📊 Korea Market Dashboard — Bars for U.S. & Korea Rates (Customizable)")
st.caption("Left axis: KOSPI & USD/KRW (lines). Right axis: U.S. Fed Funds & BOK Base Rate (BARS, percent with 1% ticks).")

# ----------------------
# Sidebar
# ----------------------
with st.sidebar:
    st.header("⚙️ Settings")
    start_date = st.date_input("Start date (YYYY-MM-DD)", value=dt.date(2020, 1, 1),
                               min_value=dt.date(1990,1,1), max_value=dt.date.today())
    normalize_left = st.checkbox("Normalize KOSPI / USDKRW to 100 at start", value=True)
    bar_freq = st.selectbox("Bar frequency for rates", ["Monthly (recommended)", "Daily"])
    st.subheader("Bar appearance")
    monthly_bar_days = st.slider("Monthly bar width (days)", 5, 28, 18)
    daily_bar_days = st.slider("Daily bar width (days)", 1, 5, 1)
    group_gap = st.slider("Gap between rate bars (0.00–0.60)", 0.00, 0.60, 0.20, step=0.05)
    show_labels = st.checkbox("Show value labels on bars", value=True)
    label_decimals = st.selectbox("Label decimals", [0,1,2], index=1)
    st.subheader("Right axis range")
    fix_range = st.checkbox("Fix right y-axis range", value=False)
    min_pct = st.number_input("Right y min (%)", value=0.0, step=0.5, disabled=not fix_range)
    max_pct = st.number_input("Right y max (%)", value=10.0, step=0.5, disabled=not fix_range)
    show_table = st.checkbox("Show data table (last 30 days)", value=False)
    st.divider()
    st.subheader("🔑 ECOS (BOK) API")
    st.markdown("한국은행 **ECOS Open API 인증키**를 입력하세요. (https://ecos.bok.or.kr/api/)")
    ecos_api_key = st.text_input("ECOS API Key", value="", type="password", help="개인 API Key를 입력하세요.")
    st.caption("통계표 722Y001 • 항목 0101000 • 주기 M (한국은행 기준금리)")
    st.divider()
    st.subheader("🔑 FRED (optional)")
    st.markdown("EFFR/FEDFUNDS가 보이지 않으면 FRED **API Key**를 입력하세요. (https://fred.stlouisfed.org/docs/api/api_key.html)")
    fred_api_key = st.text_input("FRED API Key (optional)", value="", type="password")

# ----------------------
# Data fetchers
# ----------------------
@st.cache_data(show_spinner=True)
def fetch_yf(symbol: str, start: dt.date) -> pd.Series:
    """Download from Yahoo Finance and return a named Series."""
    df = yf.download(symbol, start=start, progress=False, auto_adjust=True)
    if df.empty:
        return pd.Series(dtype=float, name=symbol)
    col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    s = df[col].copy()
    s.name = symbol
    return s

@st.cache_data(show_spinner=True)
def fetch_fred_csv(series_id: str) -> pd.Series:
    """
    Fetch a FRED series via fredgraph CSV export (no API key).
    Returns a Series named `series_id` indexed by datetime.
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        df_csv = pd.read_csv(io.StringIO(r.text))
        if 'DATE' not in df_csv.columns or series_id not in df_csv.columns:
            return pd.Series(dtype=float, name=series_id)
        df_csv['DATE'] = pd.to_datetime(df_csv['DATE'])
        s = pd.Series(pd.to_numeric(df_csv[series_id], errors='coerce').values, index=df_csv['DATE'], name=series_id)
        return s
    except Exception:
        return pd.Series(dtype=float, name=series_id)

@st.cache_data(show_spinner=True)
def fetch_fred_api_json(series_id: str, api_key: str, start: dt.date) -> pd.Series:
    """
    Fetch FRED observations via official API (requires API key).
    Returns a Series named series_id indexed by datetime.
    """
    if not api_key:
        return pd.Series(dtype=float, name=series_id)
    start_s = f"{start:%Y-%m-%d}"
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={api_key}&file_type=json&observation_start={start_s}"
    )
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        js = r.json()
        obs = js.get("observations", [])
        if not obs:
            return pd.Series(dtype=float, name=series_id)
        dates = pd.to_datetime([o.get("date") for o in obs])
        vals = pd.to_numeric([o.get("value", ".") for o in obs], errors="coerce")
        s = pd.Series(vals, index=dates, name=series_id).dropna()
        return s
    except Exception:
        return pd.Series(dtype=float, name=series_id)

def yyyymm(d: dt.date) -> str:
    return f"{d.year}{d.month:02d}"

@st.cache_data(show_spinner=True)
def fetch_bok_base_rate(api_key: str, start: dt.date) -> pd.Series:
    """
    ECOS StatisticSearch:
      https://ecos.bok.or.kr/api/StatisticSearch/{API_KEY}/json/kr/1/100000/722Y001/M/{YYYYMM}/{YYYYMM}/0101000
    722Y001: 기준금리 및 여수신금리, 0101000: 한국은행 기준금리, 주기: M(월)
    Returns monthly series.
    """
    name = "BOK Base Rate (%)"
    if not api_key:
        return pd.Series(dtype=float, name=name)

    start_m = yyyymm(start)
    end_m = yyyymm(dt.date.today())
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/100000/"
        f"722Y001/M/{start_m}/{end_m}/0101000"
    )
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        container = data.get("StatisticSearch") or data.get("statisticSearch") or data.get("Statisticsearch")
        rows = (container or {}).get("row", [])
        times, vals = [], []
        for item in rows:
            t = item.get("TIME") or item.get("time") or item.get("TIME_PERIOD")
            v = item.get("DATA_VALUE") or item.get("data_value") or item.get("OBS_VALUE")
            if not t or v in (None, "", "."):
                continue
            try:
                y = int(str(t)[:4]); m = int(str(t)[4:6])
                # Use month end date
                dt_idx = dt.date(y, m, 1) + relativedelta(months=1) - relativedelta(days=1)
                times.append(dt_idx)
                vals.append(float(v))
            except Exception:
                continue
        if not times:
            return pd.Series(dtype=float, name=name)
        s = pd.Series(vals, index=pd.to_datetime(times), name=name).sort_index()
        return s
    except Exception:
        return pd.Series(dtype=float, name=name)

@st.cache_data(show_spinner=True)
def load_us_fed_rate(fred_api_key: str, start_date: dt.date):
    """
    Load Fed Funds with robust fallbacks:
    1) FRED API EFFR (daily) if key provided
    2) FRED CSV EFFR (daily)
    3) FRED API FEDFUNDS (monthly) if key provided
    4) FRED CSV FEDFUNDS (monthly)
    """
    # 1) API EFFR
    if fred_api_key:
        s = fetch_fred_api_json("EFFR", fred_api_key, start_date)
        if not s.empty and s.dropna().size > 0:
            s.name = "US Fed Funds (%)"
            return s, "EFFR via FRED API (daily)"
    # 2) CSV EFFR
    s = fetch_fred_csv("EFFR")
    if not s.empty and s.dropna().size > 0:
        s.name = "US Fed Funds (%)"
        return s, "EFFR via CSV (daily)"
    # 3) API FEDFUNDS
    if fred_api_key:
        s = fetch_fred_api_json("FEDFUNDS", fred_api_key, start_date)
        if not s.empty and s.dropna().size > 0:
            s.name = "US Fed Funds (%)"
            return s, "FEDFUNDS via FRED API (monthly avg)"
    # 4) CSV FEDFUNDS
    s = fetch_fred_csv("FEDFUNDS")
    if not s.empty and s.dropna().size > 0:
        s.name = "US Fed Funds (%)"
        return s, "FEDFUNDS via CSV (monthly avg)"
    return pd.Series(dtype=float, name="US Fed Funds (%)"), "unavailable"

# ----------------------
# Fetch data
# ----------------------
st.write("Fetching data...")
KOSPI = "^KS11"
USDKRW = "KRW=X"

kospi = fetch_yf(KOSPI, start_date)
usdk_rw = fetch_yf(USDKRW, start_date)
effr_raw, fed_src = load_us_fed_rate(fred_api_key, start_date)
bok_base = fetch_bok_base_rate(ecos_api_key, start_date)

# Build daily frame
idx = pd.date_range(start=start_date, end=dt.date.today(), freq='D')
df = pd.DataFrame(index=idx)

if not kospi.empty:
    df['KOSPI'] = kospi.reindex(idx).ffill()
if not usdk_rw.empty:
    df['USD/KRW'] = usdk_rw.reindex(idx).ffill()

# Rates daily series (for table and for daily bars option)
rates_cols = []
if not effr_raw.empty:
    effr = effr_raw.reindex(idx).ffill().bfill()
    if not effr.dropna().empty:
        df['US Fed Funds (%)'] = effr
        rates_cols.append('US Fed Funds (%)')
if not bok_base.empty:
    df['BOK Base Rate (%)'] = bok_base.reindex(idx).ffill()
    rates_cols.append('BOK Base Rate (%)')

# Normalize left-axis series if selected
left_cols = [c for c in ['KOSPI', 'USD/KRW'] if c in df.columns]
left_df = df[left_cols].copy()
if normalize_left and not left_df.empty:
    for c in left_df.columns:
        fv = left_df[c].dropna().iloc[0]
        if fv != 0:
            left_df[c] = (left_df[c] / fv) * 100.0
    left_ylabel = "Index (Start = 100)"
else:
    left_ylabel = "Level"

# ----------------------
# Plot
# ----------------------
fig, ax_left = plt.subplots(figsize=(12, 6), dpi=150)

# Left axis lines
if not left_df.empty:
    left_df.plot(ax=ax_left)

ax_left.set_xlabel("Date")
ax_left.set_ylabel(left_ylabel)
ax_left.grid(True, alpha=0.3)
ax_left.set_title(f"From {start_date} to {dt.date.today()}")

# Right axis bars for rates
ax_right = ax_left.twinx()

def draw_grouped_bars(ax, bar_df, width_days, gap_fraction, show_value_labels, decimals):
    """
    Draw grouped bars centered at each date with specified width and gap.
    gap_fraction: fraction (0~0.6) of width reserved as empty space between groups.
    """
    if bar_df.empty:
        return []
    x = date2num(bar_df.index.to_pydatetime())
    n = len(bar_df.columns)
    total_span = width_days * (1.0 - gap_fraction)  # width used by bars
    bar_w = total_span / max(n,1)
    containers = []
    for i in range(n):
        offset = (-total_span/2.0) + (i + 0.5) * bar_w
        cont = ax.bar(x + offset, bar_df.iloc[:, i].values, width=bar_w, align='center', alpha=0.85, label=bar_df.columns[i])
        containers.append(cont)
        if show_value_labels:
            for rect, val in zip(cont.patches, bar_df.iloc[:, i].values):
                if pd.isna(val):
                    continue
                height = rect.get_height()
                ax.annotate(f"{val:.{decimals}f}%",
                            xy=(rect.get_x() + rect.get_width()/2, rect.get_y() + height),
                            xytext=(0, 3),
                            textcoords="offset points",
                            ha='center', va='bottom', fontsize=8, rotation=0)
    return containers

if rates_cols:
    right_df = df[rates_cols].copy()
    if bar_freq.startswith("Monthly"):
        bar_df = right_df.resample('M').last()
        width = float(monthly_bar_days)
    else:
        bar_df = right_df
        width = float(daily_bar_days)
    containers = draw_grouped_bars(ax_right, bar_df, width_days=width, gap_fraction=group_gap,
                                   show_value_labels=show_labels, decimals=label_decimals)

    # Right axis ticks and range
    if fix_range:
        ax_right.set_ylim(min_pct, max_pct)
    else:
        try:
            rmin = math.floor(float(bar_df.min().min()))
            rmax = math.ceil(float(bar_df.max().max()))
            if rmin == rmax:
                rmax = rmin + 1
            ax_right.set_ylim(rmin-0.1, rmax+0.1)
        except Exception:
            pass
    ax_right.yaxis.set_major_locator(MultipleLocator(1.0))
    ax_right.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{int(y)}%"))
    ax_right.set_ylabel("Rate (%) — 1% steps (bars)")
    # Merge legends
    h1, l1 = ax_left.get_legend_handles_labels()
    h2, l2 = ax_right.get_legend_handles_labels()
    ax_left.legend(h1 + h2, l1 + l2, loc='best')
else:
    ax_right.set_ylabel("Rate (%) — 1% steps (no rate series loaded)")

st.pyplot(fig, clear_figure=True)

# Status captions
try:
    if 'US Fed Funds (%)' in df.columns:
        last_obs = effr_raw.dropna().index.max()
        last_obs_str = last_obs.strftime("%Y-%m-%d") if last_obs is not None else "N/A"
        st.caption(f"U.S. Fed Funds source: **{fed_src}**, last observation: **{last_obs_str}**")
    elif fed_src == 'unavailable':
        st.warning('U.S. Fed Funds를 불러오지 못했습니다. 네트워크 또는 FRED 차단 이슈일 수 있습니다. 사이드바에 **FRED API Key**를 넣고 다시 시도하세요.')
except Exception:
    pass

# ----------------------
# Table (last 30 days)
# ----------------------
if show_table:
    st.dataframe(df.tail(30), use_container_width=True)

with st.expander("ℹ️ Notes & Data Sources"):
    st.markdown("""
- **Left axis**: KOSPI (`^KS11`), USD/KRW (`KRW=X`) — lines, optionally normalized to 100 at start.
- **Right axis**: U.S. Fed Funds & **BOK Base Rate** — **BARS** in percent with **1% tick steps**.
- **Bar controls**: width (days), gap between bars, value labels (w/ decimals), and fixed right-y range.
- FRED: EFFR daily (fallback to FEDFUNDS monthly). ECOS: 722Y001 · 0101000 (monthly).
""")

st.success("Custom bar chart ready. Adjust width/gap/labels and right-axis range from the sidebar.")
