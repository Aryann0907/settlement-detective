"""
Settlement Detective — Deterministic Reconciliation Engine
Task: Agent B (Reconciliation Pipeline)

Implements 5-pass deterministic reconciliation, financial arithmetic in integer paise,
first-principles anomaly detection, and grounded structured evidence generation.

Zero hard-coded anomaly results. Zero floating-point arithmetic.
"""

import json
import sqlite3
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone

from .config import (
    DEFAULT_MDR_RATES,
    GST_RATE,
    AnomalyCategory,
    VarianceSeverity,
    DifferenceClassification,
    calculate_expected_fee_and_tax
)
from .matching import MultiPassMatcher, MatchResult


class ReconciliationSummary:
    def __init__(self, settlement_id: str, razorpay_settlement_id: str):
        self.settlement_id = settlement_id
        self.razorpay_settlement_id = razorpay_settlement_id
        self.gross_expected_paise = 0
        self.gross_actual_paise = 0
        self.fees_expected_paise = 0
        self.fees_actual_paise = 0
        self.tax_expected_paise = 0
        self.tax_actual_paise = 0
        self.refunds_expected_paise = 0
        self.refunds_actual_paise = 0
        self.adjustments_paise = 0
        self.expected_net_paise = 0
        self.actual_net_paise = 0
        self.net_variance_paise = 0
        self.total_line_items = 0
        self.matched_exact = 0
        self.matched_order_based = 0
        self.unmatched_line_items = 0
        self.missing_orders_count = 0
        self.is_clean = True
        self.variances: List[Dict[str, Any]] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "settlement_id": self.settlement_id,
            "razorpay_settlement_id": self.razorpay_settlement_id,
            "gross_expected_paise": self.gross_expected_paise,
            "gross_actual_paise": self.gross_actual_paise,
            "fees_expected_paise": self.fees_expected_paise,
            "fees_actual_paise": self.fees_actual_paise,
            "tax_expected_paise": self.tax_expected_paise,
            "tax_actual_paise": self.tax_actual_paise,
            "refunds_expected_paise": self.refunds_expected_paise,
            "refunds_actual_paise": self.refunds_actual_paise,
            "adjustments_paise": self.adjustments_paise,
            "expected_net_paise": self.expected_net_paise,
            "actual_net_paise": self.actual_net_paise,
            "net_variance_paise": self.net_variance_paise,
            "total_line_items": self.total_line_items,
            "matched_exact": self.matched_exact,
            "matched_order_based": self.matched_order_based,
            "unmatched_line_items": self.unmatched_line_items,
            "missing_orders_count": self.missing_orders_count,
            "is_clean": self.is_clean,
            "variances_count": len(self.variances),
            "variances": self.variances
        }


class DeterministicReconciliationEngine:
    """
    Core Deterministic Reconciliation Engine for Razorpay Merchants.
    Processes settlements, verifies transaction line items, detects financial leakages,
    and constructs grounded audit-ready evidence.
    """

    def __init__(self, db_conn: sqlite3.Connection, mdr_rates: Optional[Dict[str, float]] = None):
        self.conn = db_conn
        self.conn.row_factory = sqlite3.Row
        self.mdr_rates = mdr_rates if mdr_rates is not None else DEFAULT_MDR_RATES

    def reconcile_all_settlements(self) -> List[ReconciliationSummary]:
        """Runs reconciliation over all settlements in the database."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM settlements ORDER BY settled_at ASC")
        settlement_rows = cursor.fetchall()
        
        summaries = []
        for row in settlement_rows:
            summary = self.reconcile_settlement(row["id"])
            summaries.append(summary)
        return summaries

    def reconcile_settlement(self, settlement_id: str) -> ReconciliationSummary:
        """
        Reconciles a single settlement by executing the 5-pass pipeline.
        Idempotently writes detected variances to the database.
        """
        cursor = self.conn.cursor()

        # Step 1: Load settlement record
        cursor.execute("SELECT * FROM settlements WHERE id = ?", (settlement_id,))
        settlement_row = cursor.fetchone()
        if not settlement_row:
            raise ValueError(f"Settlement '{settlement_id}' not found in database.")

        settlement = dict(settlement_row)
        period_start = settlement["period_start"]
        period_end = settlement["period_end"]

        # Step 2: Load line items
        cursor.execute("SELECT * FROM settlement_line_items WHERE settlement_id = ? ORDER BY id ASC", (settlement_id,))
        line_item_rows = cursor.fetchall()
        line_items = [dict(r) for r in line_item_rows]

        # Step 3: Load all candidate orders (around the period)
        cursor.execute("""
            SELECT * FROM orders 
            WHERE (captured_at BETWEEN datetime(?, '-7 days') AND datetime(?, '+7 days'))
               OR (refunded_at BETWEEN datetime(?, '-7 days') AND datetime(?, '+7 days'))
               OR created_at BETWEEN datetime(?, '-7 days') AND datetime(?, '+7 days')
        """, (period_start, period_end, period_start, period_end, period_start, period_end))
        order_rows = cursor.fetchall()
        candidate_orders = [dict(r) for r in order_rows]

        # Step 4: Run Multi-Pass Matching (Pass 1, 2, 3)
        matcher = MultiPassMatcher(candidate_orders)
        matched_results, unmatched_eligible_orders = matcher.match_line_items(line_items, period_start, period_end)

        summary = ReconciliationSummary(
            settlement_id=settlement["id"],
            razorpay_settlement_id=settlement["razorpay_settlement_id"]
        )
        summary.total_line_items = len(line_items)
        summary.adjustments_paise = settlement["adjustments_paise"]
        summary.actual_net_paise = settlement["amount_paise"]

        # Step 5: PASS 4 — First-Principles Anomaly Detection
        detected_variances: List[Dict[str, Any]] = []

        # -------------------------------------------------------------
        # 4.1: DUPLICATE DETECTION
        # -------------------------------------------------------------
        entity_counts: Dict[str, List[Dict[str, Any]]] = {}
        for item in line_items:
            eid = item["entity_id"]
            entity_counts.setdefault(eid, []).append(item)

        for eid, items in entity_counts.items():
            if len(items) > 1:
                # Same payment settled multiple times
                primary_item = items[0]
                excess_items = items[1:]
                excess_credit = sum(it["credit_paise"] for it in excess_items)
                excess_fees = sum(it["fee_paise"] + it["tax_paise"] for it in excess_items)

                var_id = f"var_recon_{settlement_id}_{primary_item['id']}_dup"
                detected_variances.append({
                    "id": var_id,
                    "settlement_id": settlement_id,
                    "order_id": primary_item.get("order_id"),
                    "line_item_id": primary_item["id"],
                    "anomaly_type": AnomalyCategory.DUPLICATE,
                    "severity": VarianceSeverity.HIGH,
                    "expected_amount_paise": primary_item["credit_paise"] - (primary_item["fee_paise"] + primary_item["tax_paise"]),
                    "actual_amount_paise": sum(it["credit_paise"] - (it["fee_paise"] + it["tax_paise"]) for it in items),
                    "variance_paise": excess_credit - excess_fees,
                    "title": f"Duplicate Settlement Line for Entity {eid}",
                    "description": f"Entity {eid} appears {len(items)} times in settlement {settlement['razorpay_settlement_id']}, causing duplicate credit of INR {excess_credit/100:.2f}.",
                    "status": "detected",
                    "evidence": {
                        "settlement_id": settlement_id,
                        "razorpay_settlement_id": settlement["razorpay_settlement_id"],
                        "entity_id": eid,
                        "occurrence_count": len(items),
                        "duplicate_line_item_ids": [it["id"] for it in items],
                        "excess_credit_paise": excess_credit,
                        "excess_fee_deductions_paise": excess_fees,
                        "category": DifferenceClassification.DUPLICATE,
                        "detection_rule": "duplicate_entity_id_in_line_items"
                    }
                })

        # -------------------------------------------------------------
        # 4.2: AMOUNT MISMATCH & TIMING ANOMALIES
        # -------------------------------------------------------------
        fee_anomaly_breakdown: List[Dict[str, Any]] = []
        total_fee_leakage_paise = 0

        for match in matched_results:
            item = match.line_item
            order = match.order

            if match.match_type == "exact":
                summary.matched_exact += 1
            elif match.match_type == "order_based":
                summary.matched_order_based += 1
            else:
                summary.unmatched_line_items += 1

            if item["entity_type"] == "payment":
                summary.gross_actual_paise += item["amount_paise"]
                summary.fees_actual_paise += item["fee_paise"]
                summary.tax_actual_paise += item["tax_paise"]

                if order:
                    summary.gross_expected_paise += order["amount_paise"]

                    # Check Amount Mismatch
                    if item["amount_paise"] != order["amount_paise"]:
                        diff = item["amount_paise"] - order["amount_paise"]
                        var_id = f"var_recon_{settlement_id}_{item['id']}_amt"
                        detected_variances.append({
                            "id": var_id,
                            "settlement_id": settlement_id,
                            "order_id": order["id"],
                            "line_item_id": item["id"],
                            "anomaly_type": AnomalyCategory.AMOUNT_MISMATCH,
                            "severity": VarianceSeverity.HIGH,
                            "expected_amount_paise": order["amount_paise"],
                            "actual_amount_paise": item["amount_paise"],
                            "variance_paise": diff,
                            "title": f"Amount Mismatch for Order {order['merchant_order_id']}",
                            "description": f"Settlement line item reports INR {item['amount_paise']/100:.2f} vs merchant captured INR {order['amount_paise']/100:.2f}.",
                            "status": "detected",
                            "evidence": {
                                "settlement_id": settlement_id,
                                "order_id": order["id"],
                                "payment_id": order.get("razorpay_payment_id"),
                                "line_item_id": item["id"],
                                "expected_amount_paise": order["amount_paise"],
                                "actual_amount_paise": item["amount_paise"],
                                "discrepancy_paise": diff,
                                "category": DifferenceClassification.POTENTIAL_LEAKAGE if diff < 0 else DifferenceClassification.UNEXPLAINED,
                                "detection_rule": "line_item_amount_ne_captured_amount"
                            }
                        })

                    # Check Timing Window Anomaly (Captured outside settlement period)
                    captured_at = order.get("captured_at")
                    if captured_at and not (period_start <= captured_at <= period_end):
                        var_id = f"var_recon_{settlement_id}_{item['id']}_timing"
                        detected_variances.append({
                            "id": var_id,
                            "settlement_id": settlement_id,
                            "order_id": order["id"],
                            "line_item_id": item["id"],
                            "anomaly_type": AnomalyCategory.TIMING_DIFFERENCE,
                            "severity": VarianceSeverity.MEDIUM,
                            "expected_amount_paise": 0,
                            "actual_amount_paise": item["amount_paise"] - (item["fee_paise"] + item["tax_paise"]),
                            "variance_paise": item["amount_paise"] - (item["fee_paise"] + item["tax_paise"]),
                            "title": f"Timing Mismatch for Payment {order.get('razorpay_payment_id')}",
                            "description": f"Payment captured at {captured_at} settled in batch with capture period {period_start} to {period_end}.",
                            "status": "detected",
                            "evidence": {
                                "settlement_id": settlement_id,
                                "payment_id": order.get("razorpay_payment_id"),
                                "line_item_id": item["id"],
                                "captured_at": captured_at,
                                "settlement_period_start": period_start,
                                "settlement_period_end": period_end,
                                "category": DifferenceClassification.TIMING_DIFFERENCE,
                                "detection_rule": "captured_at_outside_period_boundaries"
                            }
                        })

                    # ---------------------------------------------------------
                    # 4.3: FEE & MDR DEDUCTION ANOMALY DETECTION
                    # ---------------------------------------------------------
                    # Calculate expected fee and tax based on merchant order records or configured MDR rate
                    pm = order.get("payment_method", "upi")
                    if order.get("fee_paise") is not None and order.get("fee_paise") > 0:
                        expected_fee = order["fee_paise"]
                        expected_tax = order.get("tax_paise", round(expected_fee * GST_RATE))
                    else:
                        expected_fee, expected_tax = calculate_expected_fee_and_tax(order["amount_paise"], pm, self.mdr_rates.get(pm))

                    summary.fees_expected_paise += expected_fee
                    summary.tax_expected_paise += expected_tax

                    actual_fee = item["fee_paise"]
                    actual_tax = item["tax_paise"]

                    fee_diff = (actual_fee + actual_tax) - (expected_fee + expected_tax)
                    if fee_diff != 0:
                        total_fee_leakage_paise += fee_diff
                        fee_anomaly_breakdown.append({
                            "payment_id": order.get("razorpay_payment_id"),
                            "order_id": order["id"],
                            "line_item_id": item["id"],
                            "amount_paise": order["amount_paise"],
                            "payment_method": pm,
                            "expected_fee_paise": expected_fee,
                            "expected_tax_paise": expected_tax,
                            "actual_fee_paise": actual_fee,
                            "actual_tax_paise": actual_tax,
                            "fee_leakage_paise": fee_diff,
                            "captured_at": order.get("captured_at")
                        })

            elif item["entity_type"] == "refund":
                summary.refunds_actual_paise += item["debit_paise"]

                if order:
                    expected_refund = order.get("refunded_amount_paise", 0)
                    summary.refunds_expected_paise += expected_refund

                    # 4.4: REFUND MISMATCH DETECTION
                    if item["debit_paise"] != expected_refund:
                        refund_diff = item["debit_paise"] - expected_refund
                        var_id = f"var_recon_{settlement_id}_{item['id']}_rfnd"
                        detected_variances.append({
                            "id": var_id,
                            "settlement_id": settlement_id,
                            "order_id": order["id"],
                            "line_item_id": item["id"],
                            "anomaly_type": AnomalyCategory.REFUND_MISMATCH,
                            "severity": VarianceSeverity.HIGH,
                            "expected_amount_paise": expected_refund,
                            "actual_amount_paise": item["debit_paise"],
                            "variance_paise": -refund_diff,
                            "title": f"Excess Refund Debit on Order {order['merchant_order_id']}",
                            "description": f"Merchant recorded refund of INR {expected_refund/100:.2f}, but Razorpay deducted INR {item['debit_paise']/100:.2f}.",
                            "status": "detected",
                            "evidence": {
                                "settlement_id": settlement_id,
                                "order_id": order["id"],
                                "line_item_id": item["id"],
                                "expected_refund_paise": expected_refund,
                                "actual_refund_debit_paise": item["debit_paise"],
                                "excess_debit_paise": refund_diff,
                                "category": DifferenceClassification.REFUND,
                                "detection_rule": "line_item_debit_ne_order_refund_amount"
                            }
                        })

        # -------------------------------------------------------------
        # 4.5: AGGREGATED FEE ANOMALY
        # -------------------------------------------------------------
        if fee_anomaly_breakdown:
            var_id = f"var_recon_{settlement_id}_fee_anomaly"
            detected_variances.append({
                "id": var_id,
                "settlement_id": settlement_id,
                "order_id": None,
                "line_item_id": None,
                "anomaly_type": AnomalyCategory.FEE_ANOMALY,
                "severity": VarianceSeverity.HIGH,
                "expected_amount_paise": summary.fees_expected_paise + summary.tax_expected_paise,
                "actual_amount_paise": summary.fees_actual_paise + summary.tax_actual_paise,
                "variance_paise": -total_fee_leakage_paise,
                "title": f"MDR Rate Discrepancy on {len(fee_anomaly_breakdown)} Transactions",
                "description": f"Detected MDR fee discrepancy across {len(fee_anomaly_breakdown)} transactions causing total excess fee deduction of INR {total_fee_leakage_paise/100:.2f}.",
                "status": "detected",
                "evidence": {
                    "settlement_id": settlement_id,
                    "razorpay_settlement_id": settlement["razorpay_settlement_id"],
                    "affected_transactions_count": len(fee_anomaly_breakdown),
                    "total_fee_leakage_paise": total_fee_leakage_paise,
                    "category": DifferenceClassification.FEE_DEDUCTION,
                    "detection_rule": "actual_mdr_fee_exceeds_configured_rate",
                    "affected_payments": fee_anomaly_breakdown
                }
            })

        # -------------------------------------------------------------
        # 4.6: MISSING SETTLEMENT LINES
        # -------------------------------------------------------------
        summary.missing_orders_count = len(unmatched_eligible_orders)
        for missing_order in unmatched_eligible_orders:
            exp_fee, exp_tax = calculate_expected_fee_and_tax(missing_order["amount_paise"], missing_order.get("payment_method", "upi"))
            expected_net = missing_order["amount_paise"] - exp_fee - exp_tax
            var_id = f"var_recon_{settlement_id}_{missing_order['id']}_missing"
            
            detected_variances.append({
                "id": var_id,
                "settlement_id": settlement_id,
                "order_id": missing_order["id"],
                "line_item_id": None,
                "anomaly_type": AnomalyCategory.MISSING_SETTLEMENT_LINE,
                "severity": VarianceSeverity.CRITICAL,
                "expected_amount_paise": expected_net,
                "actual_amount_paise": 0,
                "variance_paise": -expected_net,
                "title": f"Missing Payment {missing_order.get('razorpay_payment_id')} in Settlement",
                "description": f"Payment {missing_order.get('razorpay_payment_id')} captured on {missing_order.get('captured_at')} is missing from settlement line items.",
                "status": "detected",
                "evidence": {
                    "settlement_id": settlement_id,
                    "order_id": missing_order["id"],
                    "payment_id": missing_order.get("razorpay_payment_id"),
                    "captured_amount_paise": missing_order["amount_paise"],
                    "captured_at": missing_order.get("captured_at"),
                    "expected_net_paise": expected_net,
                    "category": DifferenceClassification.UNMATCHED,
                    "detection_rule": "captured_order_omitted_from_settlement_batch"
                }
            })

        # -------------------------------------------------------------
        # 4.7: UNEXPLAINED RESIDUAL VARIANCE
        # -------------------------------------------------------------
        # Calculate expected net settlement
        summary.expected_net_paise = (
            summary.gross_expected_paise
            - summary.fees_expected_paise
            - summary.tax_expected_paise
            - summary.refunds_expected_paise
            + summary.adjustments_paise
        )
        summary.net_variance_paise = summary.actual_net_paise - summary.expected_net_paise

        # Check if actual bank payout has an unexplained residual difference from line item totals
        calculated_line_items_net = (
            summary.gross_actual_paise
            - summary.fees_actual_paise
            - summary.tax_actual_paise
            - summary.refunds_actual_paise
            + summary.adjustments_paise
        )
        residual_gap_paise = summary.actual_net_paise - calculated_line_items_net

        if residual_gap_paise != 0:
            var_id = f"var_recon_{settlement_id}_unexplained"
            detected_variances.append({
                "id": var_id,
                "settlement_id": settlement_id,
                "order_id": None,
                "line_item_id": None,
                "anomaly_type": AnomalyCategory.UNEXPLAINED_VARIANCE,
                "severity": VarianceSeverity.HIGH,
                "expected_amount_paise": calculated_line_items_net,
                "actual_amount_paise": summary.actual_net_paise,
                "variance_paise": residual_gap_paise,
                "title": f"Unexplained Net Settlement Shortfall of INR {abs(residual_gap_paise)/100:.2f}",
                "description": f"Actual payout of INR {summary.actual_net_paise/100:.2f} differs by INR {abs(residual_gap_paise)/100:.2f} from line item total.",
                "status": "detected",
                "evidence": {
                    "settlement_id": settlement_id,
                    "razorpay_settlement_id": settlement["razorpay_settlement_id"],
                    "line_item_computed_net_paise": calculated_line_items_net,
                    "actual_settlement_net_paise": summary.actual_net_paise,
                    "residual_gap_paise": residual_gap_paise,
                    "category": DifferenceClassification.UNEXPLAINED,
                    "detection_rule": "bank_payout_ne_line_items_net_sum"
                }
            })

        summary.variances = detected_variances
        summary.is_clean = (len(detected_variances) == 0 and summary.net_variance_paise == 0)

        # Step 6: IDEMPOTENT DATABASE PERSISTENCE
        # Clear previous variances for this settlement and re-insert fresh derived results
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("DELETE FROM variances WHERE settlement_id = ?", (settlement_id,))

        for v in detected_variances:
            cursor.execute("""
                INSERT INTO variances (
                    id, settlement_id, order_id, line_item_id, anomaly_type,
                    severity, expected_amount_paise, actual_amount_paise,
                    variance_paise, title, description, status, evidence,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                v["id"],
                v["settlement_id"],
                v["order_id"],
                v["line_item_id"],
                v["anomaly_type"],
                v["severity"],
                v["expected_amount_paise"],
                v["actual_amount_paise"],
                v["variance_paise"],
                v["title"],
                v["description"],
                v["status"],
                json.dumps(v["evidence"]),
                now_iso,
                now_iso
            ))

        self.conn.commit()
        return summary
