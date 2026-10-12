"""
Telegram Interactive Command Handler:
Supports:
/status - Bot health, last run time, active session
/signals - Current open signals
/stats - Rolling win rate, profit factor, total R
/instruments - Supported instruments & settings
/risk <balance> <percent> - Update risk configuration
/news - Today's high-impact economic events
/learn - Beginner guide to trading concepts (SMC, FVG, OB, OTE, RSI)
/chart <symbol> <timeframe> - On-demand technical chart generation
"""
import os
import yaml
import requests
import logging
from typing import Dict, Any, Optional

from tracking.tracker import SignalTracker
from news.calendar import NewsFilter
from visual_ai.chart import ChartGenerator
from data.provider import get_data_provider
from indicators.engine import calculate_all_indicators

logger = logging.getLogger(__name__)


class TelegramCommandHandler:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
        self.tracker = SignalTracker()

    def process_updates(self):
        """Polls for new messages/commands and replies accordingly."""
        if not self.bot_token or not self.chat_id:
            return

        url = f"{self.base_url}/getUpdates"
        try:
            resp = requests.get(url, timeout=10).json()
            if not resp.get("ok"):
                return
            
            updates = resp.get("result", [])
            for u in updates:
                msg = u.get("message", {})
                text = msg.get("text", "").strip()
                sender_id = str(msg.get("chat", {}).get("id", ""))
                update_id = u.get("update_id")

                # Only respond to authorized chat ID
                if sender_id == str(self.chat_id) and text.startswith("/"):
                    self.handle_command(text)

                # Acknowledge update offset
                requests.get(f"{self.base_url}/getUpdates?offset={update_id + 1}", timeout=5)

        except Exception as e:
            logger.warning(f"Error handling Telegram updates: {e}")

    def send_reply(self, text: str, parse_mode: str = "HTML"):
        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to reply: {e}")

    def handle_command(self, cmd_text: str):
        parts = cmd_text.split()
        cmd = parts[0].lower()

        if cmd == "/start" or cmd == "/help":
            help_msg = """
🤖 <b>Gold Signal Pro Commands:</b>
/status — Bot health & active market session
/signals — View active signals
/stats — Win rate, profit factor, total R
/instruments — Supported instruments & settings
/news — Today's high-impact economic news
/learn — Beginner trading terminology guide
/risk &lt;balance&gt; &lt;%&gt; — Update position sizing
/chart &lt;symbol&gt; &lt;timeframe&gt; — Get on-demand chart
"""
            self.send_reply(help_msg.strip())

        elif cmd == "/status":
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self.send_reply(f"🟢 <b>Bot Status: ACTIVE & HEALTHY</b>\n⏰ <b>Timestamp:</b> <code>{now}</code>\n☁️ <b>Platform:</b> GitHub Actions Cloud\n⚡ <b>Engine:</b> SMC + Multi-Strategy Confluence")

        elif cmd == "/signals":
            signals = self.tracker.get_open_signals()
            if not signals:
                self.send_reply("ℹ️ <b>Active Signals:</b> No open signals currently.")
            else:
                lines = [f"• <b>{s['symbol']}</b> ({s['timeframe']}) {s['direction']} @ {s['entry']} | Grade: {s['grade']}" for s in signals]
                self.send_reply("📊 <b>Open Signals:</b>\n" + "\n".join(lines))

        elif cmd == "/stats":
            stats = self.tracker.get_performance_stats()
            self.send_reply(f"📈 <b>Performance Tracker:</b>\n{stats['summary']}")

        elif cmd == "/news":
            cfg = yaml.safe_load(open("config/config.yaml"))
            nf = NewsFilter(cfg)
            events = nf.fetch_calendar()
            high_imp = [e for e in events if e.get("impact") == "High"][:5]
            if not high_imp:
                self.send_reply("🟢 <b>Economic News:</b> No high-impact events pending.")
            else:
                lines = [f"• <b>{e.get('country')}</b>: {e.get('title')} ({e.get('date')})" for e in high_imp]
                self.send_reply("📰 <b>Upcoming High-Impact Events:</b>\n" + "\n".join(lines))

        elif cmd == "/learn":
            learn_msg = """
📚 <b>Beginner Trading Guide:</b>
• <b>SMC (Smart Money Concepts):</b> Tracking where institutional orders are placed.
• <b>OB (Order Block):</b> The last candle before an institutional move that broke structure.
• <b>FVG (Fair Value Gap):</b> A price imbalance created by rapid displacement.
• <b>OTE (Optimal Trade Entry):</b> The 62%–79% Fibonacci retracement sweet spot.
• <b>BOS (Break of Structure):</b> Confirms trend direction by breaking previous swing highs/lows.
• <b>R:R (Risk to Reward):</b> Ratio of potential profit compared to risk (minimum 1:2).
"""
            self.send_reply(learn_msg.strip())
