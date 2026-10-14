"""
Demo A+ Alert Sender — Gold Signal Pro
Sends a realistic A+ signal preview to Telegram incorporating:
- Complete enhanced message format
- Fundamental context section (Real yields, DXY, Fear & Greed, ETF flows, VIX, News)
- Session hunter context (London-NY Overlap, Pakistan Time PKT)
- Probabilistic heuristic win score
"""

import os
from datetime import datetime, timezone
from telegram_bot.notifier import TelegramNotifier


def build_demo_signal():
    """Realistic A+ long signal on gold — demonstration only."""
    return {
        "symbol": "XAUUSD",
        "timeframe": "30M",
        "direction": "LONG",
        "entry": 2650.0,
        "stop_loss": 2639.0,
        "tp1": 2661.0,
        "tp2": 2672.0,
        "tp3": 2688.0,
        "risk_reward_tp2": 3.3,
        "suggested_lot_size": 0.05,
        "dollar_risk": 0.50,
        "strategy": "SMC Demand Zone + Judas Swing Reclamation",
        "data_source": "Yahoo GC=F (Reference Futures)",
        "account_type": "Cent Account Mode (1.0% risk | ~50 USC risk)",
        "mt5_verified": False,
    }


def build_demo_confluence():
    """Realistic A+ confluence breakdown."""
    return {
        "grade": "A+",
        "total_score": 91.0,
        "technical_score": 79.0,
        "fundamental_boost": 8,
        "session_boost": 8,
        "fundamental_bias": "BULLISH",
        "fundamental_conflict": False,
        "reasons": [
            "• Trend: Bullish trend alignment across EMAs, Supertrend, and HTF (ADX: 28.5)",
            "• Structure: Bullish Break of Structure (BOS) closed above 20-bar high",
            "• Momentum: RSI curling up (54.2); MACD histogram bullish momentum",
            "• Levels: Bullish Order Block 2640–2648 respected (OTE 68.5% Fib)",
            "• Candlestick: Hammer / Pin bar rejection candle confirmed at support",
            "• Intermarket: DXY softening below short-term trend, confirming gold tailwind",
            "• Session & Regime: London / New York Overlap (peak liquidity & volume) (TRENDING)",
        ],
    }


def build_demo_fundamentals():
    return {
        "raw_score": 5,
        "bias": "BULLISH",
        "components": {
            "yields": {"details": "Bullish (10Y yield: 4.12%, real yield ~-0.3%)", "fed_stance": "Dovish lean"},
            "dxy": {"details": "Bullish gold (level: 101.8, trend: DOWN, -0.6% this week)"},
            "fear_and_greed": {"details": "31 (Fear) -> Bullish gold safe-haven demand"},
            "etf": {"details": "Institutional Accumulation (GLD Volume +15%, Price Rising)"},
            "vix": {"details": "Elevated Risk (VIX 24.3) -> Safe-haven demand"},
            "news": {"details": "Mildly bullish (rate cut expectations headlines)"}
        }
    }


def build_demo_session():
    return {
        "label": "London-NY Overlap (13:00-17:00 UTC = 18:00-22:00 PKT)",
        "priority_tag": "⭐ PEAK WINDOW (London-NY Overlap)",
        "session_boost": 8,
        "is_peak": True
    }


def build_demo_news():
    """Clear news window — safe to trade."""
    return {
        "is_safe": True,
        "active_warning": False,
        "upcoming_event": None,
    }


def send_demo_alert():
    notifier = TelegramNotifier()

    if not notifier.is_configured():
        print("❌ No Telegram credentials found.")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.")
        return False

    signal = build_demo_signal()
    confluence = build_demo_confluence()
    news = build_demo_news()
    fund = build_demo_fundamentals()
    sess = build_demo_session()

    # Format exactly as the real pipeline does
    full_message = notifier.format_signal_message(
        signal,
        confluence,
        news,
        fundamental_data=fund,
        session_info=sess
    )

    print("Sending enhanced demo A+ alert to Telegram...")
    success = notifier.send_message(full_message)

    if success:
        print("✅ Demo A+ alert sent! Check your Telegram now.")
    else:
        print("❌ Failed to send. Check token/chat_id and network.")

    return success


if __name__ == "__main__":
    ok = send_demo_alert()
    exit(0 if ok else 1)
