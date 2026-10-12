"""
Comprehensive Test Suite for Hardened Production Requirements:
1. Data feed validation:
   - Monotonic timestamps, duplicate rejection, NaN/infinite detection, OHLC logic
   - Incomplete current forming candle drop
2. Hardened Risk Engine:
   - Ultra-strict 0.25% risk ceiling ($0.125 on $50 account)
   - Rejection when stop loss distance creates monetary loss > $0.125 at 0.01 lot
   - Accurate recognition of Cent Account volume mechanics
3. News Filter Fail-Closed Behavior:
   - Immediate suppression if calendar feed is unreachable / returns empty
4. Deduplication & State Tracking:
   - Dedup key prevents repeated alerts on the same bar
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from data.validator import DataValidator
from risk.hardened_manager import HardenedRiskManager
from news.calendar import NewsFilter
from tracking.tracker import SignalTracker


def test_data_validator_drops_forming_candle():
    """Ensure active, forming candle is discarded to eliminate look-ahead bias."""
    now = datetime.now(timezone.utc)
    # 60 candles spaced by 30 mins, with the last candle starting 10 minutes ago
    dates = [now - timedelta(minutes=10) - timedelta(minutes=30 * (59 - i)) for i in range(60)]
    df = pd.DataFrame({
        "open": [2000.0 + i for i in range(60)],
        "high": [2005.0 + i for i in range(60)],
        "low": [1995.0 + i for i in range(60)],
        "close": [2002.0 + i for i in range(60)],
        "volume": [1000 for _ in range(60)]
    }, index=pd.DatetimeIndex(dates))

    validator = DataValidator(max_stale_minutes=1440, min_candles_required=20)
    valid, sanitized, reason = validator.validate_and_sanitize(df, "GC=F", "30m", now_time=now)
    assert valid is True
    # The last candle was only 10 minutes old (duration is 30m), so it must be dropped
    assert len(sanitized) == 59


def test_data_validator_rejects_corrupted_ohlc():
    """Ensure invalid OHLC geometry (e.g. low > high) is flagged and rejected."""
    now = datetime.now(timezone.utc)
    dates = [now - timedelta(minutes=10) - timedelta(minutes=30 * (59 - i)) for i in range(60)]
    df = pd.DataFrame({
        "open": [2000.0] * 60,
        "high": [1990.0] * 60,  # Invalid: high is less than low
        "low": [2010.0] * 60,
        "close": [2000.0] * 60,
        "volume": [1000] * 60
    }, index=pd.DatetimeIndex(dates))

    validator = DataValidator(max_stale_minutes=1440, min_candles_required=20)
    valid, sanitized, reason = validator.validate_and_sanitize(df, "GC=F", "30m", now_time=now)
    assert valid is False
    assert "ERR_CORRUPT_OHLC" in reason


def test_hardened_risk_rejects_excessive_risk_on_50_account():
    """
    On a standard account with $50 balance and 0.25% risk limit ($0.125 max loss),
    a gold trade with a $6.00 stop loss at 0.01 standard lot risks $6.00.
    The hardened risk manager must reject this with RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE.
    """
    config = {
        "risk": {
            "account_balance_usd": 50.0,
            "risk_per_trade_percent": 0.25,
            "min_risk_reward": 2.5
        }
    }
    mgr = HardenedRiskManager(config)

    # Entry 2650, SL 2644 ($6.00 raw stop), TP 2670 ($20.00 reward -> R:R ~ 3.1)
    res = mgr.evaluate_signal_risk("XAUUSD", 2650.0, 2644.0, 2670.0)
    assert res["approved"] is False
    assert "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE" in res["reason"]
    assert res["requires_cent_account"] is True


def test_hardened_risk_approves_cent_account():
    """
    On an Exness Cent Account, 0.01 cent lot risks 1/100th ($0.01 per dollar move).
    A $6.00 stop = $0.06 loss, which is safely below the $0.125 risk ceiling.
    """
    config = {
        "risk": {
            "account_balance_usd": 50.0,
            "risk_per_trade_percent": 0.25,
            "min_risk_reward": 2.5
        }
    }
    mgr = HardenedRiskManager(config)

    res = mgr.evaluate_signal_risk("XAUUSD", 2650.0, 2644.0, 2670.0, is_cent_account=True)
    assert res["approved"] is True
    assert res["planned_rr"] >= 2.5
    assert res["dollar_risk"] <= 0.125


def test_news_filter_fail_closed_on_error():
    """Verify fail-closed requirement: if news feed cannot be fetched, signals are suppressed."""
    config = {
        "news_filter": {
            "enabled": True,
            "feed_url": "https://invalid-non-existent-domain-xyz.com/calendar.json",
            "fail_closed_on_error": True
        }
    }
    filter_inst = NewsFilter(config)
    res = filter_inst.check_news_status("XAUUSD")
    assert res["is_safe"] is False
    assert res["feed_ok"] is False
    assert "CALENDAR_UNAVAILABLE_FAIL_CLOSED" in res["reason"]


def test_signal_tracker_deduplication(tmp_path):
    """Verify that identical setups on the same bar are blocked by deduplication."""
    db_file = str(tmp_path / "test_signals.db")
    tracker = SignalTracker(db_path=db_file)

    sig = {
        "symbol": "XAUUSD",
        "timeframe": "30m",
        "strategy": "Trend Pullback",
        "direction": "LONG",
        "entry": 2650.0,
        "stop_loss": 2645.0,
        "tp1": 2655.0,
        "tp2": 2662.5,
        "suggested_lot_size": 0.01,
        "confluence_score": 88.0,
        "grade": "A+",
        "dedup_key": "unique_hash_candle_123"
    }

    assert tracker.is_duplicate_signal(sig["dedup_key"]) is False
    row_id = tracker.log_new_signal(sig)
    assert row_id > 0
    assert tracker.is_duplicate_signal(sig["dedup_key"]) is True
