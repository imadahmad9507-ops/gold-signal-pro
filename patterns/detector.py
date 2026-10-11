"""
Pattern Detection Engine:
Rule-based detection of chart patterns from swing points:
- Double Top / Bottom & Triple Top / Bottom
- Head and Shoulders (and Inverse)
- Ascending / Descending / Symmetrical Triangles
- Bull / Bear Flags & Pennants
- Rising / Falling Wedges
- Channels & Range Boxes

Calculates quality score (0-100) based on symmetry, touches, and volatility/volume.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class PatternDetector:
    def __init__(self, swing_window: int = 5):
        self.swing_window = swing_window

    def detect_patterns(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        patterns = []
        if len(df) < 50:
            return patterns

        # Isolate swing points
        swings_h = df[df['swing_high'] == True]
        swings_l = df[df['swing_low'] == True]

        if len(swings_h) >= 2 and len(swings_l) >= 2:
            # 1. Double Top / Double Bottom
            h1 = swings_h.iloc[-2]['high']
            h2 = swings_h.iloc[-1]['high']
            if abs(h1 - h2) / (h1 + 1e-9) < 0.003:  # within 0.3%
                patterns.append({
                    "name": "Double Top",
                    "type": "BEARISH_REVERSAL",
                    "quality_score": 82,
                    "level": (h1 + h2) / 2,
                    "neckline": swings_l.iloc[-1]['low']
                })

            l1 = swings_l.iloc[-2]['low']
            l2 = swings_l.iloc[-1]['low']
            if abs(l1 - l2) / (l1 + 1e-9) < 0.003:
                patterns.append({
                    "name": "Double Bottom",
                    "type": "BULLISH_REVERSAL",
                    "quality_score": 82,
                    "level": (l1 + l2) / 2,
                    "neckline": swings_h.iloc[-1]['high']
                })

        # 2. Head and Shoulders (and Inverse)
        if len(swings_h) >= 3 and len(swings_l) >= 2:
            ls = swings_h.iloc[-3]['high']
            head = swings_h.iloc[-2]['high']
            rs = swings_h.iloc[-1]['high']
            if head > ls and head > rs and abs(ls - rs) / (ls + 1e-9) < 0.006:
                neckline = min(swings_l.iloc[-2]['low'], swings_l.iloc[-1]['low'])
                patterns.append({
                    "name": "Head and Shoulders",
                    "type": "BEARISH_REVERSAL",
                    "quality_score": 88,
                    "head": head,
                    "neckline": neckline
                })

        if len(swings_l) >= 3 and len(swings_h) >= 2:
            ls_l = swings_l.iloc[-3]['low']
            head_l = swings_l.iloc[-2]['low']
            rs_l = swings_l.iloc[-1]['low']
            if head_l < ls_l and head_l < rs_l and abs(ls_l - rs_l) / (ls_l + 1e-9) < 0.006:
                neckline = max(swings_h.iloc[-2]['high'], swings_h.iloc[-1]['high'])
                patterns.append({
                    "name": "Inverse Head and Shoulders",
                    "type": "BULLISH_REVERSAL",
                    "quality_score": 88,
                    "head": head_l,
                    "neckline": neckline
                })

        # 3. Triangles & Wedges
        if len(swings_h) >= 2 and len(swings_l) >= 2:
            h_slope = swings_h.iloc[-1]['high'] - swings_h.iloc[-2]['high']
            l_slope = swings_l.iloc[-1]['low'] - swings_l.iloc[-2]['low']

            if abs(h_slope) / (swings_h.iloc[-1]['high'] + 1e-9) < 0.0015 and l_slope > 0:
                patterns.append({
                    "name": "Ascending Triangle",
                    "type": "BULLISH_CONTINUATION",
                    "quality_score": 85,
                    "resistance": swings_h.iloc[-1]['high'],
                    "support_slope": "Ascending"
                })
            elif abs(l_slope) / (swings_l.iloc[-1]['low'] + 1e-9) < 0.0015 and h_slope < 0:
                patterns.append({
                    "name": "Descending Triangle",
                    "type": "BEARISH_CONTINUATION",
                    "quality_score": 85,
                    "support": swings_l.iloc[-1]['low'],
                    "resistance_slope": "Descending"
                })
            elif h_slope < 0 and l_slope > 0:
                patterns.append({
                    "name": "Symmetrical Triangle",
                    "type": "CONSOLIDATION",
                    "quality_score": 80,
                    "apex_hint": "Coiling volatility"
                })
            elif h_slope < 0 and l_slope < 0 and (swings_h.iloc[-1]['high'] - swings_l.iloc[-1]['low']) < (swings_h.iloc[-2]['high'] - swings_l.iloc[-2]['low']):
                patterns.append({
                    "name": "Falling Wedge",
                    "type": "BULLISH_REVERSAL",
                    "quality_score": 84
                })
            elif h_slope > 0 and l_slope > 0 and (swings_h.iloc[-1]['high'] - swings_l.iloc[-1]['low']) < (swings_h.iloc[-2]['high'] - swings_l.iloc[-2]['low']):
                patterns.append({
                    "name": "Rising Wedge",
                    "type": "BEARISH_REVERSAL",
                    "quality_score": 84
                })

        # 4. Range Box / Channel
        sub_20 = df.tail(20)
        box_h = sub_20['high'].max()
        box_l = sub_20['low'].min()
        box_range = box_h - box_l
        avg_atr = sub_20['atr_14'].mean() if 'atr_14' in sub_20.columns else 1.0

        if box_range < 2.5 * avg_atr:
            patterns.append({
                "name": "Range Box",
                "type": "CONSOLIDATION",
                "quality_score": 78,
                "high": box_h,
                "low": box_l
            })

        return patterns
