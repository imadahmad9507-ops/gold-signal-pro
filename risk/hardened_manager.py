"""
Hardened Risk Management Engine
================================
Enforces a strict monetary risk limit (0.25% of account balance,
e.g. $0.125 on a $50 USD-equivalent equity) per trade.

Unit convention (CRITICAL — read before editing):
--------------------------------------------------
Gold (XAUUSD / XAUUSDc) prices are always quoted in USD per troy ounce
on every account type, including Exness Cent accounts.  The Cent account
distinction is purely a *display* convention: the account balance panel
shows a number 100× larger (USC) but the underlying gold contract is
still priced in USD.

Therefore, for all gold instruments:
  price_distance  [USD / oz]   — the raw move against you
  contract_size   [oz / lot]   — ounces per 1.0 lot
  loss_per_lot    [USD / lot]  = price_distance × contract_size
                                 NO further FX conversion is required.

For a standard account XAUUSD (100 oz/lot):
  loss_per_lot = stop_dist_usd × 100   → large → rejected at 0.01 lot on $50

For an Exness Cent Account XAUUSDc (1 oz/lot):
  loss_per_lot = stop_dist_usd × 1.0
  At 0.01 lot with a $6 stop: 0.01 × 1.0 × $6 = $0.06 USD → approved

The `exchange_rate_to_usd` field in the spec is kept only for future
non-gold instruments (e.g. a USD-settled silver contract priced in EUR).
It is NOT applied to gold instruments where gold prices are natively USD.
"""
import math
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
        Returns the full, verified contract specification for an instrument.

        Sources:
        - XAUUSD  : Exness Standard Account — 100 troy oz per standard lot.
        - XAUUSDc : Exness Cent Account     — 1 troy oz per cent lot.
                    Gold price is still quoted in USD/oz on both account types.
                    The cent account merely displays the balance in USC (1 USD = 100 USC).

        IMPORTANT: `exchange_rate_to_usd` for gold instruments is 1.0.
        Gold prices ARE USD prices.  Multiplying by 0.01 for a cent account
        would be a double-denomination error (treating a USD value as USC
        and then dividing by 100 again).
        """
        inst = self.instruments_cfg.get(symbol, {})
        asset_type = inst.get("asset_type", "commodity")

        # ── Standard Exness Gold CFD (USD account) ──────────────────────────
        if symbol in ("XAUUSD", "GC=F"):
            return {
                "symbol": symbol,
                # 1 standard lot = 100 troy oz; gold price in USD/oz
                "contract_size": 100.0,       # oz per lot
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 20.0,
                "tick_size": 0.01,            # USD price step
                "tick_value_per_lot": 1.0,    # $1.00 per $0.01 move on 1.0 lot
                "typical_spread": inst.get("typical_spread_pips", 0.25),  # USD
                "commission_per_lot": inst.get("commission_per_lot", 0.0),
                "estimated_slippage": inst.get("estimated_slippage", 0.10),
                "account_currency": "USD",
                "is_cent_account": False,
                # Gold price already denominated in USD — no conversion needed.
                "exchange_rate_to_usd": 1.0,
                "spec_source": "assumed_specification",
                "mt5_verified": False
            }

        # ── Exness Cent Account Gold CFD (USC account display) ──────────────
        elif symbol == "XAUUSDc":
            return {
                "symbol": symbol,
                # 1 cent lot = 1 troy oz (1/100th of the standard 100 oz lot).
                # Gold price is STILL quoted in USD/oz — not USC.
                "contract_size": 1.0,         # oz per cent lot
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 200.0,
                "tick_size": 0.01,
                "tick_value_per_lot": 0.01,   # $0.01 USD per $0.01 move on 1.0 cent lot
                "typical_spread": inst.get("typical_spread_pips", 0.35),
                "commission_per_lot": 0.0,
                "estimated_slippage": 0.10,
                "account_currency": "USC",    # display currency; 1 USD = 100 USC
                "is_cent_account": True,
                # Gold price is in USD whether account is standard or cent.
                # Do NOT apply this to loss calculation — loss is already in USD.
                "exchange_rate_to_usd": 1.0,
                "spec_source": "assumed_specification",
                "mt5_verified": False
            }

        # ── Forex instruments (standard 100k lot) ───────────────────────────
        elif asset_type == "forex":
            return {
                "symbol": symbol,
                "contract_size": 100_000.0,
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
                "exchange_rate_to_usd": 1.0,
            }

        # ── Crypto ──────────────────────────────────────────────────────────
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
                "exchange_rate_to_usd": 1.0,
            }

        # ── Unknown / unverified instrument — REJECT, never guess ───────────
        return {
            "symbol": symbol,
            "is_unsupported": True,
            "reason": (
                f"MISSING_CONTRACT_SPEC: Instrument '{symbol}' has no verified "
                "broker specifications.  Rejecting to prevent incorrect sizing."
            ),
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
        open_signals_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Evaluates risk parameters against account equity and returns either an
        APPROVED trade result or a structured REJECTION with exact rationale.

        All monetary values are computed and compared in USD.
        For gold instruments, price distance in USD/oz × contract size in oz/lot
        gives loss in USD/lot directly — no FX multiplication is applied.
        """
        # ── Currency & Equity Configuration Validation ───────────────────────
        account_curr = self.risk_cfg.get("account_currency", "USD")
        if not isinstance(account_curr, str) or account_curr.upper() not in ("USD", "USC"):
            return {
                "approved": False,
                "rejection_code": "AMBIGUOUS_CURRENCY_CONFIG",
                "reason": f"Configured account currency '{account_curr}' is unsupported or ambiguous. Must be explicitly 'USD' or 'USC'."
            }
        account_curr = account_curr.upper()

        has_usd = "account_balance_usd" in self.risk_cfg and self.risk_cfg["account_balance_usd"] is not None
        has_usc = "account_balance_usc" in self.risk_cfg and self.risk_cfg["account_balance_usc"] is not None

        # Helper to validate finite positive numeric balance
        def _validate_num(val, name):
            try:
                num = float(val)
                if not math.isfinite(num) or num <= 0.0:
                    return None, f"Configured {name} ({val}) must be a positive finite number."
                return num, None
            except (ValueError, TypeError):
                return None, f"Configured {name} ({val}) is not a valid number."

        # If account_currency is USD, require explicit account_balance_usd
        if account_curr == "USD":
            if not has_usd:
                return {
                    "approved": False,
                    "rejection_code": "AMBIGUOUS_CURRENCY_CONFIG",
                    "reason": "Missing required field 'account_balance_usd' for account_currency 'USD'. Never silently infer balance."
                }
            val_usd, err = _validate_num(self.risk_cfg["account_balance_usd"], "account_balance_usd")
            if err:
                return {"approved": False, "rejection_code": "INVALID_BALANCE_VALUE", "reason": err}

            # If account_balance_usc is also provided, validate economic equivalence (1 USD = 100 USC)
            if has_usc:
                val_usc, err_usc = _validate_num(self.risk_cfg["account_balance_usc"], "account_balance_usc")
                if err_usc:
                    return {"approved": False, "rejection_code": "INVALID_BALANCE_VALUE", "reason": err_usc}
                if abs(val_usd * 100.0 - val_usc) > 1e-4:
                    return {
                        "approved": False,
                        "rejection_code": "AMBIGUOUS_CURRENCY_CONFIG",
                        "reason": f"Conflicting balances configured: {val_usd} USD != {val_usc} USC (expected {val_usd * 100.0} USC)."
                    }
            balance_usd = val_usd

        # If account_currency is USC, require explicit account_balance_usc
        elif account_curr == "USC":
            if not has_usc:
                return {
                    "approved": False,
                    "rejection_code": "AMBIGUOUS_CURRENCY_CONFIG",
                    "reason": "Missing required field 'account_balance_usc' for account_currency 'USC'. Never silently infer from USD."
                }
            val_usc, err = _validate_num(self.risk_cfg["account_balance_usc"], "account_balance_usc")
            if err:
                return {"approved": False, "rejection_code": "INVALID_BALANCE_VALUE", "reason": err}

            # If account_balance_usd is also provided, validate economic equivalence
            if has_usd:
                val_usd, err_usd = _validate_num(self.risk_cfg["account_balance_usd"], "account_balance_usd")
                if err_usd:
                    return {"approved": False, "rejection_code": "INVALID_BALANCE_VALUE", "reason": err_usd}
                if abs(val_usd * 100.0 - val_usc) > 1e-4:
                    return {
                        "approved": False,
                        "rejection_code": "AMBIGUOUS_CURRENCY_CONFIG",
                        "reason": f"Conflicting balances configured: {val_usc} USC != {val_usd} USD (expected {val_usd * 100.0} USC)."
                    }
            balance_usd = val_usc / 100.0

        balance = balance_usd
        risk_pct = float(self.risk_cfg.get("risk_per_trade_percent", 0.25))
        max_monetary_risk = round(balance * (risk_pct / 100.0), 6)  # USD
        max_monetary_risk_usc = round(max_monetary_risk * 100.0, 4) # USC (e.g. 12.5 USC)

        min_rr = float(self.risk_cfg.get("min_risk_reward", 2.5))
        max_concurrent = int(self.risk_cfg.get("max_concurrent_signals", 1))

        # ── Guard: concurrent position cap ──────────────────────────────────
        if open_signals_count >= max_concurrent:
            return {
                "approved": False,
                "rejection_code": "MAX_CONCURRENT_POSITIONS_REACHED",
                "reason": (
                    f"Open signals ({open_signals_count}) meets or exceeds "
                    f"the configured maximum ({max_concurrent})."
                ),
            }

        # ── Look up verified instrument specification ────────────────────────
        spec = self.get_contract_spec(symbol)
        if spec.get("is_unsupported"):
            return {
                "approved": False,
                "rejection_code": "MISSING_CONTRACT_SPEC",
                "reason": spec.get(
                    "reason",
                    f"Contract specifications for {symbol} are unverified.",
                ),
            }

        contract_size = spec["contract_size"]   # oz/lot  (gold) or base units
        min_lot       = spec["min_lot"]          # lots
        lot_step      = spec.get("lot_step", 0.01)
        typical_spread = spec["typical_spread"]  # USD (gold spread in price units)
        slippage      = spec["estimated_slippage"]  # USD
        commission    = spec["commission_per_lot"]   # USD per lot (0.0 for cent)
        is_cent       = spec.get("is_cent_account", False)
        # NOTE: exchange_rate_to_usd is 1.0 for gold; kept in spec for non-gold future use.
        # It is intentionally NOT used in the gold loss calculation below.

        # ── Direction and distance validation ───────────────────────────────
        if bias == "LONG":
            if proposed_stop >= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_STOP_PLACEMENT",
                    "reason": (
                        f"LONG stop loss ({proposed_stop}) must be strictly "
                        f"below entry ({entry_price})."
                    ),
                }
            if proposed_tp2 <= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_TARGET_PLACEMENT",
                    "reason": (
                        f"LONG take-profit ({proposed_tp2}) must be strictly "
                        f"above entry ({entry_price})."
                    ),
                }
            raw_risk_dist  = entry_price - proposed_stop   # USD / oz
            reward_dist    = proposed_tp2 - entry_price    # USD / oz
        elif bias == "SHORT":
            if proposed_stop <= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_STOP_PLACEMENT",
                    "reason": (
                        f"SHORT stop loss ({proposed_stop}) must be strictly "
                        f"above entry ({entry_price})."
                    ),
                }
            if proposed_tp2 >= entry_price:
                return {
                    "approved": False,
                    "rejection_code": "INVALID_TARGET_PLACEMENT",
                    "reason": (
                        f"SHORT take-profit ({proposed_tp2}) must be strictly "
                        f"below entry ({entry_price})."
                    ),
                }
            raw_risk_dist  = proposed_stop - entry_price   # USD / oz
            reward_dist    = entry_price - proposed_tp2    # USD / oz
        else:
            return {
                "approved": False,
                "rejection_code": "INVALID_BIAS",
                "reason": f"Unknown trade bias: '{bias}'.  Expected 'LONG' or 'SHORT'.",
            }

        # ── Widen risk distance by spread + slippage buffer ─────────────────
        #   total_risk_dist  [USD / oz]
        total_risk_dist = raw_risk_dist + typical_spread + slippage

        # ── Reward-to-Risk check ─────────────────────────────────────────────
        effective_rr = round(reward_dist / (total_risk_dist + 1e-9), 2)
        if effective_rr < min_rr:
            return {
                "approved": False,
                "rejection_code": "INSUFFICIENT_REWARD_TO_RISK",
                "reason": (
                    f"Effective R:R (1:{effective_rr}) is below the required "
                    f"minimum (1:{min_rr})."
                ),
            }

        # ── Monetary position-sizing (all values in USD) ─────────────────────
        #
        #   gold price distance is USD/oz  (price quoted in USD on ALL account types)
        #   contract_size       is oz/lot
        #   ─────────────────────────────────────────────────────────────────
        #   loss_per_lot_usd    [USD/lot] = price_distance [USD/oz]
        #                                  × contract_size [oz/lot]
        #                                  + commission     [USD/lot]
        #
        #   For XAUUSDc (1 oz/lot):
        #     loss_per_lot_usd = 6.35 USD/oz × 1.0 oz/lot + 0.0 = 6.35 USD/lot
        #
        #   The cent account shows the balance in USC but the gold EXPOSURE is
        #   still USD.  Do NOT multiply by 0.01 — that would understate risk 100×.
        #
        loss_per_lot_usd = (total_risk_dist * contract_size) + commission   # USD / lot

        # Ideal fractional lot to risk exactly max_monetary_risk:
        ideal_lot = max_monetary_risk / (loss_per_lot_usd + 1e-9)

        # Expected loss at broker minimum volume (0.01 lot):
        loss_at_min_volume = round(min_lot * loss_per_lot_usd, 6)   # USD

        # Hard gate: even min lot must stay within the risk ceiling ──────────
        if loss_at_min_volume > max_monetary_risk:
            logger.info(
                "[%s] REJECTED — min lot (%.2f) risks $%.4f USD, "
                "ceiling is $%.4f USD (%.4f%% of $%.2f).",
                symbol, min_lot, loss_at_min_volume,
                max_monetary_risk, risk_pct, balance,
            )
            return {
                "approved": False,
                "rejection_code": "RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE",
                "reason": (
                    f"Minimum broker size ({min_lot} lot) incurs "
                    f"${loss_at_min_volume:.4f} USD risk, exceeding your strict "
                    f"${max_monetary_risk:.4f} ({risk_pct}% of ${balance:.2f}) "
                    "risk ceiling."
                ),
                "loss_at_min_volume_usd": loss_at_min_volume,
                "max_monetary_risk_usd": max_monetary_risk,
                "minimum_lot_size": min_lot,
                "requires_cent_account": not is_cent,
            }

        # Floor to valid lot_step so the ceiling is NEVER exceeded ───────────
        safe_lot = max(min_lot, math.floor(ideal_lot / lot_step) * lot_step)
        safe_lot = round(safe_lot, 2)

        # Derive final confirmed dollar loss at the approved lot ─────────────
        final_dollar_loss = round(safe_lot * loss_per_lot_usd, 6)   # USD

        # Assertion: approved trade must never exceed risk ceiling ────────────
        assert final_dollar_loss <= max_monetary_risk + 1e-9, (
            f"INTERNAL ERROR: Approved trade dollar loss ${final_dollar_loss:.6f} "
            f"exceeds risk ceiling ${max_monetary_risk:.6f}.  "
            "This is a bug in the lot-sizing logic."
        )

        # ── Derive full TP ladder ────────────────────────────────────────────
        if bias == "LONG":
            tp1 = proposed_tp1 if proposed_tp1 else round(entry_price + 1.0 * raw_risk_dist, 2)
            tp3 = proposed_tp3 if proposed_tp3 else round(entry_price + 3.5 * raw_risk_dist, 2)
        else:
            tp1 = proposed_tp1 if proposed_tp1 else round(entry_price - 1.0 * raw_risk_dist, 2)
            tp3 = proposed_tp3 if proposed_tp3 else round(entry_price - 3.5 * raw_risk_dist, 2)

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
            "raw_risk_distance_usd": round(raw_risk_dist, 4),
            "total_risk_distance_usd": round(total_risk_dist, 4),
            "loss_per_lot_usd": round(loss_per_lot_usd, 6),
            "effective_rr": effective_rr,
            "suggested_lot_size": safe_lot,
            "expected_dollar_loss": final_dollar_loss,
            "max_allowed_dollar_risk": round(max_monetary_risk, 6),
            "expected_loss_usc": round(final_dollar_loss * 100.0, 4),
            "max_allowed_risk_usc": max_monetary_risk_usc,
            "account_currency": account_curr,
            "spec_source": spec.get("spec_source", "assumed_specification"),
            "mt5_verified": spec.get("mt5_verified", False)
        }

    def evaluate_signal_risk(
        self,
        symbol: str,
        entry: float,
        stop_loss: float,
        tp2: float,
        is_cent_account: Optional[bool] = None,
        account_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Convenience evaluator for pipeline integration.
        Maps the analysis symbol (e.g. GC=F or XAUUSD) to the sizing target symbol based on
        either account_type ("cent" vs "standard") or explicit is_cent_account flag.
        Defaults to config['risk']['account_type'] or config['risk']['account_currency'] == 'USC'.
        """
        bias = "LONG" if tp2 > entry else "SHORT"

        # Determine account type from parameter or config
        cfg_acct_type = str(self.risk_cfg.get("account_type", "")).lower()
        cfg_acct_curr = str(self.risk_cfg.get("account_currency", "USD")).upper()

        if is_cent_account is not None:
            use_cent = bool(is_cent_account)
        elif account_type is not None:
            use_cent = (account_type.lower() in ("cent", "usc", "cent_account"))
        else:
            use_cent = (cfg_acct_type in ("cent", "usc", "cent_account")) or (cfg_acct_curr == "USC")

        # Map commodity gold to XAUUSDc if cent account sizing profile is active
        target_symbol = (
            "XAUUSDc"
            if (use_cent and ("XAU" in symbol or "GC" in symbol))
            else symbol
        )

        res = self.evaluate_and_size_trade(target_symbol, bias, entry, stop_loss, tp2)
        if res["approved"]:
            return {
                "approved": True,
                "reason": "OK",
                "planned_rr": res["effective_rr"],
                "lot_size": res["suggested_lot_size"],
                "dollar_risk": res["expected_dollar_loss"],
                "risk_usc": res.get("expected_loss_usc"),
                "max_allowed_dollar_risk": res.get("max_allowed_dollar_risk"),
                "max_allowed_risk_usc": res.get("max_allowed_risk_usc"),
                "spec_source": res.get("spec_source"),
                "mt5_verified": res.get("mt5_verified"),
                "requires_cent_account": False,
                "is_cent_account": use_cent,
            }
        else:
            code = res.get("rejection_code", "REJECTED")
            reason_text = res.get("reason", code)
            return {
                "approved": False,
                "reason": f"{code}: {reason_text}",
                "planned_rr": 0.0,
                "lot_size": 0.0,
                "dollar_risk": res.get("loss_at_min_volume_usd", 0.0),
                "requires_cent_account": res.get("requires_cent_account", False),
                "is_cent_account": use_cent,
            }
