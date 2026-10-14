"""
Session Volume Profile Engine:
Computes Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL)
for given lookback windows or sessions. 

The Point of Control (POC) represents the price level where the highest volume was traded.
Institutional buyers and sellers defend POCs as major magnets and liquidity shelves.
Value Area covers ~70% of the traded volume distribution.
"""
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


class VolumeProfileEngine:
    def __init__(self, value_area_pct: float = 0.70, num_bins: int = 50):
        self.value_area_pct = value_area_pct
        self.num_bins = num_bins

    def calculate_profile(self, df: pd.DataFrame, bars_lookback: int = 48) -> Dict[str, Any]:
        """
        Calculates POC, VAH, VAL over the last N bars (e.g. 48 bars on 15M/30M represents recent sessions).
        """
        if df is None or len(df) < 10:
            return {
                "poc": None,
                "vah": None,
                "val": None,
                "total_volume": 0.0,
                "price_to_poc_dist": None,
                "profile_bias": "NEUTRAL"
            }

        sample = df.tail(bars_lookback).copy()
        
        # Ensure volume exists; if volume is missing or flat, synthesize from range * tickproxy
        if "volume" not in sample.columns or sample["volume"].sum() <= 0:
            sample["volume"] = (sample["high"] - sample["low"]) * 1000.0 + 100.0

        low_min = sample["low"].min()
        high_max = sample["high"].max()

        if high_max <= low_min:
            last_c = float(sample["close"].iloc[-1])
            return {
                "poc": last_c,
                "vah": last_c,
                "val": last_c,
                "total_volume": float(sample["volume"].sum()),
                "price_to_poc_dist": 0.0,
                "profile_bias": "NEUTRAL"
            }

        # Create price bins
        bin_edges = np.linspace(low_min, high_max, self.num_bins + 1)
        bin_mids = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        bin_volumes = np.zeros(self.num_bins)

        # Distribute bar volume across bins that overlap the bar's [low, high]
        for _, row in sample.iterrows():
            bar_l = row["low"]
            bar_h = row["high"]
            bar_v = row["volume"]
            
            # Find bins overlapping with this bar
            mask = (bin_mids >= bar_l) & (bin_mids <= bar_h)
            num_overlapping = np.sum(mask)
            if num_overlapping > 0:
                bin_volumes[mask] += bar_v / num_overlapping
            else:
                # Closest bin gets volume
                closest_idx = np.abs(bin_mids - row["close"]).argmin()
                bin_volumes[closest_idx] += bar_v

        total_vol = float(np.sum(bin_volumes))
        if total_vol <= 0:
            total_vol = 1.0

        poc_idx = int(np.argmax(bin_volumes))
        poc_price = float(bin_mids[poc_idx])

        # Value area calculation (70% of total volume radiating out from POC)
        target_vol = total_vol * self.value_area_pct
        current_vol = bin_volumes[poc_idx]
        upper_idx = poc_idx
        lower_idx = poc_idx

        while current_vol < target_vol and (upper_idx < self.num_bins - 1 or lower_idx > 0):
            next_upper_vol = bin_volumes[upper_idx + 1] if upper_idx < self.num_bins - 1 else 0.0
            next_lower_vol = bin_volumes[lower_idx - 1] if lower_idx > 0 else 0.0

            if next_upper_vol >= next_lower_vol and upper_idx < self.num_bins - 1:
                upper_idx += 1
                current_vol += next_upper_vol
            elif lower_idx > 0:
                lower_idx -= 1
                current_vol += next_lower_vol
            elif upper_idx < self.num_bins - 1:
                upper_idx += 1
                current_vol += next_upper_vol
            else:
                break

        vah_price = float(bin_mids[upper_idx])
        val_price = float(bin_mids[lower_idx])
        current_close = float(sample["close"].iloc[-1])
        poc_dist = current_close - poc_price

        # Profile Bias:
        # Price above POC and Value Area -> Bullish institutional auction
        # Price below POC and Value Area -> Bearish auction
        # Inside Value Area -> Consolidation / Mean-reversion
        if current_close > vah_price:
            bias = "STRONG_BULLISH_EXPANSION"
        elif current_close > poc_price:
            bias = "MILD_BULLISH"
        elif current_close < val_price:
            bias = "STRONG_BEARISH_EXPANSION"
        elif current_close < poc_price:
            bias = "MILD_BEARISH"
        else:
            bias = "AT_POC_EQUILIBRIUM"

        return {
            "poc": round(poc_price, 2),
            "vah": round(vah_price, 2),
            "val": round(val_price, 2),
            "total_volume": round(total_vol, 2),
            "price_to_poc_dist": round(poc_dist, 2),
            "profile_bias": bias
        }
