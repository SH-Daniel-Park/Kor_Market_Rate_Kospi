
# korea_market_dashboard_dashed_rates_labels_excel.py
# Streamlit app: Left lines (KOSPI black, USD/KRW yellow), Right dashed lines (US Fed Funds red, BOK Base Rate blue)
# Adds: top-left single-line data labels on the chart, Excel download (yyyy-mm-dd), PNG download.
# Robust FRED loader (API/CSV fallback) + ECOS API. Distutils-free.
# Run: streamlit run korea_market_dashboard_dashed_rates_labels_excel.py

import io
import math
import datetime as dt
from dateutil.relativedelta import relativedelta
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FuncFormatter
from matplotlib.dates import DateFormatter
import streamlit as st
import requests

st.set_page_config(page_title="Korea Market Dashboard (Dashed + Labels + Excel)", layout="wide")

st.title("📊 Korea Market Dashboard — Dashed Rates + Labels + Excel")
st.caption("Left: KOSPI **black**, USD/KRW **yellow**. Right: U.S. Fed Funds **red dashed**, BOK Base Rate **blue dashed**. Right axis uses 1% ticks.")

# ----------------------
# Sidebar
# ----------------------
with st.sidebar:
    st.header("⚙️ Settings")
    start_date = st.date_input("Start date (YYYY-MM-DD)", value=dt.date(2020, 1, 1),
                               min_value=dt.date(1990,1,1), max_value=dt.date.today())
    normalize_left = st.checkbox("Normalize KOSPI / USDKRW to 100 at start", value=True)
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
    import io
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

# Rates daily series (for right dashed lines)
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
# Plot (fixed colors + dashed rates + top-left labels)
# ----------------------
fig, ax_left = plt.subplots(figsize=(12, 6), dpi=150)
fig.subplots_adjust(top=0.85)  # room for top labels

# Left: specified colors
line_colors = {'KOSPI': 'black', 'USD/KRW': 'yellow'}
if not left_df.empty:
    cols = list(left_df.columns)
    colors = [line_colors.get(c, None) for c in cols]
    left_df.plot(ax=ax_left, color=colors, linewidth=1.8)

# Right: dashed rate lines
ax_right = ax_left.twinx()
if rates_cols:
    if 'US Fed Funds (%)' in df.columns:
        ax_right.plot(df.index, df['US Fed Funds (%)'], linestyle='--', color='red', linewidth=2.0, label='US Fed Funds (%)')
    if 'BOK Base Rate (%)' in df.columns:
        ax_right.plot(df.index, df['BOK Base Rate (%)'], linestyle='--', color='blue', linewidth=2.0, label='BOK Base Rate (%)')
    try:
        rmin = math.floor(float(df[rates_cols].min().min()))
        rmax = math.ceil(float(df[rates_cols].max().max()))
        if rmin == rmax:
            rmax = rmin + 1
        ax_right.set_ylim(rmin-0.1, rmax+0.1)
    except Exception:
        pass
    ax_right.yaxis.set_major_locator(MultipleLocator(1.0))
    ax_right.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{int(y)}%"))
    ax_right.set_ylabel("Rate (%) — 1% steps (dashed)")

# Axis labels, grid, and date format
ax_left.set_xlabel("Date")
ax_left.set_ylabel(left_ylabel)
ax_left.grid(True, alpha=0.3)
ax_left.set_title(f"From {start_date} to {dt.date.today()}")
ax_left.xaxis.set_major_formatter(DateFormatter('%Y-%m-%d'))
for label in ax_left.get_xticklabels():
    label.set_rotation(0)
    label.set_ha('center')

# ----------------------
# Top-left single-line data labels (yyyy-mm-dd)
# ----------------------
def fmt(v, is_rate=False):
    if pd.isna(v):
        return "NA"
    return f"{v:,.2f}%" if is_rate else f"{v:,.2f}"

last_vals = []
if 'KOSPI' in df.columns:
    last_vals.append(f"KOSPI: {fmt(df['KOSPI'].dropna().iloc[-1] if not df['KOSPI'].dropna().empty else float('nan'))}")
if 'USD/KRW' in df.columns:
    last_vals.append(f"USD/KRW: {fmt(df['USD/KRW'].dropna().iloc[-1] if not df['USD/KRW'].dropna().empty else float('nan'))}")
if 'US Fed Funds (%)' in df.columns:
    last_vals.append(f"US Fed Funds: {fmt(df['US Fed Funds (%)'].dropna().iloc[-1] if not df['US Fed Funds (%)'].dropna().empty else float('nan'), True)}")
if 'BOK Base Rate (%)' in df.columns:
    last_vals.append(f"BOK Base Rate: {fmt(df['BOK Base Rate (%)'].dropna().iloc[-1] if not df['BOK Base Rate (%)'].dropna().empty else float('nan'), True)}")

label_line = " | ".join(last_vals)
# Put a white-rounded box at top-left, left-aligned on a single line
ax_left.text(0.01, 1.05, label_line, transform=ax_left.transAxes, ha='left', va='bottom',
             fontsize=10, bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))

# Legend
h1, l1 = ax_left.get_legend_handles_labels()
h2, l2 = ax_right.get_legend_handles_labels()
if h1 or h2:
    ax_left.legend(h1 + h2, l1 + l2, loc='best')

# Render plot
st.pyplot(fig, clear_figure=True)

# ----------------------
# Downloads (PNG + Excel with yyyy-mm-dd dates)
# ----------------------
# PNG
buf_png = io.BytesIO()
fig.savefig(buf_png, format="png", dpi=150, bbox_inches="tight")
buf_png.seek(0)
today_str = dt.date.today().strftime("%Y-%m-%d")

st.download_button(
    label="📥 Download chart as PNG",
    data=buf_png.getvalue(),
    file_name=f"market_dashboard_{today_str}.png",
    mime="image/png"
)

# Excel (dates as yyyy-mm-dd)
df_out = df.copy()
df_out.index.name = "Date"
df_xlsx = df_out.reset_index()
df_xlsx["Date"] = df_xlsx["Date"].dt.strftime("%Y-%m-%d")

buf_xlsx = io.BytesIO()
with pd.ExcelWriter(buf_xlsx, engine="openpyxl") as writer:
    df_xlsx.to_excel(writer, index=False, sheet_name="Data")
buf_xlsx.seek(0)

st.download_button(
    label="📒 Download data as Excel (yyyy-mm-dd)",
    data=buf_xlsx.getvalue(),
    file_name=f"market_dashboard_{today_str}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# ----------------------
# Table (last 30 days, yyyy-mm-dd index)
# ----------------------
if show_table:
    df_show = df.tail(30).copy()
    df_show.index = df_show.index.strftime("%Y-%m-%d")
    st.dataframe(df_show, use_container_width=True)

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
