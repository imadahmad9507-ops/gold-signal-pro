"""
Data Validation Engine:
Validates incoming market data for:
- Chronological ordering and monotonic timestamps
- Duplicate timestamps
- NaN, null, and infinite values
- Invalid OHLC logic (e.g. low > high, open/close out of range)
- Stale data detection
- Incomplete current candle filtering (ensures only completed closed candles are used)
- Minimum candle history requirements for indicators
"""
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)


class DataValidationError(Exception):
    pass


class DataValidator:
    def __init__(self, max_stale_minutes: int = 120, min_candles_required: int = 50):
        self.max_stale_minutes = max_stale_minutes
        self.min_candles_required = min_candles_required

    def validate_and_sanitize(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        now_time: Optional[datetime] = None
    ) -> Tuple[bool, pd.DataFrame, str]:
        """
        Validates OHLCV DataFrame.
        Returns: (is_valid, sanitized_df, error_or_warning_reason)
        """
        if df is None or df.empty:
            return False, pd.DataFrame(), f"ERR_EMPTY_DATA: No data returned for {symbol} ({timeframe})"

        if len(df) < self.min_candles_required:
            return False, df, f"ERR_INSUFFICIENT_HISTORY: Received {len(df)} candles, minimum required is {self.min_candles_required}"

        # 1. Column standardization
        required_cols = ['open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                return False, df, f"ERR_MISSING_COLUMN: Column '{col}' missing from dataset"

        sanitized = df.copy()

        # 2. Check and ensure UTC DatetimeIndex
        if not isinstance(sanitized.index, pd.DatetimeIndex):
            try:
                sanitized.index = pd.to_datetime(sanitized.index, utc=True)
            except Exception as e:
                return False, df, f"ERR_INVALID_INDEX: DatetimeIndex conversion failed: {e}"
        else:
            if sanitized.index.tz is None:
                sanitized.index = sanitized.index.tz_localize("UTC")
            else:
                sanitized.index = sanitized.index.tz_convert("UTC")

        # 3. Check for duplicates and chronological order
        if sanitized.index.has_duplicates:
            dup_count = sanitized.index.duplicated().sum()
            logger.warning(f"Found {dup_count} duplicate timestamps for {symbol}. Keeping last.")
            sanitized = sanitized[~sanitized.index.duplicated(keep='last')]

        if not sanitized.index.is_monotonic_increasing:
            logger.warning(f"Timestamps for {symbol} were out of order. Sorting.")
            sanitized = sanitized.sort_index()

        # 4. Check for NaN, Null, and Inf values
        if sanitized[required_cols].isna().any().any():
            return False, df, f"ERR_NAN_VALUES: Dataset contains NaN/Null values in core OHLC fields"

        for col in required_cols:
            if np.isinf(sanitized[col]).any():
                return False, df, f"ERR_INF_VALUES: Infinite values detected in {col}"

        # 5. Logical OHLC sanity checks
        # high must be >= open, close, and low
        invalid_high = (sanitized['high'] < sanitized['open']) | (sanitized['high'] < sanitized['close']) | (sanitized['high'] < sanitized['low'])
        if invalid_high.any():
            bad_count = invalid_high.sum()
            return False, df, f"ERR_CORRUPT_OHLC: High price lower than Open/Close/Low in {bad_count} candles"

        # low must be <= open, close, and high
        invalid_low = (sanitized['low'] > sanitized['open']) | (sanitized['low'] > sanitized['close'])
        if invalid_low.any():
            bad_count = invalid_low.sum()
            return False, df, f"ERR_CORRUPT_OHLC: Low price higher than Open/Close in {bad_count} candles"

        # Prices must be strictly positive
        if (sanitized[required_cols] <= 0).any().any():
            return False, df, f"ERR_NON_POSITIVE_PRICE: Found non-positive price in OHLC data"

        # 6. Filter incomplete current candle (Closed-Candle Enforcement)
        # If the last candle timestamp is within the current active bar window, drop it to ensure only closed bars are evaluated
        if now_time is None:
            now_time = datetime.now(timezone.utc)
        elif now_time.tzinfo is None:
            now_time = now_time.replace(tzinfo=timezone.utc)

        tf_minutes_map = {
            "1m": 1, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440
        }
        bar_duration_min = tf_minutes_map.get(timeframe, 30)
        last_candle_time = sanitized.index[-1]
        time_since_last_candle = (now_time - last_candle_time).total_seconds() / 60.0

        # If the last bar's duration has not fully elapsed, it is still forming: drop it!
        if time_since_last_candle < bar_duration_min:
            logger.debug(f"Dropping active unclosed candle at {last_candle_time} for {symbol} ({timeframe})")
            sanitized = sanitized.iloc[:-1]

        # 7. Check data staleness (except for weekend/closed market periods)
        last_closed_time = sanitized.index[-1]
        stale_delta = (now_time - last_closed_time).total_seconds() / 60.0
        # If market should be open but data is hours old, flag it
        is_weekend = now_time.weekday() in [5, 6]
        if not is_weekend and stale_delta > self.max_stale_minutes:
            return False, sanitized, f"ERR_STALE_DATA: Last closed bar is {stale_delta:.1f} minutes old (max permitted: {self.max_stale_minutes}m)"

        return True, sanitized, "OK"
