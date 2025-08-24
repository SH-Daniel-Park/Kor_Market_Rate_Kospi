
# korea_market_dashboard_bokapi.py
# Streamlit app: KOSPI, USD/KRW, US Fed Funds Rate (via FRED CSV), BOK Base Rate (via ECOS API)
# No pandas_datareader or distutils dependency.

import datetime as dt
from dateutil.relativedelta import relativedelta
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import streamlit as st
import requests

st.set_page_config(page_title="Korea Market Dashboard (BOK API)", layout="wide")

st.title("📊 Korea Market Dashboard — BOK Base Rate (ECOS API)")
st.caption("KOSPI, USD/KRW, U.S. Fed Funds Rate (FRED CSV), and the official **Bank of Korea Base Rate** (ECOS API).")

with st.sidebar:
    st.header("⚙️ Settings")
    start_date = st.date_input("Start date (YYYY-MM-DD)", value=dt.date(2020, 1, 1), min_value=dt.date(1990,1,1), max_value=dt.date.today())
    normalize = st.checkbox("Normalize series to 100 at start", value=True)
    show_table = st.checkbox("Show data table", value=False)
    st.divider()
    st.subheader("🔑 ECOS (BOK) API")
    st.markdown("한국은행 **ECOS Open API 인증키**를 입력하세요. (https://ecos.bok.or.kr/api/)")
    ecos_api_key = st.text_input("ECOS API Key", value="", type="password", help="개인 API Key를 입력하세요.")
    st.caption("통계표 722Y001 • 항목 0101000 • 주기 M (한국은행 기준금리)")

@st.cache_data(show_spinner=True)
def fetch_yf(symbol, start):
    df = yf.download(symbol, start=start, progress=False, auto_adjust=True)
    if df.empty:
        return pd.Series(dtype=float, name=symbol)
    col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    s = df[col].copy(); s.name = symbol
    return s


import io
import pandas as pd
import requests
import datetime as dt

def fetch_fred_csv(series_id: str, start: dt.date) -> pd.Series:
    """
    Fetch a FRED series via the public fredgraph CSV export (no API key).
    Example URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=EFFR
    Returns a daily Series indexed by datetime, name = series_id.
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    # Expect columns: DATE, {series_id}
    if 'DATE' not in df.columns or series_id not in df.columns:
        return pd.Series(dtype=float, name=series_id)
    df['DATE'] = pd.to_datetime(df['DATE'])
    s = pd.Series(df[series_id].values, index=df['DATE'], name=series_id)
    # coerce '.' or non-numeric to NaN
    s = pd.to_numeric(s, errors='coerce')
    # filter by start
    s = s[s.index.date >= start]
    return s


def yyyymm(d: dt.date) -> str:
    return f"{d.year}{d.month:02d}"

@st.cache_data(show_spinner=True)
def fetch_bok_base_rate(api_key: str, start: dt.date):
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
        r = requests.get(url, timeout=20)
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
                # month end
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

# Symbols
KOSPI = "^KS11"
USDKRW = "KRW=X"
EFFR_ID = "EFFR"  # Fed Funds

st.write("Fetching data...")
kospi = fetch_yf(KOSPI, start_date)
usdk_rw = fetch_yf(USDKRW, start_date)
effr = fetch_fred_csv(EFFR_ID, start_date)
bok_base = fetch_bok_base_rate(ecos_api_key, start_date)

# Build daily frame
idx = pd.date_range(start=start_date, end=dt.date.today(), freq='D')
df = pd.DataFrame(index=idx)
if not kospi.empty:
    df['KOSPI'] = kospi.reindex(idx).ffill()
if not usdk_rw.empty:
    df['USD/KRW'] = usdk_rw.reindex(idx).ffill()
if not effr.empty:
    df['US Fed Funds (%)'] = effr.reindex(idx).ffill()
if not bok_base.empty:
    df['BOK Base Rate (%)'] = bok_base.reindex(idx).ffill()

df = df.dropna(how='all')
if df.empty:
    if ecos_api_key == "":
        st.error("No data available. ECOS API Key가 비어있습니다. 사이드바에 API Key를 입력하세요.")
    else:
        st.error("No data available for the selected period. 시작일을 조정해 보세요.")
    st.stop()

# Normalize
plot_df = df.copy()
if normalize:
    for c in plot_df.columns:
        first_valid = plot_df[c].dropna().iloc[0]
        if first_valid != 0:
            plot_df[c] = (plot_df[c] / first_valid) * 100.0
    y_label = "Index (Start = 100)"
else:
    y_label = "Level (various units)"

# Plot
fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
plot_df.plot(ax=ax)
ax.set_title(f"From {start_date} to {dt.date.today()}")
ax.set_xlabel("Date")
ax.set_ylabel(y_label)
ax.grid(True, alpha=0.3)
st.pyplot(fig, clear_figure=True)

# Table
if show_table:
    st.dataframe(df.tail(30), use_container_width=True)

with st.expander("ℹ️ Notes & Data Sources"):
    st.markdown("""
- **KOSPI**: Yahoo Finance `^KS11`
- **USD/KRW**: Yahoo Finance `KRW=X`
- **U.S. Fed Funds Rate**: FRED CSV export (`fredgraph.csv?id=EFFR`)
- **BOK Base Rate**: ECOS Open API `StatisticSearch` (Table `722Y001`, Item `0101000`, Frequency `M`)
- 월별 지표는 그래프 편의를 위해 일 단위로 forward-fill합니다.
- Normalize ON: 시작일 값을 100으로 환산해 비교합니다.
""")
st.success("Ready. Enter your ECOS API key in the sidebar to load the official BOK Base Rate.")
