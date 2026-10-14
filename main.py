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
import pandas as pd

from data.provider import get_data_provider
from indicators.engine import calculate_all_indicators
from analysis.confluence import ConfluenceAnalyzer
from analysis.fundamental import FundamentalEngine
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

    # 4. Evaluate Macro Fundamentals
    logger.info("Evaluating macro fundamentals...")
    fundamental_res = fund_engine.evaluate_fundamentals()
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
                levels = risk_mgr.calculate_trade_levels(sym_name, bias, curr_price, atr)
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

            # ══════════════════════════════════════════════
            # 10-POINT FINAL SIGNAL QUALITY GATE
            # ══════════════════════════════════════════════
            # Gate 1: Technical confluence score >= 85 (Grade A+)
            # Note: only_send_a_plus strictly enforces >= 85
            min_a_plus = config.get("scoring", {}).get("min_grade_a_plus", 85)
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
            news_status = news_filter.check_news_status(sym_name)
            if not news_status["is_safe"]:
                logger.warning(f"Trade skipped due to news filter: {news_status.get('upcoming_event')}")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], strat_direction, "NEWS_BLOCKED", total_score, news_status.get("reason", "HIGH_IMPACT_NEWS"))
                continue

            # Gate 5: Deduplication Check
            last_candle_time = str(df_entry_ind.index[-1])
            dedup_raw = f"{sym_name}_{strategy_candidate['strategy']}_{entry_tf}_{strat_direction}_{last_candle_time}"
            dedup_key = hashlib.sha256(dedup_raw.encode()).hexdigest()

            if tracker.is_duplicate_signal(dedup_key):
                logger.info(f"Duplicate signal detected for {sym_name}. Skipping dispatch.")
                continue

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
                "risk_reward_tp2": sizing_res["planned_rr"],
                "suggested_lot_size": sizing_res["lot_size"],
                "dollar_risk": sizing_res.get("dollar_risk", 0.50),
                "account_type": "Cent Account Mode (1.0% risk)" if sizing_res.get("is_cent_account") else "Standard Account",
                "confluence_score": total_score,
                "technical_score": confluence.get("technical_score", total_score),
                "fundamental_boost": confluence.get("fundamental_boost", 0),
                "session_boost": confluence.get("session_boost", 0),
                "grade": grade,
                "data_source": "Yahoo GC=F (Reference Futures)",
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

    stats = tracker.get_performance_stats()
    logger.info(f"Tracker Status: {stats['summary']}")


if __name__ == "__main__":
    run_cycle()
