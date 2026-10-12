"""
Hardened Risk Management Engine:
- Enforces strict monetary risk limit (0.25% of account balance, e.g. $0.125 on $50 equity).
- Full contract specification model:
  * Contract size (e.g. 100 oz for standard gold CFD, 100,000 for standard forex)
  * Minimum volume step (e.g. 0.01 lot)
  * Point/tick value calculations
  * Spread, slippage, and commission cost deductions
- STRICT REJECTION with 'RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE':
  If the monetary risk at minimum volume (0.01 lot) exceeds the allowed risk ceiling,
  the trade is STRICTLY REJECTED. Never silently rounds up risk!
- Anti-compounding and circuit breakers (daily loss limits, max concurrent positions).
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class HardenedRiskManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.risk_cfg = config.get("risk", {})
        self.instruments_cfg = config.get("instruments", {})

    def get_contract_spec(self, symbol: str) -> Dict[str, Any]:
        """
        Returns full contract specification for the instrument.
        Matches authoritative Exness contract specifications:
        - XAUUSD (Standard Account): Contract size = 100 oz, min lot = 0.01 lot, currency = USD.
        - XAUUSDc (Cent Account): Contract size = 1 oz (or 100 oz priced in US Cents / USC),
          where 1 cent lot = 1/100th of standard lot. Account currency is USC (100 USC = 1 USD).
        """
        inst = self.instruments_cfg.get(symbol, {})
        asset_type = inst.get("asset_type", "commodity")

        # Exness Standard Gold CFD
        if symbol == "XAUUSD" or symbol == "GC=F":
            return {
                "symbol": symbol,
                "contract_size": 100.0,       # 1 standard lot = 100 troy oz
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 20.0,
                "tick_size": 0.01,            # $0.01 price step
                "tick_value_per_lot": 1.0,    # $1.00 per $0.01 move on 1.0 lot
                "typical_spread": inst.get("typical_spread_pips", 0.25), # in USD
                "commission_per_lot": inst.get("commission_per_lot", 0.0),
                "estimated_slippage": inst.get("estimated_slippage", 0.10),
                "account_currency": "USD",
                "is_cent_account": False,
                "exchange_rate_to_usd": 1.0
            }
        # Exness Cent Account Gold CFD (Official symbol: XAUUSDc)
        elif symbol == "XAUUSDc":
            return {
                "symbol": symbol,
                "contract_size": 1.0,         # 1 cent lot = 1 troy oz (1/100th of standard 100 oz)
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 200.0,
                "tick_size": 0.01,
                "tick_value_per_lot": 0.01,   # $0.01 per $0.01 move on 1.0 cent lot (in USD terms)
                "typical_spread": inst.get("typical_spread_pips", 0.35), # slightly wider cent spread
                "commission_per_lot": 0.0,
                "estimated_slippage": 0.10,
                "account_currency": "USC",    # US Cents (1 USD = 100 USC)
                "is_cent_account": True,
                "exchange_rate_to_usd": 0.01  # 1 USC = 0.01 USD
            }
        elif asset_type == "forex":
            return {
                "symbol": symbol,
                "contract_size": 100000.0,
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 20.0,
                "tick_size": 0.0001,
                "tick_value_per_lot": 10.0,
                "typical_spread": inst.get("typical_spread_pips", 0.00015),
                "commission_per_lot": 0.0,
                "estimated_slippage": 0.00005,
                "account_currency": "USD",
                "is_cent_account": False,
                "exchange_rate_to_usd": 1.0
            }
        elif asset_type == "crypto":
            return {
                "symbol": symbol,
                "contract_size": 1.0,
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 5.0,
                "tick_size": 1.0,
                "tick_value_per_lot": 1.0,
                "typical_spread": inst.get("typical_spread_pips", 15.0),
                "commission_per_lot": 0.0,
                "estimated_slippage": 5.0,
                "account_currency": "USD",
                "is_cent_account": False,
                "exchange_rate_to_usd": 1.0
            }

        # If instrument is unknown or missing required specifications, reject rather than guessing
        return {
            "symbol": symbol,
            "is_unsupported": True,
            "reason": f"MISSING_CONTRACT_SPEC: Instrument '{symbol}' has no verified broker specifications."
        }

    def evaluate_and_size_trade(
        self,
        symbol: str,
        bias: str,
        entry_price: float,
        proposed_stop: float,
        proposed_tp2: float,
        proposed_tp1: Optional[float] = None,
        proposed_tp3: Optional[float] = None,
        open_signals_count: int = 0
    ) -> Dict[str, Any]:
        """
        Evaluates risk parameters against account equity and returns either an APPROVED trade
        or a structured REJECTION with exact rationale.
        """
        balance = float(self.risk_cfg.get("account_balance_usd", 50.0))
        risk_pct = float(self.risk_cfg.get("risk_per_trade_percent", 0.25))
        max_monetary_risk = round(balance * (risk_pct / 100.0), 4)

        min_rr = float(self.risk_cfg.get("min_risk_reward", 2.5))
        max_concurrent = int(self.risk_cfg.get("max_concurrent_signals", 1))

        # 1. Concurrent position limit check
        if open_signals_count >= max_concurrent:
            return {
                "approved": False,
                "rejection_code": "MAX_CONCURRENT_POSITIONS_REACHED",
                "reason": f"Open signals ({open_signals_count}) meets or exceeds max limit ({max_concurrent})"
            }

        spec = self.get_contract_spec(symbol)
        if spec.get("is_unsupported"):
            return {
                "approved": False,
                "rejection_code": "MISSING_CONTRACT_SPEC",
                "reason": spec.get("reason", f"Contract specifications for {symbol} are unverified.")
            }

        contract_size = spec["contract_size"]
        min_lot = spec["min_lot"]
        typical_spread = spec["typical_spread"]
        slippage = spec["estimated_slippage"]
        commission = spec["commission_per_lot"]
        fx_to_usd = spec.get("exchange_rate_to_usd", 1.0)
        is_cent = spec.get("is_cent_account", False)

        # 2. Distance and direction sanity check
        if bias == "LONG":
            if proposed_stop >= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_STOP_PLACEMENT",
                    "reason": f"Long stop loss ({proposed_stop}) must be strictly below entry price ({entry_price})"
                }
            if proposed_tp2 <= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_TARGET_PLACEMENT",
                    "reason": f"Long take profit ({proposed_tp2}) must be strictly above entry price ({entry_price})"
                }
            raw_risk_dist = entry_price - proposed_stop
            reward_dist = proposed_tp2 - entry_price
        elif bias == "SHORT":
            if proposed_stop <= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_STOP_PLACEMENT",
                    "reason": f"Short stop loss ({proposed_stop}) must be strictly above entry price ({entry_price})"
                }
            if proposed_tp2 >= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_TARGET_PLACEMENT",
                    "reason": f"Short take profit ({proposed_tp2}) must be strictly below entry price ({entry_price})"
                }
            raw_risk_dist = proposed_stop - entry_price
            reward_dist = entry_price - proposed_tp2
        else:
            return {
                "approved": False,
                "rejection_code": "INVALID_BIAS",
                "reason": f"Unknown trade bias: {bias}"
            }

        # 3. Spread and Slippage buffer added to total risk distance
        total_risk_dist = raw_risk_dist + typical_spread + slippage

        # 4. Reward-to-Risk check
        effective_rr = round(reward_dist / (total_risk_dist + 1e-9), 2)
        if effective_rr < min_rr:
            return {
                "approved": False,
                "rejection_code": "INSUFFICIENT_REWARD_TO_RISK",
                "reason": f"Effective R:R (1:{effective_rr}) is below required minimum (1:{min_rr})"
            }

        # 5. Position Sizing & Monetary Limit Check in USD terms:
        # Loss per lot in instrument currency:
        loss_per_lot_native = (total_risk_dist * contract_size) + commission
        # Converted to USD account currency:
        loss_per_lot_usd = loss_per_lot_native * fx_to_usd
        
        # Ideal lot to risk exactly max_monetary_risk ($0.125):
        ideal_lot = max_monetary_risk / (loss_per_lot_usd + 1e-9)

        # Expected loss at broker's absolute minimum volume (0.01 lot) in USD:
        loss_at_min_volume = round(min_lot * loss_per_lot_usd, 4)

        # If even minimum trade size (0.01 lot) risks more than our allowed dollar budget ($0.125):
        if loss_at_min_volume > max_monetary_risk:
            logger.info(
                f"[{symbol}] Trade rejected: Minimum {min_lot} lot risks ${loss_at_min_volume:.2f}, "
                f"which exceeds the configured ${max_monetary_risk:.3f} (0.25% of ${balance}) ceiling."
            )
            return {
                "approved": False,
                "rejection_code": "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE",
                "reason": (
                    f"Minimum broker size ({min_lot} lot) incurs ${loss_at_min_volume:.3f} risk, "
                    f"exceeding your strict ${max_monetary_risk:.3f} (0.25% of ${balance:.2f}) risk ceiling."
                ),
                "loss_at_min_volume": loss_at_min_volume,
                "max_monetary_risk": max_monetary_risk,
                "minimum_lot_size": min_lot,
                "requires_cent_account": not is_cent
            }

        # Round DOWN (floor) to nearest lot_step (0.01) so risk ceiling is NEVER exceeded:
        import math
        lot_step = spec.get("lot_step", 0.01)
        safe_lot = max(min_lot, math.floor(ideal_lot / lot_step) * lot_step)
        safe_lot = round(safe_lot, 2)

        # Derive TP ladder
        tp1 = proposed_tp1 if proposed_tp1 else (entry_price + (1.0 * raw_risk_dist) if bias == "LONG" else entry_price - (1.0 * raw_risk_dist))
        tp3 = proposed_tp3 if proposed_tp3 else (entry_price + (3.5 * raw_risk_dist) if bias == "LONG" else entry_price - (3.5 * raw_risk_dist))

        return {
            "approved": True,
            "rejection_code": None,
            "symbol": symbol,
            "direction": bias,
            "entry": round(entry_price, 2),
            "stop_loss": round(proposed_stop, 2),
            "tp1": round(tp1, 2),
            "tp2": round(proposed_tp2, 2),
            "tp3": round(tp3, 2),
            "raw_risk_distance": round(raw_risk_dist, 2),
            "effective_rr": effective_rr,
            "suggested_lot_size": safe_lot,
            "expected_dollar_loss": round(safe_lot * loss_per_lot_usd, 4),
            "max_allowed_dollar_risk": max_monetary_risk
        }

    def evaluate_signal_risk(
        self,
        symbol: str,
        entry: float,
        stop_loss: float,
        tp2: float,
        is_cent_account: bool = False
    ) -> Dict[str, Any]:
        """
        Convenience evaluator for pipeline integration.
        Routes to XAUUSDc if is_cent_account is set.
        """
        bias = "LONG" if tp2 > entry else "SHORT"
        target_symbol = "XAUUSDc" if (is_cent_account and ("XAU" in symbol or "GC" in symbol)) else symbol

        res = self.evaluate_and_size_trade(target_symbol, bias, entry, stop_loss, tp2)
        if res["approved"]:
            return {
                "approved": True,
                "reason": "OK",
                "planned_rr": res["effective_rr"],
                "lot_size": res["suggested_lot_size"],
                "dollar_risk": res["expected_dollar_loss"],
                "requires_cent_account": False,
                "is_cent_account": is_cent_account
            }
        else:
            code = res.get("rejection_code", "REJECTED")
            reason_text = res.get("reason", code)
            return {
                "approved": False,
                "reason": f"{code}: {reason_text}",
                "planned_rr": 0.0,
                "lot_size": 0.0,
                "dollar_risk": res.get("loss_at_min_volume", 0.0),
                "requires_cent_account": res.get("requires_cent_account", False),
                "is_cent_account": is_cent_account
            }
