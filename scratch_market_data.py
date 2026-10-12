import yfinance as yf
import pandas as pd

print("yfinance version:", yf.__version__)

for sym in ["GC=F", "XAUUSD=X"]:
    print(f"\n=================== Fetching: {sym} ===================")
    try:
        ticker = yf.Ticker(sym)
        df = ticker.history(period="5d", interval="30m")
        if df.empty:
            print(f"RESULT: {sym} returned an EMPTY DataFrame!")
        else:
            print(f"RESULT: {sym} shape = {df.shape}")
            cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            latest = df.tail(1)[cols]
            print(f"Latest candle timestamp: {df.index[-1]}")
            print(latest.to_string())
    except Exception as e:
        print(f"ERROR fetching {sym}: {e}")
