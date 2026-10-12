"""
ICT / Smart Money Concepts (SMC) Engine:
- Order Blocks (Bullish & Bearish OB, tested count, impulse validation)
- Fair Value Gaps (FVG) / Imbalances (Bullish & Bearish, Consequent Encroachment at 50%)
- Liquidity sweeps (Buy-side & Sell-side sweeps, equal highs/lows)
- Power of Three (AMD Model): Accumulation (Asia), Manipulation/Judas Swing (London Open), Distribution (NY)
- ICT Session Kill Zones: Asian (8PM-12AM NY), London (2AM-5AM NY), NY AM (7AM-10AM NY), NY PM (1:30PM-3PM NY), Silver Bullet
- Premium vs Discount Dealing Ranges (50% Equilibrium) & Optimal Trade Entry (OTE 62%-79%)
"""
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd


class ICTEngine:
    def __init__(self):
        pass

    def detect_fvgs(self, df: pd.DataFrame, max_lookback: int = 50) -> List[Dict[str, Any]]:
        """
        Detects 3-candle Fair Value Gaps (imbalances).
        Candle 1 and Candle 3 non-overlapping gap.
        """
        fvgs = []
        if len(df) < 5:
            return fvgs

        sub = df.tail(max_lookback)
        for i in range(2, len(sub)):
            c1 = sub.iloc[i - 2]
            c2 = sub.iloc[i - 1]
            c3 = sub.iloc[i]

            # Bullish FVG: c3 low > c1 high
            if c3['low'] > c1['high']:
                gap_size = c3['low'] - c1['high']
                ce = c1['high'] + (gap_size * 0.5)  # Consequent Encroachment (50%)
                fvgs.append({
                    "type": "BULLISH_FVG",
                    "top": c3['low'],
                    "bottom": c1['high'],
                    "ce": ce,
                    "bar_time": c2.name,
                    "gap_size": round(gap_size, 2)
                })

            # Bearish FVG: c3 high < c1 low
            elif c3['high'] < c1['low']:
                gap_size = c1['low'] - c3['high']
                ce = c3['high'] + (gap_size * 0.5)
                fvgs.append({
                    "type": "BEARISH_FVG",
                    "top": c1['low'],
                    "bottom": c3['high'],
                    "ce": ce,
                    "bar_time": c2.name,
                    "gap_size": round(gap_size, 2)
                })

        return fvgs

    def detect_order_blocks(self, df: pd.DataFrame, lookback: int = 40) -> List[Dict[str, Any]]:
        """
        Detects institutional order blocks:
        Bullish OB: Last bearish candle prior to a strong bullish displacement breaking structure.
        Bearish OB: Last bullish candle prior to a strong bearish displacement breaking structure.
        """
        obs = []
        if len(df) < 15:
            return obs

        sub = df.tail(lookback)
        atr_avg = sub['atr_14'].mean() if 'atr_14' in sub.columns else 10.0

        for i in range(3, len(sub) - 1):
            curr = sub.iloc[i]
            next1 = sub.iloc[i + 1]

            # Bullish OB check
            if curr['close'] < curr['open']:  # Bearish candle
                # Next candle produces high momentum displacement
                if next1['close'] > next1['open'] and (next1['close'] - next1['open']) > 1.4 * atr_avg:
                    obs.append({
                        "type": "BULLISH_OB",
                        "top": curr['high'],
                        "bottom": curr['low'],
                        "time": curr.name,
                        "tested": False
                    })

            # Bearish OB check
            elif curr['close'] > curr['open']:  # Bullish candle
                if next1['close'] < next1['open'] and (next1['open'] - next1['close']) > 1.4 * atr_avg:
                    obs.append({
                        "type": "BEARISH_OB",
                        "top": curr['high'],
                        "bottom": curr['low'],
                        "time": curr.name,
                        "tested": False
                    })

        return obs

    def compute_dealing_range(self, df: pd.DataFrame, lookback: int = 60) -> Dict[str, Any]:
        """
        Calculates Premium vs Discount Equilibrium (50%) and Optimal Trade Entry (OTE 62% - 79%).
        """
        sub = df.tail(lookback)
        high = sub['high'].max()
        low = sub['low'].min()
        equilibrium = (high + low) / 2.0
        current_price = sub.iloc[-1]['close']

        # OTE Fibonacci calculation
        diff = high - low
        ote_62 = high - (diff * 0.618)
        ote_705 = high - (diff * 0.705)  # Ideal sweet spot
        ote_79 = high - (diff * 0.786)

        is_discount = current_price < equilibrium
        is_premium = current_price > equilibrium
        in_ote = (ote_79 <= current_price <= ote_62)

        return {
            "range_high": round(high, 2),
            "range_low": round(low, 2),
            "equilibrium": round(equilibrium, 2),
            "current_zone": "DISCOUNT" if is_discount else "PREMIUM",
            "ote_zone": {"62": round(ote_62, 2), "70.5": round(ote_705, 2), "79": round(ote_79, 2)},
            "in_ote_zone": in_ote
        }

    def detect_liquidity_sweeps(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Detects recent liquidity sweeps (Judas swing or stop sweeps) where price wicks
        past previous equal highs/lows and immediately reclaims inside the level.
        """
        if len(df) < 25:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        recent_highs = df.iloc[-20:-2]['high'].max()
        recent_lows = df.iloc[-20:-2]['low'].min()

        # Buy-Side Liquidity Sweep (BSL)
        if prev['high'] > recent_highs and prev['close'] < recent_highs and last['close'] < last['open']:
            return {
                "type": "BUY_SIDE_LIQUIDITY_SWEEP",
                "swept_level": round(recent_highs, 2),
                "bias": "SHORT",
                "desc": f"Swept buy-side liquidity above {recent_highs:.2f} with strong bearish rejection"
            }

        # Sell-Side Liquidity Sweep (SSL)
        if prev['low'] < recent_lows and prev['close'] > recent_lows and last['close'] > last['open']:
            return {
                "type": "SELL_SIDE_LIQUIDITY_SWEEP",
                "swept_level": round(recent_lows, 2),
                "bias": "LONG",
                "desc": f"Swept sell-side liquidity below {recent_lows:.2f} with institutional reclamation"
            }

        return None

    def get_kill_zone_status(self, timestamp: pd.Timestamp) -> Dict[str, Any]:
        """
        Evaluates ICT session kill zones (in NY EST/EDT equivalent UTC times):
        - Asian Kill Zone: 00:00 - 04:00 UTC (Range consolidation)
        - London Kill Zone: 06:00 - 09:00 UTC (Judas Swing / Manipulation)
        - New York AM Kill Zone: 11:00 - 14:00 UTC (True Distribution)
        - Silver Bullet: 14:00 - 15:00 UTC
        """
        h = timestamp.hour
        if 6 <= h < 9:
            return {"active": True, "zone": "London Kill Zone", "priority": "HIGH", "amd_phase": "Manipulation (Judas Swing)"}
        elif 11 <= h < 14:
            return {"active": True, "zone": "New York AM Kill Zone", "priority": "HIGH", "amd_phase": "Distribution (True Move)"}
        elif 14 <= h < 15:
            return {"active": True, "zone": "Silver Bullet Window", "priority": "VERY_HIGH", "amd_phase": "Distribution Continuation"}
        elif 0 <= h < 4:
            return {"active": True, "zone": "Asian Kill Zone", "priority": "LOW", "amd_phase": "Accumulation (Range Building)"}

        return {"active": False, "zone": "Outside Kill Zones", "priority": "NONE", "amd_phase": "Normal Session"}
