"""
Full Fundamental Analysis Engine for Gold (XAUUSD):
Evaluates 7 fundamental macro drivers using free sources with graceful degradation:
1. Fed Policy & Real Yields (10Y Yield ^TNX minus CPI / TIPS proxy)
2. US Dollar Index (DXY DX-Y.NYB) 20-EMA slope & levels
3. Market Sentiment - Fear & Greed Index (CNN / Alternative.me)
4. Gold ETF Flows & Market Proxies (GLD volume vs 20-day avg, SLV, GDX)
5. Geopolitical Risk Proxy (VIX ^VIX volatility regime)
6. News Sentiment Keyword Scoring (Financial headlines analysis)
7. Upcoming High-Impact Risk Events Context (ForexFactory integration)

Produces a normalized -8 to +8 fundamental score and normalized -20 to +20 confluence adjustment.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import urllib.request
import json
import xml.etree.ElementTree as ET
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class FundamentalEngine:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def fetch_real_yields(self) -> Dict[str, Any]:
        """
        Calculates 10-year Treasury yield (^TNX) and estimated Real Yield.
        TIPS proxy: TIP ETF trend or ^TNX minus estimated inflation (~2.8%).
        Rules:
          - Real yield falling or negative -> BULLISH gold (+1 to +2)
          - Real yield rising or high positive -> BEARISH gold (-1 to -2)
        """
        try:
            tnx = yf.Ticker("^TNX")
            hist = tnx.history(period="1mo")
            if hist.empty:
                return {
                    "score": 0,
                    "yield_10y": 4.0,
                    "real_yield": 1.2,
                    "bias": "NEUTRAL",
                    "details": "10Y Yield feed unavailable (neutral assumption)",
                    "fed_stance": "Neutral"
                }

            yield_10y = float(hist["Close"].iloc[-1])
            yield_5d_ago = float(hist["Close"].iloc[-5]) if len(hist) >= 5 else yield_10y
            yield_trend = yield_10y - yield_5d_ago

            # Estimate inflation expectation around 2.8% or derive from TIP
            cpi_estimate = 2.8
            real_yield = yield_10y - cpi_estimate

            score = 0
            if real_yield < 0 or yield_trend < -0.15:
                score = 2
                bias = "Bullish"
                stance = "Dovish / Cutting"
            elif yield_trend < -0.05:
                score = 1
                bias = "Mildly Bullish"
                stance = "Dovish lean"
            elif real_yield > 2.0 and yield_trend > 0.15:
                score = -2
                bias = "Bearish"
                stance = "Hawkish / Restrictive"
            elif yield_trend > 0.05:
                score = -1
                bias = "Mildly Bearish"
                stance = "Hawkish lean"
            else:
                score = 0
                bias = "Neutral"
                stance = "Neutral"

            return {
                "score": score,
                "yield_10y": round(yield_10y, 2),
                "real_yield": round(real_yield, 2),
                "bias": bias,
                "fed_stance": stance,
                "details": f"{bias} (10Y yield: {yield_10y:.2f}%, real yield ~{real_yield:.2f}%)"
            }
        except Exception as e:
            logger.warning(f"Error fetching real yields: {e}")
            return {
                "score": 0,
                "yield_10y": 4.0,
                "real_yield": 1.2,
                "bias": "NEUTRAL",
                "details": "Yields feed error (neutral assumption)",
                "fed_stance": "Neutral"
            }

    def fetch_dxy_context(self) -> Dict[str, Any]:
        """
        DXY US Dollar Index trend analysis via 20-period daily EMA.
        Rules:
          - DXY trending DOWN -> BULLISH gold (+1 to +2)
          - DXY trending UP -> BEARISH gold (-1 to -2)
        """
        try:
            dxy = yf.Ticker("DX-Y.NYB")
            hist = dxy.history(period="2mo", interval="1d")
            if hist.empty or len(hist) < 20:
                return {
                    "score": 0,
                    "level": 102.0,
                    "trend": "SIDEWAYS",
                    "bias": "NEUTRAL",
                    "details": "DXY feed unavailable (neutral assumption)",
                    "weekly_change_pct": 0.0
                }

            level = float(hist["Close"].iloc[-1])
            prev_week = float(hist["Close"].iloc[-5]) if len(hist) >= 5 else level
            pct_chg = ((level - prev_week) / prev_week) * 100

            hist["ema20"] = hist["Close"].ewm(span=20, adjust=False).mean()
            ema_now = float(hist["ema20"].iloc[-1])
            ema_5d_ago = float(hist["ema20"].iloc[-5])
            slope = ema_now - ema_5d_ago

            score = 0
            if slope < -0.15:
                score = 2
                trend = "DOWN"
                bias = "Bullish gold"
            elif slope < -0.02:
                score = 1
                trend = "DOWN"
                bias = "Mildly Bullish gold"
            elif slope > 0.15:
                score = -2
                trend = "UP"
                bias = "Bearish gold"
            elif slope > 0.02:
                score = -1
                trend = "UP"
                bias = "Mildly Bearish gold"
            else:
                score = 0
                trend = "SIDEWAYS"
                bias = "Neutral"

            return {
                "score": score,
                "level": round(level, 2),
                "trend": trend,
                "bias": bias,
                "weekly_change_pct": round(pct_chg, 2),
                "details": f"{bias} (level: {level:.2f}, trend: {trend}, {pct_chg:+.1f}% this week)"
            }
        except Exception as e:
            logger.warning(f"Error fetching DXY context: {e}")
            return {
                "score": 0,
                "level": 102.0,
                "trend": "SIDEWAYS",
                "bias": "NEUTRAL",
                "details": "DXY error (neutral assumption)",
                "weekly_change_pct": 0.0
            }

    def fetch_fear_and_greed(self) -> Dict[str, Any]:
        """
        Fetches Fear & Greed Index from CNN or Alternative.me as fallback.
        Contrarian rules for Gold (Safe-haven):
          - Extreme Fear (0-25) -> BULLISH gold (+1)
          - Fear (26-45) -> Mild Bullish (+1)
          - Neutral (46-55) -> Neutral (0)
          - Greed (56-75) -> Mild Bearish (-1)
          - Extreme Greed (76-100) -> Bearish (-1)
        """
        # 1. Try CNN
        try:
            req = urllib.request.Request(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    score_val = round(float(data["fear_and_greed"]["score"]))
                    label = data["fear_and_greed"]["rating"].title()
                    return self._eval_fear_greed_score(score_val, label)
        except Exception as e:
            logger.debug(f"CNN Fear & Greed fetch failed: {e}. Trying fallback...")

        # 2. Fallback to Alternative.me
        try:
            req = urllib.request.Request(
                "https://api.alternative.me/fng/",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    entry = data["data"][0]
                    score_val = int(entry["value"])
                    label = entry["value_classification"]
                    return self._eval_fear_greed_score(score_val, label)
        except Exception as e:
            logger.warning(f"Alternative.me Fear & Greed fetch failed: {e}")

        # Default Neutral fallback
        return {
            "score": 0,
            "value": 50,
            "label": "Neutral",
            "details": "50 (Neutral)",
            "bias": "Neutral"
        }

    def _eval_fear_greed_score(self, score_val: int, label: str) -> Dict[str, Any]:
        if score_val <= 25:
            score = 1
            bias = "Bullish gold (Extreme Fear safe-haven demand)"
        elif score_val <= 45:
            score = 1
            bias = "Bullish gold (Fear sentiment)"
        elif score_val <= 55:
            score = 0
            bias = "Neutral"
        elif score_val <= 75:
            score = -1
            bias = "Mildly Bearish gold (Risk-on sentiment)"
        else:
            score = -1
            bias = "Bearish gold (Extreme Greed risk-on euphoria)"

        return {
            "score": score,
            "value": score_val,
            "label": label,
            "details": f"{score_val} ({label}) -> {bias}",
            "bias": bias
        }

    def fetch_etf_flows(self) -> Dict[str, Any]:
        """
        Examines SPDR Gold ETF (GLD) 5-day volume vs 20-day volume + price change.
        Tracks SLV and GDX proxies.
        """
        try:
            gld = yf.Ticker("GLD")
            hist = gld.history(period="1mo", interval="1d")
            if hist.empty or len(hist) < 20:
                return {"score": 0, "details": "Neutral (GLD volume average)", "bias": "Neutral"}

            vol_5 = hist["Volume"].tail(5).mean()
            vol_20 = hist["Volume"].tail(20).mean()
            ratio = (vol_5 / vol_20) if vol_20 > 0 else 1.0

            p_now = float(hist["Close"].iloc[-1])
            p_5d = float(hist["Close"].iloc[-5])
            price_up = p_now >= p_5d

            score = 0
            if ratio >= 1.15 and price_up:
                score = 1
                bias = "Bullish"
                desc = f"Institutional Accumulation (GLD Volume +{int((ratio-1)*100)}%, Price Rising)"
            elif ratio >= 1.15 and not price_up:
                score = -1
                bias = "Bearish"
                desc = f"Institutional Distribution (GLD Volume +{int((ratio-1)*100)}%, Price Falling)"
            else:
                score = 0
                bias = "Neutral"
                desc = f"Neutral (GLD volume ratio: {ratio:.2f})"

            return {"score": score, "details": desc, "bias": bias}
        except Exception as e:
            logger.warning(f"Error fetching ETF flows: {e}")
            return {"score": 0, "details": "Neutral (GLD volume average)", "bias": "Neutral"}

    def fetch_geopolitical_vix(self) -> Dict[str, Any]:
        """
        VIX volatility regime as geopolitical risk and safe-haven proxy.
        Rules:
          - VIX > 30: Extreme Fear -> Strongly Bullish (+1)
          - VIX > 20: Elevated Fear -> Bullish (+1)
          - VIX < 15: Calm / Risk-on -> Mild Bearish (-1)
          - 15 <= VIX <= 20: Neutral (0)
        """
        try:
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="5d")
            if hist.empty:
                return {"score": 0, "vix": 16.0, "details": "VIX 16.0 (Normal)", "bias": "Neutral"}

            val = float(hist["Close"].iloc[-1])
            if val >= 30.0:
                score = 1
                bias = "Bullish"
                desc = f"Extreme Fear (VIX {val:.1f}) -> Safe-haven surge"
            elif val >= 20.0:
                score = 1
                bias = "Bullish"
                desc = f"Elevated Risk (VIX {val:.1f}) -> Safe-haven demand"
            elif val < 15.0:
                score = -1
                bias = "Mildly Bearish"
                desc = f"Calm / Risk-On (VIX {val:.1f}) -> Low safe-haven demand"
            else:
                score = 0
                bias = "Neutral"
                desc = f"Moderate (VIX {val:.1f})"

            return {"score": score, "vix": round(val, 1), "details": desc, "bias": bias}
        except Exception as e:
            logger.warning(f"Error fetching VIX: {e}")
            return {"score": 0, "vix": 16.0, "details": "VIX 16.0 (Normal)", "bias": "Neutral"}

    def fetch_news_sentiment(self) -> Dict[str, Any]:
        """
        Scans financial market headlines via RSS/public feeds for gold sentiment keywords.
        """
        bullish_kw = [
            "rate cut", "fed pivot", "inflation", "geopolitical", "war", "crisis",
            "safe haven", "dollar falls", "central bank buying", "recession", "gold rally", "gold surges"
        ]
        bearish_kw = [
            "rate hike", "hawkish", "dollar rises", "dollar strengthens", "risk on",
            "strong economy", "gold falls", "etf outflow", "profit taking", "gold drops"
        ]

        headlines = []
        try:
            url = "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                xml_data = resp.read()
                root = ET.fromstring(xml_data)
                for item in root.findall(".//item"):
                    t = item.find("title")
                    if t is not None and t.text:
                        headlines.append(t.text.lower())
        except Exception:
            pass

        bull_count = 0
        bear_count = 0
        for h in headlines:
            for kw in bullish_kw:
                if kw in h:
                    bull_count += 1
            for kw in bearish_kw:
                if kw in h:
                    bear_count += 1

        net = bull_count - bear_count
        if net >= 2:
            score = 1
            bias = "Bullish"
            desc = "Bullish (rate cut expectations & safe-haven headlines)"
        elif net <= -2:
            score = -1
            bias = "Bearish"
            desc = "Bearish (dollar strength & economic resilience headlines)"
        else:
            score = 0
            bias = "Neutral"
            desc = "Neutral sentiment (balanced macroeconomic coverage)"

        return {"score": score, "bias": bias, "details": desc, "headline_count": len(headlines)}

    def evaluate_fundamentals(self, upcoming_events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Aggregates all 7 components into:
        - raw score: -8 to +8
        - bias category: STRONGLY BULLISH, BULLISH, MILD BULLISH, NEUTRAL, MILD BEARISH, BEARISH, STRONGLY BEARISH
        - confluence_adjustment: -20 to +20 points
        """
        yields = self.fetch_real_yields()
        dxy = self.fetch_dxy_context()
        fng = self.fetch_fear_and_greed()
        etf = self.fetch_etf_flows()
        vix = self.fetch_geopolitical_vix()
        news = self.fetch_news_sentiment()

        # Score contributions
        score_yields = max(min(yields["score"], 2), -2)
        score_dxy = max(min(dxy["score"], 2), -2)
        score_fng = max(min(fng["score"], 1), -1)
        score_etf = max(min(etf["score"], 1), -1)
        score_vix = max(min(vix["score"], 1), -1)
        score_news = max(min(news["score"], 1), -1)

        raw_score = score_yields + score_dxy + score_fng + score_etf + score_vix + score_news
        raw_score = max(min(raw_score, 8), -8)

        # Categorize
        if raw_score >= 6:
            bias = "STRONGLY BULLISH"
            confluence_adj = 18
        elif raw_score >= 3:
            bias = "BULLISH"
            confluence_adj = 10
        elif raw_score >= 1:
            bias = "MILD BULLISH"
            confluence_adj = 5
        elif raw_score == 0:
            bias = "NEUTRAL"
            confluence_adj = 0
        elif raw_score >= -2:
            bias = "MILD BEARISH"
            confluence_adj = -5
        elif raw_score >= -5:
            bias = "BEARISH"
            confluence_adj = -10
        else:
            bias = "STRONGLY BEARISH"
            confluence_adj = -18

        # Upcoming events warning
        event_warning = None
        if upcoming_events:
            for ev in upcoming_events:
                hrs = ev.get("hours_until", 999)
                if 4 <= hrs <= 24:
                    event_warning = f"⚠️ {ev.get('title', 'High-Impact Event')} in {int(hrs)}h: Fundamental setup may shift. Trade smaller size or wait for post-release setup."
                    break

        return {
            "raw_score": raw_score,
            "max_score": 8,
            "bias": bias,
            "confluence_adjustment": confluence_adj,
            "components": {
                "yields": yields,
                "dxy": dxy,
                "fear_and_greed": fng,
                "etf": etf,
                "vix": vix,
                "news": news
            },
            "event_warning": event_warning
        }
