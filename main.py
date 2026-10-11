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

    provider = get_data_provider("yfinance")
    analyzer = ConfluenceAnalyzer(config)
    risk_mgr = RiskManager(config)
    news_filter = NewsFilter(config)
    chart_gen = ChartGenerator()
    ai_reader = VisualAIReader()
    tracker = SignalTracker()
    notifier = TelegramNotifier()

    instruments = config.get("instruments", {})
    entry_tf = config.get("timeframes", {}).get("entry", "30m")

    logger.info("Starting gold-signal-pro analysis cycle...")

    for sym_name, sym_info in instruments.items():
        if not is_market_open(sym_name):
            logger.info(f"Market currently closed for {sym_name}. Skipping cycle.")
            continue

        symbol_yf = sym_info.get("symbol_yf", "GC=F")
        try:
            # 1. Fetch Entry Timeframe
            df_entry = provider.fetch_ohlcv(symbol_yf, entry_tf, limit=300)
            df_entry_ind = calculate_all_indicators(df_entry)

            # 2. Confluence Analysis
            confluence = analyzer.calculate_confluence(df_entry_ind, sym_name)
            logger.info(f"{sym_name} Analysis -> Score: {confluence['total_score']} | Grade: {confluence['grade']} | Bias: {confluence['bias']}")

            # Check if live alerts are enabled or in test review
            live_allowed = sym_info.get("live_enabled", False)
            if not live_allowed:
                logger.info(f"{sym_name} live signals are locked by Quality Gate (Forward testing mode).")

            if confluence["is_tradeable"]:
                bias = confluence["bias"]
                curr_price = df_entry_ind.iloc[-1]["close"]
                atr = df_entry_ind.iloc[-1]["atr_14"]
                
                levels = risk_mgr.calculate_trade_levels(sym_name, bias, curr_price, atr)
                if not levels:
                    logger.info(f"Risk filter rejected setup for {sym_name} (Spread or R:R constraint).")
                    continue

                signal_dict = {
                    "symbol": sym_name,
                    "timeframe": entry_tf,
                    "direction": bias,
                    **levels,
                    "confluence_score": confluence["total_score"],
                    "grade": confluence["grade"]
                }

                # 3. News Check
                news_status = news_filter.check_news_status(sym_name)
                if not news_status["is_safe"]:
                    logger.warning(f"Trade skipped due to imminent high impact news: {news_status['upcoming_event']}")
                    continue

                # 4. Generate Chart Image
                chart_path = chart_gen.render_signal_chart(df_entry_ind, sym_name, entry_tf, signal_dict)
                logger.info(f"Rendered technical chart: {chart_path}")

                # 5. Visual AI Second Opinion
                visual_res = ai_reader.analyze_chart_image(chart_path, sym_name, entry_tf)

                # 6. Dispatch Alert to Telegram
                msg_text = notifier.format_signal_message(signal_dict, confluence, news_status, visual_res)
                if live_allowed or os.environ.get("FORCE_DISPATCH"):
                    notifier.send_photo(chart_path, caption=f"Chart Analysis: {sym_name} ({entry_tf})")
                    notifier.send_message(msg_text)

                # 7. Log to SQLite Tracker
                tracker.log_new_signal(signal_dict, visual_res)
                logger.info(f"Successfully recorded signal for {sym_name} into tracker.")

        except Exception as e:
            logger.error(f"Error processing {sym_name}: {e}", exc_info=True)

    # Output rolling performance stats
    stats = tracker.get_performance_stats()
    logger.info(f"Tracker Status: {stats['summary']}")


if __name__ == "__main__":
    run_cycle()
