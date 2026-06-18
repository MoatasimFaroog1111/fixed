"""
data_fetcher.py v2
التغييرات:
  - إصلاح M-06: إزالة auto_adjust=True المُهمَل في yfinance الحديثة
  - إصلاح L-02: إزالة os.system('pip install') — استخدم requirements.txt
شغّله مرة واحدة: python data_fetcher.py
"""
import os
import pickle
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

import yfinance as yf   # يجب أن يكون مثبتاً: pip install -r requirements.txt

logger = logging.getLogger(__name__)

DATA_DIR    = "data"
START_DAILY = "2013-01-01"
HOURLY_DAYS = 729

TICKERS = {
    "AUXLN": ("GC=F",     "Gold"),
    "AGXLN": ("SI=F",     "Silver"),
    "PTXLN": ("PL=F",     "Platinum"),
    "PDXLN": ("PA=F",     "Palladium"),
    "DXY":   ("DX-Y.NYB", "Dollar Index"),
}

os.makedirs(DATA_DIR, exist_ok=True)


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    متوافق مع yfinance 1.x الذي يُعيد MultiIndex بشكل (Price, Ticker).
    Level 0 = Close/High/Low/Volume، Level 1 = رمز الورقة.
    """
    if isinstance(df.columns, pd.MultiIndex):
        # نأخذ Level 0 مباشرةً — يحتوي على أسماء الأعمدة المطلوبة
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    needed = [c for c in ["close", "high", "low", "volume"] if c in df.columns]
    df = df[needed].copy()
    df.dropna(inplace=True)
    return df


def fetch_daily(security_id: str, ticker: str, name: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{security_id}_daily.pkl")
    print(f"  📅 يومية {name} منذ {START_DAILY}...")
    try:
        df = yf.download(ticker, start=START_DAILY, interval="1d", progress=False)
        if df.empty:
            print(f"  ⚠️  لا بيانات يومية لـ {name}")
            return None
        df = _clean_df(df)
        with open(path, "wb") as f:
            pickle.dump(df, f)
        print(f"  ✅ {len(df):,} يوم | {df.index[0].date()} ← {df.index[-1].date()}")
        return df
    except Exception as e:
        logger.error("Failed to fetch daily data for %s: %s", name, e)
        return None


def fetch_hourly(security_id: str, ticker: str, name: str) -> pd.DataFrame:
    path  = os.path.join(DATA_DIR, f"{security_id}_hourly.pkl")
    start = (datetime.now() - timedelta(days=HOURLY_DAYS)).strftime("%Y-%m-%d")
    print(f"  🕐 ساعية {name} منذ {start}...")
    try:
        df = yf.download(ticker, start=start, interval="1h", progress=False)
        if df.empty:
            print(f"  ⚠️  لا بيانات ساعية لـ {name}")
            return None
        df = _clean_df(df)
        with open(path, "wb") as f:
            pickle.dump(df, f)
        print(f"  ✅ {len(df):,} ساعة | {df.index[0].date()} ← {df.index[-1].date()}")
        return df
    except Exception as e:
        logger.error("Failed to fetch hourly data for %s: %s", name, e)
        return None


def load_prices(security_id: str, interval: str = "daily") -> np.ndarray:
    path = os.path.join(DATA_DIR, f"{security_id}_{interval}.pkl")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        df = pickle.load(f)
    return df["close"].values.astype(float)


def load_dataframe(security_id: str, interval: str = "daily") -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{security_id}_{interval}.pkl")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


if __name__ == "__main__":
    print("=" * 55)
    print("  تحميل البيانات التاريخية — BullionVault Bot v7")
    print("=" * 55)

    daily_results  = {}
    hourly_results = {}

    for sid, (ticker, name) in TICKERS.items():
        print(f"\n── {name} ({sid}) ──")
        d = fetch_daily(sid, ticker, name)
        if d is not None:
            daily_results[sid] = len(d)
        h = fetch_hourly(sid, ticker, name)
        if h is not None:
            hourly_results[sid] = len(h)

    print("\n" + "=" * 55)
    print("  ملخص التحميل:")
    print(f"  {'المعدن':<10} {'يومية':>10} {'ساعية':>10}")
    print(f"  {'-'*30}")
    for sid in list(TICKERS.keys()):
        d = daily_results.get(sid,  0)
        h = hourly_results.get(sid, 0)
        if d or h:
            print(f"  {sid:<10} {d:>9,} {h:>10,}")
    print()
    print("  ✅ اكتمل التحميل.")
    print("  الخطوة التالية: python historical_trainer.py")
    print("=" * 55)
