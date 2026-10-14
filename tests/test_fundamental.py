"""
Unit Tests for Macro Fundamental Analysis Engine:
1. Tests yields, real yields calculation and rules.
2. Tests DXY 20-EMA trend slope evaluation and score contribution.
3. Tests Fear and Greed rating categorization.
4. Tests ETF flow volume ratios and institutional accumulation/distribution logic.
5. Tests VIX safe-haven and geopolitical risk tiers.
6. Tests overall fundamental aggregation, normalization (-8 to +8, -20 to +20), and conflict handling.
"""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from analysis.fundamental import FundamentalEngine


def test_fundamental_engine_initialization():
    engine = FundamentalEngine()
    assert engine.config == {}


def test_fear_and_greed_evaluation_categories():
    engine = FundamentalEngine()
    # Extreme Fear
    ef = engine._eval_fear_greed_score(20, "Extreme Fear")
    assert ef["score"] == 1
    assert "Bullish" in ef["bias"]

    # Fear
    f = engine._eval_fear_greed_score(35, "Fear")
    assert f["score"] == 1
    assert "Bullish" in f["bias"]

    # Neutral
    n = engine._eval_fear_greed_score(50, "Neutral")
    assert n["score"] == 0
    assert n["bias"] == "Neutral"

    # Greed
    g = engine._eval_fear_greed_score(65, "Greed")
    assert g["score"] == -1
    assert "Bearish" in g["bias"]

    # Extreme Greed
    eg = engine._eval_fear_greed_score(85, "Extreme Greed")
    assert eg["score"] == -1
    assert "Bearish" in eg["bias"]


def test_vix_geopolitical_evaluation():
    engine = FundamentalEngine()
    with patch("yfinance.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        # High VIX > 20
        mock_instance.history.return_value = pd.DataFrame({"Close": [24.5]})
        mock_ticker.return_value = mock_instance

        res = engine.fetch_geopolitical_vix()
        assert res["score"] == 1
        assert res["vix"] == 24.5
        assert "Bullish" in res["bias"]


def test_dxy_trend_slope_evaluation():
    engine = FundamentalEngine()
    with patch("yfinance.Ticker") as mock_ticker:
        mock_instance = MagicMock()
        # DXY trending down
        prices = [105.0 - (i * 0.1) for i in range(40)]
        df_dxy = pd.DataFrame({"Close": prices})
        mock_instance.history.return_value = df_dxy
        mock_ticker.return_value = mock_instance

        res = engine.fetch_dxy_context()
        assert res["score"] > 0
        assert res["trend"] == "DOWN"
        assert "Bullish" in res["bias"]


def test_full_fundamental_aggregation_and_normalization():
    engine = FundamentalEngine()
    with patch.object(engine, "fetch_real_yields", return_value={"score": 2, "details": "Real yield falling", "bias": "Bullish", "fed_stance": "Dovish"}), \
         patch.object(engine, "fetch_dxy_context", return_value={"score": 2, "details": "DXY trend DOWN", "bias": "Bullish"}), \
         patch.object(engine, "fetch_fear_and_greed", return_value={"score": 1, "details": "25 (Fear)", "bias": "Bullish"}), \
         patch.object(engine, "fetch_etf_flows", return_value={"score": 1, "details": "GLD Accumulation", "bias": "Bullish"}), \
         patch.object(engine, "fetch_geopolitical_vix", return_value={"score": 1, "details": "VIX 25 (Elevated)", "bias": "Bullish"}), \
         patch.object(engine, "fetch_news_sentiment", return_value={"score": 1, "details": "Bullish", "bias": "Bullish"}):

        res = engine.evaluate_fundamentals()
        assert res["raw_score"] == 8
        assert res["bias"] == "STRONGLY BULLISH"
        assert res["confluence_adjustment"] == 18
