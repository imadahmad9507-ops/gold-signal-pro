"""
Enhanced Session Hunting & Schedule Manager:
- Manages complete UTC and PKT session schedules:
  * Asian Session: 23:00 - 08:00 UTC (04:00 - 13:00 PKT)
  * London Session: 07:00 - 17:00 UTC (12:00 - 22:00 PKT) | Kill Zone: 08:00 - 10:00 UTC
  * New York Session: 13:00 - 22:00 UTC (18:00 - 03:00 PKT) | Kill Zone: 13:00 - 16:00 UTC
  * London-NY Overlap (Peak Window): 13:00 - 17:00 UTC (18:00 - 22:00 PKT)
  * Silver Bullet Window: 15:00 - 16:00 UTC (20:00 - 21:00 PKT)
- Provides session confluence bonuses:
  * London Kill Zone: +5 pts
  * NY Kill Zone: +5 pts
  * London-NY Overlap: +8 pts
  * Silver Bullet (FVG): +10 pts
  * Asian Session: 0 pts
  * Outside Kill Zones: -5 pts
- Generates pre-open briefings, AMD expectations, Judas swing tracking, and session summaries.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd


class SessionWatchManager:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @staticmethod
    def utc_to_pkt_str(dt: Optional[datetime] = None) -> str:
        if dt is None:
            dt = datetime.now(timezone.utc)
        pkt_time = dt + timedelta(hours=5)
        return pkt_time.strftime("%H:%M PKT")

    def get_session_context(self, current_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Determines current active session, kill zones, overlap, and scoring bonuses.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        h = current_time.hour
        m = current_time.minute
        time_decimal = h + m / 60.0

        is_london_killzone = (8.0 <= time_decimal < 10.0)
        is_ny_killzone = (13.0 <= time_decimal < 16.0)
        is_overlap = (13.0 <= time_decimal < 17.0)
        is_silver_bullet = (15.0 <= time_decimal < 16.0)
        is_asian = (23.0 <= time_decimal or time_decimal < 8.0)
        is_london = (7.0 <= time_decimal < 17.0)
        is_ny = (13.0 <= time_decimal < 21.0)

        # Calculate session score boost
        if is_silver_bullet:
            boost = 10
            label = "Silver Bullet Window (15:00-16:00 UTC = 20:00-21:00 PKT)"
            priority_tag = "🎯 SILVER BULLET WINDOW"
        elif is_overlap:
            boost = 8
            label = "London-NY Overlap (13:00-17:00 UTC = 18:00-22:00 PKT)"
            priority_tag = "⭐ PEAK WINDOW (London-NY Overlap)"
        elif is_london_killzone:
            boost = 5
            label = "London Kill Zone (08:00-10:00 UTC = 13:00-15:00 PKT)"
            priority_tag = "🔥 LONDON KILL ZONE"
        elif is_ny_killzone:
            boost = 5
            label = "New York Kill Zone (13:00-16:00 UTC = 18:00-21:00 PKT)"
            priority_tag = "🔥 NEW YORK KILL ZONE"
        elif is_asian:
            boost = 0
            label = "Asian Session (23:00-08:00 UTC = 04:00-13:00 PKT)"
            priority_tag = "🌏 ASIAN SESSION"
        elif is_london or is_ny:
            boost = 0
            label = "Active Regular Session"
            priority_tag = "⚡ ACTIVE SESSION"
        else:
            boost = -5
            label = "Off-Peak / Rollover Window"
            priority_tag = "💤 OFF-PEAK"

        return {
            "time_utc": current_time.strftime("%H:%M UTC"),
            "time_pkt": self.utc_to_pkt_str(current_time),
            "label": label,
            "priority_tag": priority_tag,
            "session_boost": boost,
            "is_overlap": is_overlap,
            "is_london_killzone": is_london_killzone,
            "is_ny_killzone": is_ny_killzone,
            "is_silver_bullet": is_silver_bullet,
            "is_asian": is_asian,
            "is_peak": is_overlap or is_london_killzone or is_ny_killzone or is_silver_bullet
        }

    def compute_asian_range(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculates Asian session high, low, and range (23:00 UTC to 08:00 UTC).
        """
        if df.empty:
            return {"high": None, "low": None, "range": 0.0, "intact": True}

        # Filter recent bars in Asian hours (23:00 to 07:59 UTC)
        # Using the last 24-48 hours
        asian_bars = []
        for idx, row in df.tail(48).iterrows():
            ts = idx if isinstance(idx, pd.Timestamp) else pd.to_datetime(idx)
            if ts.hour >= 23 or ts.hour < 8:
                asian_bars.append(row)

        if not asian_bars:
            return {"high": None, "low": None, "range": 0.0, "intact": True}

        df_asian = pd.DataFrame(asian_bars)
        ah = float(df_asian["high"].max())
        al = float(df_asian["low"].min())
        curr_price = float(df["close"].iloc[-1])

        high_swept = curr_price > ah
        low_swept = curr_price < al

        status = "Asian range intact"
        if high_swept:
            status = f"Asian High ({ah:.2f}) SWEPT — watching for bearish reversal / Judas swing"
        elif low_swept:
            status = f"Asian Low ({al:.2f}) SWEPT — watching for bullish reversal / Judas swing"

        return {
            "high": round(ah, 2),
            "low": round(al, 2),
            "range": round(ah - al, 2),
            "high_swept": high_swept,
            "low_swept": low_swept,
            "status": status
        }

    def get_upcoming_session(self, current_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        h = current_time.hour
        m = current_time.minute

        # 30-min Pre-London Briefing: 07:30 UTC = 12:30 PKT
        if h == 7 and 25 <= m <= 35:
            return {
                "session": "london",
                "opens_at": "08:00 UTC = 13:00 PKT",
                "minutes_left": 60 - m if m > 30 else 30
            }
        # 30-min Pre-NY Briefing: 12:30 UTC = 17:30 PKT
        if h == 12 and 25 <= m <= 35:
            return {
                "session": "newyork",
                "opens_at": "13:00 UTC = 18:00 PKT",
                "minutes_left": 60 - m if m > 30 else 30
            }
        # Asian Open Briefing: 23:00 UTC = 04:00 PKT
        if h == 22 and 50 <= m <= 59:
            return {
                "session": "asian",
                "opens_at": "23:00 UTC = 04:00 PKT",
                "minutes_left": 60 - m
            }
        return None

    def is_in_watch_mode(self, current_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Active during London and NY hunt windows.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        h = current_time.hour
        if 8 <= h < 11:
            return {
                "in_watch_mode": True,
                "active_session": "London Hunt Mode",
                "focus": "Judas Swing & Asian Range Sweep Reversals"
            }
        elif 13 <= h < 17:
            return {
                "in_watch_mode": True,
                "active_session": "NY & Overlap Hunt Mode",
                "focus": "Continuation Pullbacks & Silver Bullet FVGs"
            }
        return {
            "in_watch_mode": False,
            "active_session": "Standard Monitor",
            "focus": "Regular Market Scanning"
        }

    def generate_pre_open_game_plan(
        self,
        df_ind: pd.DataFrame,
        symbol: str,
        session_info: Dict[str, Any],
        fundamental_bias: str = "NEUTRAL"
    ) -> str:
        last = df_ind.iloc[-1]
        c = float(last["close"])
        atr = float(last["atr_14"])

        asian = self.compute_asian_range(df_ind)
        ah_str = f"{asian['high']:.2f}" if asian["high"] else "N/A"
        al_str = f"{asian['low']:.2f}" if asian["low"] else "N/A"

        round_key = round(c / 50.0) * 50.0
        sess_name = session_info["session"].upper()
        opens_at = session_info["opens_at"]

        plan = f"""
🌅 <b>PRE-OPEN BRIEFING: {symbol} — {sess_name} SESSION</b>
⏰ <b>Opens at:</b> {opens_at}
━━━━━━━━━━━━━━━━━━━━
📌 <b>Current Price:</b> <code>{c:.2f}</code> | ATR(14): <code>{atr:.2f}</code>
⚖️ <b>Fundamental Bias:</b> <code>{fundamental_bias}</code>

📊 <b>Key Reference Levels:</b>
• Asian Range High: <code>{ah_str}</code>
• Asian Range Low: <code>{al_str}</code>
• Asian Range Status: <i>{asian['status']}</i>
• Psychological Round Level: <code>{round_key:.0f}</code>

🔭 <b>AMD & Institutional Expectations:</b>
• <b>Accumulation:</b> Asian range formed between {al_str} and {ah_str}.
• <b>Manipulation (Judas Swing):</b> Expect an initial fake-out run above {ah_str} or below {al_str} to harvest retail stops.
• <b>Distribution:</b> Look for confirmation of rejection / BOS back inside range to ride the real trend move.

⚠️ <i>Spread Notice: Avoid market entries during the first 5 minutes of open while broker liquidity normalizes.</i>
"""
        return plan.strip()
