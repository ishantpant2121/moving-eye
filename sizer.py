# sizer.py
"""
Position Sizing Calculator
===========================
Calculates contracts, stop price, stop distance, and risk in INR
for Phase 2, Step 4 of the algo-trading bot.

Formulas:
  risk_per_trade  = account_balance * 0.01        (1% hard max, never exceed this)
  stop_distance   = 1.5 * signal["atr"]           (in price terms)
  raw_contracts   = risk_per_trade / stop_distance (base size)

Multipliers in order:
  - If regime == "VOLATILE":      * 0.5
  - If score["strength"] == "strong": * 1.25
  - If weekly_drawdown > 5%:      * 0.5
"""

def calculate_weekly_drawdown(daily_pnl, base_balance=50000.0):
    """
    Calculates the maximum weekly drawdown percentage from a list of daily P&L values.
    Drawdown is defined as the peak-to-trough decline of the cumulative weekly equity.

    Args:
        daily_pnl: List of daily P&L values (floats/ints) for the current week.
        base_balance: Starting balance of the week.

    Returns:
        float: Maximum weekly drawdown percentage (e.g., 5.5 for 5.5%).
    """
    if not daily_pnl:
        return 0.0

    # Reconstruct cumulative equity curve starting with the base balance
    equity = [base_balance]
    for pnl in daily_pnl:
        equity.append(equity[-1] + pnl)

    peak = equity[0]
    max_drawdown_pct = 0.0

    for eq in equity:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd_pct = (peak - eq) / peak * 100.0
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

    return max_drawdown_pct


def calculate_size(signal, score, regime, account_balance=50000, daily_pnl=None, weekly_drawdown=None):
    """
    Calculates position size (contracts), stop price, risk in INR, and returns details.

    Args:
        signal:          dict — from signals.scan_entry(). Keys used: "atr", "price", "signal"
        score:           dict — from scorer.score_signal(). Keys used: "strength"
        regime:          str or dict — current market regime (e.g. "TRENDING", "VOLATILE")
        account_balance: float — account balance in currency units (default 50000)
        daily_pnl:       list — daily P&L values to compute weekly drawdown (if weekly_drawdown is None)
        weekly_drawdown: float — weekly drawdown percentage (pre-calculated). Takes priority over daily_pnl.

    Returns:
        dict:
            "contracts":          float — contracts size rounded to 4 decimals
            "risk_inr":           float — risk amount in INR rounded to 2 decimals
            "stop_price":         float — stop price rounded to 2 decimals
            "stop_distance":      float — stop distance rounded to 2 decimals
            "multiplier_applied":  str — comma-separated string of applied multipliers or "none"
            "account_balance":    float — the balance used in calculation
    """
    # ── 1. Basic validation ──
    if not isinstance(signal, dict):
        raise ValueError("Signal must be a dictionary.")
    if not isinstance(score, dict):
        raise ValueError("Score must be a dictionary.")

    atr = signal.get("atr")
    if atr is None or atr <= 0:
        raise ValueError("ATR must be greater than zero.")

    entry_price = signal.get("price")
    if entry_price is None or entry_price <= 0:
        raise ValueError("Entry price must be greater than zero.")

    # ── 2. Determine trade direction ──
    sig_name = signal.get("signal", "").upper()
    if "LONG" in sig_name:
        is_long = True
    elif "SHORT" in sig_name:
        is_long = False
    else:
        raise ValueError(f"Unable to determine trade direction from signal name: '{sig_name}'")

    # ── 3. Base calculations ──
    # 1% hard max risk
    risk_per_trade = account_balance * 0.01
    
    stop_distance = 1.5 * atr
    raw_contracts = risk_per_trade / stop_distance

    # ── 4. Extract regime and drawdown ──
    if isinstance(regime, dict):
        regime_name = regime.get("regime", "")
    else:
        regime_name = str(regime)

    if weekly_drawdown is None:
        if daily_pnl is not None:
            weekly_drawdown = calculate_weekly_drawdown(daily_pnl, account_balance)
        else:
            weekly_drawdown = 0.0

    # ── 5. Apply multipliers in order ──
    contracts = raw_contracts
    multipliers_applied = []

    # Regime Check
    if regime_name == "VOLATILE":
        contracts *= 0.5
        multipliers_applied.append("volatile")

    # Score Check
    if score.get("strength") == "strong":
        contracts *= 1.25
        multipliers_applied.append("strong_bonus")

    # Drawdown Check
    if weekly_drawdown > 5.0:
        contracts *= 0.5
        multipliers_applied.append("drawdown")

    # ── 6. 1% Hard max capping (never exceed risk_per_trade) ──
    # The actual risk is proportional to the size of the contracts relative to the raw size.
    effective_multiplier = contracts / raw_contracts if raw_contracts > 0 else 1.0
    risk_inr = risk_per_trade * effective_multiplier

    if risk_inr > risk_per_trade:
        risk_inr = risk_per_trade
        contracts = raw_contracts

    # ── 7. Calculate stop price ──
    if is_long:
        stop_price = entry_price - stop_distance
    else:
        stop_price = entry_price + stop_distance

    # ── 8. Formulate final results and round ──
    contracts_final = round(contracts, 4)
    if contracts_final <= 0:
        raise ValueError("Calculated contracts size must be greater than zero.")

    multiplier_applied = ", ".join(multipliers_applied) if multipliers_applied else "none"

    return {
        "contracts": contracts_final,
        "risk_inr": round(risk_inr, 2),
        "stop_price": round(stop_price, 2),
        "stop_distance": round(stop_distance, 2),
        "multiplier_applied": multiplier_applied,
        "account_balance": account_balance
    }
