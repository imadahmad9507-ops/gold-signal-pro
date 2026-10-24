"""
Enhanced Session Hunter Strategy:
Specialized in session opens (London, New York, Overlap, Silver Bullet).
Detects:
1. Judas Swing: Liquidity sweep of the Asian session high or low during London open (08:00 - 10:00 UTC)
   followed by a confirmation candle back inside the range.
2. New York Open Continuation & Range Breakout (13:00 - 16:00 UTC)
3. Silver Bullet FVG Setup: Fresh Fair Value Gap formed during the 15:00 - 16:00 UTC window
   following a liquidity sweep.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import pandas as pd


class BaseStrategy(ABC):
    name: str = "BaseStrategy"
    compatible_regimes: list = ["TRENDING", "RANGING", "MODERATE"]

    @abstractmethod
    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        pass


class SessionHunterStrategy(BaseStrategy):
    name = "Institutional Session Hunter"
    compatible_regimes = ["TRENDING", "RANGING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 15:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = float(last["atr_14"])
        c = float(last["close"])
        ts = last.name if isinstance(last.name, pd.Timestamp) else pd.to_datetime(last.name)
        hour = ts.hour
        minute = ts.minute
        time_decimal = hour + minute / 60.0

        # Extract Asian session range (bars from 23:00 to 08:00 UTC)
        asian_bars = []
        for idx, row in df.tail(48).iterrows():
            t = idx if isinstance(idx, pd.Timestamp) else pd.to_datetime(idx)
            if t.hour >= 23 or t.hour < 8:
                asian_bars.append(row)

        if not asian_bars:
            return None

        df_asian = pd.DataFrame(asian_bars)
        asian_high = float(df_asian["high"].max())
        asian_low = float(df_asian["low"].min())

        # 1. LONDON KILL ZONE (08:00 - 10:00 UTC = 13:00 - 15:00 PKT): Judas Swing
        if 8.0 <= time_decimal < 11.0:
            # Bullish Judas Swing: Swept Asian Low, reversed up and closed back above Asian Low
            if prev["low"] < asian_low and c > asian_low and c > last["open"]:
                sl = prev["low"] - 0.4 * atr
                rd = c - sl
                if rd <= 0 or rd > 3.5 * atr:
                    return None
                return {
                    "strategy": "Judas Swing Reversal (London)",
                    "direction": "LONG",
                    "entry": c,
                    "stop_loss": sl,
                    "tp1": c + 1.0 * rd,
                    "tp2": c + 2.8 * rd,
                    "tp3": asian_high if (asian_high - c) >= 2.8 * rd else (c + 4.0 * rd),
                    "reason": f"Judas swing liquidity sweep below Asian low ({asian_low:.2f}) + bullish reclamation"
                }

            # Bearish Judas Swing: Swept Asian High, reversed down and closed back below Asian High
            if prev["high"] > asian_high and c < asian_high and c < last["open"]:
                sl = prev["high"] + 0.4 * atr
                rd = sl - c
                if rd <= 0 or rd > 3.5 * atr:
                    return None
                return {
                    "strategy": "Judas Swing Reversal (London)",
                    "direction": "SHORT",
                    "entry": c,
                    "stop_loss": sl,
                    "tp1": c - 1.0 * rd,
                    "tp2": c - 2.8 * rd,
                    "tp3": asian_low if (c - asian_low) >= 2.8 * rd else (c - 4.0 * rd),
                    "reason": f"Judas swing liquidity sweep above Asian high ({asian_high:.2f}) + bearish rejection"
                }

        # 2. SILVER BULLET WINDOW (15:00 - 16:00 UTC = 20:00 - 21:00 PKT): FVG Expansion
        if 15.0 <= time_decimal <= 16.5:
            # Check for 3-candle Fair Value Gap (FVG)
            if len(df) >= 3:
                c1 = df.iloc[-3]
                c3 = df.iloc[-1]
                # Bullish FVG: c1 high < c3 low
                if c3["low"] > c1["high"]:
                    fvg_low = c1["high"]
                    fvg_high = c3["low"]
                    sl = fvg_low - 0.3 * atr
                    rd = c - sl
                    if rd > 0:
                        return {
                            "strategy": "Silver Bullet FVG (New York)",
                            "direction": "LONG",
                            "entry": c,
                            "stop_loss": sl,
                            "tp1": c + 1.0 * rd,
                            "tp2": c + 2.8 * rd,
                            "tp3": c + 4.0 * rd,
                            "reason": f"Silver Bullet fresh bullish FVG ({fvg_low:.2f}–{fvg_high:.2f}) during 15:00-16:00 UTC window"
                        }
                # Bearish FVG: c1 low > c3 high
                if c3["high"] < c1["low"]:
                    fvg_high = c1["low"]
                    fvg_low = c3["high"]
                    sl = fvg_high + 0.3 * atr
                    rd = sl - c
                    if rd > 0:
                        return {
                            "strategy": "Silver Bullet FVG (New York)",
                            "direction": "SHORT",
                            "entry": c,
                            "stop_loss": sl,
                            "tp1": c - 1.0 * rd,
                            "tp2": c - 2.8 * rd,
                            "tp3": c - 4.0 * rd,
                            "reason": f"Silver Bullet fresh bearish FVG ({fvg_low:.2f}–{fvg_high:.2f}) during 15:00-16:00 UTC window"
                        }

        # 3. NY OVERLAP CONTINUATION (13:00 - 17:00 UTC)
        if 13.0 <= time_decimal < 17.0:
            ema20 = float(last.get("ema_20", c))
            ema50 = float(last.get("ema_50", c))
            # Trend continuation during overlap
            if ema20 > ema50 and last["low"] <= ema20 * 1.002 and c > ema20 and c > last["open"]:
                sl = min(last["low"], prev["low"]) - 0.4 * atr
                rd = c - sl
                if 0 < rd <= 3.0 * atr:
                    return {
                        "strategy": "London-NY Overlap Momentum",
                        "direction": "LONG",
                        "entry": c,
                        "stop_loss": sl,
                        "tp1": c + 1.0 * rd,
                        "tp2": c + 2.8 * rd,
                        "tp3": c + 4.0 * rd,
                        "reason": "Institutional overlap volume continuation off dynamic EMA 20"
                    }
            elif ema20 < ema50 and last["high"] >= ema20 * 0.998 and c < ema20 and c < last["open"]:
                sl = max(last["high"], prev["high"]) + 0.4 * atr
                rd = sl - c
                if 0 < rd <= 3.0 * atr:
                    return {
                        "strategy": "London-NY Overlap Momentum",
                        "direction": "SHORT",
                        "entry": c,
                        "stop_loss": sl,
                        "tp1": c - 1.0 * rd,
                        "tp2": c - 2.8 * rd,
                        "tp3": c - 4.0 * rd,
                        "reason": "Institutional overlap volume continuation off dynamic EMA 20 resistance"
                    }

        return None
