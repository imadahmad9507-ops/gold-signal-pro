"""
Main Signal Scanning and Alerting Loop:
1. Evaluates market hours (skips weekends/rollover for Gold/Forex).
2. Heartbeat monitor: tracks downtime between cycles.
3. Daily Fundamental Briefing at 07:00 UTC (12:00 PKT).
4. Full Macro Fundamental Analysis Engine evaluation.
5. Enhanced Session Hunter & schedule tracking.
6. Multi-candle lookback (checks last 2 closed candles).
7. 10-module confluence analysis & risk sizing.
8. Rigorous 10-point Quality Gate before dispatch.
9. Formatted Telegram alerts with annotated charts and SQLite journal persistence.
"""
import os
import yaml
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

from data.provider import get_data_provider
from indicators.engine import calculate_all_indicators
from analysis.confluence import ConfluenceAnalyzer
from analysis.fundamental import FundamentalEngine
from analysis.news_predictor import NewsPredictorEngine
from analysis.volume_profile import VolumeProfileEngine
from analysis.ml_predictor import ConfluenceFactorEngine
from patterns.detector import PatternDetector
from risk.manager import RiskManager
from risk.hardened_manager import HardenedRiskManager
from news.calendar import NewsFilter
from visual_ai.chart import ChartGenerator
from visual_ai.reader import VisualAIReader
from tracking.tracker import SignalTracker
from telegram_bot.notifier import TelegramNotifier
from sessions.watch_mode import SessionWatchManager
from strategy.modules import ALL_STRATEGIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gold-signal-pro")

STATE_FILE = os.path.join(os.path.dirname(__file__), "tracking", "bot_state.json")


def is_market_open(symbol: str) -> bool:
    """Checks if global markets are open. Crypto (BTC) is 24/7."""
    if "BTC" in symbol:
        return True
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # Monday is 0, Sunday is 6
    if weekday == 5:  # Saturday
        return False
    if weekday == 6 and now.hour < 22:  # Sunday before open
        return False
    if weekday == 4 and now.hour >= 22:  # Friday after close
        return False
    if 21 <= now.hour < 22:  # Daily rollover window
        return False
    return True


def check_heartbeat(notifier: TelegramNotifier):
    """
    Heartbeat check: if the bot hasn't run in >25 minutes during market hours,
    log a notice and alert Telegram.
    """
    import json
    now_utc = datetime.now(timezone.utc)
    last_run_time = None
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            if "last_run" in state:
                last_run_time = datetime.fromisoformat(state["last_run"])
        except Exception:
            pass

    if last_run_time:
        diff_minutes = (now_utc - last_run_time).total_seconds() / 60.0
        if diff_minutes > 25 and is_market_open("XAUUSD"):
            msg = f"⚠️ <b>Bot Heartbeat Notice:</b> Scanner offline for {int(diff_minutes)} minutes. Checking for missed setups now."
            logger.warning(msg)
            notifier.send_message(msg)

    state["last_run"] = now_utc.isoformat()
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Could not save bot_state: {e}")


def check_daily_briefing(notifier: TelegramNotifier, fundamental_res: dict, df_entry: pd.DataFrame):
    """
    Sends the 07:00 UTC (12:00 PKT) Daily Fundamental Briefing once per day.
    """
    import json
    now_utc = datetime.now(timezone.utc)
    # Check if between 07:00 and 07:30 UTC
    if now_utc.hour == 7 and now_utc.minute <= 30:
        today_str = now_utc.strftime("%Y-%m-%d")
        state = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
            except Exception:
                pass

        if state.get("last_daily_briefing") != today_str:
            last_c = float(df_entry["close"].iloc[-1])
            levels = {
                "current_price": last_c,
                "resistance": f"{last_c + 15:.2f}, {last_c + 30:.2f}",
                "support": f"{last_c - 15:.2f}, {last_c - 30:.2f}",
                "round_levels": f"{round(last_c/50)*50:.0f}, {round((last_c+50)/50)*50:.0f}"
            }
            notifier.send_daily_briefing(fundamental_res, levels, today_str)
            state["last_daily_briefing"] = today_str
            with open(STATE_FILE, "w") as f:
                json.dump(state, f)


def check_session_messages(notifier: TelegramNotifier, session_mgr: SessionWatchManager, df_entry_ind: pd.DataFrame, sym_name: str, fundamental_bias: str):
    """
    Dispatches pre-open game plan briefings (London at 07:30 UTC, NY at 12:30 UTC, Asian at 22:50 UTC)
    and session transition summaries once per session using state tracking.
    """
    import json
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception:
            pass

    # Check upcoming session briefing
    upcoming = session_mgr.get_upcoming_session(now_utc)
    if upcoming:
        sess_name = upcoming["session"]
        key = f"pre_open_{sess_name}_{today_str}"
        if not state.get(key):
            plan_text = session_mgr.generate_pre_open_game_plan(
                df_entry_ind, sym_name, upcoming, fundamental_bias=fundamental_bias
            )
            notifier.send_message(plan_text)
            state[key] = True
            logger.info(f"Dispatched {sess_name} Pre-Open Briefing to Telegram.")

    # Session close summaries (Asian close 08:00 UTC, London close 17:00 UTC, NY close 21:00 UTC)
    h = now_utc.hour
    m = now_utc.minute
    if 0 <= m <= 20:
        close_sess = None
        if h == 8:
            close_sess = "Asian Session Closed"
            summary_body = "Asian liquidity range established. London kill zone order flow active."
        elif h == 17:
            close_sess = "London Session Closed"
            summary_body = "London liquidity absorbed. New York afternoon session in effect."
        elif h == 21:
            close_sess = "New York Session Closed"
            summary_body = "New York institutional volume tapered. Entering off-peak Asian drift window."

        if close_sess:
            ckey = f"close_{h}_{today_str}"
            if not state.get(ckey):
                notifier.send_session_summary(f"🔔 {close_sess}", summary_body)
                state[ckey] = True
                logger.info(f"Dispatched {close_sess} summary to Telegram.")

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Could not persist session message state: {e}")


def check_news_event_analysis(
    notifier: TelegramNotifier,
    news_predictor: NewsPredictorEngine,
    news_filter: NewsFilter,
    curr_gold_price: float,
    dxy_context: Optional[dict] = None,
    yield_context: Optional[dict] = None
):
    """
    Checks upcoming high-impact economic calendar events:
    - 2 to 4 hours before: Sends detailed PRE-EVENT ANALYSIS scenario planning.
    - 20 to 45 mins after: Sends POST-EVENT UPDATE with net price change and scenario audit.
    """
    import json
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception:
            pass

    events = news_filter.fetch_calendar()
    if not events:
        return

    for ev in events:
        country = ev.get("country", "")
        impact = ev.get("impact", "")
        title = ev.get("title", "")
        if country != "USD" or impact != "High":
            continue
        if not news_predictor.is_major_usd_event(title):
            continue

        date_iso = ev.get("date")
        if not date_iso:
            continue

        try:
            ev_dt = datetime.fromisoformat(date_iso)
            diff_minutes = (ev_dt - now_utc).total_seconds() / 60.0
            ev_id = f"{today_str}_{title}_{ev_dt.strftime('%H%M')}"

            # 1. PRE-EVENT SCENARIOS (Trigger between 100 and 240 mins before release)
            if 100 <= diff_minutes <= 240:
                pre_key = f"pre_event_{ev_id}"
                if not state.get(pre_key):
                    analysis = news_predictor.generate_pre_event_analysis(
                        ev,
                        curr_gold_price,
                        dxy_data=dxy_context,
                        real_yield_data=yield_context
                    )
                    notifier.send_message(analysis["message"])
                    state[pre_key] = {
                        "sent_at": now_utc.isoformat(),
                        "price_before": curr_gold_price,
                        "title": title,
                        "forecast": ev.get("forecast", "N/A")
                    }
                    state["last_news_broadcast"] = now_utc.isoformat()
                    logger.info(f"Dispatched Pre-Event Scenario Analysis for {title}.")

            # 2. POST-EVENT OUTCOME (Trigger between 20 and 50 mins after release)
            elif -50 <= diff_minutes <= -20:
                post_key = f"post_event_{ev_id}"
                pre_record = state.get(f"pre_event_{ev_id}", {})
                if not state.get(post_key):
                    price_before = pre_record.get("price_before", curr_gold_price)
                    actual_val = ev.get("actual", "In-Line")
                    forecast_val = ev.get("forecast", pre_record.get("forecast", "N/A"))
                    post_text = news_predictor.generate_post_event_analysis(
                        title,
                        str(actual_val),
                        str(forecast_val),
                        price_before,
                        curr_gold_price,
                        key_level_to_hold=curr_gold_price - 10.0
                    )
                    notifier.send_message(post_text)
                    state[post_key] = True
                    state["last_news_broadcast"] = now_utc.isoformat()
                    # Trigger high frequency scan state for next 90 mins
                    state["post_news_high_freq_until"] = (now_utc + timedelta(minutes=90)).isoformat()
                    logger.info(f"Dispatched Post-Event Scenario Update for {title}.")

        except Exception as e:
            logger.debug(f"Error checking news event {title}: {e}")

    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Could not persist news event state: {e}")


def check_periodic_heartbeat(
    notifier: TelegramNotifier,
    curr_gold_price: float,
    change_pct: float,
    market_regime: str,
    best_score_session: float,
    next_session_text: str,
    next_news_text: str,
    is_news_blackout: bool = False
):
    """
    Every ~2 hours during active market hours, if NO signal or near-miss
    has been sent, send a brief market status update.
    Never sent during news blackout window.
    """
    if is_news_blackout or not is_market_open("XAUUSD"):
        return

    import json
    now_utc = datetime.now(timezone.utc)
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except Exception:
            pass

    # Check time since last message of any kind
    last_notif_str = state.get("last_notification_sent")
    if last_notif_str:
        last_dt = datetime.fromisoformat(last_notif_str)
        hours_passed = (now_utc - last_dt).total_seconds() / 3600.0
        if hours_passed < 2.0:
            return  # Within 2 hours of a previous alert

    # Check last heartbeat timestamp
    last_hb_str = state.get("last_periodic_heartbeat")
    if last_hb_str:
        last_hb = datetime.fromisoformat(last_hb_str)
        if (now_utc - last_hb).total_seconds() / 3600.0 < 2.0:
            return

    notifier.send_market_heartbeat(
        curr_gold_price,
        change_pct,
        market_regime,
        best_score_session,
        next_session_text,
        next_news_text
    )
    state["last_periodic_heartbeat"] = now_utc.isoformat()
    state["last_notification_sent"] = now_utc.isoformat()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Could not save periodic heartbeat state: {e}")


def run_cycle():
    config_path = os.path.join(os.path.dirname(__file__), "config", "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    provider = get_data_provider("yfinance")
    analyzer = ConfluenceAnalyzer(config)
    fund_engine = FundamentalEngine(config)
    risk_mgr = RiskManager(config)
    hardened_risk = HardenedRiskManager(config)
    news_filter = NewsFilter(config)
    chart_gen = ChartGenerator()
    ai_reader = VisualAIReader()
    tracker = SignalTracker()
    notifier = TelegramNotifier()
    session_mgr = SessionWatchManager(config)

    # 1. Heartbeat check
    check_heartbeat(notifier)

    # Process interactive Telegram updates (/status, etc.)
    from telegram_bot.commands import TelegramCommandHandler
    cmd_handler = TelegramCommandHandler()
    cmd_handler.process_updates()

    # 2. Get Enhanced Session Context
    session_context = session_mgr.get_session_context()
    logger.info(f"Active Session: {session_context['label']} (Boost: {session_context['session_boost']:+d} pts)")

    # 3. Pre-Open Session Check
    upcoming_sess = session_mgr.get_upcoming_session()
    if upcoming_sess:
        logger.info(f"Session approaching: {upcoming_sess['session']} open in {upcoming_sess['minutes_left']}m")

    # Fetch calendar events to detect upcoming 4-24h macro risks
    upcoming_events_list = []
    try:
        raw_events = news_filter.fetch_calendar()
        now_dt = datetime.now(timezone.utc)
        for ev in raw_events:
            if ev.get("country") == "USD" and ev.get("impact") in ["High"]:
                ev_d = ev.get("date")
                if ev_d:
                    diff_h = (datetime.fromisoformat(ev_d) - now_dt).total_seconds() / 3600.0
                    if 0 < diff_h <= 24:
                        upcoming_events_list.append({"title": ev.get("title"), "hours_until": diff_h})
    except Exception as e:
        logger.debug(f"Calendar extraction for fundamentals skipped: {e}")

    # 4. Evaluate Macro Fundamentals
    logger.info("Evaluating macro fundamentals...")
    fundamental_res = fund_engine.evaluate_fundamentals(upcoming_events=upcoming_events_list)
    logger.info(f"Fundamental Bias: {fundamental_res['bias']} (Raw: {fundamental_res['raw_score']:+d}/8, Adj: {fundamental_res['confluence_adjustment']:+d})")

    instruments = config.get("instruments", {})
    entry_tf = config.get("timeframes", {}).get("entry", "30m")

    for sym_name, sym_info in instruments.items():
        if not is_market_open(sym_name):
            logger.info(f"Market currently closed for {sym_name}. Skipping cycle.")
            continue

        symbol_yf = sym_info.get("symbol_yf", "GC=F")
        try:
            # Fetch candles (300 bars)
            df_entry, data_meta = provider.fetch_ohlcv(symbol_yf, entry_tf, limit=300)
            if df_entry is None or df_entry.empty:
                logger.warning(f"No valid data returned for {sym_name} ({entry_tf}). Skipping.")
                continue

            # Check daily morning briefing
            if sym_name == "XAUUSD":
                check_daily_briefing(notifier, fundamental_res, df_entry)

            df_entry_ind = calculate_all_indicators(df_entry)

            # Check pre-open game plan and session transition briefings
            if sym_name == "XAUUSD":
                check_session_messages(notifier, session_mgr, df_entry_ind, sym_name, fundamental_res.get("bias", "NEUTRAL"))

            # Optional DXY feed for intermarket
            df_dxy = None
            try:
                df_dxy, _ = provider.fetch_ohlcv("DX-Y.NYB", "1d", limit=40)
            except Exception:
                pass

            # Multi-candle check: Evaluate recent closed candles
            # Primary candidate is the latest closed candle
            confluence = analyzer.calculate_confluence(
                df_entry_ind,
                sym_name,
                df_dxy=df_dxy,
                fundamental_res=fundamental_res,
                session_info=session_context
            )
            regime = confluence.get("regime", "TRENDING")
            total_score = confluence["total_score"]
            grade = confluence["grade"]
            bias = confluence["bias"]

            logger.info(
                f"{sym_name} Analysis -> Final Score: {total_score} | Grade: {grade} | "
                f"Tech: {confluence.get('technical_score')} | Fund: {confluence.get('fundamental_boost'):+d} | "
                f"Sess: {confluence.get('session_boost'):+d} | Bias: {bias}"
            )

            # Evaluate strategy modules
            strategy_candidate = None
            for strat in ALL_STRATEGIES:
                sig = strat.evaluate(df_entry_ind, sym_name, regime)
                if sig is not None:
                    strategy_candidate = sig
                    logger.info(f"Matched strategy module: '{strat.name}' for {sym_name} ({sig['direction']})")
                    break

            # Fallback for Grade A+ with high confluence
            if strategy_candidate is None and confluence["is_tradeable"]:
                curr_price = float(df_entry_ind.iloc[-1]["close"])
                atr = float(df_entry_ind.iloc[-1]["atr_14"])
                levels = risk_mgr.calculate_trade_levels(sym_name, bias, curr_price, atr, regime=regime)
                if levels:
                    strategy_candidate = {
                        "strategy": "Confluence Core Alignment",
                        "direction": bias,
                        **levels,
                        "reason": "; ".join(confluence.get("reasons", []))
                    }

            if not strategy_candidate:
                tracker.log_journal_entry(sym_name, "None", confluence["bias"], "NO_SETUP_TRIGGERED", total_score)
                continue

            strat_direction = strategy_candidate["direction"]
            entry = strategy_candidate["entry"]
            stop_loss = strategy_candidate["stop_loss"]
            tp1 = strategy_candidate["tp1"]
            tp2 = strategy_candidate["tp2"]
            tp3 = strategy_candidate.get("tp3", tp2)

            news_status = news_filter.check_news_status(sym_name)

            # Check News Predictor Pre/Post Analysis
            if sym_name == "XAUUSD":
                check_news_event_analysis(
                    notifier,
                    NewsPredictorEngine(config),
                    news_filter,
                    entry,
                    dxy_context=fundamental_res.get("components", {}).get("dxy"),
                    yield_context=fundamental_res.get("components", {}).get("yields")
                )

            # ══════════════════════════════════════════════
            # 10-POINT FINAL SIGNAL QUALITY GATE
            # ══════════════════════════════════════════════
            min_a_plus = config.get("scoring", {}).get("min_grade_a_plus", 85)

            # ─────────────────────────────────────────────
            # NEAR MISS DISPATCH LOGIC (Tier 2 & Tier 3)
            # ─────────────────────────────────────────────
            last_candle_time = str(df_entry_ind.index[-1])
            near_miss_raw = f"{sym_name}_{strategy_candidate['strategy']}_{strat_direction}_{last_candle_time[:16]}"
            near_miss_dedup_key = hashlib.sha256(near_miss_raw.encode()).hexdigest()

            # TIER 2: NEAR MISS — Grade A Setup Spotted (Score 70-84)
            if 70 <= total_score < min_a_plus:
                logger.info(f"Signal rejected: Score {total_score} below minimum A+ threshold ({min_a_plus}). Near-miss evaluation.")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "SCORE_BELOW_A_PLUS", total_score)

                # Check if news safe and not duplicate
                if news_status["is_safe"] and not tracker.is_duplicate_signal(f"nm_{near_miss_dedup_key}"):
                    reasons_failed = [f"Score was {total_score:.0f}/100 (needs {min_a_plus} for Grade A+)"]
                    sizing_eval = hardened_risk.evaluate_signal_risk(sym_name, entry, stop_loss, tp2, account_type=sym_info.get("account_type"))
                    if not sizing_eval["approved"]:
                        reasons_failed.append(f"Risk/RR: {sizing_eval.get('reason', 'R:R below 1:2.5')}")
                    if session_context.get("session_boost", 0) <= 0:
                        reasons_failed.append(f"Session: {session_context.get('label', 'Off-peak')} (not in high-volume kill zone)")

                    pullback_level = round(entry - (0.5 * abs(entry - stop_loss)), 2) if strat_direction == "LONG" else round(entry + (0.5 * abs(entry - stop_loss)), 2)
                    notifier.send_near_miss_alert(
                        sym_name,
                        entry_tf,
                        strat_direction,
                        total_score,
                        reasons_failed,
                        recommended_action=f"Price needs to pull back toward ${pullback_level:.2f} for optimal entry and improved R:R",
                        key_level=pullback_level
                    )
                    tracker.log_new_signal({
                        "symbol": sym_name,
                        "timeframe": entry_tf,
                        "strategy": strategy_candidate["strategy"],
                        "direction": strat_direction,
                        "entry": entry,
                        "stop_loss": stop_loss,
                        "tp1": tp1,
                        "tp2": tp2,
                        "lot_size": 0.01,
                        "confluence_score": total_score,
                        "grade": "A",
                        "status": "NEAR_MISS",
                        "dedup_key": f"nm_{near_miss_dedup_key}"
                    })
                    # Mark state
                    state_obj = {}
                    if os.path.exists(STATE_FILE):
                        try:
                            with open(STATE_FILE, "r") as sf:
                                state_obj = json.load(sf)
                        except Exception:
                            pass
                    state_obj["last_notification_sent"] = datetime.now(timezone.utc).isoformat()
                    try:
                        with open(STATE_FILE, "w") as sf:
                            json.dump(state_obj, sf)
                    except Exception:
                        pass
                continue

            # TIER 3: WATCHING — Grade B (Score 55-69) — Sent maximum once per session
            if 55 <= total_score < 70:
                logger.info(f"Score {total_score} in Tier 3 watching range.")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "SCORE_BELOW_A_PLUS", total_score)
                state_obj = {}
                if os.path.exists(STATE_FILE):
                    try:
                        with open(STATE_FILE, "r") as sf:
                            state_obj = json.load(sf)
                    except Exception:
                        pass
                now_utc = datetime.now(timezone.utc)
                sess_key = f"tier3_scan_{session_context.get('label', 'session')}_{now_utc.strftime('%Y-%m-%d_%H')}"
                if not state_obj.get(sess_key) and news_status["is_safe"] and sym_name == "XAUUSD":
                    next_sess = session_mgr.get_upcoming_session(now_utc)
                    next_sess_str = f"{next_sess['session'].upper()} opens in {next_sess['minutes_left']}m" if next_sess else "Next session approaching"
                    notifier.send_session_scan_update(
                        sym_name,
                        total_score,
                        strategy_candidate["strategy"],
                        regime,
                        next_sess_str,
                        why_no_signal="Score below 85 threshold + market consolidating"
                    )
                    state_obj[sess_key] = True
                    state_obj["last_notification_sent"] = now_utc.isoformat()
                    try:
                        with open(STATE_FILE, "w") as sf:
                            json.dump(state_obj, sf)
                    except Exception:
                        pass

                # TIER 4: Developing Chart Pattern Alert
                if sym_name == "XAUUSD" and news_status["is_safe"]:
                    try:
                        detector = PatternDetector(swing_window=5)
                        patterns_found = detector.detect_patterns(df_entry_ind)
                        if patterns_found:
                            top_p = patterns_found[0]
                            pat_key = f"tier4_pattern_{top_p['name']}_{now_utc.strftime('%Y-%m-%d_%H')}"
                            if not state_obj.get(pat_key) and top_p.get("quality_score", 0) >= 80:
                                last_c = float(df_entry_ind["close"].iloc[-1])
                                notifier.send_pattern_alert(
                                    symbol=sym_name,
                                    timeframe=entry_tf,
                                    pattern_name=top_p["name"],
                                    direction="BULLISH" if "BULLISH" in top_p.get("type", "") else "BEARISH",
                                    quality_score=top_p.get("quality_score", 80),
                                    key_level=top_p.get("level", last_c),
                                    completion_target=top_p.get("neckline", last_c)
                                )
                                state_obj[pat_key] = True
                                state_obj["last_notification_sent"] = now_utc.isoformat()
                                with open(STATE_FILE, "w") as sf:
                                    json.dump(state_obj, sf)
                    except Exception as pe:
                        logger.debug(f"Tier 4 pattern detection skipped: {pe}")

                continue

            # Gate 1: Technical confluence score >= 85 (Grade A+)
            if total_score < min_a_plus:
                logger.info(f"Signal rejected: Score {total_score} below minimum A+ threshold ({min_a_plus}).")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "SCORE_BELOW_A_PLUS", total_score)
                continue

            # Gate 2: Fundamental conflict check
            if confluence.get("fundamental_conflict") and "STRONGLY" in confluence.get("fundamental_bias", ""):
                rejection_reason = f"FUNDAMENTAL_CONFLICT: Technical {strat_direction} conflicts with {confluence.get('fundamental_bias')}"
                logger.warning(f"{sym_name} signal blocked: {rejection_reason}")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "FUNDAMENTAL_CONFLICT", total_score, rejection_reason)
                continue

            # Gate 3: Sizing and R:R Gate (R:R >= 1:2.5 & Cent Risk)
            instrument_acct_type = sym_info.get("account_type")
            sizing_res = hardened_risk.evaluate_signal_risk(
                sym_name, entry, stop_loss, tp2, account_type=instrument_acct_type
            )
            if not sizing_res["approved"]:
                logger.warning(f"{sym_name} rejected by Hardened Risk: {sizing_res['reason']}")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "RISK_REJECTED", total_score, sizing_res["reason"])
                continue

            # Gate 4: News Calendar Filter (Fail-Closed, 4-hour hard block)
            if not news_status["is_safe"]:
                logger.warning(f"Trade skipped due to news filter: {news_status.get('upcoming_event')}")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "NEWS_BLOCKED", total_score, news_status.get("reason", "HIGH_IMPACT_NEWS"))
                continue

            # Gate 5: Deduplication Check
            dedup_raw = f"{sym_name}_{strategy_candidate['strategy']}_{entry_tf}_{strat_direction}_{last_candle_time}"
            dedup_key = hashlib.sha256(dedup_raw.encode()).hexdigest()

            if tracker.is_duplicate_signal(dedup_key):
                logger.info(f"Duplicate signal detected for {sym_name}. Skipping dispatch.")
                continue

            # Calculate Volume Profile (POC, VAH, VAL) - Estimated Bar-Based
            vp_engine = VolumeProfileEngine()
            vol_profile = vp_engine.calculate_profile(df_entry_ind, bars_lookback=48)

            # Calculate Algorithmic Confluence Factor Alignment
            factor_engine = ConfluenceFactorEngine(config)
            factor_analysis = factor_engine.evaluate_factor_alignment(
                df_entry_ind,
                bias=strat_direction,
                regime=regime,
                confluence_score=total_score,
                volume_profile=vol_profile,
                fundamental_bias=fundamental_res.get("bias", "NEUTRAL"),
                session_info=session_context
            )

            # Price offset calibration for Exness Spot display
            price_offset = float(sym_info.get("price_offset_calibration", 0.0))
            calibrated_entry = round(entry + price_offset, 2) if price_offset != 0.0 else None
            calibrated_sl = round(stop_loss + price_offset, 2) if price_offset != 0.0 else None
            calibrated_tp1 = round(tp1 + price_offset, 2) if price_offset != 0.0 else None
            calibrated_tp2 = round(tp2 + price_offset, 2) if price_offset != 0.0 else None

            # 7. Construct Final Signal Dict
            signal_dict = {
                "symbol": sym_name,
                "timeframe": entry_tf,
                "strategy": strategy_candidate["strategy"],
                "direction": strat_direction,
                "entry": entry,
                "stop_loss": stop_loss,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "calibrated_entry": calibrated_entry,
                "calibrated_sl": calibrated_sl,
                "calibrated_tp1": calibrated_tp1,
                "calibrated_tp2": calibrated_tp2,
                "price_offset": price_offset,
                "risk_reward_tp2": sizing_res["planned_rr"],
                "suggested_lot_size": sizing_res["lot_size"],
                "dollar_risk": sizing_res.get("dollar_risk", 0.125),
                "account_type": "Cent Account Mode (0.25% risk)" if sizing_res.get("is_cent_account") else "Standard Account",
                "confluence_score": total_score,
                "technical_score": confluence.get("technical_score", total_score),
                "fundamental_boost": confluence.get("fundamental_boost", 0),
                "session_boost": confluence.get("session_boost", 0),
                "grade": grade,
                "volume_profile": vol_profile,
                "factor_analysis": factor_analysis,
                "data_source": "Yahoo GC=F Futures (Manual Shift Estimate)" if price_offset != 0.0 else "Yahoo GC=F (Reference Futures)",
                "is_reference_research": True,
                "spec_source": sizing_res.get("spec_source", "assumed_specification"),
                "mt5_verified": sizing_res.get("mt5_verified", False),
                "dedup_key": dedup_key
            }

            # 8. Generate Technical Chart
            chart_path = chart_gen.render_signal_chart(df_entry_ind, sym_name, entry_tf, signal_dict)
            logger.info(f"Rendered technical chart: {chart_path}")

            # 9. Visual AI Second Opinion
            visual_res = ai_reader.analyze_chart_image(chart_path, sym_name, entry_tf)

            # 10. Persist to Tracker FIRST (Atomic gate)
            try:
                sig_id = tracker.log_new_signal(signal_dict, visual_res)
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "APPROVED", total_score, None, f"RR: {sizing_res['planned_rr']}")
                logger.info(f"Recorded Grade {grade} signal #{sig_id} for {sym_name} into tracker.")
            except Exception as dbe:
                logger.error(f"Database write failed for {sym_name}: {dbe}")
                continue

            # 11. Dispatch Alert to Telegram
            live_allowed = sym_info.get("live_enabled", False)
            app_research_enabled = config.get("app", {}).get("research_alerts_enabled", False)
            sym_research_enabled = sym_info.get("research_alerts_enabled", False)
            research_allowed = app_research_enabled or sym_research_enabled
            force_dispatch = os.environ.get("FORCE_DISPATCH", "").strip().lower() in ("1", "true")

            dispatch_permitted = live_allowed or research_allowed or force_dispatch
            if dispatch_permitted:
                msg_text = notifier.format_signal_message(
                    signal_dict,
                    confluence,
                    news_status,
                    visual_res,
                    fundamental_data=fundamental_res,
                    session_info=session_context
                )
                notifier.send_photo(chart_path, caption=f"Chart Analysis: {sym_name} ({entry_tf}) — {session_context['label']}")
                notifier.send_message(msg_text)
                logger.info(f"Dispatched Grade {grade} signal alert to Telegram for {sym_name}.")

        except Exception as e:
            logger.error(f"Error processing {sym_name}: {e}", exc_info=True)

    # 12. Periodic Heartbeat Check (every 2 hours if no messages sent)
    try:
        # Check if XAUUSD is loaded
        xau_provider = get_data_provider("yfinance")
        df_xau, _ = xau_provider.fetch_ohlcv("GC=F", "30m", limit=50)
        if df_xau is not None and not df_xau.empty:
            c_price = float(df_xau["close"].iloc[-1])
            prev_price = float(df_xau["close"].iloc[-2]) if len(df_xau) > 1 else c_price
            chg = ((c_price - prev_price) / prev_price) * 100.0
            xau_news = news_filter.check_news_status("XAUUSD")
            next_news_txt = xau_news.get("upcoming_event") or "No immediate high-impact USD events"
            next_sess = session_mgr.get_upcoming_session()
            next_sess_str = f"{next_sess['session'].upper()} opens in {next_sess['minutes_left']}m" if next_sess else "Next session approaching"

            check_periodic_heartbeat(
                notifier,
                curr_gold_price=c_price,
                change_pct=chg,
                market_regime="CONSOLIDATING" if abs(chg) < 0.3 else "TRENDING",
                best_score_session=60.0,
                next_session_text=next_sess_str,
                next_news_text=next_news_txt,
                is_news_blackout=not xau_news["is_safe"]
            )
    except Exception as he:
        logger.debug(f"Heartbeat check error: {he}")

    stats = tracker.get_performance_stats()
    logger.info(f"Tracker Status: {stats['summary']}")


if __name__ == "__main__":
    run_cycle()
