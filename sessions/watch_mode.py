"""
Market Hours and Session Watch Manager:
- Manages instrument trading hours (Exness schedule)
- Detects upcoming market/session opens (Asia, London, New York)
- Pre-Open Game Plan generator (sent 30-60 min before open)
- Watch Mode: scans during opening rush (0-3 hours post open)
- End-of-session reporting
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd


class SessionWatchManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.instruments = config.get("instruments", {})
        # Standard Session UTC definitions
        self.sessions_utc = {
            "asia": {"start": 0, "end": 8, "name": "Asian Session (Tokyo/Sydney)"},
            "london": {"start": 7, "end": 16, "name": "London Session (European Open)"},
            "newyork": {"start": 12, "end": 21, "name": "New York Session (US Open)"}
        }

    def get_upcoming_session(self, current_time: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        current_hour = current_time.hour
        current_minute = current_time.minute

        # Check if 30-60 minutes before London (07:00 UTC) or NY (12:00/13:00 UTC)
        if current_hour == 6 and current_minute >= 0:
            return {"session": "london", "opens_at": "07:00 UTC", "minutes_left": 60 - current_minute}
        if current_hour == 11 and current_minute >= 0:
            return {"session": "newyork", "opens_at": "12:00 UTC", "minutes_left": 60 - current_minute}
        if current_hour == 23 and current_minute >= 0:
            return {"session": "asia", "opens_at": "00:00 UTC", "minutes_left": 60 - current_minute}
        return None

    def is_in_watch_mode(self, current_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Active during the opening rush (first 3 hours of London: 07-10 UTC, or NY: 12-15 UTC).
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        h = current_time.hour
        if 7 <= h < 10:
            return {"in_watch_mode": True, "active_session": "London Open Watch Mode", "target_strategies": ["Session Breakout", "Smart-Money Liquidity Sweep"]}
        elif 12 <= h < 15:
            return {"in_watch_mode": True, "active_session": "New York Open Watch Mode", "target_strategies": ["Session Breakout", "Smart-Money Liquidity Sweep", "Breakout and Retest"]}
        return {"in_watch_mode": False, "active_session": "Normal Scanning", "target_strategies": []}

    def generate_pre_open_game_plan(self, df_ind: pd.DataFrame, symbol: str, session_info: Dict[str, Any]) -> str:
        last = df_ind.iloc[-1]
        c = last['close']
        atr = last['atr_14']
        
        # Previous Day & Week calculations
        pd_bars = df_ind.iloc[-48:-24] if len(df_ind) >= 48 else df_ind.iloc[-24:]
        pdh = pd_bars['high'].max()
        pdl = pd_bars['low'].min()

        # Key round level for Gold
        round_key = round(c / 50.0) * 50.0

        # Scenario definitions
        plan = f"""
🌅 <b>PRE-OPEN GAME PLAN: {symbol}</b> ({session_info['session'].upper()} OPEN IN {session_info['minutes_left']}m)
━━━━━━━━━━━━━━━━━━━━
📌 <b>Current Price:</b> <code>{c:.2f}</code> | ATR: <code>{atr:.2f}</code>
📊 <b>Key Reference Levels:</b>
• Prev Day High (PDH): <code>{pdh:.2f}</code>
• Prev Day Low (PDL): <code>{pdl:.2f}</code>
• Major Round Level: <code>{round_key:.0f}</code>

🔭 <b>Opening Scenarios to Watch:</b>
1. 🟢 <b>Bullish Expansion:</b> Sustained 30m candle close above PDH (<code>{pdh:.2f}</code>) targets next liquidity pool.
2. 🔴 <b>Bearish Breakdown:</b> Sustained close below PDL (<code>{pdl:.2f}</code>) triggers downward continuation.
3. ⚡ <b>Liquidity Sweep (Trap):</b> Quick wick through PDH/PDL with immediate reclaim back inside range (look for Smart-Money Sweep).

⚠️ <i>Spread Warning: Avoid entering in the first 5 minutes of session open while Exness spreads normalize.</i>
"""
        return plan.strip()
