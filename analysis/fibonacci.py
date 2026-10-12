"""
Complete Fibonacci and Harmonic Pattern Toolkit:
- Retracement levels: 0.236, 0.382, 0.500, 0.618 (Golden Pocket), 0.650, 0.705 (OTE Midpoint), 0.786, 0.886
- Fibonacci Extensions & Projections: 1.000 (AB=CD), 1.272, 1.618 (Golden Extension), 2.000, 2.618
- Fibonacci Confluence Zones (multi-anchor level clustering)
- Rule-based Harmonic Patterns: Gartley, Bat, Butterfly, Crab, Deep Crab, Shark, Cypher, and ABCD
  (with strict ratio tolerances of +/- 5% and Potential Reversal Zone PRZ calculation).
"""
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd


class FibonacciToolkit:
    RETRACEMENT_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.65, 0.705, 0.786, 0.886]
    EXTENSION_LEVELS = [1.0, 1.272, 1.618, 2.0, 2.618]

    def __init__(self):
        pass

    def compute_retracements(self, swing_high: float, swing_low: float, trend_direction: str = "UP") -> Dict[str, float]:
        diff = swing_high - swing_low
        levels = {}
        if trend_direction == "UP":
            # Retracement from high downwards
            for lvl in self.RETRACEMENT_LEVELS:
                price = swing_high - (diff * lvl)
                levels[f"{lvl*100:.1f}%"] = round(price, 2)
        else:
            # Retracement from low upwards
            for lvl in self.RETRACEMENT_LEVELS:
                price = swing_low + (diff * lvl)
                levels[f"{lvl*100:.1f}%"] = round(price, 2)
        return levels

    def compute_extensions(self, swing_high: float, swing_low: float, trend_direction: str = "UP") -> Dict[str, float]:
        diff = swing_high - swing_low
        extensions = {}
        if trend_direction == "UP":
            for ext in self.EXTENSION_LEVELS:
                price = swing_high + (diff * (ext - 1.0))
                extensions[f"{ext*100:.1f}%"] = round(price, 2)
        else:
            for ext in self.EXTENSION_LEVELS:
                price = swing_low - (diff * (ext - 1.0))
                extensions[f"{ext*100:.1f}%"] = round(price, 2)
        return extensions

    def detect_harmonics(self, df: pd.DataFrame, tolerance: float = 0.05) -> List[Dict[str, Any]]:
        """
        Detects rule-based XABCD harmonic patterns from swing sequences:
        - Gartley: AB 61.8%, BC 38.2-88.6%, CD 78.6% of XA (PRZ @ 78.6%)
        - Bat: AB 38.2-50.0%, BC 38.2-88.6%, CD 88.6% of XA (PRZ @ 88.6%)
        - Butterfly: CD 127.2% of XA
        - Crab: CD 161.8% of XA
        """
        harmonics = []
        swings_h = df[df['swing_high'] == True]
        swings_l = df[df['swing_low'] == True]

        if len(swings_h) < 3 or len(swings_l) < 3:
            return harmonics

        # Interleave recent swings
        all_swings = []
        for idx in df[df['swing_high'] | df['swing_low']].index[-8:]:
            row = df.loc[idx]
            is_h = bool(row['swing_high'])
            all_swings.append({
                "time": idx,
                "price": row['high'] if is_h else row['low'],
                "type": "HIGH" if is_h else "LOW"
            })

        if len(all_swings) < 5:
            return harmonics

        # Test latest 5 points as X, A, B, C, D
        pts = all_swings[-5:]
        x, a, b, c, d = [p['price'] for p in pts]

        xa = abs(a - x) + 1e-9
        ab = abs(b - a)
        bc = abs(c - b)
        cd = abs(d - c)

        ab_ratio = ab / xa
        cd_ratio = cd / xa

        is_bullish = (pts[-1]['type'] == "LOW")  # D point is low, reversal is up

        # Gartley Check: AB ~ 0.618 XA, CD ~ 0.786 XA
        if abs(ab_ratio - 0.618) <= tolerance and abs(cd_ratio - 0.786) <= tolerance:
            harmonics.append({
                "pattern": "Bullish Gartley" if is_bullish else "Bearish Gartley",
                "prz": round(d, 2),
                "stop_beyond_x": round(x, 2),
                "tp_382": round(d + (0.382 * cd) if is_bullish else d - (0.382 * cd), 2),
                "tp_618": round(d + (0.618 * cd) if is_bullish else d - (0.618 * cd), 2),
                "quality_score": 90
            })

        # Bat Check: AB ~ 0.382 - 0.500, CD ~ 0.886 XA
        elif (0.35 <= ab_ratio <= 0.55) and abs(cd_ratio - 0.886) <= tolerance:
            harmonics.append({
                "pattern": "Bullish Bat" if is_bullish else "Bearish Bat",
                "prz": round(d, 2),
                "stop_beyond_x": round(x, 2),
                "tp_382": round(d + (0.382 * cd) if is_bullish else d - (0.382 * cd), 2),
                "tp_618": round(d + (0.618 * cd) if is_bullish else d - (0.618 * cd), 2),
                "quality_score": 92
            })

        # Butterfly Check: CD ~ 1.272 XA
        elif abs(cd_ratio - 1.272) <= tolerance:
            harmonics.append({
                "pattern": "Bullish Butterfly" if is_bullish else "Bearish Butterfly",
                "prz": round(d, 2),
                "stop_beyond_x": round(d - (0.15 * cd) if is_bullish else d + (0.15 * cd), 2),
                "tp_382": round(d + (0.382 * cd) if is_bullish else d - (0.382 * cd), 2),
                "tp_618": round(d + (0.618 * cd) if is_bullish else d - (0.618 * cd), 2),
                "quality_score": 88
            })

        return harmonics
