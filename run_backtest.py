"""
Runner script for Step 2 Backtest on XAUUSD (Gold).
Fetches data via provider, executes walk-forward out-of-sample backtest,
and reports results honestly.
"""
import yaml
import logging
import pandas as pd
from data.provider import get_data_provider
from backtest.engine import Backtester

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_backtest")

def main():
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    provider = get_data_provider("yfinance")
    symbol = "GC=F"
    timeframe = "30m"

    logger.info(f"Fetching {symbol} ({timeframe}) historical data...")
    try:
        df = provider.fetch_ohlcv(symbol, timeframe, limit=3000)
    except Exception as e:
        logger.error(f"Failed to fetch {symbol}: {e}")
        return

    logger.info(f"Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}.")
    
    backtester = Backtester(config)
    logger.info("Running Walk-Forward & Out-of-Sample Validation...")
    results = backtester.walk_forward_validation(df, symbol="XAUUSD", train_ratio=0.65)

    train = results["train"]
    test = results["test_out_of_sample"]
    mc = results["monte_carlo_test"]

    print("\n" + "="*60)
    print("               XAUUSD 30M BACKTEST REPORT")
    print("="*60)
    print(f"Train Period : {results['train_period']}")
    print(f"Test Period  : {results['test_period']}")
    print("-" * 60)
    print(f"TRAIN TRADES : {train['total_trades']}")
    print(f"Train WinRate: {train['win_rate']}%")
    print(f"Train PF     : {train['profit_factor']}")
    print(f"Train Exp(R) : {train['expectancy_r']} R")
    print(f"Train MaxDD  : {train['max_drawdown_r']} R")
    print("-" * 60)
    print(f"OUT-OF-SAMPLE TEST TRADES : {test['total_trades']}")
    print(f"Test WinRate              : {test['win_rate']}%")
    print(f"Test Profit Factor        : {test['profit_factor']}")
    print(f"Test Expectancy (R)       : {test['expectancy_r']} R")
    print(f"Test Max Drawdown         : {test['max_drawdown_r']} R")
    print(f"Test Max Losing Streak    : {test['max_losing_streak']} trades")
    print("-" * 60)
    print(f"MONTE CARLO (95th %ile Max DD)    : {mc['simulated_max_dd_95th']} R")
    print(f"MONTE CARLO (95th %ile Streak)    : {mc['simulated_max_streak_95th']} trades")
    print("="*60)
    print(f"QUALITY GATE VERDICT: {results['verdict']}")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
