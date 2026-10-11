"""
Multi-Strategy Backtest Runner:
Runs walk-forward backtests independently on each of the 8 strategies on XAUUSD,
applies quality gate criteria to each, and saves their pass/fail status.
"""
import yaml
import logging
import pandas as pd
from data.provider import get_data_provider
from indicators.engine import calculate_all_indicators
from analysis.confluence import ConfluenceAnalyzer
from strategy.modules import ALL_STRATEGIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("multi_strategy_backtest")


def backtest_single_strategy(strategy, df_ind: pd.DataFrame, spread: float = 0.25):
    analyzer = ConfluenceAnalyzer(yaml.safe_load(open("config/config.yaml")))
    trades = []
    active = None

    for i in range(100, len(df_ind)):
        curr_bar = df_ind.iloc[i]

        # Manage active
        if active is not None:
            if active["direction"] == "LONG":
                if curr_bar["low"] <= active["stop_loss"]:
                    trades.append({"pnl_r": -1.0, "outcome": "SL"})
                    active = None
                    continue
                elif curr_bar["high"] >= active["tp2"]:
                    trades.append({"pnl_r": 2.0, "outcome": "TP2"})
                    active = None
                    continue
            elif active["direction"] == "SHORT":
                if curr_bar["high"] >= active["stop_loss"]:
                    trades.append({"pnl_r": -1.0, "outcome": "SL"})
                    active = None
                    continue
                elif curr_bar["low"] <= active["tp2"]:
                    trades.append({"pnl_r": 2.0, "outcome": "TP2"})
                    active = None
                    continue

        if active is None:
            window = df_ind.iloc[:i]
            regime = analyzer.analyze_market_regime(window)[1]
            sig = strategy.evaluate(window, "XAUUSD", regime)
            if sig is not None:
                active = {
                    "direction": sig["direction"],
                    "entry": sig["entry"],
                    "stop_loss": sig["stop_loss"],
                    "tp1": sig["tp1"],
                    "tp2": sig["tp2"],
                    "strategy": strategy.name
                }

    total = len(trades)
    if total == 0:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0}

    wins = [t for t in trades if t["pnl_r"] > 0]
    losses = [t for t in trades if t["pnl_r"] < 0]
    win_rate = (len(wins) / total) * 100
    pf = (len(wins) * 2.0) / (len(losses) * 1.0 + 1e-9) if losses else 999.0
    exp = (len(wins) * 2.0 - len(losses) * 1.0) / total

    return {
        "trades": total,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "expectancy": round(exp, 2)
    }


def main():
    p = get_data_provider("yfinance")
    df = p.fetch_ohlcv("GC=F", "30m", limit=3000)
    df_ind = calculate_all_indicators(df)

    split = int(len(df_ind) * 0.65)
    train_df = df_ind.iloc[:split]
    test_df = df_ind.iloc[split:]

    print("\n" + "="*80)
    print("           INDEPENDENT MULTI-STRATEGY WALK-FORWARD REPORT (XAUUSD 30M)")
    print("="*80)
    print(f"{'Strategy Name':<32} | {'Train PF':<8} | {'Test PF':<8} | {'Test Trades':<11} | {'Quality Gate'}")
    print("-"*80)

    for strat in ALL_STRATEGIES:
        train_res = backtest_single_strategy(strat, train_df)
        test_res = backtest_single_strategy(strat, test_df)

        passed = test_res["profit_factor"] >= 1.3 and test_res["trades"] >= 5 and test_res["expectancy"] > 0
        verdict = "[PASS]" if passed else "[FAIL]"

        print(f"{strat.name:<32} | {train_res['profit_factor']:<8} | {test_res['profit_factor']:<8} | {test_res['trades']:<11} | {verdict}")

    print("="*80 + "\n")


if __name__ == "__main__":
    main()
