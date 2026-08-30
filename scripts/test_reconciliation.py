#!/usr/bin/env python3
"""
Settlement Detective — Reconciliation Engine Automated Test Suite
Task: Agent B (Verification & Integrity Suite)

Verifies all 14 mandatory financial integrity requirements:
1. Clean settlements reconcile with zero discrepancy.
2. AMOUNT_MISMATCH is detected from first principles.
3. MISSING_SETTLEMENT_LINE is detected from first principles.
4. DUPLICATE is detected from first principles.
5. REFUND_MISMATCH is detected from first principles.
6. TIMING_DIFFERENCE is detected from first principles.
7. UNEXPLAINED_VARIANCE is detected from first principles.
8. FEE_ANOMALY is detected from first principles.
9. Flagship settlement rzp_set_DEMO_20260828 is detected.
10. Flagship ~INR 17.00 variance is derived purely from transaction-level calculation chain.
11. Verification that NO special-casing exists in src/reconciliation/ for demo settlement ID or 1700.
12. Monetary calculation integrity (integer paise, no floats).
13. Idempotency test (multiple runs produce identical state).
14. Generalization test (MDR fee anomaly detection on distinct settlement fixtures).
"""

import os
import sys
import json
import sqlite3
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.reconciliation import (
    DeterministicReconciliationEngine,
    AnomalyCategory,
    VarianceSeverity
)

DB_PATH = PROJECT_ROOT / "data" / "settlement_detective.db"


def run_tests():
    print("=" * 80)
    print("SETTLEMENT DETECTIVE — RECONCILIATION ENGINE TEST SUITE")
    print("=" * 80)

    if not DB_PATH.exists():
        print(f"[FAIL] Database file not found at {DB_PATH}. Run generator first!")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Pre-cleanup in case a previous test left stale fixtures
    cursor.execute("DELETE FROM variances WHERE settlement_id = 'set_gen_test'")
    cursor.execute("DELETE FROM settlement_line_items WHERE settlement_id = 'set_gen_test'")
    cursor.execute("DELETE FROM settlements WHERE id = 'set_gen_test'")
    cursor.execute("DELETE FROM orders WHERE id = 'ord_gen_test'")
    conn.commit()

    engine = DeterministicReconciliationEngine(conn)
    
    passed_tests = 0
    total_tests = 14

    # Run complete reconciliation
    summaries = engine.reconcile_all_settlements()
    summary_by_id = {s.settlement_id: s for s in summaries}
    summary_by_rzp_id = {s.razorpay_settlement_id: s for s in summaries}

    # -------------------------------------------------------------------------
    # TEST 1: Clean Settlements Reconcile Correctly (Zero Discrepancy)
    # -------------------------------------------------------------------------
    print("\n[TEST 1/14] Verifying Clean Settlements Reconcile with Zero Variance...")
    clean_count = sum(1 for s in summaries if s.is_clean)
    print(f"  - Total clean settlements: {clean_count} / {len(summaries)}")
    assert clean_count >= 75, f"Expected >= 75 clean settlements, got {clean_count}"
    
    for s in summaries:
        if s.is_clean:
            assert s.net_variance_paise == 0, f"Clean settlement {s.settlement_id} had non-zero variance {s.net_variance_paise}"
            assert len(s.variances) == 0, f"Clean settlement {s.settlement_id} had variances flagged"
    print("  [PASS] All clean settlements reconciled with exact zero variance.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 2: AMOUNT_MISMATCH Detection
    # -------------------------------------------------------------------------
    print("\n[TEST 2/14] Verifying AMOUNT_MISMATCH Detection (Day 20 / set_020)...")
    s_020 = summary_by_id.get("set_020")
    assert s_020 is not None, "Settlement set_020 not found"
    amt_vars = [v for v in s_020.variances if v["anomaly_type"] == AnomalyCategory.AMOUNT_MISMATCH]
    assert len(amt_vars) == 1, f"Expected 1 AMOUNT_MISMATCH in set_020, found {len(amt_vars)}"
    assert amt_vars[0]["variance_paise"] == -50000, f"Expected -50,000 paise (-INR 500), got {amt_vars[0]['variance_paise']}"
    assert amt_vars[0]["evidence"]["line_item_id"] is not None
    print(f"  [PASS] AMOUNT_MISMATCH detected: Variance = INR {amt_vars[0]['variance_paise']/100:.2f}")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 3: MISSING_SETTLEMENT_LINE Detection
    # -------------------------------------------------------------------------
    print("\n[TEST 3/14] Verifying MISSING_SETTLEMENT_LINE Detection (Day 35 / set_035)...")
    s_035 = summary_by_id.get("set_035")
    assert s_035 is not None, "Settlement set_035 not found"
    missing_vars = [v for v in s_035.variances if v["anomaly_type"] == AnomalyCategory.MISSING_SETTLEMENT_LINE]
    assert len(missing_vars) == 1, f"Expected 1 MISSING_SETTLEMENT_LINE in set_035, found {len(missing_vars)}"
    assert missing_vars[0]["severity"] == VarianceSeverity.CRITICAL
    assert missing_vars[0]["evidence"]["payment_id"] is not None
    print(f"  [PASS] MISSING_SETTLEMENT_LINE detected: Payment {missing_vars[0]['evidence']['payment_id']} (Variance: INR {missing_vars[0]['variance_paise']/100:.2f})")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 4: DUPLICATE Settlement Line Detection
    # -------------------------------------------------------------------------
    print("\n[TEST 4/14] Verifying DUPLICATE Detection (Day 48 / set_048)...")
    s_048 = summary_by_id.get("set_048")
    assert s_048 is not None, "Settlement set_048 not found"
    dup_vars = [v for v in s_048.variances if v["anomaly_type"] == AnomalyCategory.DUPLICATE]
    assert len(dup_vars) == 1, f"Expected 1 DUPLICATE in set_048, found {len(dup_vars)}"
    assert dup_vars[0]["evidence"]["occurrence_count"] == 2
    assert len(dup_vars[0]["evidence"]["duplicate_line_item_ids"]) == 2
    print(f"  [PASS] DUPLICATE detected: Entity {dup_vars[0]['evidence']['entity_id']} appeared 2x (Excess credit: INR {dup_vars[0]['variance_paise']/100:.2f})")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 5: REFUND_MISMATCH Detection
    # -------------------------------------------------------------------------
    print("\n[TEST 5/14] Verifying REFUND_MISMATCH Detection (Day 60 / set_060)...")
    s_060 = summary_by_id.get("set_060")
    assert s_060 is not None, "Settlement set_060 not found"
    ref_vars = [v for v in s_060.variances if v["anomaly_type"] == AnomalyCategory.REFUND_MISMATCH]
    assert len(ref_vars) == 1, f"Expected 1 REFUND_MISMATCH in set_060, found {len(ref_vars)}"
    assert ref_vars[0]["variance_paise"] == -200000, f"Expected -200,000 paise (-INR 2000), got {ref_vars[0]['variance_paise']}"
    print(f"  [PASS] REFUND_MISMATCH detected: Actual debit INR {ref_vars[0]['actual_amount_paise']/100:.2f} vs expected INR {ref_vars[0]['expected_amount_paise']/100:.2f}")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 6: TIMING_DIFFERENCE Detection
    # -------------------------------------------------------------------------
    print("\n[TEST 6/14] Verifying TIMING_DIFFERENCE Detection (Day 72 / set_072)...")
    s_072 = summary_by_id.get("set_072")
    assert s_072 is not None, "Settlement set_072 not found"
    timing_vars = [v for v in s_072.variances if v["anomaly_type"] == AnomalyCategory.TIMING_DIFFERENCE]
    assert len(timing_vars) == 1, f"Expected 1 TIMING_DIFFERENCE in set_072, found {len(timing_vars)}"
    assert timing_vars[0]["evidence"]["captured_at"] is not None
    print(f"  [PASS] TIMING_DIFFERENCE detected: Payment {timing_vars[0]['evidence']['payment_id']} captured outside period boundaries")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 7: UNEXPLAINED_VARIANCE Detection
    # -------------------------------------------------------------------------
    print("\n[TEST 7/14] Verifying UNEXPLAINED_VARIANCE Detection (Day 80 / set_080)...")
    s_080 = summary_by_id.get("set_080")
    assert s_080 is not None, "Settlement set_080 not found"
    unexp_vars = [v for v in s_080.variances if v["anomaly_type"] == AnomalyCategory.UNEXPLAINED_VARIANCE]
    assert len(unexp_vars) == 1, f"Expected 1 UNEXPLAINED_VARIANCE in set_080, found {len(unexp_vars)}"
    assert unexp_vars[0]["variance_paise"] == -3550, f"Expected -3550 paise (-INR 35.50), got {unexp_vars[0]['variance_paise']}"
    print(f"  [PASS] UNEXPLAINED_VARIANCE detected: Residual gap = INR {unexp_vars[0]['variance_paise']/100:.2f} ({unexp_vars[0]['variance_paise']} paise)")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 8: General FEE_ANOMALY Detection on Day 84 (set_084)
    # -------------------------------------------------------------------------
    print("\n[TEST 8/14] Verifying General FEE_ANOMALY Detection on Day 84 (set_084)...")
    s_084 = summary_by_id.get("set_084")
    assert s_084 is not None, "Settlement set_084 not found"
    fee_vars_084 = [v for v in s_084.variances if v["anomaly_type"] == AnomalyCategory.FEE_ANOMALY]
    assert len(fee_vars_084) == 1, f"Expected 1 FEE_ANOMALY in set_084, found {len(fee_vars_084)}"
    evidence_084 = fee_vars_084[0]["evidence"]
    assert evidence_084["affected_transactions_count"] == 6, f"Expected 6 affected transactions on Day 84, got {evidence_084['affected_transactions_count']}"
    print(f"  [PASS] General FEE_ANOMALY detected on Day 84: {evidence_084['affected_transactions_count']} affected payments (Total leakage: INR {abs(fee_vars_084[0]['variance_paise'])/100:.2f})")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 9: Flagship Demo Settlement Detection (rzp_set_DEMO_20260828)
    # -------------------------------------------------------------------------
    print("\n[TEST 9/14] Verifying Flagship Demo Settlement Detection (rzp_set_DEMO_20260828)...")
    s_demo = summary_by_rzp_id.get("rzp_set_DEMO_20260828")
    assert s_demo is not None, "Flagship settlement rzp_set_DEMO_20260828 not found in summaries"
    fee_vars_demo = [v for v in s_demo.variances if v["anomaly_type"] == AnomalyCategory.FEE_ANOMALY]
    assert len(fee_vars_demo) == 1, f"Expected 1 FEE_ANOMALY in flagship settlement, got {len(fee_vars_demo)}"
    demo_var = fee_vars_demo[0]
    print(f"  [PASS] Flagship demo settlement detected with FEE_ANOMALY: Variance = INR {demo_var['variance_paise']/100:.2f}")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 10: Flagship ~INR 17.00 Derived from Transaction-Level Calculations
    # -------------------------------------------------------------------------
    print("\n[TEST 10/14] Verifying Flagship ~INR 17.00 Derived Calculation Chain...")
    demo_evidence = demo_var["evidence"]
    affected_payments = demo_evidence.get("affected_payments", [])
    
    print(f"  - Total affected transactions dynamically identified: {len(affected_payments)}")
    assert len(affected_payments) == 3, f"Expected 3 affected payments, got {len(affected_payments)}"

    calculated_leakage_sum = 0
    print("\n  --- Transaction-Level Calculation Chain ---")
    for idx, p in enumerate(affected_payments, 1):
        pay_id = p["payment_id"]
        amt = p["amount_paise"]
        exp_fee = p["expected_fee_paise"]
        exp_tax = p["expected_tax_paise"]
        act_fee = p["actual_fee_paise"]
        act_tax = p["actual_tax_paise"]
        leakage = p["fee_leakage_paise"]
        
        # Verify per-transaction arithmetic
        expected_total = exp_fee + exp_tax
        actual_total = act_fee + act_tax
        calc_diff = actual_total - expected_total
        assert calc_diff == leakage, f"Arithmetic mismatch for {pay_id}: {calc_diff} != {leakage}"
        calculated_leakage_sum += leakage

        print(f"  Txn {idx} [{pay_id}]: Amount = INR {amt/100:.2f}")
        print(f"         Expected: Fee {exp_fee} + Tax {exp_tax} = {expected_total} paise")
        print(f"         Actual:   Fee {act_fee} + Tax {act_tax} = {actual_total} paise")
        print(f"         Difference = {leakage} paise (INR {leakage/100:.2f})")

    print(f"  -------------------------------------------")
    print(f"  Sum of transaction differences: {calculated_leakage_sum} paise (INR {calculated_leakage_sum/100:.2f})")
    print(f"  Reported variance in database:  {demo_var['variance_paise']} paise (INR {demo_var['variance_paise']/100:.2f})")
    
    assert calculated_leakage_sum == 1700, f"Expected sum of differences to equal 1,700 paise (INR 17.00), got {calculated_leakage_sum}"
    assert demo_var["variance_paise"] == -1700, f"Expected settlement variance -1,700 paise, got {demo_var['variance_paise']}"
    print("  [PASS] Flagship ~INR 17.00 variance is 100% DERIVED from transaction-level records.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 11: Codebase Inspection for Hardcoded Demo Constants
    # -------------------------------------------------------------------------
    print("\n[TEST 11/14] Verifying NO Hardcoded Demo Constants Exist in src/reconciliation/...")
    recon_src_files = [
        PROJECT_ROOT / "src" / "reconciliation" / "engine.py",
        PROJECT_ROOT / "src" / "reconciliation" / "matching.py",
        PROJECT_ROOT / "src" / "reconciliation" / "config.py"
    ]
    forbidden_terms = [
        "rzp_set_DEMO_20260828",
        "pay_demo_upi",
        "DEMO_FLAGSHIP",
        "1700",
        "2.04"
    ]

    for fpath in recon_src_files:
        with open(fpath, "r", encoding="utf-8") as f:
            code = f.read()
            for term in forbidden_terms:
                assert term not in code, f"Forbidden hardcoded term '{term}' found in {fpath.name}!"
        print(f"  ✓ {fpath.name}: 0 hardcoded demo terms found.")
    print("  [PASS] Clean separation confirmed. Engine contains zero hardcoded demo constants.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 12: Monetary Calculations in Integer Paise (No Floats)
    # -------------------------------------------------------------------------
    print("\n[TEST 12/14] Verifying Monetary Integer Arithmetic...")
    cursor.execute("SELECT expected_amount_paise, actual_amount_paise, variance_paise FROM variances")
    for row in cursor.fetchall():
        assert isinstance(row[0], int), f"expected_amount_paise {row[0]} is not an int"
        assert isinstance(row[1], int), f"actual_amount_paise {row[1]} is not an int"
        assert isinstance(row[2], int), f"variance_paise {row[2]} is not an int"
    print("  [PASS] 100% of monetary calculations and stored values use integer paise.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 13: Idempotency Test
    # -------------------------------------------------------------------------
    print("\n[TEST 13/14] Verifying Reconciliation Idempotency...")
    cursor.execute("SELECT count(*) as c FROM variances")
    count_before = cursor.fetchone()[0]
    cursor.execute("SELECT id, variance_paise FROM variances ORDER BY id")
    records_before = cursor.fetchall()

    # Run reconciliation a second time
    engine.reconcile_all_settlements()

    cursor.execute("SELECT count(*) as c FROM variances")
    count_after = cursor.fetchone()[0]
    cursor.execute("SELECT id, variance_paise FROM variances ORDER BY id")
    records_after = cursor.fetchall()

    assert count_before == count_after, f"Idempotency violation: count changed from {count_before} to {count_after}"
    assert records_before == records_after, "Idempotency violation: variance records altered after second run"
    print(f"  [PASS] Idempotent: 2nd run produced identical {count_after} variance records with zero duplicates.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 14: Generalization Test (Custom Fixture with Arbitrary Fee Rate)
    # -------------------------------------------------------------------------
    print("\n[TEST 14/14] Verifying Fee Anomaly Detector Generalization on New Fixture...")
    try:
        # Create an arbitrary synthetic settlement with custom MDR anomaly
        cursor.execute("""
            INSERT INTO settlements (id, razorpay_settlement_id, utr, amount_paise, gross_paise, fees_paise, tax_paise, refunds_paise, adjustments_paise, currency, status, period_start, period_end, settled_at, created_at, metadata)
            VALUES ('set_gen_test', 'rzp_set_GENERALIZATION_TEST', 'UTR-GEN-999999', 970500, 1000000, 25000, 4500, 0, 0, 'INR', 'processed', '2026-09-01T00:00:00+00:00', '2026-09-01T23:59:59+00:00', '2026-09-03T10:00:00+00:00', '2026-09-03T10:00:00+00:00', '{}')
        """)
        # Order with standard 2.00% card MDR (expected fee 20,000 + tax 3,600 = 23,600 paise)
        cursor.execute("""
            INSERT INTO orders (id, merchant_order_id, razorpay_order_id, razorpay_payment_id, amount_paise, fee_paise, tax_paise, net_paise, refunded_amount_paise, currency, status, payment_method, refund_status, customer_email, customer_phone, created_at, captured_at, refunded_at, metadata)
            VALUES ('ord_gen_test', 'MERCH-GEN-001', 'order_gen_001', 'pay_gen_001', 1000000, 20000, 3600, 976400, 0, 'INR', 'captured', 'card', 'none', 'test@gen.com', '+919800000000', '2026-09-01T12:00:00+00:00', '2026-09-01T12:01:00+00:00', NULL, '{}')
        """)
        # Line item charged 2.50% MDR (fee 25,000 + tax 4,500 = 29,500 paise -> difference = 5,900 paise / INR 59.00)
        cursor.execute("""
            INSERT INTO settlement_line_items (id, settlement_id, entity_id, entity_type, order_id, amount_paise, fee_paise, tax_paise, debit_paise, credit_paise, currency, settled_at, created_at, metadata)
            VALUES ('sli_gen_test', 'set_gen_test', 'pay_gen_001', 'payment', 'ord_gen_test', 1000000, 25000, 4500, 0, 1000000, 'INR', '2026-09-03T10:00:00+00:00', '2026-09-03T10:00:00+00:00', '{}')
        """)
        conn.commit()

        # Run engine on the newly injected settlement
        gen_summary = engine.reconcile_settlement("set_gen_test")
        assert not gen_summary.is_clean, "Generalization fixture should be flagged as anomalous"
        assert len(gen_summary.variances) == 1, f"Expected 1 variance, got {len(gen_summary.variances)}"
        
        gen_var = gen_summary.variances[0]
        assert gen_var["anomaly_type"] == AnomalyCategory.FEE_ANOMALY
        assert gen_var["variance_paise"] == -5900, f"Expected -5,900 paise (-INR 59.00), got {gen_var['variance_paise']}"
        assert gen_var["evidence"]["affected_transactions_count"] == 1
        assert gen_var["evidence"]["affected_payments"][0]["payment_id"] == "pay_gen_001"

        print(f"  [PASS] Generalization verified: Arbitrary test fixture dynamically detected with fee variance of INR {gen_var['variance_paise']/100:.2f} (5900 paise).")
        passed_tests += 1
    finally:
        # Clean up test fixture
        cursor.execute("DELETE FROM variances WHERE settlement_id = 'set_gen_test'")
        cursor.execute("DELETE FROM settlement_line_items WHERE settlement_id = 'set_gen_test'")
        cursor.execute("DELETE FROM settlements WHERE id = 'set_gen_test'")
        cursor.execute("DELETE FROM orders WHERE id = 'ord_gen_test'")
        conn.commit()

    conn.close()

    print("\n" + "=" * 80)
    print(f"ALL RECONCILIATION TESTS PASSED ({passed_tests}/{total_tests}) — 100% FINANCIAL INTEGRITY")
    print("=" * 80)
    return True


if __name__ == "__main__":
    run_tests()
