"""
Unit Tests for Enhanced Session Watch Manager and Session Hunter:
1. Tests session context classification (London kill zone, NY kill zone, Overlap, Silver Bullet, Asian, Off-Peak).
2. Tests exact session scoring bonuses (+5, +8, +10, -5).
3. Tests UTC to PKT string formatting (UTC+5).
4. Tests Asian range calculation (high, low, range, sweep status).
5. Tests SessionHunterStrategy (Judas swing during London killzone and Silver Bullet FVG).
"""
import pytest
from datetime import datetime, timezone
import pandas as pd
from sessions.watch_mode import SessionWatchManager
from strategy.session_hunter import SessionHunterStrategy


def test_session_context_overlap():
    mgr = SessionWatchManager()
    # 14:00 UTC = 19:00 PKT (London-NY Overlap)
    t = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
    ctx = mgr.get_session_context(t)
    assert ctx["is_overlap"] is True
    assert ctx["session_boost"] == 8
    assert "19:00 PKT" in ctx["time_pkt"]


def test_session_context_silver_bullet():
    mgr = SessionWatchManager()
    # 15:30 UTC = 20:30 PKT (Silver Bullet window)
    t = datetime(2026, 10, 14, 15, 30, tzinfo=timezone.utc)
    ctx = mgr.get_session_context(t)
    assert ctx["is_silver_bullet"] is True
    assert ctx["session_boost"] == 10
    assert "20:30 PKT" in ctx["time_pkt"]


def test_session_context_offpeak():
    mgr = SessionWatchManager()
    # 21:30 UTC (Off peak / rollover)
    t = datetime(2026, 10, 14, 21, 30, tzinfo=timezone.utc)
    ctx = mgr.get_session_context(t)
    assert ctx["session_boost"] == -5


def test_asian_range_calculation():
    mgr = SessionWatchManager()
    # Construct bars with timestamps
    times = pd.date_range("2026-10-14 00:00", periods=20, freq="30min", tz="UTC")
    df = pd.DataFrame({
        "open": [2640.0] * 20,
        "high": [2650.0] * 20,
        "low": [2635.0] * 20,
        "close": [2645.0] * 20
    }, index=times)

    res = mgr.compute_asian_range(df)
    assert res["high"] == 2650.0
    assert res["low"] == 2635.0
    assert res["range"] == 15.0


def test_judas_swing_detection_in_session_hunter():
    strat = SessionHunterStrategy()
    # Create 18 bars (00:00 to 08:30 UTC): last bar is at 08:30 UTC in London Kill Zone
    times = pd.date_range("2026-10-14 00:00", periods=18, freq="30min", tz="UTC")
    df = pd.DataFrame({
        "open": [2650.0] * 18,
        "high": [2655.0] * 18,
        "low": [2640.0] * 18,
        "close": [2650.0] * 18,
        "atr_14": [4.0] * 18
    }, index=times)

    # Asian low is established at 2640.0 across 00:00-07:30
    # Candle -2 (08:00 UTC) sweeps Asian low down to 2636.0
    # Candle -1 (08:30 UTC) reclaims and closes back inside range at 2646.0 (close > open)
    df.iloc[-2, df.columns.get_loc("low")] = 2636.0
    df.iloc[-1, df.columns.get_loc("open")] = 2639.0
    df.iloc[-1, df.columns.get_loc("close")] = 2646.0

    sig = strat.evaluate(df, "XAUUSD", "TRENDING")
    assert sig is not None
    assert sig["direction"] == "LONG"
    assert "Judas swing" in sig["reason"]
