"""
Settlement Detective — Reconciliation Configuration
Defines merchant MDR fee rates, tax rates, tolerances, and classification enums.
"""

from typing import Dict, Any

# Configured Merchant Baseline MDR Rates
# Standard rates negotiated by merchant per payment method
DEFAULT_MDR_RATES: Dict[str, float] = {
    "upi": 0.009,          # Standard UPI: 0.90% (90 bps)
    "card": 0.020,         # Credit/Debit Cards: 2.00% (200 bps)
    "netbanking": 0.018,   # Netbanking: 1.80% (180 bps)
    "wallet": 0.015        # Digital Wallets: 1.50% (150 bps)
}

# Standard GST on payment gateway fees in India
GST_RATE: float = 0.18     # 18.00% GST

# Permissible rounding tolerance in paise
ROUNDING_TOLERANCE_PAISE: int = 1

# Anomaly Classification Categories
class AnomalyCategory:
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    MISSING_SETTLEMENT_LINE = "MISSING_SETTLEMENT_LINE"
    DUPLICATE = "DUPLICATE"
    REFUND_MISMATCH = "REFUND_MISMATCH"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    UNEXPLAINED_VARIANCE = "UNEXPLAINED_VARIANCE"
    FEE_ANOMALY = "FEE_ANOMALY"

# Variance Severity Levels
class VarianceSeverity:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

# Difference Classifications (Pass 5)
class DifferenceClassification:
    FEE_DEDUCTION = "FEE_DEDUCTION"
    TAX_DEDUCTION = "TAX_DEDUCTION"
    REFUND = "REFUND"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    ROUNDING = "ROUNDING"
    DUPLICATE = "DUPLICATE"
    UNMATCHED = "UNMATCHED"
    UNEXPLAINED = "UNEXPLAINED"
    POTENTIAL_LEAKAGE = "POTENTIAL_LEAKAGE"


from decimal import Decimal, ROUND_HALF_UP


def calculate_expected_fee_and_tax(amount_paise: int, payment_method: str, custom_mdr_rate: float = None) -> tuple[int, int]:
    """
    Deterministically computes expected fee and GST tax in integer paise.
    All monetary calculations use strict integer arithmetic with Decimal rounding.
    """
    mdr = custom_mdr_rate if custom_mdr_rate is not None else DEFAULT_MDR_RATES.get(payment_method, 0.02)
    amount_dec = Decimal(str(amount_paise))
    mdr_dec = Decimal(str(mdr))
    gst_dec = Decimal(str(GST_RATE))

    expected_fee_paise = int((amount_dec * mdr_dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    expected_tax_paise = int((Decimal(str(expected_fee_paise)) * gst_dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return expected_fee_paise, expected_tax_paise


def simulate_transaction_reconciliation(
    amount_paise: Any = None,
    payment_method: str = "upi",
    actual_mdr_rate: Any = None,
    *,
    amount_inr: Any = None,
    expected_mdr_percent: Any = None,
    gst_percent: Any = None,
    actual_settlement_inr: Any = None,
    actual_settlement_paise: Any = None,
    actual_mdr_percent: Any = None,
) -> Dict[str, Any]:
    """Reconcile one hypothetical transaction deterministically using Decimal and integer paise.

    Supports both:
    1. New primary interface: amount_inr, payment_method, expected_mdr_percent, gst_percent, actual_settlement_inr
    2. Legacy interface: amount_paise, payment_method, actual_mdr_rate / actual_mdr_percent
    """
    # 1. Normalize amount
    if amount_inr is not None:
        amount_inr_dec = Decimal(str(amount_inr))
        calc_amount_paise = int((amount_inr_dec * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    elif amount_paise is not None:
        calc_amount_paise = int(amount_paise)
        amount_inr_dec = (Decimal(calc_amount_paise) / Decimal("100")).quantize(Decimal("0.01"))
    else:
        raise ValueError("Either amount_inr or amount_paise must be provided.")

    if calc_amount_paise <= 0:
        raise ValueError("Amount must be greater than zero.")

    # 2. Normalize payment method
    pm = str(payment_method).lower().strip()
    if pm not in DEFAULT_MDR_RATES:
        raise ValueError(f"Unsupported payment method: '{payment_method}'. Supported methods: upi, card, netbanking, wallet.")

    # 3. Expected MDR & GST Percent
    baseline_mdr_rate = DEFAULT_MDR_RATES[pm]
    if expected_mdr_percent is not None:
        exp_mdr_pct_dec = Decimal(str(expected_mdr_percent))
        exp_mdr_rate = float(exp_mdr_pct_dec / Decimal("100"))
    else:
        exp_mdr_pct_dec = (Decimal(str(baseline_mdr_rate)) * Decimal("100")).quantize(Decimal("0.01"))
        exp_mdr_rate = baseline_mdr_rate

    if gst_percent is not None:
        gst_pct_dec = Decimal(str(gst_percent))
    else:
        gst_pct_dec = (Decimal(str(GST_RATE)) * Decimal("100")).quantize(Decimal("0.01"))

    # 4. Compute Expected Fees, Tax, Net
    expected_fee_paise = int((Decimal(calc_amount_paise) * exp_mdr_pct_dec / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    expected_tax_paise = int((Decimal(expected_fee_paise) * gst_pct_dec / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    expected_net_paise = calc_amount_paise - expected_fee_paise - expected_tax_paise

    # 5. Compute Actual Settlement & Variance
    is_new_payload = actual_settlement_inr is not None or actual_settlement_paise is not None

    if actual_settlement_inr is not None:
        act_settle_inr_dec = Decimal(str(actual_settlement_inr))
        calc_actual_settle_paise = int((act_settle_inr_dec * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        calc_actual_net_paise = calc_actual_settle_paise
        # In new payload, variance = expected_net - actual_settlement (positive = shortfall)
        calc_variance_paise = expected_net_paise - calc_actual_settle_paise
        actual_fee_paise = 0
        actual_tax_paise = 0
        act_mdr_rate = exp_mdr_rate
    elif actual_settlement_paise is not None:
        calc_actual_settle_paise = int(actual_settlement_paise)
        act_settle_inr_dec = (Decimal(calc_actual_settle_paise) / Decimal("100")).quantize(Decimal("0.01"))
        calc_actual_net_paise = calc_actual_settle_paise
        calc_variance_paise = expected_net_paise - calc_actual_settle_paise
        actual_fee_paise = 0
        actual_tax_paise = 0
        act_mdr_rate = exp_mdr_rate
    elif actual_mdr_percent is not None or actual_mdr_rate is not None:
        if actual_mdr_percent is not None:
            act_mdr_pct_dec = Decimal(str(actual_mdr_percent))
            act_mdr_rate = float(act_mdr_pct_dec / Decimal("100"))
        else:
            act_mdr_rate = float(actual_mdr_rate)
            act_mdr_pct_dec = Decimal(str(act_mdr_rate * 100))

        actual_fee_paise = int((Decimal(calc_amount_paise) * act_mdr_pct_dec / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        actual_tax_paise = int((Decimal(actual_fee_paise) * gst_pct_dec / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        calc_actual_net_paise = calc_amount_paise - actual_fee_paise - actual_tax_paise
        calc_actual_settle_paise = calc_actual_net_paise
        act_settle_inr_dec = (Decimal(calc_actual_settle_paise) / Decimal("100")).quantize(Decimal("0.01"))
        # For legacy actual_mdr callers: actual_net - expected_net
        calc_variance_paise = calc_actual_net_paise - expected_net_paise
    else:
        actual_fee_paise = expected_fee_paise
        actual_tax_paise = expected_tax_paise
        calc_actual_net_paise = expected_net_paise
        calc_actual_settle_paise = expected_net_paise
        act_settle_inr_dec = (Decimal(calc_actual_settle_paise) / Decimal("100")).quantize(Decimal("0.01"))
        calc_variance_paise = 0
        act_mdr_rate = exp_mdr_rate

    # 6. Classification, Severity & Rounding Tolerance
    is_within_tolerance = abs(calc_variance_paise) <= ROUNDING_TOLERANCE_PAISE
    variance_inr_val = round(float(Decimal(calc_variance_paise) / Decimal("100")), 2)

    if is_within_tolerance:
        classification = "CLEAN" if is_new_payload else "MATCHED"
        severity = "NONE"
    else:
        classification = AnomalyCategory.FEE_ANOMALY
        abs_var = abs(calc_variance_paise)
        if abs_var <= 100:
            severity = VarianceSeverity.LOW
        elif abs_var <= 10000:
            severity = VarianceSeverity.MEDIUM
        elif abs_var <= 100000:
            severity = VarianceSeverity.HIGH
        else:
            severity = VarianceSeverity.CRITICAL

    return {
        "amount_paise": calc_amount_paise,
        "amount_inr": float(amount_inr_dec),
        "payment_method": pm,
        "expected_mdr_rate": exp_mdr_rate,
        "expected_mdr_percent": float(exp_mdr_pct_dec),
        "gst_percent": float(gst_pct_dec),
        "expected_fee_paise": expected_fee_paise,
        "expected_tax_paise": expected_tax_paise,
        "expected_net_paise": expected_net_paise,
        "actual_mdr_rate": act_mdr_rate,
        "actual_fee_paise": actual_fee_paise,
        "actual_tax_paise": actual_tax_paise,
        "actual_net_paise": calc_actual_net_paise,
        "actual_settlement_paise": calc_actual_settle_paise,
        "actual_settlement_inr": float(act_settle_inr_dec),
        "variance_paise": calc_variance_paise,
        "variance_inr": variance_inr_val,
        "classification": classification,
        "severity": severity,
        "within_rounding_tolerance": is_within_tolerance,
        "data_source": "READ_ONLY_SIMULATION",
    }
