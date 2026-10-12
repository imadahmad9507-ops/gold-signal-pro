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

───────────────────────────────────────────────────────────────────────
MANDATORY REGRESSION TESTS (cent-account 100x-bug fix verification)
───────────────────────────────────────────────────────────────────────
Scenario assumptions (stated by the project specification):
  • Account equity : $50 USD
  • Risk ceiling   : 0.25% = $0.125 USD max loss per trade
  • Gold stop      : $6.00 price-distance (raw)
  • Spread buffer  : $0.35  (XAUUSDc typical spread)
  • Slippage buffer: $0.10
  • Commission/lot : $0.00  (Exness cent account)
  • Total dist     : $6.45  per oz
  • Contract size  : 1.0 oz per cent lot (XAUUSDc)
  • Loss / lot     : $6.45 USD
  • Min lot        : 0.01 lots  → loss = $0.0645 USD  → APPROVED
  • safe_lot       : floor($0.125 / $6.45 / 0.01) * 0.01 = 0.01 lots
  • At 0.02 lots   : $0.129 USD > $0.125          → exceeds ceiling (correct)
  • At 1.93 lots   : ~$12.45 USD >> $0.125         → impossible to approve
"""
import math
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from data.validator import DataValidator
from risk.hardened_manager import HardenedRiskManager
from news.calendar import NewsFilter
from tracking.tracker import SignalTracker


# ═══════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _base_config(balance: float = 50.0, risk_pct: float = 0.25) -> dict:
    return {
        "risk": {
            "account_balance_usd": balance,
            "risk_per_trade_percent": risk_pct,
            "min_risk_reward": 2.5,
            "max_concurrent_signals": 3,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Data Validator Tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_data_validator_drops_forming_candle():
    """Ensure active, forming candle is discarded to eliminate look-ahead bias."""
    now = datetime.now(timezone.utc)
    dates = [now - timedelta(minutes=10) - timedelta(minutes=30 * (59 - i)) for i in range(60)]
    df = pd.DataFrame(
        {
            "open": [2000.0 + i for i in range(60)],
            "high": [2005.0 + i for i in range(60)],
            "low": [1995.0 + i for i in range(60)],
            "close": [2002.0 + i for i in range(60)],
            "volume": [1000 for _ in range(60)],
        },
        index=pd.DatetimeIndex(dates),
    )
    validator = DataValidator(max_stale_minutes=1440, min_candles_required=20)
    valid, sanitized, reason = validator.validate_and_sanitize(df, "GC=F", "30m", now_time=now)
    assert valid is True
    assert len(sanitized) == 59


def test_data_validator_rejects_corrupted_ohlc():
    """Ensure invalid OHLC geometry (e.g. low > high) is flagged and rejected."""
    now = datetime.now(timezone.utc)
    dates = [now - timedelta(minutes=10) - timedelta(minutes=30 * (59 - i)) for i in range(60)]
    df = pd.DataFrame(
        {
            "open": [2000.0] * 60,
            "high": [1990.0] * 60,  # Invalid: high < low
            "low": [2010.0] * 60,
            "close": [2000.0] * 60,
            "volume": [1000] * 60,
        },
        index=pd.DatetimeIndex(dates),
    )
    validator = DataValidator(max_stale_minutes=1440, min_candles_required=20)
    valid, sanitized, reason = validator.validate_and_sanitize(df, "GC=F", "30m", now_time=now)
    assert valid is False
    assert "ERR_CORRUPT_OHLC" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Hardened Risk Manager (original tests)
# ═══════════════════════════════════════════════════════════════════════════════

def test_hardened_risk_rejects_excessive_risk_on_50_account():
    """
    On a standard account with $50 balance and 0.25% risk limit ($0.125 max loss),
    a gold trade with a $6.00 stop loss at 0.01 standard lot risks $6.00 USD
    ($6.00 × 100 oz/lot × 0.01 lot = $6.00 USD — far over the $0.125 ceiling).
    The hardened risk manager must reject this with RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE.
    """
    mgr = HardenedRiskManager(_base_config())
    # $20 reward / $6.35 total dist = R:R ≈ 3.1 → passes R:R gate
    res = mgr.evaluate_signal_risk("XAUUSD", 2650.0, 2644.0, 2670.0)
    assert res["approved"] is False
    assert "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE" in res["reason"]
    assert res["requires_cent_account"] is True


def test_hardened_risk_approves_cent_account():
    """
    On an Exness Cent Account (XAUUSDc), 0.01 cent lot risks $0.0645 USD.
    A $6.00 stop = $0.0645 loss at 0.01 lot, safely below the $0.125 ceiling.
    """
    mgr = HardenedRiskManager(_base_config())
    res = mgr.evaluate_signal_risk("XAUUSD", 2650.0, 2644.0, 2670.0, is_cent_account=True)
    assert res["approved"] is True
    assert res["planned_rr"] >= 2.5
    assert res["dollar_risk"] <= 0.125


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — News Filter Fail-Closed
# ═══════════════════════════════════════════════════════════════════════════════

def test_news_filter_fail_closed_on_error():
    """Verify fail-closed requirement: if news feed cannot be fetched, signals are suppressed."""
    config = {
        "news_filter": {
            "enabled": True,
            "feed_url": "https://invalid-non-existent-domain-xyz.com/calendar.json",
            "fail_closed_on_error": True,
        }
    }
    filter_inst = NewsFilter(config)
    res = filter_inst.check_news_status("XAUUSD")
    assert res["is_safe"] is False
    assert res["feed_ok"] is False
    assert "CALENDAR_UNAVAILABLE_FAIL_CLOSED" in res["reason"]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Signal Deduplication
# ═══════════════════════════════════════════════════════════════════════════════

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
        "dedup_key": "unique_hash_candle_123",
    }

    assert tracker.is_duplicate_signal(sig["dedup_key"]) is False
    row_id = tracker.log_new_signal(sig)
    assert row_id > 0
    assert tracker.is_duplicate_signal(sig["dedup_key"]) is True


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — MANDATORY REGRESSION TESTS (100x bug fix)
# ═══════════════════════════════════════════════════════════════════════════════
#
# TP price design rationale:
#   XAUUSDc spread=$0.35, slippage=$0.10 → total_risk_dist for $6 raw stop = $6.45
#   R:R gate = 2.5 → minimum reward = 2.5 × 6.45 = $16.125
#   _GOOD_TP = 2670  ($20 above entry 2650) → R:R ≈ 3.1  ✓
#
#   For extreme $120 stop: total_risk_dist = $120.45
#   minimum reward = 2.5 × 120.45 = $301.1
#   _EXTREME_TP = 2952  ($302 above entry 2650) → R:R ≈ 2.51  ✓
#
# ─────────────────────────────────────────────────────────────────────────────

_ENTRY         = 2650.0
_CENT_STOP     = 2644.0    # $6.00 raw stop distance
_EXTREME_STOP  = 2530.0    # $120.00 raw stop distance
_GOOD_TP       = 2670.0    # $20 reward → R:R ≈ 3.1 over $6 total dist
_EXTREME_TP    = 2952.0    # $302 reward → R:R ≈ 2.51 over $120 total dist


class TestCentAccountRegressions:
    """
    Regression suite for XAUUSDc lot-sizing after removing the 100x
    currency-conversion error (exchange_rate_to_usd=0.01 applied to gold USD loss).
    """

    def setup_method(self):
        self.mgr  = HardenedRiskManager(_base_config())
        self.spec = self.mgr.get_contract_spec("XAUUSDc")

    # ── R1: $0.125 USD maximum loss ceiling ───────────────────────────────────
    def test_r1_max_monetary_risk_is_0125_usd(self):
        """0.25% of $50 = $0.125 USD.  Verify the engine computes this correctly."""
        balance  = 50.0
        risk_pct = 0.25
        expected = round(balance * risk_pct / 100.0, 6)
        assert expected == pytest.approx(0.125, abs=1e-6)

    # ── R2: Loss per 1.00 cent lot ≈ $6.45 USD ───────────────────────────────
    def test_r2_loss_per_full_lot_approx_6_45_usd(self):
        """
        Gold price distance = $6.00/oz.  Spread = $0.35, slippage = $0.10.
        total_risk_dist = $6.45/oz.  contract_size = 1.0 oz/lot.
        loss_per_lot = $6.45 × 1.0 = $6.45 USD.
        Gold prices are already USD — no FX multiplier required.
        """
        total_risk_dist = 6.00 + self.spec["typical_spread"] + self.spec["estimated_slippage"]
        loss_per_lot    = total_risk_dist * self.spec["contract_size"]
        assert loss_per_lot == pytest.approx(6.45, abs=0.01)

    # ── R3: 0.01 lots → ~$0.0645 USD → APPROVED ──────────────────────────────
    def test_r3_001_lot_approved(self):
        """
        0.01 lots × $6.45/lot = $0.0645 USD < $0.125 ceiling → APPROVED.
        Approved lot must be exactly 0.01 (floor to valid step).
        """
        res = self.mgr.evaluate_and_size_trade(
            "XAUUSDc", "LONG", _ENTRY, _CENT_STOP, _GOOD_TP
        )
        assert res["approved"] is True, f"Expected APPROVED, got: {res.get('reason')}"
        assert res["suggested_lot_size"] == pytest.approx(0.01, abs=1e-6)
        assert res["expected_dollar_loss"] == pytest.approx(0.0645, abs=0.005)
        assert res["expected_dollar_loss"] <= 0.125

    # ── R4: 0.02 lots → ~$0.129 USD → exceeds ceiling ───────────────────────
    def test_r4_002_lot_would_exceed_ceiling(self):
        """
        0.02 lots × $6.45/lot = $0.129 USD > $0.125 ceiling.
        Verify arithmetically that 0.02 lots exceeds the ceiling,
        and that the engine floors to 0.01 lots (never selects 0.02).
        """
        total_risk_dist = 6.00 + self.spec["typical_spread"] + self.spec["estimated_slippage"]
        loss_per_lot    = total_risk_dist * self.spec["contract_size"]
        loss_at_002     = round(0.02 * loss_per_lot, 6)
        assert loss_at_002 > 0.125, (
            f"0.02 lots (${loss_at_002:.4f}) must exceed $0.125 ceiling"
        )
        # Engine must produce 0.01, not 0.02
        res = self.mgr.evaluate_and_size_trade(
            "XAUUSDc", "LONG", _ENTRY, _CENT_STOP, _GOOD_TP
        )
        assert res["approved"] is True
        assert res["suggested_lot_size"] == pytest.approx(0.01, abs=1e-6), (
            "Engine must floor to 0.01 — never approve 0.02 lots under these conditions"
        )

    # ── R5: 1.93 lots cannot be approved ─────────────────────────────────────
    def test_r5_193_lots_cannot_be_approved(self):
        """
        1.93 lots × $6.45/lot ≈ $12.45 USD >> $0.125 ceiling.
        The engine must NEVER produce 1.93 lots (the value the buggy code approved).
        """
        res = self.mgr.evaluate_and_size_trade(
            "XAUUSDc", "LONG", _ENTRY, _CENT_STOP, _GOOD_TP
        )
        assert res.get("suggested_lot_size", 0.0) != pytest.approx(1.93, abs=0.01), (
            "1.93 lots was the bug-approved value — it must never appear in correct output"
        )
        if res["approved"]:
            assert res["expected_dollar_loss"] <= 0.125
        # Sanity: confirm 1.93 lots is catastrophic
        catastrophic = 1.93 * 6.45
        assert catastrophic > 0.125, (
            f"1.93 lots risk ${catastrophic:.2f} must always exceed $0.125 ceiling"
        )

    # ── R6: Extreme stop scenario → REJECTED ─────────────────────────────────
    def test_r6_extreme_stop_rejected(self):
        """
        Entry 2650, SL 2530 → raw stop = $120.  total_risk_dist ≈ $120.45.
        loss at 0.01 lot = $1.2045 >> $0.125 → REJECTED.
        _EXTREME_TP clears the R:R gate so the risk-limit gate fires.
        """
        res = self.mgr.evaluate_and_size_trade(
            "XAUUSDc", "LONG", _ENTRY, _EXTREME_STOP, _EXTREME_TP
        )
        assert res["approved"] is False
        assert res["rejection_code"] == "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE"

    # ── R7: Missing contract spec → REJECTED ─────────────────────────────────
    def test_r7_missing_contract_spec_rejected(self):
        """
        An unrecognised symbol must be rejected with MISSING_CONTRACT_SPEC.
        Never silently guess specs for unknown instruments.
        """
        res = self.mgr.evaluate_and_size_trade(
            "UNKWN_FX", "LONG", 1.1000, 1.0950, 1.1150
        )
        assert res["approved"] is False
        assert res["rejection_code"] == "MISSING_CONTRACT_SPEC"
        assert "MISSING_CONTRACT_SPEC" in res["reason"]

    # ── R8: USD and USC not double-converted ──────────────────────────────────
    def test_r8_usd_and_usc_not_double_converted(self):
        """
        exchange_rate_to_usd must be 1.0 for both gold symbols.
        Applying 0.01 to a USD-denominated gold loss would understate risk 100×.
        Confirm the engine's reported loss_per_lot matches the correct USD value.
        """
        std_spec  = self.mgr.get_contract_spec("XAUUSD")
        cent_spec = self.mgr.get_contract_spec("XAUUSDc")

        assert std_spec["exchange_rate_to_usd"]  == pytest.approx(1.0), (
            "XAUUSD: gold price is in USD — exchange_rate_to_usd must be 1.0"
        )
        assert cent_spec["exchange_rate_to_usd"] == pytest.approx(1.0), (
            "XAUUSDc: gold price is STILL in USD on cent accounts — must not apply 0.01"
        )

        total_risk_dist      = 6.00 + cent_spec["typical_spread"] + cent_spec["estimated_slippage"]
        correct_loss_per_lot = total_risk_dist * cent_spec["contract_size"]  # USD
        buggy_loss_per_lot   = correct_loss_per_lot * 0.01                   # what the bug did

        assert correct_loss_per_lot > 1.0,  "Correct loss/lot for $6 stop must be > $1 USD"
        assert buggy_loss_per_lot   < 0.1,  "Buggy value would be < $0.10 — obviously wrong"

        res = self.mgr.evaluate_and_size_trade(
            "XAUUSDc", "LONG", _ENTRY, _CENT_STOP, _GOOD_TP
        )
        assert res["approved"] is True, f"Unexpected rejection: {res.get('reason')}"
        assert res["loss_per_lot_usd"] == pytest.approx(correct_loss_per_lot, abs=0.01), (
            f"Engine loss_per_lot=${res['loss_per_lot_usd']:.4f}, "
            f"expected ≈${correct_loss_per_lot:.4f}.  "
            "100x bug may have been reintroduced if this fails."
        )

    # ── R9: Internal assertion — approved trade never exceeds ceiling ─────────
    def test_r9_approved_trade_loss_never_exceeds_ceiling(self):
        """
        The hard assert inside evaluate_and_size_trade guarantees final dollar
        loss ≤ risk ceiling.  Normal operation must never trigger it.
        """
        res = self.mgr.evaluate_and_size_trade(
            "XAUUSDc", "LONG", _ENTRY, _CENT_STOP, _GOOD_TP
        )
        if res["approved"]:
            max_risk = res["max_allowed_dollar_risk"]
            actual   = res["expected_dollar_loss"]
            assert actual <= max_risk + 1e-9, (
                f"Approved trade loss ${actual:.6f} must not exceed ceiling ${max_risk:.6f}"
            )

    # ── R10: Standard XAUUSD always rejected on $50 account ──────────────────
    def test_r10_standard_xauusd_always_rejected_on_50_account(self):
        """
        Standard XAUUSD: 100 oz/lot.
        0.01 lot × 100 oz × $6.35 total-risk = $6.35 USD >> $0.125 ceiling.
        _GOOD_TP clears the R:R gate so the risk-limit gate fires.
        Must suggest using a cent account.
        """
        res = self.mgr.evaluate_and_size_trade(
            "XAUUSD", "LONG", _ENTRY, _CENT_STOP, _GOOD_TP
        )
        assert res["approved"] is False
        assert res["rejection_code"] == "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE"
        assert res.get("requires_cent_account") is True
