"""
Confluence Analysis Engine:
Implements 9 modular evaluators:
1. Trend (EMA 20/50/200, ADX, Supertrend, HTF alignment)
2. Momentum (RSI, MACD)
3. Volatility (ATR, Bollinger squeeze/expansion)
4. Market Structure (BOS, ChoCH, Swings)
5. Support / Resistance (Swing clusters, round numbers e.g. $2000/$2050 for Gold, Fibonacci retracement)
6. Candlestick Confirmation (Engulfing, Pin bar/Hammer at key levels)
7. Intermarket Confirmation (DXY, 10Y Yield inverse direction)
8. Market Regime (Trending vs Ranging vs High-Volatility/Chaotic)
9. Session Analysis (London, NY, Asian, avoid rollover)
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, Optional


class ConfluenceAnalyzer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.weights = config.get("scoring", {}).get("weights", {
            "trend": 25,
            "momentum": 15,
            "volatility": 10,
            "market_structure": 20,
            "support_resistance": 15,
            "candlestick": 5,
            "intermarket": 5,
            "regime": 5
        })

    def analyze_trend(self, df_entry: pd.DataFrame, df_htf_1h: Optional[pd.DataFrame] = None, df_htf_4h: Optional[pd.DataFrame] = None) -> Tuple[float, str, str]:
        """Returns (score_ratio 0..1, bias 'LONG'/'SHORT'/'NEUTRAL', reason_str)"""
        last = df_entry.iloc[-1]
        c = last['close']
        ema20 = last['ema_20']
        ema50 = last['ema_50']
        ema200 = last['ema_200']
        st_dir = last['supertrend_dir']
        adx = last['adx']

        long_points = 0
        short_points = 0
        total_checks = 6

        if c > ema20 > ema50 > ema200:
            long_points += 3
        elif c < ema20 < ema50 < ema200:
            short_points += 3
        else:
            if c > ema50:
                long_points += 1
            elif c < ema50:
                short_points += 1

        if st_dir == 1:
            long_points += 1
        elif st_dir == -1:
            short_points += 1

        if adx > 22:
            if long_points > short_points:
                long_points += 1
            elif short_points > long_points:
                short_points += 1

        # Higher timeframe alignment
        if df_htf_1h is not None and not df_htf_1h.empty:
            htf1_last = df_htf_1h.iloc[-1]
            if htf1_last['close'] > htf1_last.get('ema_50', htf1_last['close']):
                long_points += 1
            else:
                short_points += 1
            total_checks += 1

        if df_htf_4h is not None and not df_htf_4h.empty:
            htf4_last = df_htf_4h.iloc[-1]
            if htf4_last['close'] > htf4_last.get('ema_200', htf4_last['close']):
                long_points += 1
            else:
                short_points += 1
            total_checks += 1

        if long_points >= 4 and long_points > short_points + 1:
            score = long_points / total_checks
            return score, "LONG", f"Bullish trend alignment across EMAs, Supertrend, and HTF (ADX: {adx:.1f})"
        elif short_points >= 4 and short_points > long_points + 1:
            score = short_points / total_checks
            return score, "SHORT", f"Bearish trend alignment across EMAs, Supertrend, and HTF (ADX: {adx:.1f})"
        return 0.1, "NEUTRAL", "Trend is mixed or flat"

    def analyze_momentum(self, df: pd.DataFrame, bias: str) -> Tuple[float, str]:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        rsi = last['rsi_14']
        macd = last['macd']
        macd_signal = last['macd_signal']
        macd_hist = last['macd_hist']

        score = 0.0
        reasons = []

        if bias == "LONG":
            # RSI oversold bounce or healthy trend zone (45 - 65)
            if 30 <= rsi <= 60 and rsi > prev['rsi_14']:
                score += 0.5
                reasons.append(f"RSI curling up ({rsi:.1f})")
            # MACD bullish cross or expanding positive histogram
            if macd > macd_signal or macd_hist > prev['macd_hist']:
                score += 0.5
                reasons.append("MACD histogram bullish momentum")
        elif bias == "SHORT":
            if 40 <= rsi <= 70 and rsi < prev['rsi_14']:
                score += 0.5
                reasons.append(f"RSI turning down ({rsi:.1f})")
            if macd < macd_signal or macd_hist < prev['macd_hist']:
                score += 0.5
                reasons.append("MACD histogram bearish momentum")
        else:
            return 0.1, "Neutral momentum"

        return min(score, 1.0), "; ".join(reasons) if reasons else "Moderate momentum"

    def analyze_volatility(self, df: pd.DataFrame) -> Tuple[float, str]:
        last = df.iloc[-1]
        bb_width = last['bb_width']
        avg_bb_width = df['bb_width'].tail(50).mean()
        
        # Avoid extreme spikes (abnormal news explosion) or total dead flat
        if bb_width > avg_bb_width * 2.8:
            return 0.2, "Excessive volatility expansion (high risk/wide spreads)"
        elif bb_width < avg_bb_width * 0.4:
            return 0.4, "Tight squeeze (breakout pending)"
        else:
            return 0.9, f"Controlled healthy volatility regime (ATR {last['atr_14']:.2f})"

    def analyze_market_structure(self, df: pd.DataFrame, bias: str) -> Tuple[float, str]:
        """Detect swing break of structure (BOS) beyond recent 20-bar channel."""
        if len(df) < 25:
            return 0.5, "Insufficient bars for structure"

        prev_bars = df.iloc[-21:-1]
        last_bar = df.iloc[-1]
        last_c = last_bar['close']

        if bias == "LONG":
            channel_high = prev_bars['high'].max()
            if last_c > channel_high:
                return 1.0, f"Bullish Break of Structure (BOS) closed above 20-bar high ({channel_high:.2f})"
            return 0.2, f"Below structural high ({channel_high:.2f})"
        elif bias == "SHORT":
            channel_low = prev_bars['low'].min()
            if last_c < channel_low:
                return 1.0, f"Bearish Break of Structure (BOS) closed below 20-bar low ({channel_low:.2f})"
            return 0.2, f"Above structural low ({channel_low:.2f})"

        return 0.2, "Neutral structure"

    def analyze_support_resistance(self, df: pd.DataFrame, symbol: str, bias: str) -> Tuple[float, str]:
        last_c = df.iloc[-1]['close']
        score = 0.5
        notes = []

        # 1. Round numbers (especially critical for Gold, e.g. multiples of $50 or $10)
        if "GC" in symbol or "XAU" in symbol:
            rem50 = last_c % 50
            dist_to_key = min(rem50, 50 - rem50)
            if dist_to_key <= 3.0:
                score += 0.3
                notes.append(f"Near psychological round level ({round(last_c/50)*50:.0f})")

        # 2. Daily Pivot Points
        recent_bars = df.tail(48) # roughly 1 day of 30m bars
        h = recent_bars['high'].max()
        l = recent_bars['low'].min()
        c = recent_bars['close'].iloc[-1]
        pivot = (h + l + c) / 3

        if bias == "LONG" and last_c > pivot:
            score += 0.2
            notes.append(f"Trading above Day Pivot ({pivot:.2f})")
        elif bias == "SHORT" and last_c < pivot:
            score += 0.2
            notes.append(f"Trading below Day Pivot ({pivot:.2f})")

        return min(score, 1.0), "; ".join(notes) if notes else "Intermediate level"

    def analyze_candlestick(self, df: pd.DataFrame, bias: str) -> Tuple[float, str]:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        body = abs(last['close'] - last['open'])
        full_range = last['high'] - last['low'] + 1e-9

        # Engulfing
        if bias == "LONG":
            bull_engulf = (prev['close'] < prev['open']) and (last['close'] > last['open']) and (last['close'] >= prev['open'])
            hammer = (last['close'] > last['open']) and ((min(last['open'], last['close']) - last['low']) > 1.8 * body)
            if bull_engulf:
                return 0.9, "Bullish Engulfing candle confirmed at support"
            if hammer:
                return 0.85, "Hammer / Pin bar rejection candle"
        elif bias == "SHORT":
            bear_engulf = (prev['close'] > prev['open']) and (last['close'] < last['open']) and (last['close'] <= prev['open'])
            shooting_star = (last['close'] < last['open']) and ((last['high'] - max(last['open'], last['close'])) > 1.8 * body)
            if bear_engulf:
                return 0.9, "Bearish Engulfing candle confirmed at resistance"
            if shooting_star:
                return 0.85, "Shooting Star / Pin bar rejection candle"

        return 0.4, "Standard price action candle"

    def analyze_intermarket(self, df_dxy: Optional[pd.DataFrame], symbol: str, bias: str) -> Tuple[float, str]:
        if "GC" not in symbol and "XAU" not in symbol:
            return 0.5, "Non-gold instrument (neutral intermarket)"
        if df_dxy is None or df_dxy.empty or len(df_dxy) < 5:
            return 0.5, "DXY data feed unavailable (neutral assumption)"

        dxy_last = df_dxy.iloc[-1]['close']
        dxy_ma = df_dxy['close'].tail(20).mean()
        dxy_rising = dxy_last > dxy_ma

        # Gold normally has inverse correlation to US Dollar Index
        if bias == "LONG":
            if not dxy_rising:
                return 0.9, f"DXY softening below short-term trend ({dxy_last:.2f}), confirming gold tailwind"
            else:
                return 0.2, f"Warning: DXY is strengthening ({dxy_last:.2f}), diverging from gold long"
        elif bias == "SHORT":
            if dxy_rising:
                return 0.9, f"DXY rising above trend ({dxy_last:.2f}), supporting bearish gold pressure"
            else:
                return 0.2, f"Warning: DXY softening ({dxy_last:.2f}), diverging from gold short"

        return 0.5, "DXY neutral"

    def analyze_market_regime(self, df: pd.DataFrame) -> Tuple[float, str, str]:
        last = df.iloc[-1]
        adx = last['adx']
        bb_width = last['bb_width']
        avg_bb_width = df['bb_width'].tail(50).mean()

        if adx >= 25 and bb_width >= avg_bb_width * 0.9:
            return 0.9, "TRENDING", "Strong trend regime (favorable for directional confluence)"
        elif adx < 20 and bb_width < avg_bb_width * 0.8:
            return 0.4, "RANGING", "Tight range-bound regime (lower directional probability)"
        elif bb_width > avg_bb_width * 2.5:
            return 0.2, "CHAOTIC", "Extreme volatility regime (no trades recommended)"
        return 0.6, "MODERATE", "Normal market conditions"

    def analyze_session(self, timestamp: pd.Timestamp) -> Tuple[float, str, bool]:
        """Examines UTC timestamp for market session. Avoids daily rollover window (21:00-23:00 UTC)."""
        hour = timestamp.hour
        # Rollover avoid
        if 21 <= hour <= 22:
            return 0.1, "Rollover window (spreads wide, illiquid)", False

        # London session: 07:00 - 16:00 UTC
        # NY session: 12:00 - 21:00 UTC
        # London-NY Overlap: 12:00 - 16:00 UTC
        if 12 <= hour <= 16:
            return 1.0, "London / New York Overlap (peak liquidity & volume)", True
        elif 7 <= hour < 12:
            return 0.85, "London Session (active liquidity)", True
        elif 16 < hour <= 20:
            return 0.75, "New York Afternoon Session", True
        elif 0 <= hour < 7:
            return 0.4, "Asian Session (lower volume for metals)", True
        return 0.3, "Late off-peak session", True

    def calculate_confluence(
        self,
        df_entry: pd.DataFrame,
        symbol: str,
        df_htf_1h: Optional[pd.DataFrame] = None,
        df_htf_4h: Optional[pd.DataFrame] = None,
        df_dxy: Optional[pd.DataFrame] = None,
        fundamental_res: Optional[Dict[str, Any]] = None,
        session_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Aggregates technical, fundamental, and session evaluators into a final score (0-100) and grade."""
        last_time = df_entry.index[-1]
        
        # 1. Trend
        t_score, bias, t_reason = self.analyze_trend(df_entry, df_htf_1h, df_htf_4h)
        if bias == "NEUTRAL":
            return {"grade": "C", "total_score": 30, "bias": "NEUTRAL", "reasons": ["Mixed market direction"], "is_tradeable": False}

        # 2. Momentum
        m_score, m_reason = self.analyze_momentum(df_entry, bias)
        # 3. Volatility
        v_score, v_reason = self.analyze_volatility(df_entry)
        # 4. Structure
        s_score, s_reason = self.analyze_market_structure(df_entry, bias)
        # 5. S/R
        sr_score, sr_reason = self.analyze_support_resistance(df_entry, symbol, bias)
        # 6. Candlestick
        c_score, c_reason = self.analyze_candlestick(df_entry, bias)
        # 7. Intermarket
        im_score, im_reason = self.analyze_intermarket(df_dxy, symbol, bias)
        # 8. Regime
        reg_score, reg_type, reg_reason = self.analyze_market_regime(df_entry)
        # 9. Session
        sess_score, sess_desc, sess_valid = self.analyze_session(last_time)

        # Weighted technical calculation
        score_breakdown = {
            "trend": t_score * self.weights["trend"],
            "momentum": m_score * self.weights["momentum"],
            "volatility": v_score * self.weights["volatility"],
            "market_structure": s_score * self.weights["market_structure"],
            "support_resistance": sr_score * self.weights["support_resistance"],
            "candlestick": c_score * self.weights["candlestick"],
            "intermarket": im_score * self.weights["intermarket"],
            "regime": reg_score * self.weights["regime"]
        }
        technical_score = sum(score_breakdown.values())

        if not sess_valid:
            technical_score *= 0.5
        if reg_type == "CHAOTIC":
            technical_score *= 0.4

        technical_score = round(min(max(technical_score, 0), 100), 1)
        total_score = technical_score

        # 10. Fundamental Integration
        fund_boost = 0
        fund_conflict = False
        fund_bias = "NEUTRAL"
        fund_reason = None
        if fundamental_res is not None:
            fund_bias = fundamental_res.get("bias", "NEUTRAL")
            adj = fundamental_res.get("confluence_adjustment", 0)

            # Check directional agreement
            is_bullish_fund = "BULLISH" in fund_bias
            is_bearish_fund = "BEARISH" in fund_bias

            if (bias == "LONG" and is_bullish_fund) or (bias == "SHORT" and is_bearish_fund):
                fund_boost = adj + 5  # Bonus +5 for agreement
                fund_reason = f"Fundamentals AGREE with technical {bias} ({fund_bias}, +{fund_boost} pts)"
            elif (bias == "LONG" and is_bearish_fund) or (bias == "SHORT" and is_bullish_fund):
                fund_boost = -abs(adj) - 10
                fund_conflict = True
                fund_reason = f"CRITICAL WARNING: Fundamentals CONFLICT with technical {bias} ({fund_bias}, {fund_boost} pts)"
            else:
                fund_boost = 0
                fund_reason = f"Fundamentals neutral or mixed ({fund_bias})"

            total_score += fund_boost

        # 11. Session Boost Integration
        session_boost = 0
        if session_info is not None:
            session_boost = session_info.get("session_boost", 0)
            total_score += session_boost

        total_score = round(min(max(total_score, 0), 100), 1)

        grade = "C"
        min_a_plus = self.config.get("scoring", {}).get("min_grade_a_plus", 85)
        min_a = self.config.get("scoring", {}).get("min_grade_a", 75)
        min_b = self.config.get("scoring", {}).get("min_grade_b", 68)

        # Critical Rule: If fundamental bias STRONGLY conflicts, block A+ grade
        if fund_conflict and "STRONGLY" in fund_bias:
            grade = "C"
        elif total_score >= min_a_plus:
            grade = "A+"
        elif total_score >= min_a:
            grade = "A"
        elif total_score >= min_b:
            grade = "B"

        reasons = [
            f"• Trend: {t_reason}",
            f"• Structure: {s_reason}",
            f"• Momentum: {m_reason}",
            f"• Levels: {sr_reason}",
            f"• Candlestick: {c_reason}",
            f"• Intermarket: {im_reason}",
            f"• Session & Regime: {sess_desc} ({reg_type})"
        ]
        if fund_reason:
            reasons.append(f"• Macro Fundamentals: {fund_reason}")

        return {
            "bias": bias,
            "total_score": total_score,
            "technical_score": technical_score,
            "fundamental_boost": fund_boost,
            "session_boost": session_boost,
            "fundamental_conflict": fund_conflict,
            "fundamental_bias": fund_bias,
            "grade": grade,
            "breakdown": score_breakdown,
            "regime": reg_type,
            "session": sess_desc,
            "reasons": reasons,
            "is_tradeable": grade in self.config.get("scoring", {}).get("send_grades", ["A", "B"])
        }

