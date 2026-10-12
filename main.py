"""
Main Signal Scanning and Alerting Loop:
1. Evaluates market hours (skips weekends/rollover for Gold/Forex).
2. Fetches multi-timeframe candle data.
3. Computes 9-module confluence analysis & risk sizing.
4. Cross-checks high-impact news filter.
5. Generates annotated technical charts and optional Visual AI opinion.
6. Dispatches to Telegram and logs to SQLite tracker.
"""
import os
import yaml
import logging
from datetime import datetime, timezone
import pandas as pd

from data.provider import get_data_provider
from indicators.engine import calculate_all_indicators
from analysis.confluence import ConfluenceAnalyzer
from risk.manager import RiskManager
from news.calendar import NewsFilter
from visual_ai.chart import ChartGenerator
from visual_ai.reader import VisualAIReader
from tracking.tracker import SignalTracker
from telegram_bot.notifier import TelegramNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gold-signal-pro")


def is_market_open(symbol: str) -> bool:
    """Checks if global markets are open. Crypto (BTC) is 24/7."""
    if "BTC" in symbol:
        return True
    now = datetime.now(timezone.utc)
    # Weekend check: Saturday or Sunday before 22:00 UTC
    weekday = now.weekday()  # Monday is 0, Sunday is 6
    if weekday == 5:  # Saturday
        return False
    if weekday == 6 and now.hour < 22:  # Sunday before open
        return False
    if weekday == 4 and now.hour >= 22:  # Friday after close
        return False
    # Daily rollover window (21:00 - 22:15 UTC)
    if 21 <= now.hour < 22:
        return False
    return True


def run_cycle():
    config_path = os.path.join(os.path.dirname(__file__), "config", "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    from risk.hardened_manager import HardenedRiskManager
    from strategy.modules import ALL_STRATEGIES
    import hashlib

    provider = get_data_provider("yfinance")
    analyzer = ConfluenceAnalyzer(config)
    risk_mgr = RiskManager(config)
    hardened_risk = HardenedRiskManager(config)
    news_filter = NewsFilter(config)
    chart_gen = ChartGenerator()
    ai_reader = VisualAIReader()
    tracker = SignalTracker()
    notifier = TelegramNotifier()

    # Process any user commands sent via Telegram (/status, /signals, /learn, etc.)
    from telegram_bot.commands import TelegramCommandHandler
    cmd_handler = TelegramCommandHandler()
    cmd_handler.process_updates()

    # Advanced Institutional & Session Modules
    from analysis.ict_concepts import ICTEngine
    from analysis.fibonacci import FibonacciToolkit
    from sessions.watch_mode import SessionWatchManager
    ict_engine = ICTEngine()
    fib_toolkit = FibonacciToolkit()
    session_mgr = SessionWatchManager(config)

    # 0. Check Pre-Open Session Briefing (30-60m before Asia/London/NY open)
    upcoming_sess = session_mgr.get_upcoming_session()
    if upcoming_sess:
        logger.info(f"Session approaching: {upcoming_sess['session']} open in {upcoming_sess['minutes_left']}m. Preparing game plan.")

    instruments = config.get("instruments", {})
    entry_tf = config.get("timeframes", {}).get("entry", "30m")

    logger.info("Starting gold-signal-pro analysis cycle...")

    for sym_name, sym_info in instruments.items():
        if not is_market_open(sym_name):
            logger.info(f"Market currently closed for {sym_name}. Skipping cycle.")
            continue

        symbol_yf = sym_info.get("symbol_yf", "GC=F")
        try:
            # 1. Fetch Entry Timeframe & Validate Candles (Enforces closed candles, chronological order, non-stale)
            df_entry, data_meta = provider.fetch_ohlcv(symbol_yf, entry_tf, limit=300)
            if df_entry is None or df_entry.empty:
                logger.warning(f"No valid data returned for {sym_name} ({entry_tf}). Skipping.")
                continue

            df_entry_ind = calculate_all_indicators(df_entry)

            # 2. Confluence Analysis & Market Regime
            confluence = analyzer.calculate_confluence(df_entry_ind, sym_name)
            regime = confluence.get("regime", "TRENDING")
            total_score = confluence["total_score"]
            grade = confluence["grade"]
            logger.info(f"{sym_name} Analysis -> Score: {total_score} | Grade: {grade} | Regime: {regime} | Bias: {confluence['bias']}")

            # Check if live alerts are enabled or in test review
            live_allowed = sym_info.get("live_enabled", False)
            if not live_allowed:
                logger.info(f"{sym_name} live signals are locked by Quality Gate (Forward testing mode).")

            # 3. Evaluate 8 Modular Strategies
            strategy_candidate = None
            for strat in ALL_STRATEGIES:
                sig = strat.evaluate(df_entry_ind, sym_name, regime)
                if sig is not None:
                    strategy_candidate = sig
                    logger.info(f"Matched strategy module: '{strat.name}' for {sym_name} ({sig['direction']})")
                    break

            # If no specific modular strategy triggered, fallback to high-confluence baseline if Grade A+
            if strategy_candidate is None and confluence["is_tradeable"]:
                bias = confluence["bias"]
                curr_price = df_entry_ind.iloc[-1]["close"]
                atr = df_entry_ind.iloc[-1]["atr_14"]
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

            bias = strategy_candidate["direction"]
            entry = strategy_candidate["entry"]
            stop_loss = strategy_candidate["stop_loss"]
            tp1 = strategy_candidate["tp1"]
            tp2 = strategy_candidate["tp2"]
            tp3 = strategy_candidate.get("tp3", tp2)

            # 4. Hardened Risk & Position Sizing Gate ($50 / 0.25% ceiling check)
            sizing_res = hardened_risk.evaluate_signal_risk(sym_name, entry, stop_loss, tp2)
            if not sizing_res["approved"]:
                rejection_msg = f"RISK REJECTED: {sizing_res['reason']}"
                logger.warning(f"{sym_name} setup rejected by Hardened Risk Manager: {sizing_res['reason']}")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], bias, "RISK_REJECTED", total_score, sizing_res["reason"], str(sizing_res))
                continue

            # 5. News Calendar Filter (Fail-Closed)
            news_status = news_filter.check_news_status(sym_name)
            if not news_status["is_safe"]:
                logger.warning(f"Trade skipped due to news filter: {news_status['upcoming_event']}")
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], bias, "NEWS_BLOCKED", total_score, news_status.get("reason", "HIGH_IMPACT_NEWS"))
                continue

            # 6. Deduplication Check
            last_candle_time = str(df_entry_ind.index[-1])
            dedup_raw = f"{sym_name}_{strategy_candidate['strategy']}_{entry_tf}_{bias}_{last_candle_time}"
            dedup_key = hashlib.sha256(dedup_raw.encode()).hexdigest()

            if tracker.is_duplicate_signal(dedup_key):
                logger.info(f"Duplicate signal detected for {sym_name} (already alerted on this candle). Skipping.")
                continue

            # 7. Construct Final Signal Dict
            signal_dict = {
                "symbol": sym_name,
                "timeframe": entry_tf,
                "strategy": strategy_candidate["strategy"],
                "direction": bias,
                "entry": entry,
                "stop_loss": stop_loss,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "risk_reward_tp2": sizing_res["planned_rr"],
                "suggested_lot_size": sizing_res["lot_size"],
                "account_type": "Cent Account Mode (1 oz/lot)" if sizing_res.get("is_cent_account") else "Standard Account (100 oz/lot)",
                "confluence_score": total_score,
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

            # 10. Persist Signal to Tracker FIRST (Atomic gate: Prevents alert dispatch if duplicate or write fails)
            try:
                sig_id = tracker.log_new_signal(signal_dict, visual_res)
                tracker.log_journal_entry(sym_name, strategy_candidate["strategy"], bias, "APPROVED", total_score, None, f"RR: {sizing_res['planned_rr']}")
                logger.info(f"Successfully recorded Grade {grade} signal #{sig_id} for {sym_name} into tracker.")
            except Exception as dbe:
                logger.error(f"Database write failed for {sym_name}. Aborting alert dispatch to prevent unrecorded state: {dbe}")
                continue

            # 11. Dispatch Alert to Telegram (Only after database state is secured)
            msg_text = notifier.format_signal_message(signal_dict, confluence, news_status, visual_res)
            if live_allowed or os.environ.get("FORCE_DISPATCH"):
                notifier.send_photo(chart_path, caption=f"Chart Analysis: {sym_name} ({entry_tf})")
                notifier.send_message(msg_text)

        except Exception as e:
            logger.error(f"Error processing {sym_name}: {e}", exc_info=True)

    # Output rolling performance stats
    stats = tracker.get_performance_stats()
    logger.info(f"Tracker Status: {stats['summary']}")


if __name__ == "__main__":
    run_cycle()
