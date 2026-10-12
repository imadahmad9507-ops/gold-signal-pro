"""
Demo A+ Alert Sender — Gold Signal Pro
Sends a realistic A+ signal preview to Telegram so you can see EXACTLY what
arrives when a real Grade A+ setup is detected by the live scanner.

Usage:
    python send_demo_alert.py

The signal values below are realistic but synthetic — this is a demonstration
of what the full pipeline sends. The bot automatically sends this same format
when real market conditions score ≥85 and R:R ≥ 1:2.5.
"""

import os
from datetime import datetime, timezone
from telegram_bot.notifier import TelegramNotifier


def build_demo_signal():
    """Realistic A+ long signal on gold — demonstration only."""
    return {
        "symbol": "XAUUSD",
        "timeframe": "H1",
        "direction": "LONG",
        "entry": 2648.50,
        "stop_loss": 2638.20,
        "tp1": 2658.80,
        "tp2": 2669.10,
        "tp3": 2684.50,
        "risk_reward_tp2": 2.58,
        "suggested_lot_size": 0.01,
        "strategy": "SMC Demand Zone + H4 OB Confluence",
        "data_source": "Yahoo GC=F (Reference Futures) [DEMO PREVIEW]",
        "account_type": "Cent Account XAUUSDc (0.25% risk = 12.5 USC)",
        "mt5_verified": False,
    }


def build_demo_confluence():
    """Realistic A+ confluence breakdown."""
    return {
        "grade": "A+",
        "total_score": 88,
        "reasons": [
            "✅ H4 Bullish Order Block respected (demand zone: 2635–2648)",
            "✅ M15 Break of Structure (BOS) to the upside confirmed",
            "✅ Fibonacci 61.8% retracement alignment at entry zone",
            "✅ H1 RSI divergence: oversold → bullish momentum shift",
            "✅ 200 EMA acting as dynamic support (H1 timeframe)",
            "✅ Session: London open momentum aligns with daily bias",
            "✅ DXY (USD Index) weakening — inverse correlation favours gold LONG",
            "🔵 Volume spike at demand zone: institutional accumulation signal",
        ],
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

    # Format exactly as the real pipeline does
    msg_body = notifier.format_signal_message(signal, confluence, news)

    # Wrap with a clear DEMO banner
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    demo_banner = (
        "🎯 <b>DEMO PREVIEW — THIS IS WHAT AN A+ ALERT LOOKS LIKE</b>\n"
        f"📅 Sent at: <code>{utc_now}</code>\n"
        "⚠️ <i>Synthetic signal for pipeline verification — not a live trade call</i>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
    )

    full_message = demo_banner + msg_body

    print("Sending demo A+ alert to Telegram...")
    success = notifier.send_message(full_message)

    if success:
        print("✅ Demo A+ alert sent! Check your Telegram now.")
    else:
        print("❌ Failed to send. Check token/chat_id and network.")

    return success


if __name__ == "__main__":
    ok = send_demo_alert()
    exit(0 if ok else 1)
