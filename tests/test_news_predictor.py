"""
Unit Tests for Upgrade 4:
- Major News Event Prediction Engine (CPI, NFP, PPI, FOMC)
- Near-Miss Deduplication & Tier Evaluation
- Periodic Heartbeat Filtering during News Blackout
- CME FedWatch Fallback & Scenarios
"""
import pytest
from datetime import datetime, timezone
from analysis.news_predictor import NewsPredictorEngine
from telegram_bot.notifier import TelegramNotifier
from tracking.tracker import SignalTracker


def test_news_predictor_event_recognition():
    engine = NewsPredictorEngine()
    assert engine.is_major_usd_event("Core CPI m/m") is True
    assert engine.is_major_usd_event("Non-Farm Employment Change") is True
    assert engine.is_major_usd_event("FOMC Statement") is True
    assert engine.is_major_usd_event("PPI m/m") is True
    assert engine.is_major_usd_event("German ZEW Economic Sentiment") is False


def test_news_predictor_cme_fedwatch_graceful_fallback():
    engine = NewsPredictorEngine()
    res = engine.fetch_fedwatch_probability()
    assert "cut_probability" in res
    assert "hold_probability" in res
    assert "hike_probability" in res
    assert res["cut_probability"] + res["hold_probability"] + res["hike_probability"] == 100


def test_news_predictor_scenario_calculations():
    engine = NewsPredictorEngine()
    event_data = {
        "title": "CPI m/m",
        "country": "USD",
        "impact": "High",
        "forecast": "0.3%",
        "previous": "0.2%",
        "date": "2026-10-15T12:30:00+00:00"
    }
    analysis = engine.generate_pre_event_analysis(
        event_data,
        current_gold_price=2650.0,
        dxy_data={"level": 102.2, "trend": "BEARISH", "weekly_change_pct": -0.5},
        real_yield_data={"real_yield": 1.4}
    )

    assert "PRE-EVENT ANALYSIS" in analysis["message"]
    assert "BULLISH SCENARIO" in analysis["message"]
    assert "BEARISH SCENARIO" in analysis["message"]
    assert "NEUTRAL SCENARIO" in analysis["message"]
    assert analysis["levels"]["c"] == 2650.0
    assert analysis["levels"]["res1"] > 2650.0
    assert analysis["levels"]["sup1"] < 2650.0


def test_news_predictor_post_event_audit():
    engine = NewsPredictorEngine()
    post_msg = engine.generate_post_event_analysis(
        event_title="Core CPI m/m",
        actual_val="0.4%",
        forecast_val="0.2%",
        price_before=2660.0,
        current_price=2635.0,
        key_level_to_hold=2630.0
    )
    assert "POST-EVENT UPDATE" in post_msg
    assert "BEAT" in post_msg
    assert "$25.00" in post_msg
    assert "2630.00" in post_msg


def test_near_miss_message_and_deduplication(tmp_path):
    notifier = TelegramNotifier()
    msg = ""
    # Test formatting of Near-Miss alert
    sent = notifier.send_near_miss_alert(
        symbol="XAUUSD",
        timeframe="30m",
        direction="LONG",
        score=78.5,
        reasons_failed=["Score 78.5/100 (need 85 for A+)", "R:R 1:1.9 (need 1:2.5)"],
        recommended_action="Wait for pullback to $2640.00",
        key_level=2640.0
    )
    # Token not set in test environment, but shouldn't raise exception
    assert sent is False

    # Verify tracker deduplication logic accepts near-miss key format
    db_file = str(tmp_path / "test_tracker.db")
    tracker = SignalTracker(db_file)
    dedup_key = "nm_xauusd_long_20261014_1400"
    assert tracker.is_duplicate_signal(dedup_key) is False

    tracker.log_new_signal({
        "symbol": "XAUUSD",
        "timeframe": "30m",
        "strategy": "Breakout and Retest",
        "direction": "LONG",
        "entry": 2650.0,
        "stop_loss": 2640.0,
        "tp1": 2660.0,
        "tp2": 2675.0,
        "lot_size": 0.01,
        "confluence_score": 78.5,
        "grade": "A",
        "status": "NEAR_MISS",
        "dedup_key": dedup_key
    })
    assert tracker.is_duplicate_signal(dedup_key) is True
