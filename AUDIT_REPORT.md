# Detailed Architecture and Defect Audit Report
**Project:** gold-signal-pro  
**Audit Date:** 2026-10-12  
**Scope:** Full-repository analysis (data layer, strategies, confluence scoring, risk engine, persistence, calendar, GitHub Actions).

---

### Executive Defect Matrix

| ID | Module | Severity | Issue Summary | Impact |
|:---|:---|:---:|:---|:---|
| **CRIT-01** | `risk/manager.py` | **CRITICAL** | Silent floor rounding to `0.01` lot regardless of account risk ceiling. | On $50 account with $0.125 risk ceiling, a $5 stop loss risks $0.50 (400% of allowed risk). Fails to reject with `RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE`. |
| **CRIT-02** | `tracking/tracker.py` & `.github/workflows/signals.yml` | **CRITICAL** | Ephemeral runner state and SQLite merge conflicts; lack of idempotency deduplication key. | GitHub runners can drop or fail git-commit push on race conditions. Signals can be sent multiple times across runs because there is no unique setup hash deduplication. |
| **CRIT-03** | `news/calendar.py` | **CRITICAL** | Fail-open behavior when ForexFactory feed is unavailable. | If calendar download fails, `check_news_status` returns `is_safe: True` ("proceed with reduced confidence"), allowing trades right into major CPI/NFP news. Violates fail-closed policy. |
| **HIGH-01** | `data/provider.py` | **HIGH** | `GC=F` futures price treated as executable XAUUSD spot CFD price without validation or source labeling. | Futures and spot CFD have basis spread, different rollover schedules, and differing session closes. Incomplete live candles are not strictly filtered out. |
| **HIGH-02** | `main.py` & `analysis/confluence.py` | **HIGH** | Confluence score displayed as "Winning Percentage Probability" without calibration. | Labeling a rule-based 85/100 score as "68%-74% probability" is mathematically unfounded and misleading. |
| **HIGH-03** | `strategy/modules.py` & `main.py` | **HIGH** | Disconnected strategy execution: `main.py` ran an ad-hoc confluence check rather than running the 8 registered modular strategies with regime gating. | The 8 backtested strategy modules were never actually invoked in `main.py` to produce signals. |
| **MED-01** | `backtest/engine.py` | **MED** | Lookahead and intrabar collision ambiguities; assumes TP1 always triggers BE without slippage; does not record MAE/MFE. | Backtest accuracy degraded; optimistic assumptions on simultaneous SL/TP touches. |
| **MED-02** | `visual_ai/chart.py` | **MED** | Missing provider/source stamp, timeframe timezone labeling, and SMC visual zones. | Charts lacked explicit labeling that prices are derived from reference futures (`GC=F`) vs spot CFD. |
| **LOW-01** | `config/config.yaml` | **LOW** | Hardcoded spread and pip values without dynamic broker specification integration. | Lacks dynamic contract spec models for different account types (Cent vs Standard). |

---

### Phase-by-Phase Remediation Roadmap

1. **Phase 2 (Data Layer):**
   - Implement data validation engine (`DataValidator`) checking for gaps, timestamps, monotonic ordering, NaN/Inf, and incomplete candle filtering.
   - Separate Reference Data (`GC=F`) from Broker Spot Data (`XAUUSD`), add pluggable provider interface (`BaseDataProvider`), and enforce source stamping.
2. **Phase 3 (Risk Hardening):**
   - Implement exact monetary risk calculations taking contract size, tick value, spread, and commission into account.
   - If monetary risk at minimum volume (0.01) > allowed risk ceiling ($0.125 on $50 account), strictly reject setup with `RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE`.
   - Add maximum concurrent position and daily drawdown circuit breakers.
3. **Phase 4 (Confluence & SMC Alignment):**
   - Connect the 8 modular strategies directly into `main.py`.
   - Ensure confluence score is strictly labeled as rule-based confluence (not uncalibrated win probabilities).
   - Enforce regime gating (Trend vs Range vs Chaotic).
4. **Phase 5 (Backtest Hardening):**
   - Conservative intrabar resolution (if both SL and TP hit in same bar, conservative SL assumption unless finer data available).
   - Realized R calculations with exact partial exits (TP1 40%, TP2 40%, TP3 20%).
5. **Phase 6 & 7 (Persistence & Idempotency):**
   - Database schema upgrade with versioned migration support.
   - Support SQLite locally + durable Postgres / hosted URL integration with connection pooling and graceful offline queue.
   - Idempotency key `hash(symbol, strategy, timeframe, direction, candle_timestamp)`.
6. **Phase 8 (News Hardening):**
   - Fail-closed economic news calendar. If calendar is unavailable or stale, reject new signals immediately.
7. **Phase 9, 10, 11 (Operations & 6-Week Forward Testing Journal):**
   - Add structured forward-testing signal journal table (`journal_entries`).
   - Clean headless charts with source tags.
   - Update tests and run verification suite.
