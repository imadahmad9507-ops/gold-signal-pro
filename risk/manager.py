"""
Risk Management Engine:
- Stop loss placement from ATR or nearest swing structure
- Minimum Risk:Reward validation (>= 1:2)
- Multi-target ladder: TP1 (1R), TP2 (2R), TP3 (3.5R)
- Position sizing: Lot size calculation based on account balance & risk %
- Exness spread & volatility safety filter
"""
from typing import Dict, Any, Optional


class RiskManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.risk_cfg = config.get("risk", {})
        self.instruments_cfg = config.get("instruments", {})

    def calculate_trade_levels(
        self,
        symbol: str,
        bias: str,
        current_price: float,
        atr: float,
        recent_swing_low: Optional[float] = None,
        recent_swing_high: Optional[float] = None,
        regime: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        inst_cfg = self.instruments_cfg.get(symbol, {})
        base_atr_mult = inst_cfg.get("atr_multiplier", 1.5)
        # Dynamic volatility expansion: widen stops/targets slightly in high volatility or trending regimes
        if regime in ["VOLATILE", "CHAOTIC"]:
            atr_mult = base_atr_mult * 1.3
        elif regime == "TRENDING":
            atr_mult = base_atr_mult * 1.15
        elif regime == "CONSOLIDATING":
            atr_mult = base_atr_mult * 0.95
        else:
            atr_mult = base_atr_mult

        min_rr = self.risk_cfg.get("min_risk_reward", 2.0)
        spread = inst_cfg.get("typical_spread_pips", 0.25)
        min_stop_dist = inst_cfg.get("min_stop_distance_pips", 1.5)

        entry = current_price

        if bias == "LONG":
            atr_stop = entry - (atr * atr_mult)
            structure_stop = (recent_swing_low - 0.2) if recent_swing_low else atr_stop
            # Pick the safer (further, but reasonable) stop
            stop_loss = min(atr_stop, structure_stop) if abs(entry - structure_stop) < 3.0 * atr else atr_stop
            
            risk_distance = entry - stop_loss
            if risk_distance < min_stop_dist:
                risk_distance = min_stop_dist
                stop_loss = entry - risk_distance

            tp1_r = self.risk_cfg.get("tp1_r", 1.0)
            tp2_r = self.risk_cfg.get("tp2_r", 2.8)
            tp3_r = self.risk_cfg.get("tp3_r", 4.0)

            # Take Profit ladder
            tp1 = entry + (tp1_r * risk_distance)
            tp2 = entry + (tp2_r * risk_distance)
            tp3 = entry + (tp3_r * risk_distance)
            rr_ratio = (tp2 - entry) / (risk_distance + 1e-9)

        elif bias == "SHORT":
            atr_stop = entry + (atr * atr_mult)
            structure_stop = (recent_swing_high + 0.2) if recent_swing_high else atr_stop
            stop_loss = max(atr_stop, structure_stop) if abs(structure_stop - entry) < 3.0 * atr else atr_stop

            risk_distance = stop_loss - entry
            if risk_distance < min_stop_dist:
                risk_distance = min_stop_dist
                stop_loss = entry + risk_distance

            tp1_r = self.risk_cfg.get("tp1_r", 1.0)
            tp2_r = self.risk_cfg.get("tp2_r", 2.8)
            tp3_r = self.risk_cfg.get("tp3_r", 4.0)

            tp1 = entry - (tp1_r * risk_distance)
            tp2 = entry - (tp2_r * risk_distance)
            tp3 = entry - (tp3_r * risk_distance)
            rr_ratio = (entry - tp2) / (risk_distance + 1e-9)
        else:
            return None

        # Check spread vs stop distance (Spread safety guard)
        if spread >= risk_distance * 0.35:
            # Spread is too large relative to stop loss
            return None

        # Check min R:R with tolerance
        if round(rr_ratio, 2) < min_rr:
            return None

        # Lot size calculation
        lot_size = self.calculate_position_size(symbol, risk_distance)

        return {
            "entry": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "tp3": round(tp3, 2),
            "risk_distance": round(risk_distance, 2),
            "risk_reward_tp2": round(rr_ratio, 2),
            "suggested_lot_size": lot_size
        }

    def calculate_position_size(self, symbol: str, risk_distance: float) -> float:
        balance = self.risk_cfg.get("account_balance_usd", 1000.0)
        risk_pct = self.risk_cfg.get("risk_per_trade_percent", 1.0) / 100.0
        risk_amount_usd = balance * risk_pct

        inst_cfg = self.instruments_cfg.get(symbol, {})
        pip_val = inst_cfg.get("pip_value", 1.0) # For gold: 1 lot = 100 oz -> $1 move = $100 -> 0.01 lot = $1 move is $1

        # For XAUUSD: 1 pip ($0.10) with 0.01 lot is $0.10, so $1 price move per 0.01 lot = $1.00 risk
        # lot = risk_amount / (risk_distance * 100)
        if "GC" in symbol or "XAU" in symbol:
            raw_lot = risk_amount_usd / (risk_distance * 100.0 + 1e-9)
        else:
            raw_lot = risk_amount_usd / (risk_distance * 10000.0 + 1e-9)

        # Round to 2 decimal places, min 0.01 lot
        lot = round(max(raw_lot, 0.01), 2)
        return min(lot, 5.0)  # Max safety ceiling for beginner protection
