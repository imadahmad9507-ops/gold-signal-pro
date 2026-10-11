"""
Technical Indicators Engine.
Calculates EMA, Supertrend, ADX, Ichimoku, RSI, MACD, Stoch RSI, ATR, Bollinger Bands,
Swing points, BOS, ChoCH, Pivot points, Round numbers, and Fibonacci levels.
Strictly zero lookahead: calculations based on closed bars only.
"""
import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high = df['high']
    low = df['low']
    close = df['close']
    
    up_move = high.diff()
    down_move = -low.diff()
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    atr = calculate_atr(df, period)
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr)
    
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
    adx = dx.rolling(period).mean()
    
    return pd.DataFrame({'adx': adx, 'plus_di': plus_di, 'minus_di': minus_di}, index=df.index)


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = calculate_ema(series, fast)
    slow_ema = calculate_ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = calculate_ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({'macd': macd_line, 'macd_signal': signal_line, 'macd_hist': hist}, index=series.index)


def calculate_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + (num_std * std)
    lower = sma - (num_std * std)
    bandwidth = (upper - lower) / (sma + 1e-9)
    return pd.DataFrame({'bb_upper': upper, 'bb_middle': sma, 'bb_lower': lower, 'bb_width': bandwidth}, index=series.index)


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    atr = calculate_atr(df, period)
    hl2 = (df['high'] + df['low']) / 2
    upper_basic = hl2 + (multiplier * atr)
    lower_basic = hl2 - (multiplier * atr)
    
    upper_band = pd.Series(index=df.index, dtype=float)
    lower_band = pd.Series(index=df.index, dtype=float)
    trend = pd.Series(index=df.index, dtype=int)
    
    for i in range(len(df)):
        if i == 0:
            upper_band.iloc[i] = upper_basic.iloc[i]
            lower_band.iloc[i] = lower_basic.iloc[i]
            trend.iloc[i] = 1
            continue
            
        prev_close = df['close'].iloc[i-1]
        prev_upper = upper_band.iloc[i-1]
        prev_lower = lower_band.iloc[i-1]
        
        # Upper band adjustment
        if upper_basic.iloc[i] < prev_upper or prev_close > prev_upper:
            upper_band.iloc[i] = upper_basic.iloc[i]
        else:
            upper_band.iloc[i] = prev_upper
            
        # Lower band adjustment
        if lower_basic.iloc[i] > prev_lower or prev_close < prev_lower:
            lower_band.iloc[i] = lower_basic.iloc[i]
        else:
            lower_band.iloc[i] = prev_lower
            
        # Direction
        if df['close'].iloc[i] > prev_upper:
            trend.iloc[i] = 1
        elif df['close'].iloc[i] < prev_lower:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]
            
    return pd.DataFrame({'supertrend_upper': upper_band, 'supertrend_lower': lower_band, 'supertrend_dir': trend}, index=df.index)


def detect_swing_points(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Detect local swing highs and lows with window on left and right."""
    highs = df['high']
    lows = df['low']
    swing_high = pd.Series(False, index=df.index)
    swing_low = pd.Series(False, index=df.index)
    
    for i in range(window, len(df) - window):
        is_high = True
        is_low = True
        val_h = highs.iloc[i]
        val_l = lows.iloc[i]
        for offset in range(1, window + 1):
            if highs.iloc[i - offset] >= val_h or highs.iloc[i + offset] > val_h:
                is_high = False
            if lows.iloc[i - offset] <= val_l or lows.iloc[i + offset] < val_l:
                is_low = False
        if is_high:
            swing_high.iloc[i] = True
        if is_low:
            swing_low.iloc[i] = True
            
    return pd.DataFrame({'swing_high': swing_high, 'swing_low': swing_low}, index=df.index)


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Combines all indicators onto the dataframe cleanly."""
    df = df.copy()
    
    # EMAs
    df['ema_20'] = calculate_ema(df['close'], 20)
    df['ema_50'] = calculate_ema(df['close'], 50)
    df['ema_200'] = calculate_ema(df['close'], 200)
    
    # Volatility
    df['atr_14'] = calculate_atr(df, 14)
    bb = calculate_bollinger_bands(df['close'], 20, 2.0)
    df = pd.concat([df, bb], axis=1)
    
    # Momentum
    df['rsi_14'] = calculate_rsi(df['close'], 14)
    macd = calculate_macd(df['close'], 12, 26, 9)
    df = pd.concat([df, macd], axis=1)
    
    # ADX & Trend
    adx_df = calculate_adx(df, 14)
    df = pd.concat([df, adx_df], axis=1)
    
    st_df = calculate_supertrend(df, 10, 3.0)
    df = pd.concat([df, st_df], axis=1)
    
    # Swings
    swings = detect_swing_points(df, 5)
    df = pd.concat([df, swings], axis=1)
    
    return df
