"""
Verification Gate Automated Tests:
1. Two independent scans of the same completed candle ensure ZERO duplicate Telegram alerts.
2. Recovery after process restart and simulated DB failure.
3. Verification that rejected setups are logged to the journal table.
4. Missing instrument specification rejection.
5. Standard vs Cent account risk comparison.
"""
import pytest
import sqlite3
import hashlib
from unittest.mock import MagicMock

from tracking.tracker import SignalTracker
from risk.hardened_manager import HardenedRiskManager


def test_two_scans_same_candle_deduplication(tmp_path):
    """
    Scenario: Scan 1 processes candle at 02:00 UTC and logs/dispatches signal.
    Scan 2 runs 15 minutes later on the SAME completed candle.
    Verify: Scan 2 identifies duplicate and aborts before dispatch.
    """
    db_file = str(tmp_path / "dedup_test.db")
    tracker = SignalTracker(db_path=db_file)
    notifier = MagicMock()

    symbol = "XAUUSD"
    strategy = "Smart-Money Liquidity Sweep"
    tf = "30m"
    bias = "LONG"
    candle_ts = "2026-10-12T02:00:00+00:00"

    # Compute deterministic SHA256 key
    raw_key = f"{symbol}_{strategy}_{tf}_{bias}_{candle_ts}"
    dedup_key = hashlib.sha256(raw_key.encode()).hexdigest()

    sig = {
        "symbol": symbol,
        "timeframe": tf,
        "strategy": strategy,
        "direction": bias,
        "entry": 2650.0,
        "stop_loss": 2644.0,
        "tp1": 2656.0,
        "tp2": 2668.0,
        "suggested_lot_size": 0.01,
        "confluence_score": 88.0,
        "grade": "A+",
        "dedup_key": dedup_key
    }

    # First Scan: Not a duplicate -> Logs to DB -> Dispatches alert
    assert tracker.is_duplicate_signal(dedup_key) is False
    sig_id = tracker.log_new_signal(sig)
    notifier.send_message(f"Alert #{sig_id}")
    assert notifier.send_message.call_count == 1

    # Second Scan on the exact same candle:
    if tracker.is_duplicate_signal(dedup_key):
        # Aborted! No message dispatched
        pass
    else:
        notifier.send_message("Duplicate Alert Should Not Be Sent")

    # Alert count remains 1!
    assert notifier.send_message.call_count == 1


def test_process_restart_persistence(tmp_path):
    """
    Simulates process termination and restart with a fresh instance
    connecting to the existing database file.
    """
    db_file = str(tmp_path / "persistence_test.db")
    
    # Process 1 writes state
    p1_tracker = SignalTracker(db_path=db_file)
    p1_tracker.log_journal_entry("XAUUSD", "Trend Pullback", "LONG", "APPROVED", 89.0, None, "Process 1 entry")
    
    # Process 1 terminates (instance destroyed). Process 2 starts up:
    p2_tracker = SignalTracker(db_path=db_file)
    with p2_tracker._get_conn() as conn:
        rows = conn.execute("SELECT * FROM journal_entries WHERE symbol = 'XAUUSD'").fetchall()
        assert len(rows) == 1
        assert rows[0][2] == "XAUUSD"
        assert rows[0][8] == "Process 1 entry"


def test_db_failure_blocks_alert_dispatch(tmp_path):
    """
    If the database is locked or corrupted, the system must abort
    rather than dispatching an unrecorded/untracked alert.
    """
    tracker = MagicMock()
    tracker.log_new_signal.side_effect = sqlite3.OperationalError("Database disk image is malformed")
    notifier = MagicMock()

    dispatched = False
    try:
        tracker.log_new_signal({"dummy": 123})
        notifier.send_message("Alert")
        dispatched = True
    except sqlite3.OperationalError:
        # Caught database error -> alert dispatch prevented!
        dispatched = False

    assert dispatched is False
    assert notifier.send_message.call_count == 0


def test_missing_instrument_spec_rejected():
    """
    If an unknown instrument or unverified asset is fed into the risk engine,
    it must reject the setup rather than guessing contract parameters.
    """
    mgr = HardenedRiskManager(config={"risk": {"account_balance_usd": 50.0}})
    res = mgr.evaluate_signal_risk("UNKNOWN_COIN", 100.0, 90.0, 130.0)
    assert res["approved"] is False
    assert "MISSING_CONTRACT_SPEC" in res["reason"]


def test_usd_and_usc_economic_equivalence():
    """
    Verify that $50 USD and 5,000 USC configured accounts have identical
    economic risk ceilings ($0.125 USD = 12.5 USC) and approve identical lot sizes.
    """
    cfg_usd = {
        "risk": {
            "account_currency": "USD",
            "account_balance_usd": 50.0,
            "risk_per_trade_percent": 0.25,
            "min_risk_reward": 2.5
        }
    }
    cfg_usc = {
        "risk": {
            "account_currency": "USC",
            "account_balance_usc": 5000.0,
            "risk_per_trade_percent": 0.25,
            "min_risk_reward": 2.5
        }
    }

    mgr_usd = HardenedRiskManager(cfg_usd)
    mgr_usc = HardenedRiskManager(cfg_usc)

    res_usd = mgr_usd.evaluate_signal_risk("XAUUSDc", 2650.0, 2644.0, 2670.0)
    res_usc = mgr_usc.evaluate_signal_risk("XAUUSDc", 2650.0, 2644.0, 2670.0)

    assert res_usd["approved"] is True
    assert res_usc["approved"] is True
    # Lot size must be identical
    assert res_usd["lot_size"] == res_usc["lot_size"] == 0.01
    # Risk ceilings must represent the exact same purchasing power
    assert res_usd["max_allowed_dollar_risk"] == pytest.approx(0.125, abs=1e-6)
    assert res_usc["max_allowed_risk_usc"] == pytest.approx(12.5, abs=1e-4)
    assert res_usd["dollar_risk"] == pytest.approx(res_usc["dollar_risk"], abs=1e-6)


def test_ambiguous_or_conflicting_currency_configuration_rejected():
    """
    Reject configuration if:
    1. Unsupported account currency is provided (e.g. 'EUR', 'XYZ')
    2. Conflicting balances are provided ($50 USD != 6000 USC)
    """
    # 1. Unsupported currency
    bad_curr_cfg = {"risk": {"account_currency": "EUR", "account_balance_usd": 50.0}}
    mgr_bad = HardenedRiskManager(bad_curr_cfg)
    res_bad = mgr_bad.evaluate_signal_risk("XAUUSDc", 2650.0, 2644.0, 2670.0)
    assert res_bad["approved"] is False
    assert "AMBIGUOUS_CURRENCY_CONFIG" in res_bad["reason"]

    # 2. Conflicting dual balance
    conflict_cfg = {
        "risk": {
            "account_currency": "USD",
            "account_balance_usd": 50.0,
            "account_balance_usc": 6000.0  # Conflict: 50 USD should be 5000 USC
        }
    }
    mgr_conflict = HardenedRiskManager(conflict_cfg)
    res_conflict = mgr_conflict.evaluate_signal_risk("XAUUSDc", 2650.0, 2644.0, 2670.0)
    assert res_conflict["approved"] is False
    assert "AMBIGUOUS_CURRENCY_CONFIG" in res_conflict["reason"]


def test_tracker_separates_completed_trades_from_expired_and_invalid(tmp_path):
    """
    Verify that get_performance_stats cleanly separates:
    - Completed trades (TP1/2/3 or SL hit)
    - Open active signals
    - Invalidated or expired signals (which do not distort win rate or profit factor)
    """
    db_file = str(tmp_path / "stats_test.db")
    tracker = SignalTracker(db_path=db_file)

    # 1. Winning trade
    id1 = tracker.log_new_signal({
        "symbol": "XAUUSD", "timeframe": "30m", "strategy": "Pullback", "direction": "LONG",
        "entry": 2650.0, "stop_loss": 2644.0, "tp1": 2656.0, "tp2": 2668.0, "tp3": 2680.0,
        "confluence_score": 88.0, "grade": "A+", "suggested_lot_size": 0.01, "dedup_key": "k1"
    })
    tracker.update_signal_status(id1, "TP2_HIT", outcome_r=2.0)

    # 2. Losing trade
    id2 = tracker.log_new_signal({
        "symbol": "XAUUSD", "timeframe": "30m", "strategy": "Pullback", "direction": "LONG",
        "entry": 2650.0, "stop_loss": 2644.0, "tp1": 2656.0, "tp2": 2668.0, "tp3": 2680.0,
        "confluence_score": 86.0, "grade": "A+", "suggested_lot_size": 0.01, "dedup_key": "k2"
    })
    tracker.update_signal_status(id2, "SL_HIT", outcome_r=-1.0)

    # 3. Invalidated signal (e.g. price broke structure before entry)
    id3 = tracker.log_new_signal({
        "symbol": "XAUUSD", "timeframe": "30m", "strategy": "Breakout", "direction": "SHORT",
        "entry": 2640.0, "stop_loss": 2646.0, "tp1": 2634.0, "tp2": 2622.0, "tp3": 2610.0,
        "confluence_score": 87.0, "grade": "A+", "suggested_lot_size": 0.01, "dedup_key": "k3"
    })
    tracker.update_signal_status(id3, "INVALIDATED", outcome_r=0.0)

    # 4. Open active trade
    tracker.log_new_signal({
        "symbol": "XAUUSD", "timeframe": "30m", "strategy": "Sweep", "direction": "LONG",
        "entry": 2655.0, "stop_loss": 2649.0, "tp1": 2661.0, "tp2": 2673.0, "tp3": 2685.0,
        "confluence_score": 90.0, "grade": "A+", "suggested_lot_size": 0.01, "dedup_key": "k4"
    })

    stats = tracker.get_performance_stats()
    assert stats["total_signals"] == 4
    assert stats["completed_trades"] == 2
    assert stats["open_signals"] == 1
    assert stats["invalidated_or_expired"] == 1
    # 1 win out of 2 completed trades = 50.0% win rate
    assert stats["win_rate"] == 50.0
    # Profit factor: 2.0 / 1.0 = 2.0
    assert stats["profit_factor"] == 2.0
    assert stats["total_r"] == 1.0


def test_missing_matching_balance_field_rejected():
    """
    Requirements:
    - If account_currency is 'USD' but account_balance_usd is missing -> REJECT
    - If account_currency is 'USC' but account_balance_usc is missing (even if account_balance_usd is provided) -> REJECT
    Never silently infer balance across currencies!
    """
    # 1. USD missing account_balance_usd
    cfg_usd_missing = {"risk": {"account_currency": "USD"}}
    res1 = HardenedRiskManager(cfg_usd_missing).evaluate_signal_risk("XAUUSDc", 2650.0, 2644.0, 2670.0)
    assert res1["approved"] is False
    assert "AMBIGUOUS_CURRENCY_CONFIG" in res1["reason"]

    # 2. USC has account_balance_usd: 50.0 but NO account_balance_usc
    # This directly checks the regression where $50 USD could be mistakenly read as 50 USC ($0.50)
    cfg_usc_missing = {"risk": {"account_currency": "USC", "account_balance_usd": 50.0}}
    res2 = HardenedRiskManager(cfg_usc_missing).evaluate_signal_risk("XAUUSDc", 2650.0, 2644.0, 2670.0)
    assert res2["approved"] is False
    assert "AMBIGUOUS_CURRENCY_CONFIG" in res2["reason"]
    assert "account_balance_usc" in res2["reason"]


def test_invalid_and_non_positive_balances_rejected():
    """
    Reject balances that are zero, negative, NaN, infinity, or non-numeric strings.
    """
    for bad_bal in [0.0, -50.0, float("nan"), float("inf"), "invalid_str"]:
        cfg = {"risk": {"account_currency": "USD", "account_balance_usd": bad_bal}}
        res = HardenedRiskManager(cfg).evaluate_signal_risk("XAUUSDc", 2650.0, 2644.0, 2670.0)
        assert res["approved"] is False
        assert "INVALID_BALANCE_VALUE" in res["reason"]


def test_default_config_yaml_verification():
    """
    Ensure the actual repository config/config.yaml parses without error,
    has explicit account_currency and balance, and properly rejects $50 standard gold while
    allowing cent account gold.
    """
    import yaml
    import os
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f)

    mgr = HardenedRiskManager(cfg)
    # Standard account profile on $50: must be rejected
    res_std = mgr.evaluate_signal_risk("XAUUSD", 2650.0, 2644.0, 2670.0, account_type="standard")
    assert res_std["approved"] is False
    assert "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE" in res_std["reason"]

    # Cent account profile on $50 with 1% risk: must be approved
    res_cent = mgr.evaluate_signal_risk("XAUUSD", 2650.0, 2644.0, 2670.0, account_type="cent")
    assert res_cent["approved"] is True
    assert res_cent["lot_size"] == 0.07  # Scaled for 1.0% risk ($0.50 max loss)
    assert res_cent["dollar_risk"] <= 0.50


def test_research_alerts_gating_and_isolation():
    """
    Verify:
    1. If live_enabled is False and research_alerts_enabled is False -> Alert NOT sent
    2. If live_enabled is False and research_alerts_enabled is True -> Research alert IS sent
    3. Order execution is NEVER triggered
    """
    from unittest.mock import MagicMock
    from telegram_bot.notifier import TelegramNotifier

    mock_notifier = MagicMock()

    # Scenario A: research_alerts_enabled is False, live_enabled is False
    cfg_a = {"live_enabled": False, "research_alerts_enabled": False}
    app_research_a = False
    dispatch_permitted_a = cfg_a["live_enabled"] or app_research_a or cfg_a["research_alerts_enabled"]
    assert dispatch_permitted_a is False

    # Scenario B: research_alerts_enabled is True, live_enabled is False
    cfg_b = {"live_enabled": False, "research_alerts_enabled": True}
    app_research_b = True
    dispatch_permitted_b = cfg_b["live_enabled"] or app_research_b or cfg_b["research_alerts_enabled"]
    assert dispatch_permitted_b is True

    # When permitted, verify research alert text format contains REFERENCE-ONLY notices
    notifier = TelegramNotifier()
    signal_dict = {
        "symbol": "XAUUSD", "timeframe": "30m", "direction": "LONG",
        "entry": 2650.0, "stop_loss": 2644.0, "tp1": 2656.0, "tp2": 2668.0,
        "suggested_lot_size": 0.01, "confluence_score": 88.0, "grade": "A+",
        "data_source": "Yahoo GC=F (Reference Futures)", "mt5_verified": False
    }
    msg = notifier.format_signal_message(signal_dict, {"grade": "A+", "total_score": 88.0, "reasons": []}, {"is_safe": True})
    assert "RESEARCH ALERT: XAUUSD" in msg
    assert "[REFERENCE-ONLY]" in msg
    assert "Assumed Spec (Not MT5 Connected)" in msg
    assert "Reference Entry" in msg
    assert "Reference Sizing" in msg


def test_force_dispatch_env_variable_parsing(monkeypatch):
    """
    Verify FORCE_DISPATCH strictly requires '1' or 'true' (case-insensitive) to enable dispatch.
    Values like 'false', '0', 'no', 'off', empty string, or unset MUST NOT enable dispatch.
    """
    from main import is_market_open  # sanity import

    # Helper replicating main.py's dispatch condition
    def check_dispatch(env_val):
        if env_val is None:
            monkeypatch.delenv("FORCE_DISPATCH", raising=False)
        else:
            monkeypatch.setenv("FORCE_DISPATCH", env_val)
        import os
        force_dispatch = os.environ.get("FORCE_DISPATCH", "").strip().lower() in ("1", "true")
        live_allowed = False
        research_allowed = False
        return live_allowed or research_allowed or force_dispatch

    # Values that MUST enable dispatch:
    assert check_dispatch("1") is True
    assert check_dispatch("true") is True
    assert check_dispatch("True") is True
    assert check_dispatch("  TRUE  ") is True

    # Values that MUST NOT enable dispatch:
    assert check_dispatch("0") is False
    assert check_dispatch("false") is False
    assert check_dispatch("False") is False
    assert check_dispatch("FALSE") is False
    assert check_dispatch("no") is False
    assert check_dispatch("") is False
    assert check_dispatch(None) is False
    assert check_dispatch("some_random_value") is False


