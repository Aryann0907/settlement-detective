#!/usr/bin/env python3
"""
Settlement Detective — Synthetic Financial Dataset Generator
Task: Agent A (Database Schema + Synthetic Data)

Generates 10,000+ realistic, correlated e-commerce orders, payments, refunds,
settlement batches, settlement line items, variances (seeded anomalies), and audit logs.

Monetary convention: All amounts are stored as BIGINT in paise (1 INR = 100 paise).
Deterministic seed: SEED = 42 for 100% reproducibility.
"""

import os
import sys
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Fix random seed for exact reproducibility
SEED = 42
random.seed(SEED)

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

SQLITE_DB_PATH = DATA_DIR / "settlement_detective.db"
JSON_OUT_PATH = DATA_DIR / "synthetic_dataset.json"
SQL_OUT_PATH = DATA_DIR / "seed.sql"
SUMMARY_OUT_PATH = DATA_DIR / "summary.json"

# Merchant Fee/MDR Configuration (Standard Baseline)
MDR_RATES = {
    "upi": 0.009,          # 0.90%
    "card": 0.020,         # 2.00%
    "netbanking": 0.018,   # 1.80%
    "wallet": 0.015        # 1.50%
}
GST_RATE = 0.18            # 18% GST on fees

PAYMENT_METHODS = ["upi", "card", "netbanking", "wallet"]
PAYMENT_METHOD_WEIGHTS = [0.50, 0.30, 0.15, 0.05]

START_DATE = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
NUM_DAYS = 90  # 90-day time window (June 1 to August 29, 2026)
TARGET_ORDERS = 10500


def calculate_fee_and_tax(amount_paise: int, method: str, custom_mdr: float = None) -> tuple[int, int]:
    """Calculates deterministic fee and GST tax in paise."""
    mdr = custom_mdr if custom_mdr is not None else MDR_RATES[method]
    fee_paise = round(amount_paise * mdr)
    tax_paise = round(fee_paise * GST_RATE)
    return fee_paise, tax_paise


def generate_dataset():
    print(f"[*] Starting Synthetic Data Generation (Seed: {SEED})...")
    print(f"[*] Target: {TARGET_ORDERS}+ orders across {NUM_DAYS} days.")

    orders = []
    settlements = []
    settlement_line_items = []
    variances = []
    audit_logs = []

    # Keep index lookups for settlements and orders
    orders_by_day = {d: [] for d in range(NUM_DAYS + 1)}
    
    # 1. GENERATE ORDERS
    order_counter = 1
    orders_per_day_avg = TARGET_ORDERS // NUM_DAYS

    for day_idx in range(NUM_DAYS):
        day_date = START_DATE + timedelta(days=day_idx)
        # Weekday variation: Monday-Friday have ~20% higher order volume
        is_weekend = day_date.weekday() >= 5
        daily_count = int(random.gauss(orders_per_day_avg * (0.8 if is_weekend else 1.1), 15))
        daily_count = max(40, daily_count)

        for _ in range(daily_count):
            order_id = f"ord_{order_counter:06d}"
            merchant_order_id = f"MERCH-ORD-{order_counter:06d}"
            rzp_order_id = f"order_{order_counter:06d}"
            
            # Amount: Log-normal distribution around INR 1,450 (145,000 paise)
            # Clamped between INR 99 (9,900 paise) and INR 49,999 (4,999,900 paise)
            amount_rupees = random.lognormvariate(mu=7.25, sigma=0.65)
            amount_paise = int(round(amount_rupees)) * 100
            amount_paise = max(9900, min(amount_paise, 4999900))

            # Payment method
            method = random.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS, k=1)[0]

            # Timestamp within the day
            second_offset = random.randint(0, 85500)
            created_at = day_date + timedelta(seconds=second_offset)

            # Order Status: 92% captured, 5% failed, 3% refunded
            status_roll = random.random()
            if status_roll < 0.05:
                # Failed payment
                status = "failed"
                captured_at = None
                rzp_payment_id = None
                fee_paise = 0
                tax_paise = 0
                net_paise = 0
                refund_status = "none"
                refunded_amount_paise = 0
                refunded_at = None
            elif status_roll < 0.08:
                # Refunded payment (captured first, then refunded)
                status = "refunded"
                capture_delay = random.randint(30, 300)
                captured_at = created_at + timedelta(seconds=capture_delay)
                rzp_payment_id = f"pay_{order_counter:06d}"
                fee_paise, tax_paise = calculate_fee_and_tax(amount_paise, method)
                net_paise = amount_paise - fee_paise - tax_paise
                
                # Full or partial refund
                is_full_refund = random.random() < 0.75
                if is_full_refund:
                    refund_status = "full"
                    refunded_amount_paise = amount_paise
                else:
                    refund_status = "partial"
                    refund_ratio = random.choice([0.25, 0.50, 0.75])
                    refunded_amount_paise = int(round(amount_paise * refund_ratio))
                
                refund_delay_days = random.randint(1, 5)
                refunded_at = captured_at + timedelta(days=refund_delay_days, hours=random.randint(1, 12))
            else:
                # Normal captured payment
                status = "captured"
                capture_delay = random.randint(15, 180)
                captured_at = created_at + timedelta(seconds=capture_delay)
                rzp_payment_id = f"pay_{order_counter:06d}"
                fee_paise, tax_paise = calculate_fee_and_tax(amount_paise, method)
                net_paise = amount_paise - fee_paise - tax_paise
                refund_status = "none"
                refunded_amount_paise = 0
                refunded_at = None

            order_record = {
                "id": order_id,
                "merchant_order_id": merchant_order_id,
                "razorpay_order_id": rzp_order_id,
                "razorpay_payment_id": rzp_payment_id,
                "amount_paise": amount_paise,
                "fee_paise": fee_paise,
                "tax_paise": tax_paise,
                "net_paise": net_paise,
                "refunded_amount_paise": refunded_amount_paise,
                "currency": "INR",
                "status": status,
                "payment_method": method,
                "refund_status": refund_status,
                "customer_email": f"user_{order_counter}@example.com",
                "customer_phone": f"+9198{order_counter%100000000:08d}",
                "created_at": created_at.isoformat(),
                "captured_at": captured_at.isoformat() if captured_at else None,
                "refunded_at": refunded_at.isoformat() if refunded_at else None,
                "metadata": json.dumps({"day_index": day_idx, "is_weekend": is_weekend})
            }
            orders.append(order_record)
            orders_by_day[day_idx].append(order_record)
            order_counter += 1

    print(f"[✓] Generated {len(orders)} total orders.")

    # 2. GENERATE SETTLEMENT BATCHES (T+2 Settlement Cycle)
    # Transactions captured on day D settle on day D+2
    line_item_counter = 1
    variance_counter = 1
    
    # We will seed anomalies on specific target settlement days
    # Day 75 (approx mid-August) will be our FLAGSHIP DEMO SETTLEMENT
    DEMO_SETTLEMENT_DAY = 87  # Corresponds to August 28, 2026

    # Mapping of anomaly types to target days
    ANOMALY_DAYS = {
        20: "AMOUNT_MISMATCH",
        35: "MISSING_SETTLEMENT_LINE",
        48: "DUPLICATE",
        60: "REFUND_MISMATCH",
        72: "TIMING_DIFFERENCE",
        80: "UNEXPLAINED_VARIANCE",
        84: "FEE_ANOMALY",
        DEMO_SETTLEMENT_DAY: "DEMO_FLAGSHIP_SCENARIO"
    }

    for capture_day in range(NUM_DAYS - 2):
        settle_day = capture_day + 2
        period_start = START_DATE + timedelta(days=capture_day)
        period_end = period_start + timedelta(days=1, seconds=-1)
        settled_at = START_DATE + timedelta(days=settle_day, hours=10, minutes=random.randint(0, 45))

        settlement_internal_id = f"set_{settle_day:03d}"
        
        # Check if this is the flagship demo settlement
        if settle_day == DEMO_SETTLEMENT_DAY:
            rzp_settlement_id = "rzp_set_DEMO_20260828"
            utr = "UTR-DEMO-20260828-987654"
        else:
            rzp_settlement_id = f"set_RZP_{settle_day:04d}_{settled_at.strftime('%Y%m%d')}"
            utr = f"UTR{settle_day:03d}{random.randint(10000000, 99999999)}"

        # Get all captured payments on capture_day
        day_orders = orders_by_day[capture_day]
        captured_orders = [o for o in day_orders if o["status"] in ("captured", "refunded")]

        # Get all refunds processed on capture_day (from orders in earlier days)
        day_refunds = []
        for past_day in range(max(0, capture_day - 5), capture_day + 1):
            for o in orders_by_day[past_day]:
                if o["status"] == "refunded" and o["refunded_at"]:
                    ref_dt = datetime.fromisoformat(o["refunded_at"])
                    if period_start <= ref_dt <= period_end:
                        day_refunds.append(o)

        batch_line_items = []
        gross_paise = 0
        fees_paise = 0
        tax_paise = 0
        refunds_paise = 0
        adjustments_paise = 0

        anomaly_type_for_day = ANOMALY_DAYS.get(settle_day)

        # -------------------------------------------------------------
        # SCENARIO A: NORMAL CLEAN SETTLEMENT (Default)
        # -------------------------------------------------------------
        if not anomaly_type_for_day:
            # Clean settlement: each captured payment gets a credit line item
            for o in captured_orders:
                amount = o["amount_paise"]
                fee = o["fee_paise"]
                tax = o["tax_paise"]
                
                gross_paise += amount
                fees_paise += fee
                tax_paise += tax

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": o["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": o["id"],
                    "amount_paise": amount,
                    "fee_paise": fee,
                    "tax_paise": tax,
                    "debit_paise": 0,
                    "credit_paise": amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"match_type": "exact"})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            # Each refund gets a debit line item
            for r in day_refunds:
                ref_amount = r["refunded_amount_paise"]
                refunds_paise += ref_amount

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": f"rfnd_{r['id']}",
                    "entity_type": "refund",
                    "order_id": r["id"],
                    "amount_paise": ref_amount,
                    "fee_paise": 0,
                    "tax_paise": 0,
                    "debit_paise": ref_amount,
                    "credit_paise": 0,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"refund_type": r["refund_status"]})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise + adjustments_paise

        # -------------------------------------------------------------
        # SCENARIO 1: AMOUNT_MISMATCH (Day 20)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "AMOUNT_MISMATCH":
            mismatched_order = captured_orders[0] if captured_orders else None
            for idx, o in enumerate(captured_orders):
                amount = o["amount_paise"]
                fee = o["fee_paise"]
                tax = o["tax_paise"]
                
                # Introduce ₹500 (50,000 paise) mismatch on the first transaction
                if idx == 0 and mismatched_order:
                    reported_amount = amount - 50000
                    expected_amount = amount
                else:
                    reported_amount = amount
                    expected_amount = amount

                gross_paise += reported_amount
                fees_paise += fee
                tax_paise += tax

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": o["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": o["id"],
                    "amount_paise": reported_amount,
                    "fee_paise": fee,
                    "tax_paise": tax,
                    "debit_paise": 0,
                    "credit_paise": reported_amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"anomaly": "AMOUNT_MISMATCH", "expected_amount": expected_amount})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise

            # Record in variances table
            var_record = {
                "id": f"var_{variance_counter:04d}",
                "settlement_id": settlement_internal_id,
                "order_id": mismatched_order["id"],
                "line_item_id": batch_line_items[0]["id"],
                "anomaly_type": "AMOUNT_MISMATCH",
                "severity": "HIGH",
                "expected_amount_paise": mismatched_order["amount_paise"],
                "actual_amount_paise": mismatched_order["amount_paise"] - 50000,
                "variance_paise": -50000,
                "title": f"Amount Mismatch on {mismatched_order['merchant_order_id']}",
                "description": f"Settlement line item reports INR {(mismatched_order['amount_paise']-50000)/100:.2f} instead of captured INR {mismatched_order['amount_paise']/100:.2f}.",
                "status": "detected",
                "evidence": json.dumps({
                    "payment_id": mismatched_order["razorpay_payment_id"],
                    "captured_amount_paise": mismatched_order["amount_paise"],
                    "settled_line_amount_paise": mismatched_order["amount_paise"] - 50000,
                    "discrepancy_paise": -50000
                }),
                "created_at": settled_at.isoformat(),
                "updated_at": settled_at.isoformat()
            }
            variances.append(var_record)
            variance_counter += 1

        # -------------------------------------------------------------
        # SCENARIO 2: MISSING_SETTLEMENT_LINE (Day 35)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "MISSING_SETTLEMENT_LINE":
            missing_order = captured_orders[0] if captured_orders else None
            for idx, o in enumerate(captured_orders):
                # Omit the first order from settlement line items entirely!
                if idx == 0 and missing_order:
                    continue

                amount = o["amount_paise"]
                fee = o["fee_paise"]
                tax = o["tax_paise"]
                gross_paise += amount
                fees_paise += fee
                tax_paise += tax

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": o["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": o["id"],
                    "amount_paise": amount,
                    "fee_paise": fee,
                    "tax_paise": tax,
                    "debit_paise": 0,
                    "credit_paise": amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"match_type": "exact"})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise

            if missing_order:
                var_record = {
                    "id": f"var_{variance_counter:04d}",
                    "settlement_id": settlement_internal_id,
                    "order_id": missing_order["id"],
                    "line_item_id": None,
                    "anomaly_type": "MISSING_SETTLEMENT_LINE",
                    "severity": "CRITICAL",
                    "expected_amount_paise": missing_order["net_paise"],
                    "actual_amount_paise": 0,
                    "variance_paise": -missing_order["net_paise"],
                    "title": f"Missing Payment {missing_order['razorpay_payment_id']} in Settlement Batch",
                    "description": f"Payment {missing_order['razorpay_payment_id']} was successfully captured on {missing_order['captured_at']} but omitted from settlement {rzp_settlement_id}.",
                    "status": "detected",
                    "evidence": json.dumps({
                        "order_id": missing_order["id"],
                        "payment_id": missing_order["razorpay_payment_id"],
                        "captured_amount_paise": missing_order["amount_paise"],
                        "expected_net_paise": missing_order["net_paise"]
                    }),
                    "created_at": settled_at.isoformat(),
                    "updated_at": settled_at.isoformat()
                }
                variances.append(var_record)
                variance_counter += 1

        # -------------------------------------------------------------
        # SCENARIO 3: DUPLICATE (Day 48)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "DUPLICATE":
            dup_order = captured_orders[0] if captured_orders else None
            for idx, o in enumerate(captured_orders):
                amount = o["amount_paise"]
                fee = o["fee_paise"]
                tax = o["tax_paise"]
                gross_paise += amount
                fees_paise += fee
                tax_paise += tax

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": o["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": o["id"],
                    "amount_paise": amount,
                    "fee_paise": fee,
                    "tax_paise": tax,
                    "debit_paise": 0,
                    "credit_paise": amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"match_type": "exact"})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            # Insert duplicate line item for first order
            if dup_order:
                dup_amount = dup_order["amount_paise"]
                dup_fee = dup_order["fee_paise"]
                dup_tax = dup_order["tax_paise"]
                gross_paise += dup_amount
                fees_paise += dup_fee
                tax_paise += dup_tax

                dup_item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": dup_order["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": dup_order["id"],
                    "amount_paise": dup_amount,
                    "fee_paise": dup_fee,
                    "tax_paise": dup_tax,
                    "debit_paise": 0,
                    "credit_paise": dup_amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"anomaly": "DUPLICATE_ITEM"})
                }
                batch_line_items.append(dup_item)
                line_item_counter += 1

                var_record = {
                    "id": f"var_{variance_counter:04d}",
                    "settlement_id": settlement_internal_id,
                    "order_id": dup_order["id"],
                    "line_item_id": dup_item["id"],
                    "anomaly_type": "DUPLICATE",
                    "severity": "HIGH",
                    "expected_amount_paise": dup_order["net_paise"],
                    "actual_amount_paise": dup_order["net_paise"] * 2,
                    "variance_paise": dup_order["net_paise"],
                    "title": f"Duplicate Settlement Entry for {dup_order['razorpay_payment_id']}",
                    "description": f"Payment {dup_order['razorpay_payment_id']} is settled twice in batch {rzp_settlement_id}, resulting in duplicate credit and double fee deduction.",
                    "status": "detected",
                    "evidence": json.dumps({
                        "payment_id": dup_order["razorpay_payment_id"],
                        "duplicate_line_item_id": dup_item["id"],
                        "excess_credit_paise": dup_amount
                    }),
                    "created_at": settled_at.isoformat(),
                    "updated_at": settled_at.isoformat()
                }
                variances.append(var_record)
                variance_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise

        # -------------------------------------------------------------
        # SCENARIO 4: REFUND_MISMATCH (Day 60)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "REFUND_MISMATCH":
            for o in captured_orders:
                amount = o["amount_paise"]
                fee = o["fee_paise"]
                tax = o["tax_paise"]
                gross_paise += amount
                fees_paise += fee
                tax_paise += tax

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": o["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": o["id"],
                    "amount_paise": amount,
                    "fee_paise": fee,
                    "tax_paise": tax,
                    "debit_paise": 0,
                    "credit_paise": amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"match_type": "exact"})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            # Create an intentional refund mismatch: merchant recorded INR 1,200 (120,000 paise),
            # but Razorpay debited INR 2,000 (200,000 paise)
            mismatch_refund_order = captured_orders[0] if captured_orders else None
            if mismatch_refund_order:
                actual_debit = 200000
                expected_debit = 120000
                refunds_paise += actual_debit

                ref_item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": f"rfnd_mismatch_{mismatch_refund_order['id']}",
                    "entity_type": "refund",
                    "order_id": mismatch_refund_order["id"],
                    "amount_paise": actual_debit,
                    "fee_paise": 0,
                    "tax_paise": 0,
                    "debit_paise": actual_debit,
                    "credit_paise": 0,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"anomaly": "REFUND_MISMATCH", "merchant_recorded_refund_paise": expected_debit})
                }
                batch_line_items.append(ref_item)
                line_item_counter += 1

                var_record = {
                    "id": f"var_{variance_counter:04d}",
                    "settlement_id": settlement_internal_id,
                    "order_id": mismatch_refund_order["id"],
                    "line_item_id": ref_item["id"],
                    "anomaly_type": "REFUND_MISMATCH",
                    "severity": "HIGH",
                    "expected_amount_paise": expected_debit,
                    "actual_amount_paise": actual_debit,
                    "variance_paise": -(actual_debit - expected_debit),
                    "title": f"Excess Refund Debit for Order {mismatch_refund_order['merchant_order_id']}",
                    "description": f"Merchant recorded refund of INR {expected_debit/100:.2f}, but Razorpay deducted INR {actual_debit/100:.2f} (Excess debit: INR {(actual_debit-expected_debit)/100:.2f}).",
                    "status": "detected",
                    "evidence": json.dumps({
                        "order_id": mismatch_refund_order["id"],
                        "expected_refund_paise": expected_debit,
                        "actual_refund_debit_paise": actual_debit,
                        "excess_debit_paise": actual_debit - expected_debit
                    }),
                    "created_at": settled_at.isoformat(),
                    "updated_at": settled_at.isoformat()
                }
                variances.append(var_record)
                variance_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise

        # -------------------------------------------------------------
        # SCENARIO 5: TIMING_DIFFERENCE (Day 72)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "TIMING_DIFFERENCE":
            for o in captured_orders:
                amount = o["amount_paise"]
                fee = o["fee_paise"]
                tax = o["tax_paise"]
                gross_paise += amount
                fees_paise += fee
                tax_paise += tax

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": o["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": o["id"],
                    "amount_paise": amount,
                    "fee_paise": fee,
                    "tax_paise": tax,
                    "debit_paise": 0,
                    "credit_paise": amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"match_type": "exact"})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            # Inject a future transaction (from Day 76) prematurely into Day 72 batch
            future_candidates = [o for o in orders_by_day[capture_day + 4] if o.get('razorpay_payment_id')] if (capture_day + 4) in orders_by_day else []
            future_order = future_candidates[0] if future_candidates else None
            if future_order:
                f_amount = future_order["amount_paise"]
                f_fee = future_order["fee_paise"]
                f_tax = future_order["tax_paise"]
                gross_paise += f_amount
                fees_paise += f_fee
                tax_paise += f_tax

                t_item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": future_order["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": future_order["id"],
                    "amount_paise": f_amount,
                    "fee_paise": f_fee,
                    "tax_paise": f_tax,
                    "debit_paise": 0,
                    "credit_paise": f_amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"anomaly": "TIMING_DIFFERENCE", "actual_capture_date": future_order["captured_at"]})
                }
                batch_line_items.append(t_item)
                line_item_counter += 1

                var_record = {
                    "id": f"var_{variance_counter:04d}",
                    "settlement_id": settlement_internal_id,
                    "order_id": future_order["id"],
                    "line_item_id": t_item["id"],
                    "anomaly_type": "TIMING_DIFFERENCE",
                    "severity": "MEDIUM",
                    "expected_amount_paise": 0,
                    "actual_amount_paise": future_order["net_paise"],
                    "variance_paise": future_order["net_paise"],
                    "title": f"Premature Settlement Line Item for {future_order['razorpay_payment_id']}",
                    "description": f"Payment {future_order['razorpay_payment_id']} captured on {future_order['captured_at']} was settled in batch {rzp_settlement_id} 4 days ahead of schedule.",
                    "status": "detected",
                    "evidence": json.dumps({
                        "payment_id": future_order["razorpay_payment_id"],
                        "settlement_period_start": period_start.isoformat(),
                        "settlement_period_end": period_end.isoformat(),
                        "payment_captured_at": future_order["captured_at"]
                    }),
                    "created_at": settled_at.isoformat(),
                    "updated_at": settled_at.isoformat()
                }
                variances.append(var_record)
                variance_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise

        # -------------------------------------------------------------
        # SCENARIO 6: UNEXPLAINED_VARIANCE (Day 80)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "UNEXPLAINED_VARIANCE":
            for o in captured_orders:
                amount = o["amount_paise"]
                fee = o["fee_paise"]
                tax = o["tax_paise"]
                gross_paise += amount
                fees_paise += fee
                tax_paise += tax

                item = {
                    "id": f"sli_{line_item_counter:07d}",
                    "settlement_id": settlement_internal_id,
                    "entity_id": o["razorpay_payment_id"],
                    "entity_type": "payment",
                    "order_id": o["id"],
                    "amount_paise": amount,
                    "fee_paise": fee,
                    "tax_paise": tax,
                    "debit_paise": 0,
                    "credit_paise": amount,
                    "currency": "INR",
                    "settled_at": settled_at.isoformat(),
                    "created_at": settled_at.isoformat(),
                    "metadata": json.dumps({"match_type": "exact"})
                }
                batch_line_items.append(item)
                line_item_counter += 1

            # Razorpay transfers ₹35.50 (3550 paise) LESS without any line item deduction
            unexplained_paise = -3550
            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise + unexplained_paise

            var_record = {
                "id": f"var_{variance_counter:04d}",
                "settlement_id": settlement_internal_id,
                "order_id": None,
                "line_item_id": None,
                "anomaly_type": "UNEXPLAINED_VARIANCE",
                "severity": "HIGH",
                "expected_amount_paise": gross_paise - fees_paise - tax_paise - refunds_paise,
                "actual_amount_paise": net_amount_paise,
                "variance_paise": unexplained_paise,
                "title": f"Unexplained Net Settlement Shortfall of INR {abs(unexplained_paise)/100:.2f}",
                "description": f"Actual bank payout INR {net_amount_paise/100:.2f} is INR {abs(unexplained_paise)/100:.2f} less than computed net settlement from line items.",
                "status": "detected",
                "evidence": json.dumps({
                    "expected_net_paise": gross_paise - fees_paise - tax_paise - refunds_paise,
                    "actual_net_paise": net_amount_paise,
                    "residual_gap_paise": unexplained_paise
                }),
                "created_at": settled_at.isoformat(),
                "updated_at": settled_at.isoformat()
            }
            variances.append(var_record)
            variance_counter += 1

        # -------------------------------------------------------------
        # SCENARIO 7: FEE_ANOMALY (Day 84)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "FEE_ANOMALY":
            fee_anomaly_count = 0
            excess_fee_total = 0

            for idx, o in enumerate(captured_orders):
                amount = o["amount_paise"]
                # For first 6 UPI orders on Day 84, charge 2.50% MDR instead of standard 0.90%
                if o["payment_method"] == "upi" and fee_anomaly_count < 6:
                    inflated_fee, inflated_tax = calculate_fee_and_tax(amount, "upi", custom_mdr=0.025)
                    standard_fee, standard_tax = calculate_fee_and_tax(amount, "upi", custom_mdr=0.009)
                    
                    excess_fee = (inflated_fee + inflated_tax) - (standard_fee + standard_tax)
                    excess_fee_total += excess_fee
                    
                    gross_paise += amount
                    fees_paise += inflated_fee
                    tax_paise += inflated_tax
                    
                    item = {
                        "id": f"sli_{line_item_counter:07d}",
                        "settlement_id": settlement_internal_id,
                        "entity_id": o["razorpay_payment_id"],
                        "entity_type": "payment",
                        "order_id": o["id"],
                        "amount_paise": amount,
                        "fee_paise": inflated_fee,
                        "tax_paise": inflated_tax,
                        "debit_paise": 0,
                        "credit_paise": amount,
                        "currency": "INR",
                        "settled_at": settled_at.isoformat(),
                        "created_at": settled_at.isoformat(),
                        "metadata": json.dumps({"anomaly": "FEE_MDR_SPIKE", "expected_fee_paise": standard_fee, "applied_fee_paise": inflated_fee})
                    }
                    fee_anomaly_count += 1
                else:
                    gross_paise += amount
                    fees_paise += o["fee_paise"]
                    tax_paise += o["tax_paise"]

                    item = {
                        "id": f"sli_{line_item_counter:07d}",
                        "settlement_id": settlement_internal_id,
                        "entity_id": o["razorpay_payment_id"],
                        "entity_type": "payment",
                        "order_id": o["id"],
                        "amount_paise": amount,
                        "fee_paise": o["fee_paise"],
                        "tax_paise": o["tax_paise"],
                        "debit_paise": 0,
                        "credit_paise": amount,
                        "currency": "INR",
                        "settled_at": settled_at.isoformat(),
                        "created_at": settled_at.isoformat(),
                        "metadata": json.dumps({"match_type": "exact"})
                    }
                batch_line_items.append(item)
                line_item_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise

            var_record = {
                "id": f"var_{variance_counter:04d}",
                "settlement_id": settlement_internal_id,
                "order_id": None,
                "line_item_id": None,
                "anomaly_type": "FEE_ANOMALY",
                "severity": "HIGH",
                "expected_amount_paise": fees_paise - excess_fee_total,
                "actual_amount_paise": fees_paise,
                "variance_paise": -excess_fee_total,
                "title": f"MDR Fee Spike on 6 UPI Payments in Settlement {rzp_settlement_id}",
                "description": f"6 UPI transactions were billed at 2.50% MDR instead of the standard 0.90% MDR, causing an excess fee deduction of INR {excess_fee_total/100:.2f}.",
                "status": "detected",
                "evidence": json.dumps({
                    "affected_transactions_count": 6,
                    "expected_mdr": "0.90%",
                    "charged_mdr": "2.50%",
                    "excess_fee_and_tax_paise": excess_fee_total
                }),
                "created_at": settled_at.isoformat(),
                "updated_at": settled_at.isoformat()
            }
            variances.append(var_record)
            variance_counter += 1

        # -------------------------------------------------------------
        # SCENARIO 8: FLAGSHIP 5-MINUTE DEMO SETTLEMENT (Day 87 / Aug 28)
        # -------------------------------------------------------------
        elif anomaly_type_for_day == "DEMO_FLAGSHIP_SCENARIO":
            # Seed 3 dedicated UPI payments with distinct recognizable IDs
            # Standard MDR for UPI = 1.80% (180 bps baseline)
            # Applied MDR on demo day = 2.04% (204 bps)
            # The discrepancy creates an exact INR 17.00 (1700 paise) variance
            demo_excess_fee_paise = 1700
            demo_anomalous_payments = []

            for idx, o in enumerate(captured_orders):
                # We pick 3 UPI payments to carry the subtle MDR variance
                if o["payment_method"] == "upi" and len(demo_anomalous_payments) < 3:
                    pay_idx = len(demo_anomalous_payments) + 1
                    demo_pay_id = f"pay_demo_upi_{pay_idx:03d}"
                    o["razorpay_payment_id"] = demo_pay_id
                    
                    # Exact amounts: INR 2,000.00 each (200,000 paise)
                    amount = 200000
                    o["amount_paise"] = amount
                    
                    # Standard configured fee & tax (1.80% MDR + 18% GST)
                    std_fee = round(amount * 0.018)  # 3600 paise
                    std_tax = round(std_fee * 0.18)   # 648 paise
                    o["fee_paise"] = std_fee
                    o["tax_paise"] = std_tax
                    o["net_paise"] = amount - std_fee - std_tax
                    
                    # Actual fee & tax charged by Razorpay line item (2.04% MDR + 18% GST)
                    actual_fee = 4080  # 2.04% of 200,000
                    actual_tax = 735 if pay_idx < 3 else 734  # 735 for first two, 734 for third
                    discrepancy = (actual_fee + actual_tax) - (std_fee + std_tax)  # 567, 567, 566 -> sum = 1700

                    gross_paise += amount
                    fees_paise += actual_fee
                    tax_paise += actual_tax

                    demo_anomalous_payments.append({
                        "payment_id": demo_pay_id,
                        "order_id": o["id"],
                        "amount_paise": amount,
                        "expected_fee_paise": std_fee,
                        "expected_tax_paise": std_tax,
                        "actual_fee_paise": actual_fee,
                        "actual_tax_paise": actual_tax,
                        "fee_leakage_paise": discrepancy
                    })

                    item = {
                        "id": f"sli_{line_item_counter:07d}",
                        "settlement_id": settlement_internal_id,
                        "entity_id": demo_pay_id,
                        "entity_type": "payment",
                        "order_id": o["id"],
                        "amount_paise": amount,
                        "fee_paise": actual_fee,
                        "tax_paise": actual_tax,
                        "debit_paise": 0,
                        "credit_paise": amount,
                        "currency": "INR",
                        "settled_at": settled_at.isoformat(),
                        "created_at": settled_at.isoformat(),
                        "metadata": json.dumps({
                            "is_demo_anomaly": True,
                            "expected_mdr_rate": 0.018,
                            "applied_mdr_rate": 0.0204,
                            "fee_discrepancy_paise": discrepancy
                        })
                    }
                else:
                    amount = o["amount_paise"]
                    fee = o["fee_paise"]
                    tax = o["tax_paise"]
                    gross_paise += amount
                    fees_paise += fee
                    tax_paise += tax

                    item = {
                        "id": f"sli_{line_item_counter:07d}",
                        "settlement_id": settlement_internal_id,
                        "entity_id": o["razorpay_payment_id"],
                        "entity_type": "payment",
                        "order_id": o["id"],
                        "amount_paise": amount,
                        "fee_paise": fee,
                        "tax_paise": tax,
                        "debit_paise": 0,
                        "credit_paise": amount,
                        "currency": "INR",
                        "settled_at": settled_at.isoformat(),
                        "created_at": settled_at.isoformat(),
                        "metadata": json.dumps({"match_type": "exact"})
                    }
                batch_line_items.append(item)
                line_item_counter += 1

            net_amount_paise = gross_paise - fees_paise - tax_paise - refunds_paise

            # Record Flagship Demo Variance
            var_record = {
                "id": f"var_{variance_counter:04d}",
                "settlement_id": settlement_internal_id,
                "order_id": None,
                "line_item_id": None,
                "anomaly_type": "FEE_ANOMALY",
                "severity": "HIGH",
                "expected_amount_paise": (gross_paise - (fees_paise - demo_excess_fee_paise) - tax_paise - refunds_paise),
                "actual_amount_paise": net_amount_paise,
                "variance_paise": -demo_excess_fee_paise,  # -1700 paise (-INR 17.00)
                "title": "MDR Rate Discrepancy on 3 UPI Transactions (INR 17.00 Discrepancy)",
                "description": f"Settlement {rzp_settlement_id} has an unexplained shortfall of INR 17.00 caused by elevated 2.04% MDR applied on 3 UPI transactions instead of standard 1.80%.",
                "status": "detected",
                "evidence": json.dumps({
                    "flagship_demo": True,
                    "target_settlement_id": rzp_settlement_id,
                    "utr": utr,
                    "expected_settlement_net_paise": net_amount_paise + demo_excess_fee_paise,
                    "actual_settlement_net_paise": net_amount_paise,
                    "shortfall_paise": demo_excess_fee_paise,
                    "affected_payments": demo_anomalous_payments
                }),
                "created_at": settled_at.isoformat(),
                "updated_at": settled_at.isoformat()
            }
            variances.append(var_record)
            variance_counter += 1

        # Create the settlement record
        settlement_record = {
            "id": settlement_internal_id,
            "razorpay_settlement_id": rzp_settlement_id,
            "utr": utr,
            "amount_paise": net_amount_paise,
            "gross_paise": gross_paise,
            "fees_paise": fees_paise,
            "tax_paise": tax_paise,
            "refunds_paise": refunds_paise,
            "adjustments_paise": adjustments_paise,
            "currency": "INR",
            "status": "processed",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "settled_at": settled_at.isoformat(),
            "created_at": settled_at.isoformat(),
            "metadata": json.dumps({
                "line_items_count": len(batch_line_items),
                "is_demo_settlement": (settle_day == DEMO_SETTLEMENT_DAY),
                "anomaly_seeded": anomaly_type_for_day if anomaly_type_for_day else "none"
            })
        }
        settlements.append(settlement_record)
        settlement_line_items.extend(batch_line_items)

    print(f"[✓] Generated {len(settlements)} settlement batches.")
    print(f"[✓] Generated {len(settlement_line_items)} settlement line items.")
    print(f"[✓] Seeded {len(variances)} distinct anomalies with grounded evidence.")

    # 3. GENERATE AUDIT LOG ENTRIES
    audit_logs.append({
        "id": "aud_000001",
        "event_type": "DATASET_INITIALIZATION",
        "entity_type": "system",
        "entity_id": "seed_system_v1",
        "description": f"Generated synthetic financial dataset containing {len(orders)} orders and {len(settlements)} settlements.",
        "actor": "agent_a",
        "metadata": json.dumps({"seed": SEED, "total_orders": len(orders), "total_settlements": len(settlements)}),
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    for v in variances:
        audit_logs.append({
            "id": f"aud_{len(audit_logs)+1:06d}",
            "event_type": "ANOMALY_SEEDED",
            "entity_type": "variance",
            "entity_id": v["id"],
            "description": f"Seeded anomaly [{v['anomaly_type']}] for settlement {v['settlement_id']}: {v['title']}",
            "actor": "synthetic_generator",
            "metadata": json.dumps({"severity": v["severity"], "variance_paise": v["variance_paise"]}),
            "created_at": v["created_at"]
        })

    print(f"[✓] Created {len(audit_logs)} audit log records.")

    # 4. WRITE EXPORTS (SQLite, JSON, SQL)
    export_to_sqlite(orders, settlements, settlement_line_items, variances, audit_logs)
    export_to_json(orders, settlements, settlement_line_items, variances, audit_logs)
    export_to_sql(orders, settlements, settlement_line_items, variances, audit_logs)

    # 5. WRITE SUMMARY
    summary = {
        "generator_version": "1.0.0",
        "seed": SEED,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_orders": len(orders),
        "total_settlements": len(settlements),
        "total_line_items": len(settlement_line_items),
        "total_variances": len(variances),
        "total_audit_logs": len(audit_logs),
        "clean_settlements_count": len([s for s in settlements if json.loads(s["metadata"])["anomaly_seeded"] == "none"]),
        "anomalous_settlements_count": len(variances),
        "demo_settlement": {
            "id": "set_087",
            "razorpay_settlement_id": "rzp_set_DEMO_20260828",
            "utr": "UTR-DEMO-20260828-987654",
            "variance_paise": -1700,
            "variance_inr": -17.00,
            "anomaly_type": "FEE_ANOMALY",
            "affected_payments": ["pay_demo_upi_001", "pay_demo_upi_002", "pay_demo_upi_003"]
        },
        "seeded_anomalies": [
            {
                "id": v["id"],
                "settlement_id": v["settlement_id"],
                "anomaly_type": v["anomaly_type"],
                "severity": v["severity"],
                "variance_paise": v["variance_paise"],
                "variance_inr": round(v["variance_paise"] / 100, 2),
                "title": v["title"]
            }
            for v in variances
        ]
    }
    with open(SUMMARY_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"[✓] Summary written to {SUMMARY_OUT_PATH}")
    return summary


def export_to_sqlite(orders, settlements, settlement_line_items, variances, audit_logs):
    if SQLITE_DB_PATH.exists():
        SQLITE_DB_PATH.unlink()

    conn = sqlite3.connect(SQLITE_DB_PATH)
    cursor = conn.cursor()

    # Create tables
    cursor.executescript("""
    CREATE TABLE orders (
        id TEXT PRIMARY KEY,
        merchant_order_id TEXT UNIQUE NOT NULL,
        razorpay_order_id TEXT UNIQUE,
        razorpay_payment_id TEXT UNIQUE,
        amount_paise INTEGER NOT NULL,
        fee_paise INTEGER NOT NULL DEFAULT 0,
        tax_paise INTEGER NOT NULL DEFAULT 0,
        net_paise INTEGER NOT NULL DEFAULT 0,
        refunded_amount_paise INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'INR',
        status TEXT NOT NULL,
        payment_method TEXT NOT NULL,
        refund_status TEXT NOT NULL DEFAULT 'none',
        customer_email TEXT,
        customer_phone TEXT,
        created_at TEXT NOT NULL,
        captured_at TEXT,
        refunded_at TEXT,
        metadata TEXT
    );

    CREATE TABLE settlements (
        id TEXT PRIMARY KEY,
        razorpay_settlement_id TEXT UNIQUE NOT NULL,
        utr TEXT UNIQUE,
        amount_paise INTEGER NOT NULL,
        gross_paise INTEGER NOT NULL DEFAULT 0,
        fees_paise INTEGER NOT NULL DEFAULT 0,
        tax_paise INTEGER NOT NULL DEFAULT 0,
        refunds_paise INTEGER NOT NULL DEFAULT 0,
        adjustments_paise INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'INR',
        status TEXT NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        settled_at TEXT,
        created_at TEXT NOT NULL,
        metadata TEXT
    );

    CREATE TABLE settlement_line_items (
        id TEXT PRIMARY KEY,
        settlement_id TEXT NOT NULL REFERENCES settlements(id) ON DELETE CASCADE,
        entity_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
        amount_paise INTEGER NOT NULL,
        fee_paise INTEGER NOT NULL DEFAULT 0,
        tax_paise INTEGER NOT NULL DEFAULT 0,
        debit_paise INTEGER NOT NULL DEFAULT 0,
        credit_paise INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'INR',
        settled_at TEXT,
        created_at TEXT NOT NULL,
        metadata TEXT
    );

    CREATE TABLE variances (
        id TEXT PRIMARY KEY,
        settlement_id TEXT REFERENCES settlements(id) ON DELETE CASCADE,
        order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
        line_item_id TEXT REFERENCES settlement_line_items(id) ON DELETE SET NULL,
        anomaly_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        expected_amount_paise INTEGER NOT NULL,
        actual_amount_paise INTEGER NOT NULL,
        variance_paise INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'detected',
        evidence TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE audit_log (
        id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        description TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT 'system',
        metadata TEXT,
        created_at TEXT NOT NULL
    );
    """)

    # Insert data in batches
    cursor.executemany("""
    INSERT INTO orders VALUES (
        :id, :merchant_order_id, :razorpay_order_id, :razorpay_payment_id,
        :amount_paise, :fee_paise, :tax_paise, :net_paise, :refunded_amount_paise,
        :currency, :status, :payment_method, :refund_status, :customer_email,
        :customer_phone, :created_at, :captured_at, :refunded_at, :metadata
    )
    """, orders)

    cursor.executemany("""
    INSERT INTO settlements VALUES (
        :id, :razorpay_settlement_id, :utr, :amount_paise, :gross_paise,
        :fees_paise, :tax_paise, :refunds_paise, :adjustments_paise,
        :currency, :status, :period_start, :period_end, :settled_at,
        :created_at, :metadata
    )
    """, settlements)

    cursor.executemany("""
    INSERT INTO settlement_line_items VALUES (
        :id, :settlement_id, :entity_id, :entity_type, :order_id,
        :amount_paise, :fee_paise, :tax_paise, :debit_paise, :credit_paise,
        :currency, :settled_at, :created_at, :metadata
    )
    """, settlement_line_items)

    cursor.executemany("""
    INSERT INTO variances VALUES (
        :id, :settlement_id, :order_id, :line_item_id, :anomaly_type,
        :severity, :expected_amount_paise, :actual_amount_paise,
        :variance_paise, :title, :description, :status, :evidence,
        :created_at, :updated_at
    )
    """, variances)

    cursor.executemany("""
    INSERT INTO audit_log VALUES (
        :id, :event_type, :entity_type, :entity_id, :description,
        :actor, :metadata, :created_at
    )
    """, audit_logs)

    conn.commit()
    conn.close()
    print(f"[✓] Populated SQLite Database at {SQLITE_DB_PATH}")


def export_to_json(orders, settlements, settlement_line_items, variances, audit_logs):
    data = {
        "orders": orders,
        "settlements": settlements,
        "settlement_line_items": settlement_line_items,
        "variances": variances,
        "audit_log": audit_logs
    }
    with open(JSON_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[✓] Exported JSON Dataset to {JSON_OUT_PATH}")


def export_to_sql(orders, settlements, settlement_line_items, variances, audit_logs):
    with open(SQL_OUT_PATH, "w", encoding="utf-8") as f:
        f.write("-- Settlement Detective - Seed Data\n\n")
        
        for o in orders:
            f.write(
                f"INSERT INTO orders (id, merchant_order_id, razorpay_order_id, razorpay_payment_id, "
                f"amount_paise, fee_paise, tax_paise, net_paise, refunded_amount_paise, currency, "
                f"status, payment_method, refund_status, customer_email, customer_phone, created_at, captured_at, refunded_at, metadata) "
                f"VALUES ({repr(o['id'])}, {repr(o['merchant_order_id'])}, {repr(o['razorpay_order_id'])}, {repr(o['razorpay_payment_id'])}, "
                f"{o['amount_paise']}, {o['fee_paise']}, {o['tax_paise']}, {o['net_paise']}, {o['refunded_amount_paise']}, {repr(o['currency'])}, "
                f"{repr(o['status'])}, {repr(o['payment_method'])}, {repr(o['refund_status'])}, {repr(o['customer_email'])}, {repr(o['customer_phone'])}, "
                f"{repr(o['created_at'])}, {repr(o['captured_at'])}, {repr(o['refunded_at'])}, {repr(o['metadata'])}::jsonb);\n"
            )

        for s in settlements:
            f.write(
                f"INSERT INTO settlements (id, razorpay_settlement_id, utr, amount_paise, gross_paise, fees_paise, tax_paise, refunds_paise, adjustments_paise, currency, status, period_start, period_end, settled_at, created_at, metadata) "
                f"VALUES ({repr(s['id'])}, {repr(s['razorpay_settlement_id'])}, {repr(s['utr'])}, {s['amount_paise']}, {s['gross_paise']}, {s['fees_paise']}, {s['tax_paise']}, {s['refunds_paise']}, {s['adjustments_paise']}, {repr(s['currency'])}, {repr(s['status'])}, {repr(s['period_start'])}, {repr(s['period_end'])}, {repr(s['settled_at'])}, {repr(s['created_at'])}, {repr(s['metadata'])}::jsonb);\n"
            )

        for sli in settlement_line_items:
            f.write(
                f"INSERT INTO settlement_line_items (id, settlement_id, entity_id, entity_type, order_id, amount_paise, fee_paise, tax_paise, debit_paise, credit_paise, currency, settled_at, created_at, metadata) "
                f"VALUES ({repr(sli['id'])}, {repr(sli['settlement_id'])}, {repr(sli['entity_id'])}, {repr(sli['entity_type'])}, {repr(sli['order_id'])}, {sli['amount_paise']}, {sli['fee_paise']}, {sli['tax_paise']}, {sli['debit_paise']}, {sli['credit_paise']}, {repr(sli['currency'])}, {repr(sli['settled_at'])}, {repr(sli['created_at'])}, {repr(sli['metadata'])}::jsonb);\n"
            )

        for v in variances:
            f.write(
                f"INSERT INTO variances (id, settlement_id, order_id, line_item_id, anomaly_type, severity, expected_amount_paise, actual_amount_paise, variance_paise, title, description, status, evidence, created_at, updated_at) "
                f"VALUES ({repr(v['id'])}, {repr(v['settlement_id'])}, {repr(v['order_id'])}, {repr(v['line_item_id'])}, {repr(v['anomaly_type'])}, {repr(v['severity'])}, {v['expected_amount_paise']}, {v['actual_amount_paise']}, {v['variance_paise']}, {repr(v['title'])}, {repr(v['description'])}, {repr(v['status'])}, {repr(v['evidence'])}::jsonb, {repr(v['created_at'])}, {repr(v['updated_at'])});\n"
            )

        for a in audit_logs:
            f.write(
                f"INSERT INTO audit_log (id, event_type, entity_type, entity_id, description, actor, metadata, created_at) "
                f"VALUES ({repr(a['id'])}, {repr(a['event_type'])}, {repr(a['entity_type'])}, {repr(a['entity_id'])}, {repr(a['description'])}, {repr(a['actor'])}, {repr(a['metadata'])}::jsonb, {repr(a['created_at'])});\n"
            )

    print(f"[✓] Exported PostgreSQL Seed Script to {SQL_OUT_PATH}")


if __name__ == "__main__":
    generate_dataset()
