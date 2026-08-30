"""
Settlement Detective — Reconciliation Configuration
Defines merchant MDR fee rates, tax rates, tolerances, and classification enums.
"""

from typing import Dict

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


def calculate_expected_fee_and_tax(amount_paise: int, payment_method: str, custom_mdr_rate: float = None) -> tuple[int, int]:
    """
    Deterministically computes expected fee and GST tax in integer paise.
    All monetary calculations use strict integer arithmetic with rounding.
    """
    mdr = custom_mdr_rate if custom_mdr_rate is not None else DEFAULT_MDR_RATES.get(payment_method, 0.02)
    expected_fee_paise = round(amount_paise * mdr)
    expected_tax_paise = round(expected_fee_paise * GST_RATE)
    return expected_fee_paise, expected_tax_paise
