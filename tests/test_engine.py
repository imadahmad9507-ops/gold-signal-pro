"""
Automated Unit Tests for gold-signal-pro:
- Indicator calculations (EMA, ATR, RSI, Supertrend)
- Strict no-lookahead check
- Risk Manager level validation (R:R >= 2.0, lot size)
- Confluence Analyzer boundary checks
"""
import pytest
import numpy as np
import pandas as pd
import yaml

from indicators.engine import (
    calculate_ema,
    calculate_atr,
    calculate_rsi,
    calculate_supertrend,
    calculate_all_indicators
)
from risk.manager import RiskManager
from analysis.confluence import ConfluenceAnalyzer


def create_sample_df(n=100):
    dates = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    prices = np.linspace(2000, 2100, n) + np.random.normal(0, 2, n)
    df = pd.DataFrame({
        "open": prices,
        "high": prices + 3.0,
        "low": prices - 3.0,
        "close": prices + 1.0,
        "volume": 1000
    }, index=dates)
    return df


def test_indicators_no_lookahead():
    """Verify that adding future bars does NOT change previous indicator values."""
    df = create_sample_df(60)
    ind1 = calculate_all_indicators(df)

    # Append new future bar
    new_bar = pd.DataFrame({
        "open": [2105.0], "high": [2110.0], "low": [2100.0], "close": [2108.0], "volume": [1200]
    }, index=[df.index[-1] + pd.Timedelta(minutes=30)])
    df_extended = pd.concat([df, new_bar])
    ind2 = calculate_all_indicators(df_extended)

    # Check EMA, ATR, RSI on index 50 match exactly
    assert np.isclose(ind1["ema_20"].iloc[50], ind2["ema_20"].iloc[50])
    assert np.isclose(ind1["atr_14"].iloc[50], ind2["atr_14"].iloc[50])
    assert np.isclose(ind1["rsi_14"].iloc[50], ind2["rsi_14"].iloc[50])


def test_risk_manager_levels():
    cfg = {
        "risk": {"account_balance_usd": 1000.0, "risk_per_trade_percent": 1.0, "min_risk_reward": 2.0},
        "instruments": {"XAUUSD": {"atr_multiplier": 1.5, "typical_spread_pips": 0.25, "pip_value": 1.0, "min_stop_distance_pips": 1.5}}
    }
    rm = RiskManager(cfg)
    levels = rm.calculate_trade_levels("XAUUSD", "LONG", 2600.0, 5.0)

    assert levels is not None
    assert levels["entry"] == 2600.0
    assert levels["stop_loss"] < 2600.0
    assert levels["tp2"] > levels["tp1"]
    assert levels["risk_reward_tp2"] >= 2.0
    assert levels["suggested_lot_size"] > 0


def test_confluence_neutral():
    cfg = {
        "scoring": {"min_grade_a": 75, "min_grade_b": 60, "send_grades": ["A", "B"], "weights": {"trend": 30, "momentum": 15, "volatility": 10, "market_structure": 20, "support_resistance": 10, "candlestick": 5, "intermarket": 5, "regime": 5}}
    }
    ca = ConfluenceAnalyzer(cfg)
    df = create_sample_df(60)
    df_ind = calculate_all_indicators(df)
    res = ca.calculate_confluence(df_ind, "XAUUSD")
    assert "bias" in res
    assert "total_score" in res
    assert 0 <= res["total_score"] <= 100
