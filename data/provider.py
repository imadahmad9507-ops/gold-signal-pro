"""
Pluggable Market Data Provider with Validation, Caching, and Instrument Mapping:
- Clearly separates Reference Futures (GC=F) from Broker Spot CFD (XAUUSD=X / Broker Feed).
- Supports pluggable providers (YFinance, TwelveData, MT5 bridge placeholder).
- Integrates DataValidator for strict anomaly/gap/staleness detection.
- Labels all data with its exact origin, instrument type, and timestamp.
"""
import os
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
import pandas as pd
import yfinance as yf

from data.validator import DataValidator

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


class BaseDataProvider(ABC):
    provider_name: str = "Base"

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 500,
        validate: bool = True
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Fetch OHLCV data.
        Returns: (df, metadata_dict)
        where metadata_dict includes:
        - provider: str
        - symbol: str
        - instrument_type: 'FUTURES_REFERENCE' | 'SPOT_CFD' | 'FOREX' | 'CRYPTO'
        - timeframe: str
        - last_closed_timestamp: str
        - is_validated: bool
        - validation_status: str
        """
        pass


class YFinanceDataProvider(BaseDataProvider):
    provider_name = "YahooFinance"

    TF_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "60m",
        "4h": "1h",  # Resampled from 1h
        "1d": "1d",
    }

    def __init__(self, cache_ttl_seconds: int = 180, validator: Optional[DataValidator] = None):
        self.cache_ttl = cache_ttl_seconds
        self.validator = validator or DataValidator()

    def _get_cache_path(self, symbol: str, timeframe: str) -> str:
        safe_sym = symbol.replace("=", "_").replace("^", "").replace("-", "_").replace(".", "_")
        return os.path.join(CACHE_DIR, f"{safe_sym}_{timeframe}.parquet")

    def _determine_instrument_type(self, symbol: str) -> str:
        if symbol in ["GC=F", "NQ=F", "ES=F", "YM=F", "CL=F"]:
            return "FUTURES_REFERENCE"
        elif "XAU" in symbol or "GOLD" in symbol:
            return "SPOT_CFD"
        elif symbol.endswith("=X"):
            return "FOREX"
        elif "BTC" in symbol or "ETH" in symbol:
            return "CRYPTO"
        return "REFERENCE"

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 1000,
        validate: bool = True
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        cache_path = self._get_cache_path(symbol, timeframe)
        now = time.time()
        inst_type = self._determine_instrument_type(symbol)

        df = pd.DataFrame()
        # 1. Read from local cache if warm
        if not start and os.path.exists(cache_path):
            mtime = os.path.getmtime(cache_path)
            if now - mtime < self.cache_ttl:
                try:
                    df = pd.read_parquet(cache_path)
                    if not df.empty and len(df) >= 50:
                        logger.debug(f"Loaded {symbol} ({timeframe}) from cache.")
                except Exception as e:
                    logger.warning(f"Cache read error for {symbol}: {e}")

        # 2. Fetch remote if cache missing
        if df.empty:
            yf_interval = self.TF_MAP.get(timeframe, "30m")
            need_resample_4h = (timeframe == "4h")
            fetch_interval = "1h" if need_resample_4h else yf_interval

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
                raise ValueError(f"No market data returned from Yahoo for {symbol} on timeframe {timeframe}")

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

            if need_resample_4h:
                df = df.resample("4h").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum"
                }).dropna()

            # Cache raw parquet
            if not start:
                try:
                    df.to_parquet(cache_path)
                except Exception as e:
                    logger.warning(f"Failed to cache parquet: {e}")

        # 3. Validate and Sanitize
        val_status = "UNVALIDATED"
        if validate:
            is_valid, sanitized_df, reason = self.validator.validate_and_sanitize(df, symbol, timeframe)
            if not is_valid:
                logger.error(f"Data validation failed for {symbol}: {reason}")
                raise ValueError(f"DATA_VALIDATION_FAILURE: {reason}")
            df = sanitized_df
            val_status = reason

        df_out = df.tail(limit).copy()
        last_ts = df_out.index[-1].isoformat() if not df_out.empty else "N/A"

        meta = {
            "provider": self.provider_name,
            "symbol": symbol,
            "instrument_type": inst_type,
            "timeframe": timeframe,
            "last_closed_timestamp": last_ts,
            "is_validated": validate,
            "validation_status": val_status,
            "is_broker_execution_feed": (inst_type != "FUTURES_REFERENCE")
        }

        return df_out, meta


class MT5BridgeDataProvider(BaseDataProvider):
    """
    Placeholder/Interface for direct broker data (e.g. Exness MT5 bridge or REST bridge).
    Requires a running local MT5 terminal or authorized VPS bridge endpoint.
    """
    provider_name = "MetaTrader5_Bridge"

    def __init__(self, endpoint_url: Optional[str] = None):
        self.endpoint_url = endpoint_url

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 500,
        validate: bool = True
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        raise NotImplementedError(
            "MT5 Bridge requires an active MT5 terminal or authorized external bridge. "
            "Please configure provider: 'yfinance' or provide MT5_BRIDGE_URL."
        )


def get_data_provider(provider_type: str = "yfinance") -> BaseDataProvider:
    if provider_type == "yfinance":
        return YFinanceDataProvider()
    elif provider_type == "mt5_bridge":
        return MT5BridgeDataProvider()
    raise ValueError(f"Unsupported data provider: {provider_type}")
