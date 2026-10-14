import pytest
import pandas as pd
import numpy as np
from analysis.volume_profile import VolumeProfileEngine
from analysis.ml_predictor import MLConfluencePredictor
from risk.manager import RiskManager


def _mock_df(n=60, base_price=2000.0):
    prices = [base_price + i * 0.5 for i in range(n)]
    df = pd.DataFrame({
        "open": prices,
        "high": [p + 2.0 for p in prices],
        "low": [p - 2.0 for p in prices],
        "close": [p + 0.5 for p in prices],
        "volume": [1000 + i * 50 for i in range(n)],
        "atr_14": [3.5] * n,
        "rsi_14": [55.0] * n,
        "adx": [28.0] * n,
        "ema_20": [p + 0.1 for p in prices],
        "ema_50": [p - 1.0 for p in prices],
        "ema_200": [p - 5.0 for p in prices]
    })
    return df


def test_volume_profile_poc_calculation():
    engine = VolumeProfileEngine(value_area_pct=0.70, num_bins=30)
    df = _mock_df(50, base_price=2000.0)
    profile = engine.calculate_profile(df, bars_lookback=30)

    assert profile["poc"] is not None
    assert profile["vah"] is not None
    assert profile["val"] is not None
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    assert profile["profile_bias"] in [
        "STRONG_BULLISH_EXPANSION", "MILD_BULLISH", "STRONG_BEARISH_EXPANSION",
        "MILD_BEARISH", "AT_POC_EQUILIBRIUM"
    ]


def test_ml_confluence_predictor():
    predictor = MLConfluencePredictor()
    df = _mock_df(50, base_price=2000.0)
    vp = VolumeProfileEngine().calculate_profile(df, bars_lookback=30)

    pred = predictor.predict_setup_probability(
        df_ind=df,
        bias="LONG",
        regime="TRENDING",
        confluence_score=88.0,
        volume_profile=vp,
        fundamental_bias="STRONG_BULLISH",
        session_info={"is_peak": True, "session_boost": 5}
    )

    assert "win_probability_pct" in pred
    assert 35.0 <= pred["win_probability_pct"] <= 82.0
    assert pred["confidence_grade"] in ["HIGH", "MEDIUM", "LOW"]
    assert len(pred["key_drivers"]) > 0


def test_dynamic_atr_risk_manager():
    config = {
        "risk": {"min_risk_reward": 2.0, "account_balance_usd": 1000.0, "risk_per_trade_percent": 1.0},
        "instruments": {
            "XAUUSD": {
                "atr_multiplier": 1.5,
                "typical_spread_pips": 0.25,
                "min_stop_distance_pips": 1.5,
                "pip_value": 1.0
            }
        }
    }
    rm = RiskManager(config)

    # Base vs Volatile regime
    levels_normal = rm.calculate_trade_levels("XAUUSD", "LONG", 2000.0, atr=5.0, regime="MODERATE")
    levels_volatile = rm.calculate_trade_levels("XAUUSD", "LONG", 2000.0, atr=5.0, regime="VOLATILE")

    assert levels_normal is not None
    assert levels_volatile is not None
    # Volatile ATR multiplier (1.5 * 1.3 = 1.95) should have wider risk distance than normal (1.5)
    assert levels_volatile["risk_distance"] > levels_normal["risk_distance"]
