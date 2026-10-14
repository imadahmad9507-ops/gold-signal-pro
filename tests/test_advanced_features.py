import pytest
import pandas as pd
import numpy as np
from analysis.volume_profile import VolumeProfileEngine
from analysis.ml_predictor import ConfluenceFactorEngine
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


def test_confluence_factor_engine():
    engine = ConfluenceFactorEngine()
    df = _mock_df(50, base_price=2000.0)
    vp = VolumeProfileEngine().calculate_profile(df, bars_lookback=30)

    analysis = engine.evaluate_factor_alignment(
        df_ind=df,
        bias="LONG",
        regime="TRENDING",
        confluence_score=88.0,
        volume_profile=vp,
        fundamental_bias="STRONG_BULLISH",
        session_info={"is_peak": True, "session_boost": 5}
    )

    assert "alignment_score" in analysis
    assert -100.0 <= analysis["alignment_score"] <= 100.0
    assert analysis["confidence_grade"] in ["STRONG_CONFLUENCE", "MODERATE_CONFLUENCE", "NEUTRAL", "CONFLICTING_FACTORS"]
    assert len(analysis["key_drivers"]) > 0


def test_dynamic_atr_risk_manager_and_rr():
    config = {
        "risk": {
            "min_risk_reward": 2.5,
            "account_balance_usd": 1000.0,
            "risk_per_trade_percent": 0.25,
            "tp1_r": 1.0,
            "tp2_r": 2.5,
            "tp3_r": 4.0
        },
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
    # Volatile ATR multiplier should have wider risk distance than normal
    assert levels_volatile["risk_distance"] > levels_normal["risk_distance"]
    # Fallback path must pass its own 2.5 R:R requirement!
    assert levels_normal["risk_reward_tp2"] >= 2.5


def test_default_config_strict_risk_ceiling():
    import yaml
    import os
    from risk.hardened_manager import HardenedRiskManager

    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    with open(cfg_path, "r") as f:
        config = yaml.safe_load(f)

    # 1. Verify configured risk percent is strictly 0.25%
    risk_pct = config["risk"]["risk_per_trade_percent"]
    assert risk_pct == 0.25, f"Expected 0.25% risk per trade, found {risk_pct}%"

    # 2. Verify account balance equity
    balance_usc = config["risk"]["account_balance_usc"]
    assert balance_usc == 5000.0  # 5,000 USC = $50.00 USD

    # 3. Verify maximum monetary risk calculation
    max_risk_usd = (balance_usc / 100.0) * (risk_pct / 100.0)
    assert abs(max_risk_usd - 0.125) < 1e-4, f"Expected max risk $0.125, calculated ${max_risk_usd}"

    # 4. Verify HardenedRiskManager enforces this ceiling on Cent trade evaluation
    hrm = HardenedRiskManager(config)
    eval_res = hrm.evaluate_signal_risk("XAUUSD", 2000.0, 1995.0, 2015.0, account_type="cent")
    assert eval_res["approved"] is True
    assert eval_res["dollar_risk"] <= 0.125, f"Evaluated dollar risk {eval_res['dollar_risk']} exceeds $0.125 ceiling"
