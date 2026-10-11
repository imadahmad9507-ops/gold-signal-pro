"""
8 Modular Trading Strategy Implementations:
1. Trend Pullback
2. Breakout and Retest
3. Range Reversal
4. Smart-Money Style (Liquidity Sweep + BOS + Order Block)
5. Session Breakout (Asian / London Range Break)
6. Volatility / Bollinger Squeeze Expansion
7. Divergence Reversal (RSI/MACD divergence)
8. Previous Day/Week High-Low & Pivot Reaction
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import pandas as pd


class BaseStrategy(ABC):
    name: str = "BaseStrategy"
    compatible_regimes: list = ["TRENDING", "RANGING", "MODERATE"]

    @abstractmethod
    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        """
        Returns signal dict with 'direction', 'entry', 'stop_loss', 'tp1', 'tp2', 'tp3', 'reason' or None.
        Zero look-ahead: operates on closed candle history only.
        """
        pass


class TrendPullbackStrategy(BaseStrategy):
    name = "Trend Pullback"
    compatible_regimes = ["TRENDING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 50 or regime not in self.compatible_regimes:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = last['atr_14']
        c = last['close']
        ema20 = last['ema_20']
        ema50 = last['ema_50']
        ema200 = last['ema_200']

        # Bullish Pullback
        if ema20 > ema50 > ema200 and last['low'] <= ema20 * 1.002 and c > ema20 and 40 <= last['rsi_14'] <= 60:
            sl = min(last['low'], prev['low']) - 0.5 * atr
            rd = c - sl
            if rd <= 0 or rd > 3.0 * atr: return None
            return {
                "strategy": self.name,
                "direction": "LONG",
                "entry": c,
                "stop_loss": sl,
                "tp1": c + 1.0 * rd,
                "tp2": c + 2.0 * rd,
                "tp3": c + 3.5 * rd,
                "reason": f"Pullback to EMA 20 ({ema20:.2f}) with bullish resumption candle"
            }

        # Bearish Pullback
        if ema20 < ema50 < ema200 and last['high'] >= ema20 * 0.998 and c < ema20 and 40 <= last['rsi_14'] <= 60:
            sl = max(last['high'], prev['high']) + 0.5 * atr
            rd = sl - c
            if rd <= 0 or rd > 3.0 * atr: return None
            return {
                "strategy": self.name,
                "direction": "SHORT",
                "entry": c,
                "stop_loss": sl,
                "tp1": c - 1.0 * rd,
                "tp2": c - 2.0 * rd,
                "tp3": c - 3.5 * rd,
                "reason": f"Pullback to EMA 20 ({ema20:.2f}) with bearish rejection candle"
            }
        return None


class BreakoutRetestStrategy(BaseStrategy):
    name = "Breakout and Retest"
    compatible_regimes = ["TRENDING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 40 or regime not in self.compatible_regimes:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = last['atr_14']
        recent_20 = df.iloc[-25:-5]
        h20 = recent_20['high'].max()
        l20 = recent_20['low'].min()

        # Bullish Break & Retest
        if prev['low'] <= h20 <= prev['high'] and last['close'] > h20 and last['close'] > last['open']:
            sl = prev['low'] - 0.5 * atr
            rd = last['close'] - sl
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "LONG",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] + 1.0 * rd,
                "tp2": last['close'] + 2.0 * rd,
                "tp3": last['close'] + 3.5 * rd,
                "reason": f"Successful retest of key breakout level {h20:.2f}"
            }

        # Bearish Break & Retest
        if prev['low'] <= l20 <= prev['high'] and last['close'] < l20 and last['close'] < last['open']:
            sl = prev['high'] + 0.5 * atr
            rd = sl - last['close']
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "SHORT",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] - 1.0 * rd,
                "tp2": last['close'] - 2.0 * rd,
                "tp3": last['close'] - 3.5 * rd,
                "reason": f"Successful retest of breakdown level {l20:.2f}"
            }
        return None


class RangeReversalStrategy(BaseStrategy):
    name = "Range Reversal"
    compatible_regimes = ["RANGING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 30 or regime not in self.compatible_regimes:
            return None
        last = df.iloc[-1]
        atr = last['atr_14']
        bb_low = last['bb_lower']
        bb_high = last['bb_upper']

        # Oversold Range Edge Bounce
        if last['low'] <= bb_low and last['close'] > last['open'] and last['rsi_14'] < 35:
            sl = last['low'] - 0.5 * atr
            rd = last['close'] - sl
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "LONG",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] + 1.0 * rd,
                "tp2": last['bb_middle'],
                "tp3": bb_high,
                "reason": f"Mean-reversion bounce off lower Bollinger band ({bb_low:.2f}) with RSI {last['rsi_14']:.1f}"
            }

        # Overbought Range Edge Rejection
        if last['high'] >= bb_high and last['close'] < last['open'] and last['rsi_14'] > 65:
            sl = last['high'] + 0.5 * atr
            rd = sl - last['close']
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "SHORT",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] - 1.0 * rd,
                "tp2": last['bb_middle'],
                "tp3": bb_low,
                "reason": f"Mean-reversion rejection off upper Bollinger band ({bb_high:.2f}) with RSI {last['rsi_14']:.1f}"
            }
        return None


class SmartMoneyLiquidityStrategy(BaseStrategy):
    name = "Smart-Money Liquidity Sweep"
    compatible_regimes = ["TRENDING", "RANGING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 30:
            return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = last['atr_14']
        prev_10 = df.iloc[-15:-2]
        prior_low = prev_10['low'].min()
        prior_high = prev_10['high'].max()

        # Bullish Liquidity Sweep (Swept prior low, closed back inside with rejection)
        if prev['low'] < prior_low and prev['close'] > prior_low and last['close'] > last['open']:
            sl = prev['low'] - 0.3 * atr
            rd = last['close'] - sl
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "LONG",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] + 1.0 * rd,
                "tp2": last['close'] + 2.0 * rd,
                "tp3": prior_high,
                "reason": f"Liquidity sweep below prior low {prior_low:.2f} + institutional reclamation candle"
            }

        # Bearish Liquidity Sweep (Swept prior high, closed back below)
        if prev['high'] > prior_high and prev['close'] < prior_high and last['close'] < last['open']:
            sl = prev['high'] + 0.3 * atr
            rd = sl - last['close']
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "SHORT",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] - 1.0 * rd,
                "tp2": last['close'] - 2.0 * rd,
                "tp3": prior_low,
                "reason": f"Liquidity sweep above prior high {prior_high:.2f} + institutional sell order block"
            }
        return None


class SessionBreakoutStrategy(BaseStrategy):
    name = "Session Breakout"
    compatible_regimes = ["TRENDING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 20: return None
        last = df.iloc[-1]
        h = last.name.hour
        # London Open window: 07:00-09:00 UTC | NY Open window: 13:00-15:00 UTC
        if not ((7 <= h <= 9) or (13 <= h <= 15)):
            return None

        recent_bars = df.iloc[-12:-1]  # Asian or Pre-NY Range
        range_h = recent_bars['high'].max()
        range_l = recent_bars['low'].min()
        atr = last['atr_14']

        if last['close'] > range_h:
            sl = range_h - 1.2 * atr
            rd = last['close'] - sl
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "LONG",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] + 1.0 * rd,
                "tp2": last['close'] + 2.0 * rd,
                "tp3": last['close'] + 3.0 * rd,
                "reason": f"Session opening range expansion breakout above {range_h:.2f}"
            }
        elif last['close'] < range_l:
            sl = range_l + 1.2 * atr
            rd = sl - last['close']
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "SHORT",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] - 1.0 * rd,
                "tp2": last['close'] - 2.0 * rd,
                "tp3": last['close'] - 3.0 * rd,
                "reason": f"Session opening range breakdown below {range_l:.2f}"
            }
        return None


class VolatilitySqueezeStrategy(BaseStrategy):
    name = "Volatility Squeeze"
    compatible_regimes = ["TRENDING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 30: return None
        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = last['atr_14']
        avg_bb_width = df['bb_width'].tail(30).mean()

        # Was squeezed, now expanding
        if prev['bb_width'] < avg_bb_width * 0.75 and last['bb_width'] > prev['bb_width']:
            if last['close'] > last['bb_upper']:
                sl = last['bb_middle']
                rd = last['close'] - sl
                if rd <= 0: return None
                return {
                    "strategy": self.name,
                    "direction": "LONG",
                    "entry": last['close'],
                    "stop_loss": sl,
                    "tp1": last['close'] + 1.0 * rd,
                    "tp2": last['close'] + 2.0 * rd,
                    "tp3": last['close'] + 3.5 * rd,
                    "reason": "Bollinger squeeze volatility expansion breakout to the upside"
                }
            elif last['close'] < last['bb_lower']:
                sl = last['bb_middle']
                rd = sl - last['close']
                if rd <= 0: return None
                return {
                    "strategy": self.name,
                    "direction": "SHORT",
                    "entry": last['close'],
                    "stop_loss": sl,
                    "tp1": last['close'] - 1.0 * rd,
                    "tp2": last['close'] - 2.0 * rd,
                    "tp3": last['close'] - 3.5 * rd,
                    "reason": "Bollinger squeeze volatility expansion breakdown to the downside"
                }
        return None


class DivergenceReversalStrategy(BaseStrategy):
    name = "Divergence Reversal"
    compatible_regimes = ["RANGING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 40: return None
        last = df.iloc[-1]
        atr = last['atr_14']
        swings_l = df[df['swing_low'] == True].tail(2)
        swings_h = df[df['swing_high'] == True].tail(2)

        # Bullish Divergence (Lower Low on price, Higher Low on RSI)
        if len(swings_l) == 2:
            l1, l2 = swings_l.iloc[-2], swings_l.iloc[-1]
            if l2['low'] < l1['low'] and l2['rsi_14'] > l1['rsi_14'] and last['close'] > last['open']:
                sl = l2['low'] - 0.4 * atr
                rd = last['close'] - sl
                if rd <= 0: return None
                return {
                    "strategy": self.name,
                    "direction": "LONG",
                    "entry": last['close'],
                    "stop_loss": sl,
                    "tp1": last['close'] + 1.0 * rd,
                    "tp2": last['close'] + 2.0 * rd,
                    "tp3": last['close'] + 3.0 * rd,
                    "reason": f"Bullish RSI divergence (Price {l2['low']:.2f} vs RSI {l2['rsi_14']:.1f})"
                }

        # Bearish Divergence (Higher High on price, Lower High on RSI)
        if len(swings_h) == 2:
            h1, h2 = swings_h.iloc[-2], swings_h.iloc[-1]
            if h2['high'] > h1['high'] and h2['rsi_14'] < h1['rsi_14'] and last['close'] < last['open']:
                sl = h2['high'] + 0.4 * atr
                rd = sl - last['close']
                if rd <= 0: return None
                return {
                    "strategy": self.name,
                    "direction": "SHORT",
                    "entry": last['close'],
                    "stop_loss": sl,
                    "tp1": last['close'] - 1.0 * rd,
                    "tp2": last['close'] - 2.0 * rd,
                    "tp3": last['close'] - 3.0 * rd,
                    "reason": f"Bearish RSI divergence (Price {h2['high']:.2f} vs RSI {h2['rsi_14']:.1f})"
                }
        return None


class KeyLevelReactionStrategy(BaseStrategy):
    name = "Previous Day/Week Level Reaction"
    compatible_regimes = ["TRENDING", "RANGING", "MODERATE"]

    def evaluate(self, df: pd.DataFrame, symbol: str, regime: str) -> Optional[Dict[str, Any]]:
        if len(df) < 48: return None
        last = df.iloc[-1]
        atr = last['atr_14']
        pd_bars = df.iloc[-48:-24] if len(df) >= 48 else df.iloc[-24:]
        pdh = pd_bars['high'].max()
        pdl = pd_bars['low'].min()

        # Rejection off Previous Day High
        if last['high'] >= pdh and last['close'] < pdh and last['close'] < last['open']:
            sl = last['high'] + 0.3 * atr
            rd = sl - last['close']
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "SHORT",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] - 1.0 * rd,
                "tp2": last['close'] - 2.0 * rd,
                "tp3": pdl,
                "reason": f"Bearish rejection off Previous Day High ({pdh:.2f})"
            }

        # Rejection off Previous Day Low
        if last['low'] <= pdl and last['close'] > pdl and last['close'] > last['open']:
            sl = last['low'] - 0.3 * atr
            rd = last['close'] - sl
            if rd <= 0: return None
            return {
                "strategy": self.name,
                "direction": "LONG",
                "entry": last['close'],
                "stop_loss": sl,
                "tp1": last['close'] + 1.0 * rd,
                "tp2": last['close'] + 2.0 * rd,
                "tp3": pdh,
                "reason": f"Bullish bounce off Previous Day Low ({pdl:.2f})"
            }
        return None


ALL_STRATEGIES = [
    TrendPullbackStrategy(),
    BreakoutRetestStrategy(),
    RangeReversalStrategy(),
    SmartMoneyLiquidityStrategy(),
    SessionBreakoutStrategy(),
    VolatilitySqueezeStrategy(),
    DivergenceReversalStrategy(),
    KeyLevelReactionStrategy()
]
