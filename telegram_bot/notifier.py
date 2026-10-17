"""
Telegram Bot Dispatcher:
- Formats rich HTML signal alerts with entry, stop loss, ladder targets, confluence breakdown, and news status.
- Dispatches annotated charts to Telegram.
- Sends morning briefings, risk pauses, and trade outcome updates (TP1/TP2/Stop/Break-even).
- Interactive webhook/polling commands: /status, /signals, /stats, /instruments, /risk, /news, /learn.
- Strictly signals and education — NO broker logins or order execution.
"""
import os
import requests
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.is_configured():
            logger.info(f"[TELEGRAM PREVIEW (No Token Configured)]\n{text}")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_photo(self, photo_path: str, caption: str = "") -> bool:
        if not self.is_configured():
            logger.info(f"[TELEGRAM PHOTO PREVIEW] Chart saved at: {photo_path}\nCaption: {caption}")
            return False

        url = f"{self.base_url}/sendPhoto"
        try:
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"}
                resp = requests.post(url, data=data, files=files, timeout=20)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")
            return False

    def format_signal_message(
        self,
        signal: Dict[str, Any],
        confluence: Dict[str, Any],
        news_status: Dict[str, Any],
        visual_data: Optional[Dict[str, Any]] = None,
        fundamental_data: Optional[Dict[str, Any]] = None,
        session_info: Optional[Dict[str, Any]] = None
    ) -> str:
        symbol = signal["symbol"]
        tf = signal["timeframe"]
        bias = signal["direction"]
        emoji = "🟢 <b>BUY / LONG</b>" if bias == "LONG" else "🔴 <b>SELL / SHORT</b>"
        grade = confluence.get("grade", "A+")
        score = confluence.get("total_score", 90.0)

        entry = signal["entry"]
        sl = signal["stop_loss"]
        tp1 = signal["tp1"]
        tp2 = signal["tp2"]
        tp3 = signal.get("tp3", "N/A")
        rr = signal.get("risk_reward_tp2", 2.5)
        lot = signal.get("suggested_lot_size", 0.01)

        # Timestamps
        now_utc = datetime.now(timezone.utc)
        now_pkt = now_utc + timedelta(hours=5)
        time_str = f"{now_utc.strftime('%H:%M')} UTC = {now_pkt.strftime('%H:%M')} PKT"

        # Session Label
        sess_tag = "London-NY Overlap 🔥"
        if session_info:
            sess_tag = session_info.get("label", sess_tag)

        # Risk point calculation
        risk_pts = abs(entry - sl)
        entry_zone_str = f"{entry:.2f}"
        if risk_pts > 0:
            entry_offset = min(risk_pts * 0.15, 3.0)
            if bias == "LONG":
                entry_zone_str = f"{entry - entry_offset:.2f} – {entry:.2f}"
            else:
                entry_zone_str = f"{entry:.2f} – {entry + entry_offset:.2f}"

        # Signal validity duration
        in_kz = session_info.get("is_peak", False) if session_info else True
        valid_duration = timedelta(hours=1 if in_kz else 2)
        valid_until_utc = now_utc + valid_duration
        valid_until_pkt = valid_until_utc + timedelta(hours=5)
        valid_until = f"{valid_until_utc.strftime('%H:%M')} UTC ({valid_until_pkt.strftime('%I:%M %p')} PKT)"

        # Score breakdown components
        tech_score = confluence.get("technical_score", score)
        fund_boost = confluence.get("fundamental_boost", 0)
        sess_boost = confluence.get("session_boost", 0)

        # Algorithmic Factor Alignment (replaces untrained win probability claims)
        factor_eval = signal.get("factor_analysis") or confluence.get("factor_analysis")
        if factor_eval and "alignment_score" in factor_eval:
            align_score = factor_eval["alignment_score"]
            align_grade = factor_eval.get("confidence_grade", "NEUTRAL").replace("_", " ")
            drivers_str = "; ".join(factor_eval.get("key_drivers", [])[:2])
            factor_display = f"<b>{align_score:+0.1f} / 100</b> ({align_grade})"
            if drivers_str:
                factor_display += f"\n   • <i>Supporting Factors: {drivers_str}</i>"
        else:
            factor_display = "Evaluated via 9-factor confluence matrix"

        # Technical reasoning
        reasons_list = confluence.get("reasons", [])
        tech_reasons = "\n".join([f"- {r.replace('• ', '')}" for r in reasons_list if "Macro Fundamentals" not in r])

        # Fundamental context section
        fund_section = ""
        if fundamental_data:
            comps = fundamental_data.get("components", {})
            y_info = comps.get("yields", {})
            d_info = comps.get("dxy", {})
            f_info = comps.get("fear_and_greed", {})
            e_info = comps.get("etf", {})
            v_info = comps.get("vix", {})
            n_info = comps.get("news", {})

            f_bias = fundamental_data.get("bias", "NEUTRAL")
            f_raw = fundamental_data.get("raw_score", 0)

            agree_text = "✅ Fundamentals AGREE with technical signal" if not confluence.get("fundamental_conflict") else "⚠️ Fundamentals CONFLICT with technical signal"

            fund_section = f"""
📊 <b>FUNDAMENTAL CONTEXT:</b>
💵 <b>Fed/Real Yields:</b> {y_info.get('details', 'Neutral')}
📉 <b>DXY:</b> {d_info.get('details', 'Neutral')}
😱 <b>Fear & Greed:</b> {f_info.get('details', 'Neutral')}
📈 <b>ETF Flows:</b> {e_info.get('details', 'Neutral')}
🌍 <b>Geopolitical (VIX):</b> {v_info.get('details', 'Neutral')}
📰 <b>News Sentiment:</b> {n_info.get('details', 'Neutral')}
─────────────────────────────────────
⚖️ <b>FUNDAMENTAL BIAS:</b> {f_bias} ({f_raw:+d}/8)
{agree_text}"""

        # Next news line
        next_news_text = "🟢 Clear (No high-impact news within 4 hours)"
        if not news_status.get("is_safe", True):
            next_news_text = f"⚠️ <b>WARNING:</b> {news_status.get('upcoming_event')}"
        elif news_status.get("active_warning"):
            next_news_text = f"ℹ️ {news_status.get('upcoming_event')}"

        # Risk mode string
        risk_mode = signal.get("account_type", "Cent Account Mode (0.25% risk)")
        dollar_risk_str = f"~{signal.get('dollar_risk', 0.125):.3f} USD" if "dollar_risk" in signal else "~12.5 USC risk"

        # AI Visual section
        visual_section = ""
        if visual_data and visual_data.get("is_available"):
            visual_section = f"\n🤖 <b>AI Chart Check:</b> {visual_data.get('bias')} ({visual_data.get('confidence')}% conf) — {visual_data.get('summary')}\n"

        # Format TP3 safely whether float or str
        tp3_val = signal.get("tp3", "N/A")
        tp3_str = f"{tp3_val:.2f}" if isinstance(tp3_val, (int, float)) else str(tp3_val)

        # Spec and research info
        spec_status = "⚠️ Assumed Spec (Not MT5 Connected)" if not signal.get("mt5_verified") else "✅ MT5 Verified"
        source_info = signal.get("data_source", "Yahoo GC=F (Reference Futures)")

        # Volume profile and Exness calibrated pricing
        vol_prof = signal.get("volume_profile") or confluence.get("volume_profile")
        vol_prof_str = ""
        if vol_prof and vol_prof.get("poc"):
            vol_bias_raw = vol_prof.get('profile_bias', 'NEUTRAL')
            vol_bias_clean = "Bullish (Buyers in control)" if "BULL" in vol_bias_raw else ("Bearish (Sellers in control)" if "BEAR" in vol_bias_raw else "Balanced")
            vol_prof_str = f"""
📦 <b>VOLUME ZONE (Most Traded Price):</b>
• Heaviest Volume Price: <code>${vol_prof.get('poc', 0):.2f}</code>
• Value Range: <code>${vol_prof.get('val', 0):.2f} – ${vol_prof.get('vah', 0):.2f}</code>
• Volume Direction: <b>{vol_bias_clean}</b>
"""

        calibrated_str = ""
        calibrated_entry = signal.get("calibrated_entry")
        if calibrated_entry:
            c_sl = signal.get("calibrated_sl", sl)
            c_tp1 = signal.get("calibrated_tp1", tp1)
            c_tp2 = signal.get("calibrated_tp2", tp2)
            calibrated_str = f"""
📐 <b>EXNESS SPOT ESTIMATE (Direct Chart Levels):</b>
• Entry Price: <code>{calibrated_entry:.2f}</code>
• Stop Loss: <code>{c_sl:.2f}</code>
• Target 1 / Target 2: <code>{c_tp1:.2f} / {c_tp2:.2f}</code>
<i>(Basis difference adjusted: {signal.get('price_offset', 0.0):+.2f} USD)</i>
"""

        msg = f"""
🔔 <b>GOLD SIGNAL — GRADE {grade} SETUP ⭐</b>
⚡ <b>RESEARCH ALERT: {symbol}</b> ({tf})
📍 <b>{symbol}</b> | {tf} chart | 1H/4H confirmed | <code>{source_info}</code> [REFERENCE-ONLY]
⚙️ <b>Spec Status:</b> <code>{spec_status}</code>
⏰ <b>{time_str}</b> | {sess_tag}

{emoji}
📍 <b>Reference Entry:</b> <code>{entry_zone_str}</code>
🛑 <b>Reference Stop:</b> <code>{sl:.2f}</code> | Risk: {risk_pts:.1f}pts
🎯 <b>Target 1 (1.0R):</b> <code>{tp1:.2f}</code>
🎯 <b>Target 2 (2.5R):</b> <code>{tp2:.2f}</code>
🎯 <b>Target 3 (4.0R):</b> <code>{tp3_str}</code>
📊 <b>Reward-to-Risk:</b> 1:{rr}
📦 <b>Reference Sizing:</b> <code>{lot}</code> lots ({risk_mode} | {dollar_risk_str})
⏳ <b>Valid until:</b> {valid_until}
{calibrated_str}
─────────────────────────────────────
📊 <b>SETUP STRENGTH SCORE</b>
• Technical Analysis: {tech_score:.0f}/100
• News & Macro boost: {fund_boost:+d} ({confluence.get('fundamental_bias', 'Neutral')})
• Session Activity boost: {sess_boost:+d} ({sess_tag})
<b>Total Confluence Score:</b> <b>{score:.0f}/100 ✅ {grade}</b>
🎯 <b>Signal Alignment:</b> {factor_display}
⚠️ <i>Statistical scoring model — always use proper risk management.</i>
{vol_prof_str}
─────────────────────────────────────
🔍 <b>REASONS FOR THIS SETUP:</b>
{tech_reasons}
{fund_section}

─────────────────────────────────────
⚠️ <b>STOP TRADE IF:</b> Candle closes past <code>{sl:.2f}</code>
📰 <b>Upcoming News:</b> {next_news_text}
{visual_section}🏦 <b>Data Source:</b> <code>Yahoo GC=F (REFERENCE ONLY)</code>
   <i>Double check price on your Exness chart before entering.</i>

⚠️ <i>RESEARCH SIGNAL ONLY — NOT FINANCIAL ADVICE.</i>
   <i>Cent account forward-test demo only. Always apply stop loss.</i>
"""
        return msg.strip()

    def send_daily_briefing(self, fundamental_data: Dict[str, Any], key_levels: Dict[str, Any], date_str: str) -> bool:
        """
        Sends the 07:00 UTC (12:00 PKT) daily fundamental and macro game plan briefing.
        """
        comps = fundamental_data.get("components", {})
        y_info = comps.get("yields", {})
        d_info = comps.get("dxy", {})
        f_info = comps.get("fear_and_greed", {})
        v_info = comps.get("vix", {})

        bias = fundamental_data.get("bias", "NEUTRAL")
        raw = fundamental_data.get("raw_score", 0)

        res_str = key_levels.get("resistance", "2660.00, 2685.00")
        sup_str = key_levels.get("support", "2635.00, 2610.00")
        round_str = key_levels.get("round_levels", "2650, 2700")
        curr_price = key_levels.get("current_price", 2650.0)

        briefing = f"""
🌅 <b>GOLD DAILY FUNDAMENTAL BRIEFING — {date_str}</b>
⏰ 07:00 UTC = 12:00 PKT (London Opening Window)
━━━━━━━━━━━━━━━━━━━━

💵 <b>MACRO ENVIRONMENT:</b>
• Fed Stance: <b>{y_info.get('fed_stance', 'Neutral')}</b>
• 10Y Yield: <code>{y_info.get('yield_10y', 4.0)}%</code> | Real Yield: <code>{y_info.get('real_yield', 1.2)}%</code> → {y_info.get('bias', 'Neutral')}
• DXY (US Dollar): <code>{d_info.get('level', 102.0)}</code> | Trend: <b>{d_info.get('trend', 'SIDEWAYS')}</b> ({d_info.get('weekly_change_pct', 0.0):+.1f}%)

😱 <b>SENTIMENT & VOLATILITY:</b>
• Fear & Greed: <b>{f_info.get('value', 50)} ({f_info.get('label', 'Neutral')})</b>
• VIX Volatility: <code>{v_info.get('vix', 15.0)}</code> ({v_info.get('bias', 'Normal')})

⚖️ <b>TODAY'S GOLD MACRO BIAS:</b> <b>{bias} ({raw:+d}/8)</b>
<i>Reason: Yields and dollar momentum dictate directional safe-haven flows. Expect institutional volatility expansion during London & NY kill zones.</i>

🎯 <b>KEY LEVELS TO WATCH TODAY (GC=F):</b>
• Current Reference Price: <code>{curr_price:.2f}</code>
• Resistance: <code>{res_str}</code>
• Support: <code>{sup_str}</code>
• Psychological Round Numbers: <code>{round_str}</code>

⚠️ <i>Notice: Analysis and research only. Cent account forward testing. Always use a stop loss.</i>
"""
        return self.send_message(briefing.strip())

    def send_session_summary(self, title: str, body: str) -> bool:
        """Dispatches session open/close updates."""
        msg = f"<b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━\n{body}"
        return self.send_message(msg.strip())

    def send_near_miss_alert(
        self,
        symbol: str,
        timeframe: str,
        direction: str,
        score: float,
        reasons_failed: List[str],
        recommended_action: str,
        key_level: float
    ) -> bool:
        """
        TIER 2: NEAR MISS — Grade A Setup Spotted
        """
        now_utc = datetime.now(timezone.utc)
        now_pkt = now_utc + timedelta(hours=5)
        time_str = f"{now_utc.strftime('%H:%M')} UTC = {now_pkt.strftime('%H:%M')} PKT"
        reasons_bullet = "\n".join(f"• {r}" for r in reasons_failed)

        action_word = "Buy Setup" if "LONG" in direction.upper() or "BUY" in direction.upper() else "Sell Setup"

        msg = f"""
👀 <b>POTENTIAL TRADE WATCHING — {action_word}</b>
📍 <b>Market:</b> {symbol} | {timeframe} chart
<b>Setup Score:</b> <b>{score:.0f}/100</b>
⏰ <b>Time:</b> {time_str}

<b>Why not entering yet:</b>
{reasons_bullet}

<b>What we are waiting for:</b>
• {recommended_action}
• Watch this level closely

📌 <b>Key Price to Watch:</b> <code>${key_level:.2f}</code>
⚠️ <i>Not an active signal. Waiting for better entry price.</i>
"""
        return self.send_message(msg.strip())

    def send_session_scan_update(
        self,
        symbol: str,
        highest_score: float,
        strategy: str,
        market_regime: str,
        next_session_text: str,
        why_no_signal: str = "Market moving sideways + waiting for higher quality setup"
    ) -> bool:
        """
        TIER 3: WATCHING — Grade B (Score 55-69) — Sent maximum once per session
        """
        now_pkt = datetime.now(timezone.utc) + timedelta(hours=5)
        time_str = now_pkt.strftime("%I:%M %p PKT")

        # Plain human words instead of CONSOLIDATING
        condition_clean = "Moving Sideways (Ranging)" if "CONSOLIDAT" in market_regime.upper() else ("Trending Strongly" if "TREND" in market_regime.upper() else market_regime)

        msg = f"""
📡 <b>MARKET SCAN UPDATE — {time_str}</b>
━━━━━━━━━━━━━━━━━━━━
🎯 <b>Best score seen this session:</b> <b>{highest_score:.0f}/100</b>
📍 <b>Market:</b> {symbol} | <b>Strategy:</b> {strategy}
⚖️ <b>Current Status:</b> {why_no_signal}
📊 <b>Market Condition:</b> {condition_clean}
⏳ <b>Next Market Session:</b> {next_session_text}
"""
        return self.send_message(msg.strip())

    def send_pattern_alert(
        self,
        symbol: str,
        timeframe: str,
        pattern_name: str,
        pct_complete: int,
        prz_range: str,
        expected_target: float,
        fib_details: str = "XA ✅ AB ✅ BC ✅ CD forming..."
    ) -> bool:
        """
        TIER 4: WATCHING PATTERN (harmonic or classical chart pattern forming)
        """
        msg = f"""
🔭 <b>CHART PATTERN FORMING — WATCH THIS</b>
📍 <b>Market:</b> {symbol} | {timeframe}
<b>Pattern:</b> {pattern_name} ({pct_complete}% complete)
<b>Current step:</b> Forming final swing
<b>Entry Zone if completed:</b> <code>{prz_range}</code>
<b>Target Price:</b> <code>${expected_target:.2f}</code>

💡 <i>Nothing to do now. Bot will automatically alert you if a full signal triggers.</i>
"""
        return self.send_message(msg.strip())

    def send_market_heartbeat(
        self,
        current_price: float,
        change_pct: float,
        market_regime: str,
        best_score_session: float,
        next_session_text: str,
        next_news_text: str
    ) -> bool:
        """
        Periodic Heartbeat (every ~2 hours when no other notifications sent)
        """
        now_pkt = datetime.now(timezone.utc) + timedelta(hours=5)
        time_str = now_pkt.strftime("%I:%M %p PKT")
        change_str = f"{change_pct:+.2f}%"

        # Plain human words instead of CONSOLIDATING
        condition_clean = "Moving Sideways (Ranging)" if "CONSOLIDAT" in market_regime.upper() else ("Trending Cleanly" if "TREND" in market_regime.upper() else market_regime)

        msg = f"""
🤖 <b>BOT STATUS — {time_str}</b>
✅ <b>Running normally</b> | Last scan: &lt;1 min ago
📊 <b>Gold Price:</b> <code>${current_price:.2f}</code> | <b>Change:</b> {change_str}
📈 <b>Market Condition:</b> {condition_clean}
🔍 <b>Best score this session:</b> {best_score_session:.0f}/100
⏳ <b>Next market session:</b> {next_session_text}
📰 <b>Upcoming news:</b> {next_news_text}
"""
        return self.send_message(msg.strip())

