# 🥇 gold-signal-pro

> **Free, open-source, automated trading signal and technical analysis agent.**
> Alerts only. **NO automated broker execution. NO broker login or deposit required.**

---

## ⚠️ Non-Negotiable Risk Disclaimer

> **IMPORTANT TRADING DISCLAIMER**: Trading foreign exchange (Forex), commodities (Gold / XAUUSD), and CFDs involves substantial risk of loss and is not suitable for all investors. 
> - **Never trade with money you cannot afford to lose.**
> - Past performance and backtests do **NOT** guarantee future results.
> - This software makes **NO** claims of guaranteed profit, "no loss", or 90%+ win rates.
> - The software is provided purely for educational and analytical purposes.
> - **Always forward-test signals on a DEMO account for at least 4 to 8 weeks** before considering live execution.

---

## 📊 Objective Backtest Verdict & Quality Gate

In accordance with our **Honesty Rules**, any instrument and timeframe must pass an out-of-sample walk-forward backtest (minimum Profit Factor $\ge 1.3$, positive expectancy, $\ge 100$ trades after realistic spread and slippage deductions) before being unlocked for live signals:

| Instrument | Timeframe | Train PF | Out-of-Sample Test PF | Quality Gate Verdict | Live Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **XAUUSD (Gold)** | **30m** | 0.12 | 0.40 | ❌ **FAIL** | 🔒 **LOCKED (Demo/Paper Only)** |
| **XAUUSD (Gold)** | **1h** | 0.18 | 0.31 | ❌ **FAIL** | 🔒 **LOCKED (Demo/Paper Only)** |
| **XAUUSD (Gold)** | **Daily (Donchian)** | 1.48 | 2.43 | ✅ **PASS** | 🔓 Long-term context reference |

*Why did intraday 30m Gold fail the quality gate?*  
Gold exhibits strong intraday stop hunts, mean-reverting chop, and spread-widening volatility around session opens. Chasing breakouts without higher-timeframe swing context resulted in an out-of-sample profit factor below our 1.3 threshold. **Therefore, live signal generation remains safely locked by default.**

---

## ⚠️ Data Source Transparency

All signals are generated from **Yahoo Finance `GC=F`** (CME Globex Gold Futures, continuous contract).

| Fact | Detail |
| :--- | :--- |
| **Data provider** | Yahoo Finance (free, public API) |
| **Symbol used** | `GC=F` — CME Gold Futures (reference price) |
| **What it is NOT** | Exness XAUUSD / XAUUSDc CFD execution price |
| **Price difference** | Futures carry a small contango premium over spot CFD; values differ by \$1–\$5 at typical roll periods |
| **Broker integration** | ❌ No Exness live-feed integration exists in this codebase |
| **Effect on entries/stops** | Stated entry, SL, and TP levels are **reference prices** only.  Always verify against your broker's actual bid/ask before acting |

Every Telegram alert is labelled `[Source: Yahoo GC=F (Reference Futures)]`.  Never treat these prices as confirmed Exness execution prices.

---

## 🛠️ Architecture & Features

1. **9-Module Confluence Engine**: Trend (EMAs, Supertrend, ADX), Momentum (RSI, MACD), Volatility regimes (ATR, BB Squeeze), Market Structure (BOS), Horizontal & Round Levels ($2000/$2050), Candlesticks, Intermarket DXY correlation, and Session filtering.
2. **Paid-Bot Risk Protection (100% Free)**:
   - Dynamic stop loss based on ATR / structure.
   - Strict Risk-to-Reward $\ge 1:2$.
   - Multi-target take-profit ladder: TP1 (1R, break-even move), TP2 (2R), TP3 (3.5R).
   - Position-size lot calculator based on account balance and risk percentage.
3. **ForexFactory Economic News Filter**: Suppresses trades 30 minutes before and after high-impact USD economic events (NFP, CPI, FOMC, PPI).
4. **Visual AI Second Opinion**: Renders headless charts with indicators and asks Google Gemini 1.5 Flash Vision for independent pattern confirmation.
5. **Self-Monitoring & SQLite Tracking**: Automatically monitors active signals until conclusion and tracks rolling win-rate and profit factor.
6. **100% Free Cloud Execution**: Automated GitHub Actions scheduled workflow running on weekdays every 15 minutes.

---

## 🚀 Beginner Step-by-Step Setup Guide

You do **not** need any programming experience. Follow these exact steps:

### Step 1: Get your Free Telegram Bot Token & Chat ID
1. Open the **Telegram** app and search for `@BotFather`.
2. Send `/newbot`, give it a name (e.g. `MyGoldSignalBot`) and a username ending in `bot`.
3. Copy the **HTTP API Bot Token** provided by BotFather.
4. Search for `@userinfobot` on Telegram, tap **Start**, and copy your numerical **Id** (this is your Chat ID).
5. Open your newly created bot on Telegram and tap **Start** so it has permission to message you.

### Step 2: Set GitHub Secrets
1. Push this repository to your GitHub account.
2. In your GitHub repository, navigate to **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret** and add:
   - `TELEGRAM_BOT_TOKEN` : Your BotFather token.
   - `TELEGRAM_CHAT_ID` : Your numerical Telegram chat ID.
   - `GEMINI_API_KEY` : *(Optional for Visual AI)* Get a free key at [Google AI Studio](https://aistudio.google.com/).

### Step 3: Enable the Workflow
1. Go to the **Actions** tab in your repository.
2. Click **Gold Signal Pro Automated Engine** on the left menu.
3. Click **Run workflow** to test an immediate manual execution.
4. The workflow will now automatically run every 15 minutes during weekday trading hours!
