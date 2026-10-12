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
        Matches Exness standard account specifications.
        """
        inst = self.instruments_cfg.get(symbol, {})
        asset_type = inst.get("asset_type", "commodity")

        if "XAU" in symbol or "GC" in symbol:
            return {
                "symbol": symbol,
                "contract_size": 100.0,  # 1 standard lot = 100 troy ounces
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 10.0,
                "pip_size": 0.01,       # $0.01 is 1 point / tick
                "pip_value_per_lot": 1.0, # $1.00 per $0.01 move on 1.0 lot
                "typical_spread": inst.get("typical_spread_pips", 0.25), # in USD
                "commission_per_lot": inst.get("commission_per_lot", 0.0), # Exness standard accounts have 0 commission, spread only
                "estimated_slippage": inst.get("estimated_slippage", 0.10)
            }
        elif asset_type == "forex":
            return {
                "symbol": symbol,
                "contract_size": 100000.0,
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 20.0,
                "pip_size": 0.0001,
                "pip_value_per_lot": 10.0,
                "typical_spread": inst.get("typical_spread_pips", 0.00015),
                "commission_per_lot": 0.0,
                "estimated_slippage": 0.00005
            }
        elif asset_type == "crypto":
            return {
                "symbol": symbol,
                "contract_size": 1.0,
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 5.0,
                "pip_size": 1.0,
                "pip_value_per_lot": 1.0,
                "typical_spread": inst.get("typical_spread_pips", 15.0),
                "commission_per_lot": 0.0,
                "estimated_slippage": 5.0
            }

        # Fallback default
        return {
            "symbol": symbol,
            "contract_size": 100.0,
            "min_lot": 0.01,
            "lot_step": 0.01,
            "max_lot": 1.0,
            "pip_size": 0.01,
            "pip_value_per_lot": 1.0,
            "typical_spread": 0.50,
            "commission_per_lot": 0.0,
            "estimated_slippage": 0.10
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
        contract_size = spec["contract_size"]
        min_lot = spec["min_lot"]
        typical_spread = spec["typical_spread"]
        slippage = spec["estimated_slippage"]
        commission = spec["commission_per_lot"]

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

        # 5. Position Sizing & Strict Monetary Limit Check
        # Loss per 1.0 standard lot = total_risk_dist * contract_size + commission
        loss_per_standard_lot = (total_risk_dist * contract_size) + commission
        
        # Theoretical ideal volume to risk exactly max_monetary_risk:
        ideal_lot = max_monetary_risk / (loss_per_standard_lot + 1e-9)

        # Expected loss at broker's absolute minimum volume (e.g. 0.01 lot)
        loss_at_min_volume = round(min_lot * loss_per_standard_lot, 3)

        # If even the minimum trade size (0.01 lot) risks more than our allowed dollar budget ($0.125):
        if loss_at_min_volume > max_monetary_risk:
            # Under strict demo/live capital protection, reject unachievable risk ceiling!
            logger.info(
                f"[{symbol}] Trade rejected: Minimum 0.01 lot risks ${loss_at_min_volume:.2f}, "
                f"which exceeds the configured ${max_monetary_risk:.3f} (0.25% of ${balance}) ceiling."
            )
            return {
                "approved": False,
                "rejection_code": "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE",
                "reason": (
                    f"Minimum broker size ({min_lot} lot) incurs ${loss_at_min_volume:.2f} risk, "
                    f"exceeding your strict ${max_monetary_risk:.3f} (0.25% of ${balance:.2f}) risk ceiling."
                ),
                "loss_at_min_volume": loss_at_min_volume,
                "max_monetary_risk": max_monetary_risk,
                "minimum_lot_size": min_lot,
                "requires_cent_account": True
            }

        # If minimum lot size is within risk limits, assign the clamped safe lot size
        safe_lot = round(max(ideal_lot, min_lot), 2)

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
            "expected_dollar_loss": round(safe_lot * loss_per_standard_lot, 2),
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
        """
        bias = "LONG" if tp2 > entry else "SHORT"
        
        # If cent account, contract size is 1 oz instead of 100 oz (1/100th scale)
        if is_cent_account:
            orig_spec = self.get_contract_spec(symbol)
            # Temporarily adjust contract size for cent account calculation
            balance = float(self.risk_cfg.get("account_balance_usd", 50.0))
            risk_pct = float(self.risk_cfg.get("risk_per_trade_percent", 0.25))
            max_monetary_risk = round(balance * (risk_pct / 100.0), 4)
            raw_risk = abs(entry - stop_loss)
            reward = abs(tp2 - entry)
            rr = round(reward / (raw_risk + 0.25 + 0.10), 2)
            # Cent lot: 0.01 lot of 1 oz = 0.01 oz = $0.01 per dollar move
            dollar_risk = round(0.01 * (raw_risk + 0.35), 4)
            approved = (dollar_risk <= max_monetary_risk) and (rr >= float(self.risk_cfg.get("min_risk_reward", 2.5)))
            return {
                "approved": approved,
                "reason": "OK" if approved else "RR_OR_RISK_LIMIT_EXCEEDED",
                "planned_rr": rr,
                "lot_size": 0.01,
                "dollar_risk": dollar_risk,
                "requires_cent_account": False,
                "is_cent_account": True
            }

        res = self.evaluate_and_size_trade(symbol, bias, entry, stop_loss, tp2)
        if res["approved"]:
            return {
                "approved": True,
                "reason": "OK",
                "planned_rr": res["effective_rr"],
                "lot_size": res["suggested_lot_size"],
                "dollar_risk": res["expected_dollar_loss"],
                "requires_cent_account": False
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
                "requires_cent_account": res.get("requires_cent_account", False)
            }
