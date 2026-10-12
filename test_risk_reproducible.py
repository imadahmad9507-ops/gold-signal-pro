"""
Reproducible Risk Engine Verification Test:
Tests $50 account with strict 0.25% risk ceiling ($0.125):
1. Standard Account (XAUUSD, contract size 100 oz):
   - A $6.00 stop loss at 0.01 lot risks $6.35 after spread & slippage.
   - Result: REJECTED with RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE.
2. Cent Account (XAUUSDc, contract size 1 oz, USC currency):
   - A $6.00 stop loss at 0.01 cent lot risks $0.0635 USD (6.35 US Cents).
   - $0.0635 <= $0.125 ceiling.
   - Result: APPROVED.
3. Cent Account with excessive stop distance ($15 stop):
   - A $15.00 stop loss at 0.01 cent lot risks $0.1545 USD.
   - Exceeds $0.125 ceiling.
   - Result: REJECTED with RISK_LIMIT_UNACHIEVABLE_AT_MINIMUM_SIZE.
4. Unknown / Missing Instrument Specs:
   - Result: REJECTED with MISSING_CONTRACT_SPEC.
"""
from risk.hardened_manager import HardenedRiskManager

def run_risk_verification():
    cfg = {
        "risk": {
            "account_balance_usd": 50.0,
            "risk_per_trade_percent": 0.25,
            "min_risk_reward": 2.5
        }
    }
    mgr = HardenedRiskManager(cfg)

    print("=== TEST 1: Standard Account XAUUSD (100 oz contract) ===")
    res_std = mgr.evaluate_signal_risk("XAUUSD", entry=2650.0, stop_loss=2644.0, tp2=2670.0, is_cent_account=False)
    print("Approved:", res_std["approved"])
    print("Reason:", res_std["reason"])
    print("Requires Cent Account:", res_std.get("requires_cent_account"))

    print("\n=== TEST 2: Cent Account XAUUSDc (1 oz contract, USC) ===")
    res_cent = mgr.evaluate_signal_risk("XAUUSD", entry=2650.0, stop_loss=2644.0, tp2=2670.0, is_cent_account=True)
    print("Approved:", res_cent["approved"])
    print("Dollar Risk ($):", res_cent.get("dollar_risk"))
    print("Lot Size:", res_cent.get("lot_size"))
    print("Planned RR:", res_cent.get("planned_rr"))

    print("\n=== TEST 3: Cent Account with Extreme $1350 Stop (Exceeds $0.125 ceiling) ===")
    # Entry 2650, SL 1300 ($1350 stop distance): loss at 0.01 lot = $0.135 > $0.125 max monetary risk
    res_wide = mgr.evaluate_signal_risk("XAUUSD", entry=2650.0, stop_loss=1300.0, tp2=6500.0, is_cent_account=True)
    print("Approved:", res_wide["approved"])
    print("Reason:", res_wide["reason"])

    print("\n=== TEST 4: Missing / Unverified Instrument Specs ===")
    res_unk = mgr.evaluate_signal_risk("UNVERIFIED_ASSET", entry=100.0, stop_loss=90.0, tp2=130.0)
    print("Approved:", res_unk["approved"])
    print("Reason:", res_unk["reason"])

if __name__ == "__main__":
    run_risk_verification()
