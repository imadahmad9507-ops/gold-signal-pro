"""
Pivot Points Calculator:
Calculates Classic, Camarilla, and Woodie pivot levels from Previous Day / Previous Week OHLC.
"""
from typing import Dict, Any


class PivotCalculator:
    @staticmethod
    def calculate_all_pivots(high: float, low: float, close: float, open_price: float = None) -> Dict[str, Dict[str, float]]:
        # 1. Classic Floor Pivots
        p = (high + low + close) / 3.0
        r1 = (2.0 * p) - low
        s1 = (2.0 * p) - high
        r2 = p + (high - low)
        s2 = p - (high - low)
        r3 = high + (2.0 * (p - low))
        s3 = low - (2.0 * (high - p))

        classic = {
            "P": round(p, 2), "R1": round(r1, 2), "S1": round(s1, 2),
            "R2": round(r2, 2), "S2": round(s2, 2), "R3": round(r3, 2), "S3": round(s3, 2)
        }

        # 2. Camarilla Pivots
        diff = high - low
        cam_r4 = close + (diff * (1.1 / 2.0))
        cam_r3 = close + (diff * (1.1 / 4.0))
        cam_s3 = close - (diff * (1.1 / 4.0))
        cam_s4 = close - (diff * (1.1 / 2.0))

        camarilla = {
            "R4": round(cam_r4, 2), "R3": round(cam_r3, 2),
            "S3": round(cam_s3, 2), "S4": round(cam_s4, 2)
        }

        # 3. Woodie Pivots
        op = open_price if open_price is not None else close
        wp = (high + low + (2.0 * op)) / 4.0
        wr1 = (2.0 * wp) - low
        ws1 = (2.0 * wp) - high

        woodie = {
            "P": round(wp, 2), "R1": round(wr1, 2), "S1": round(ws1, 2)
        }

        return {
            "classic": classic,
            "camarilla": camarilla,
            "woodie": woodie
        }
