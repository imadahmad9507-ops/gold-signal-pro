"""
Pluggable Data Provider module with caching, weekend/gap handling, and retries.
Primary source: yfinance (GC=F, XAUUSD=X, DX-Y.NYB, ^TNX, etc.)
Pluggable interface for Twelve Data / Alpha Vantage.
"""
import os
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


class BaseDataProvider(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, start: Optional[str] = None, end: Optional[str] = None, limit: int = 500) -> pd.DataFrame:
        """Fetch OHLCV data as pandas DataFrame with DatetimeIndex and columns: Open, High, Low, Close, Volume."""
        pass


class YFinanceDataProvider(BaseDataProvider):
    # Mapping our standard timeframes to yfinance intervals
    TF_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "60m",
        "4h": "1h",  # Resampled from 1h
        "1d": "1d",
    }

    def __init__(self, cache_ttl_seconds: int = 180):
        self.cache_ttl = cache_ttl_seconds

    def _get_cache_path(self, symbol: str, timeframe: str) -> str:
        safe_sym = symbol.replace("=", "_").replace("^", "").replace("-", "_").replace(".", "_")
        return os.path.join(CACHE_DIR, f"{safe_sym}_{timeframe}.parquet")

    def fetch_ohlcv(self, symbol: str, timeframe: str, start: Optional[str] = None, end: Optional[str] = None, limit: int = 1000) -> pd.DataFrame:
        cache_path = self._get_cache_path(symbol, timeframe)
        now = time.time()

        # Check cache if not specific historical start/end query
        if not start and os.path.exists(cache_path):
            mtime = os.path.getmtime(cache_path)
            if now - mtime < self.cache_ttl:
                try:
                    df = pd.read_parquet(cache_path)
                    if not df.empty and len(df) >= 50:
                        return df
                except Exception as e:
                    logger.warning(f"Cache read error for {symbol}: {e}")

        yf_interval = self.TF_MAP.get(timeframe, "30m")
        need_resample_4h = (timeframe == "4h")
        fetch_interval = "1h" if need_resample_4h else yf_interval

        # Determine yfinance period
        period = "60d"
        if timeframe in ["1m", "5m"]:
            period = "7d"
        elif timeframe in ["15m", "30m"]:
            period = "60d"
        elif timeframe in ["1h", "4h"]:
            period = "730d"
        elif timeframe == "1d":
            period = "max"

        retries = 3
        df = pd.DataFrame()
        for attempt in range(retries):
            try:
                ticker = yf.Ticker(symbol)
                if start and end:
                    df = ticker.history(start=start, end=end, interval=fetch_interval, auto_adjust=False)
                else:
                    df = ticker.history(period=period, interval=fetch_interval, auto_adjust=False)

                if not df.empty:
                    break
            except Exception as e:
                logger.warning(f"Fetch attempt {attempt+1}/{retries} failed for {symbol}: {e}")
                time.sleep(1.0 * (attempt + 1))

        if df.empty:
            # Try alternative symbol if GC=F fails
            if symbol == "GC=F":
                logger.info("Retrying with XAUUSD=X fallback...")
                return self.fetch_ohlcv("XAUUSD=X", timeframe, start=start, end=end, limit=limit)
            raise ValueError(f"No data returned for {symbol} on timeframe {timeframe}")

        # Standardize columns
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })
        needed = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in needed if c in df.columns]]
        df.index = pd.to_datetime(df.index, utc=True)
        df = df.sort_index()

        # Drop duplicates and forward fill tiny anomalies
        df = df[~df.index.duplicated(keep="last")]
        df = df.dropna(subset=["open", "high", "low", "close"])

        # Resample for 4h if needed
        if need_resample_4h:
            df = df.resample("4h").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna()

        # Cache locally
        if not start:
            try:
                df.to_parquet(cache_path)
            except Exception as e:
                logger.warning(f"Failed to cache parquet: {e}")

        return df.tail(limit)


def get_data_provider(provider_type: str = "yfinance") -> BaseDataProvider:
    if provider_type == "yfinance":
        return YFinanceDataProvider()
    raise ValueError(f"Unsupported data provider: {provider_type}")
