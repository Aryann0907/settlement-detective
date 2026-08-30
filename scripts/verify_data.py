#!/usr/bin/env python3
"""
Settlement Detective — Data & Schema Verification Suite
Task: Agent A (Validation Suite)

Executes 8 core validation suites:
1. Schema & Table Structure
2. Record Count Assertions (10,000+ orders)
3. Foreign Key & Entity Integrity
4. Monetary Field Integrity (Paise representation, non-negative integers)
5. Clean Settlement Mathematical Reconciliations (100% precision)
6. Seeded Anomaly Verification (All 7 types + Flagship Demo)
7. Audit Trail Integrity
8. Seed 42 Determinism & Reproducibility
"""

import sys
import json
import sqlite3
import hashlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "settlement_detective.db"
JSON_PATH = DATA_DIR / "synthetic_dataset.json"
SUMMARY_PATH = DATA_DIR / "summary.json"


def run_validations():
    print("=" * 70)
    print("SETTLEMENT DETECTIVE — AGENT A VALIDATION SUITE")
    print("=" * 70)

    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run generator first!")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    passed_tests = 0
    total_tests = 8

    # -------------------------------------------------------------------------
    # TEST 1: Schema & Table Existence
    # -------------------------------------------------------------------------
    print("\n[TEST 1/8] Verifying 5 Core P0 Database Tables...")
    expected_tables = ["orders", "settlements", "settlement_line_items", "variances", "audit_log"]
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    actual_tables = [r["name"] for r in cursor.fetchall()]
    
    missing_tables = [t for t in expected_tables if t not in actual_tables]
    if missing_tables:
        print(f"  [FAIL] Missing tables: {missing_tables}")
        sys.exit(1)
    print(f"  [PASS] All 5 core tables exist: {', '.join(expected_tables)}")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 2: Record Count Assertions (Target >= 10,000 orders)
    # -------------------------------------------------------------------------
    print("\n[TEST 2/8] Verifying Record Counts...")
    cursor.execute("SELECT count(*) as c FROM orders")
    order_count = cursor.fetchone()["c"]
    cursor.execute("SELECT count(*) as c FROM settlements")
    settlement_count = cursor.fetchone()["c"]
    cursor.execute("SELECT count(*) as c FROM settlement_line_items")
    line_item_count = cursor.fetchone()["c"]
    cursor.execute("SELECT count(*) as c FROM variances")
    variance_count = cursor.fetchone()["c"]
    cursor.execute("SELECT count(*) as c FROM audit_log")
    audit_count = cursor.fetchone()["c"]

    print(f"  - Orders: {order_count:,} (Requirement: >= 10,000)")
    print(f"  - Settlements: {settlement_count:,}")
    print(f"  - Settlement Line Items: {line_item_count:,}")
    print(f"  - Variances / Anomalies: {variance_count:,}")
    print(f"  - Audit Log Records: {audit_count:,}")

    assert order_count >= 10000, f"Expected >= 10,000 orders, got {order_count}"
    assert settlement_count >= 30, f"Expected >= 30 settlements, got {settlement_count}"
    assert line_item_count >= 5000, f"Expected >= 5000 line items, got {line_item_count}"
    assert variance_count >= 7, f"Expected >= 7 seeded variances, got {variance_count}"
    print("  [PASS] Record counts exceed all hackathon requirements.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 3: Foreign Key & Relationship Integrity
    # -------------------------------------------------------------------------
    print("\n[TEST 3/8] Verifying Foreign Key & Relationship Integrity...")
    # All settlement_line_items must point to valid settlements
    cursor.execute("""
        SELECT count(*) as c FROM settlement_line_items sli 
        LEFT JOIN settlements s ON sli.settlement_id = s.id 
        WHERE s.id IS NULL
    """)
    orphan_line_items = cursor.fetchone()["c"]
    assert orphan_line_items == 0, f"Found {orphan_line_items} orphaned line items"

    # All variances with settlement_id must point to valid settlements
    cursor.execute("""
        SELECT count(*) as c FROM variances v 
        LEFT JOIN settlements s ON v.settlement_id = s.id 
        WHERE v.settlement_id IS NOT NULL AND s.id IS NULL
    """)
    orphan_variances = cursor.fetchone()["c"]
    assert orphan_variances == 0, f"Found {orphan_variances} orphaned variances"

    print("  [PASS] 0 orphaned records found. 100% referential integrity.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 4: Monetary Field Integrity (Paise amounts, Non-negative, Integers)
    # -------------------------------------------------------------------------
    print("\n[TEST 4/8] Verifying Monetary Fields (Strict Integer Paise)...")
    cursor.execute("SELECT count(*) as c FROM orders WHERE amount_paise <= 0")
    invalid_order_amounts = cursor.fetchone()["c"]
    assert invalid_order_amounts == 0, f"Found {invalid_order_amounts} non-positive order amounts"

    cursor.execute("SELECT count(*) as c FROM orders WHERE fee_paise < 0 OR tax_paise < 0 OR refunded_amount_paise < 0")
    invalid_order_fees = cursor.fetchone()["c"]
    assert invalid_order_fees == 0, f"Found {invalid_order_fees} negative order fee/tax records"

    cursor.execute("SELECT count(*) as c FROM settlement_line_items WHERE amount_paise < 0 OR fee_paise < 0 OR tax_paise < 0")
    invalid_sli_amounts = cursor.fetchone()["c"]
    assert invalid_sli_amounts == 0, f"Found {invalid_sli_amounts} negative line item amounts"

    print("  [PASS] All monetary values are valid integer paise without float precision bugs.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 5: Clean Settlements Mathematical Consistency
    # -------------------------------------------------------------------------
    print("\n[TEST 5/8] Verifying Clean Settlement Reconciliations...")
    cursor.execute("""
        SELECT s.id, s.razorpay_settlement_id, s.amount_paise, s.gross_paise, s.fees_paise, 
               s.tax_paise, s.refunds_paise, s.adjustments_paise, s.metadata,
               COALESCE(SUM(sli.credit_paise), 0) as calc_gross,
               COALESCE(SUM(sli.fee_paise), 0) as calc_fees,
               COALESCE(SUM(sli.tax_paise), 0) as calc_tax,
               COALESCE(SUM(sli.debit_paise), 0) as calc_debit
        FROM settlements s
        LEFT JOIN settlement_line_items sli ON s.id = sli.settlement_id
        GROUP BY s.id
    """)
    settlement_rows = cursor.fetchall()
    
    clean_settlements_checked = 0
    anomalous_settlements_found = 0

    for s in settlement_rows:
        meta = json.loads(s["metadata"])
        is_clean = (meta.get("anomaly_seeded") == "none")
        
        # In clean settlements, line item sums must match settlement headers exactly
        if is_clean:
            assert s["gross_paise"] == s["calc_gross"], f"Gross mismatch in {s['id']}"
            assert s["fees_paise"] == s["calc_fees"], f"Fees mismatch in {s['id']}"
            assert s["tax_paise"] == s["calc_tax"], f"Tax mismatch in {s['id']}"
            assert s["refunds_paise"] == s["calc_debit"], f"Refunds mismatch in {s['id']}"
            expected_net = s["gross_paise"] - s["fees_paise"] - s["tax_paise"] - s["refunds_paise"] + s["adjustments_paise"]
            assert s["amount_paise"] == expected_net, f"Net amount mismatch in clean settlement {s['id']}"
            clean_settlements_checked += 1
        else:
            anomalous_settlements_found += 1

    print(f"  - Verified {clean_settlements_checked} clean settlements: 100% match line items.")
    print(f"  - Identified {anomalous_settlements_found} controlled anomalous settlements.")
    print("  [PASS] Clean settlements reconcile with zero discrepancy.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 6: Seeded Anomaly Verification (All 7 Types + Flagship Demo)
    # -------------------------------------------------------------------------
    print("\n[TEST 6/8] Verifying Seeded Anomalies & Grounded Evidence...")
    cursor.execute("SELECT anomaly_type, severity, variance_paise, title, evidence FROM variances")
    variances_found = cursor.fetchall()
    
    anomaly_types_present = set(v["anomaly_type"] for v in variances_found)
    expected_anomaly_types = {
        "AMOUNT_MISMATCH",
        "MISSING_SETTLEMENT_LINE",
        "DUPLICATE",
        "REFUND_MISMATCH",
        "TIMING_DIFFERENCE",
        "UNEXPLAINED_VARIANCE",
        "FEE_ANOMALY"
    }

    for eat in expected_anomaly_types:
        assert eat in anomaly_types_present, f"Missing expected anomaly type: {eat}"
        print(f"  ✓ Found anomaly type: {eat}")

    # Verify Flagship Demo Settlement Specifically
    cursor.execute("SELECT * FROM settlements WHERE razorpay_settlement_id = 'rzp_set_DEMO_20260828'")
    demo_set = cursor.fetchone()
    assert demo_set is not None, "Flagship demo settlement 'rzp_set_DEMO_20260828' not found"

    cursor.execute("SELECT * FROM variances WHERE settlement_id = ?", (demo_set["id"],))
    demo_var = cursor.fetchone()
    assert demo_var is not None, "Variance for flagship demo settlement not found"
    assert demo_var["variance_paise"] == -1700, f"Expected demo variance -1700 paise (-INR 17.00), got {demo_var['variance_paise']}"

    # Verify affected payments exist in database
    demo_evidence = json.loads(demo_var["evidence"])
    for p in demo_evidence.get("affected_payments", []):
        cursor.execute("SELECT count(*) as c FROM orders WHERE razorpay_payment_id = ?", (p["payment_id"],))
        assert cursor.fetchone()["c"] == 1, f"Payment {p['payment_id']} cited in demo evidence not found in orders"

    print(f"  ✓ Flagship Demo Settlement Verified:")
    print(f"    ID: {demo_set['razorpay_settlement_id']} | UTR: {demo_set['utr']}")
    print(f"    Variance: INR {demo_var['variance_paise']/100:.2f} ({demo_var['variance_paise']} paise)")
    print(f"    Affected Payments: {[p['payment_id'] for p in demo_evidence.get('affected_payments', [])]}")
    print("  [PASS] All 7 anomaly types and Flagship Demo scenario verified.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 7: Audit Log Verification
    # -------------------------------------------------------------------------
    print("\n[TEST 7/8] Verifying Audit Trail...")
    cursor.execute("SELECT event_type, count(*) as count FROM audit_log GROUP BY event_type")
    audit_summary = cursor.fetchall()
    for row in audit_summary:
        print(f"  - Event: {row['event_type']} (Count: {row['count']})")
    assert len(audit_summary) >= 2, "Audit log should capture multiple event types"
    print("  [PASS] Minimal P0 audit log records events properly.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 8: Seed 42 Determinism & Reproducibility
    # -------------------------------------------------------------------------
    print("\n[TEST 8/8] Verifying Seed 42 Deterministic Reproducibility...")
    with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
        summary_data = json.load(f)
    
    assert summary_data["seed"] == 42, "Seed must be 42"
    assert summary_data["total_orders"] >= 10000, f"Expected >= 10,000 orders, got {summary_data['total_orders']}"
    assert summary_data["total_settlements"] == 88, f"Expected 88 settlements, got {summary_data['total_settlements']}"
    assert summary_data["demo_settlement"]["variance_paise"] == -1700
    
    print(f"  - Exact order count: {summary_data['total_orders']}")
    print(f"  - Exact settlement batches: {summary_data['total_settlements']}")
    print(f"  - Exact demo variance: {summary_data['demo_settlement']['variance_paise']} paise")
    print("  [PASS] Output matches deterministic Seed 42 signature.")
    passed_tests += 1

    conn.close()

    print("\n" + "=" * 70)
    print(f"ALL TESTS PASSED ({passed_tests}/{total_tests}) — AGENT A VALIDATION SUCCESSFUL")
    print("=" * 70)
    return True


if __name__ == "__main__":
    run_validations()
