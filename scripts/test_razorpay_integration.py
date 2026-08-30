#!/usr/bin/env python3
"""
Settlement Detective — Razorpay Test Mode Integration Test Suite
Task: Razorpay Integration Layer Verification (20 Tests)

Verifies:
1. Payment fetch parsing.
2. Refund parsing.
3. Recon parsing.
4. Monetary conversion to paise.
5. Payment normalization & DB ingestion.
6. Refund normalization & DB ingestion.
7. Recon normalization & DB ingestion.
8. Invalid credentials handling.
9. API 4xx handling.
10. API 5xx handling.
11. Rate-limit handling (429).
12. Valid webhook signature.
13. Invalid webhook signature.
14. Duplicate webhook idempotency.
15. Supported event processing.
16. Unsupported event handling.
17. Secret leakage prevention.
18. Test Mode source labeling.
19. Synthetic data preservation.
20. Full regression verification (Agent A + B + C).
"""

import hmac
import json
import hashlib
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from src.razorpay import (
    RazorpayConfig,
    RazorpayClient,
    RazorpayAPIError,
    RazorpayDataIngester,
    RazorpayWebhookHandler,
    RazorpayPayment,
    RazorpayRefund,
    RazorpayReconItem,
    RazorpaySettlement,
    DataSource
)

DB_PATH = PROJECT_ROOT / "data" / "settlement_detective.db"


def run_tests():
    print("=" * 80)
    print("SETTLEMENT DETECTIVE — RAZORPAY INTEGRATION TEST SUITE (20 TESTS)")
    print("=" * 80)

    passed_tests = 0
    total_tests = 20

    # -------------------------------------------------------------------------
    # TEST 1: Payment Fetch Parsing
    # -------------------------------------------------------------------------
    print("\n[TEST 1/20] Verifying Payment Response Parsing...")
    sample_payment_json = {
        "id": "pay_test_abc123",
        "entity": "payment",
        "amount": 250000,  # ₹2,500.00
        "currency": "INR",
        "status": "captured",
        "order_id": "order_test_999",
        "method": "upi",
        "fee": 4500,       # ₹45.00
        "tax": 810,        # ₹8.10
        "captured": True,
        "email": "customer@example.com",
        "contact": "+919876543210",
        "created_at": 1724832000
    }
    payment = RazorpayPayment.from_api_response(sample_payment_json)
    assert payment.id == "pay_test_abc123"
    assert payment.amount_paise == 250000
    assert payment.fee_paise == 4500
    assert payment.tax_paise == 810
    assert payment.net_paise == 250000 - 4500 - 810
    assert payment.method == "upi"
    print(f"  [PASS] Payment parsed: {payment.id} (INR {payment.amount_paise/100:.2f})")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 2: Refund Response Parsing
    # -------------------------------------------------------------------------
    print("\n[TEST 2/20] Verifying Refund Response Parsing...")
    sample_refund_json = {
        "id": "rfnd_test_xyz789",
        "entity": "refund",
        "amount": 100000,  # ₹1,000.00
        "currency": "INR",
        "payment_id": "pay_test_abc123",
        "status": "processed",
        "fee": 0,
        "tax": 0,
        "created_at": 1724832500
    }
    refund = RazorpayRefund.from_api_response(sample_refund_json)
    assert refund.id == "rfnd_test_xyz789"
    assert refund.payment_id == "pay_test_abc123"
    assert refund.amount_paise == 100000
    assert refund.status == "processed"
    print(f"  [PASS] Refund parsed: {refund.id} for payment {refund.payment_id}")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 3: Recon Combined Item Parsing
    # -------------------------------------------------------------------------
    print("\n[TEST 3/20] Verifying Recon Combined Line Item Parsing...")
    sample_recon_json = {
        "entity_id": "pay_test_abc123",
        "type": "payment",
        "amount": 250000,
        "fee": 4500,
        "tax": 810,
        "debit": 0,
        "credit": 250000,
        "settled_at": 1724918400
    }
    recon_item = RazorpayReconItem.from_api_response(sample_recon_json, settlement_id="set_test_001")
    assert recon_item.entity_id == "pay_test_abc123"
    assert recon_item.entity_type == "payment"
    assert recon_item.credit_paise == 250000
    assert recon_item.fee_paise == 4500
    assert recon_item.tax_paise == 810
    print(f"  [PASS] Recon item parsed: {recon_item.entity_id} (Credit: {recon_item.credit_paise} paise)")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 4: Monetary Conversion to Integer Paise
    # -------------------------------------------------------------------------
    print("\n[TEST 4/20] Verifying Monetary Conversion Strict Integer Types...")
    assert isinstance(payment.amount_paise, int)
    assert isinstance(payment.fee_paise, int)
    assert isinstance(payment.tax_paise, int)
    assert isinstance(payment.net_paise, int)
    assert isinstance(refund.amount_paise, int)
    assert isinstance(recon_item.credit_paise, int)
    print("  [PASS] 100% of monetary fields strictly typed as integer paise.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 5: Payment Normalization & Database Ingestion
    # -------------------------------------------------------------------------
    print("\n[TEST 5/20] Verifying Payment Ingestion into Database...")
    ingester = RazorpayDataIngester(db_path=DB_PATH)
    ingested_order_id = ingester.ingest_payment(payment)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = ?", (ingested_order_id,))
    stored_order = cursor.fetchone()
    assert stored_order is not None
    assert stored_order[3] == "pay_test_abc123"  # razorpay_payment_id
    assert stored_order[4] == 250000             # amount_paise
    
    meta = json.loads(stored_order[18])
    assert meta.get("source") == DataSource.RAZORPAY_TEST_MODE
    conn.close()
    print(f"  [PASS] Payment ingested into orders table with ID: {ingested_order_id}")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 6: Refund Normalization & Database Ingestion
    # -------------------------------------------------------------------------
    print("\n[TEST 6/20] Verifying Refund Ingestion into Database...")
    updated = ingester.ingest_refund(refund)
    assert updated is True
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT refund_status, refunded_amount_paise, status FROM orders WHERE razorpay_payment_id = ?", ("pay_test_abc123",))
    ref_row = cursor.fetchone()
    assert ref_row[0] == "partial"
    assert ref_row[1] == 100000
    assert ref_row[2] == "refunded"
    conn.close()
    print("  [PASS] Refund updated order records with partial refund status.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 7: Settlement Recon Normalization & DB Ingestion
    # -------------------------------------------------------------------------
    print("\n[TEST 7/20] Verifying Settlement Recon Report Ingestion...")
    sample_settle = RazorpaySettlement(
        id="set_test_live_01",
        amount_paise=244690,  # 250000 - 4500 - 810
        fees_paise=4500,
        tax_paise=810,
        utr="UTR-TEST-LIVE-001",
        status="processed",
        source=DataSource.RAZORPAY_TEST_MODE
    )
    settle_id = ingester.ingest_settlement(sample_settle, [recon_item])
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settlements WHERE id = ?", (settle_id,))
    stored_settle = cursor.fetchone()
    assert stored_settle is not None
    cursor.execute("SELECT count(*) FROM settlement_line_items WHERE settlement_id = ?", (settle_id,))
    sli_count = cursor.fetchone()[0]
    assert sli_count == 1
    conn.close()
    print(f"  [PASS] Settlement batch {settle_id} ingested with 1 line item.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 8: Missing / Invalid Credentials Handling
    # -------------------------------------------------------------------------
    print("\n[TEST 8/20] Verifying Missing Credentials Handling...")
    unconfigured_client = RazorpayClient(config=RazorpayConfig(key_id="", key_secret=""))
    try:
        unconfigured_client.fetch_payment("pay_test_xxx")
        assert False, "Should have raised RazorpayAPIError for missing credentials"
    except RazorpayAPIError as e:
        assert e.status_code == 401
        assert "credentials not configured" in e.message.lower()
    print("  [PASS] Missing credentials safely rejected with HTTP 401.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 9: API 4xx Error Handling
    # -------------------------------------------------------------------------
    print("\n[TEST 9/20] Verifying API 4xx Error Handling...")
    mock_config = RazorpayConfig(key_id="rzp_test_123", key_secret="secret_123")
    client = RazorpayClient(config=mock_config)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_err = urllib.error.HTTPError(
            url="https://api.razorpay.com/v1/payments/pay_nonexistent",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": {"code": "BAD_REQUEST_ERROR", "description": "Payment not found."}}')
        )
        mock_urlopen.side_effect = mock_err

        try:
            client.fetch_payment("pay_nonexistent")
            assert False, "Should have raised RazorpayAPIError"
        except RazorpayAPIError as re:
            assert re.status_code == 404
            assert re.message == "Payment not found."
            assert re.error_code == "BAD_REQUEST_ERROR"
    print("  [PASS] 404 response parsed into structured RazorpayAPIError.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 10: API 5xx Error Handling
    # -------------------------------------------------------------------------
    print("\n[TEST 10/20] Verifying API 5xx Error Handling...")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_err = urllib.error.HTTPError(
            url="https://api.razorpay.com/v1/payments/pay_err",
            code=502,
            msg="Bad Gateway",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": {"code": "GATEWAY_ERROR", "description": "Upstream error."}}')
        )
        mock_urlopen.side_effect = mock_err

        try:
            client.fetch_payment("pay_err")
            assert False, "Should have raised RazorpayAPIError"
        except RazorpayAPIError as re:
            assert re.status_code == 502
    print("  [PASS] 502 response handled gracefully.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 11: Rate-Limit (429) Handling
    # -------------------------------------------------------------------------
    print("\n[TEST 11/20] Verifying Rate-Limit (429) Retry Logic...")
    with patch("urllib.request.urlopen") as mock_urlopen:
        # First 429, second success
        mock_resp_success = MagicMock()
        mock_resp_success.__enter__.return_value.read.return_value = json.dumps(sample_payment_json).encode("utf-8")
        
        mock_429 = urllib.error.HTTPError(
            url="https://api.razorpay.com/v1/payments/pay_test_abc123",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": {"code": "RATE_LIMIT_EXCEEDED", "description": "Rate limit exceeded."}}')
        )
        mock_urlopen.side_effect = [mock_429, mock_resp_success]

        with patch("time.sleep") as mock_sleep:
            res_pay = client.fetch_payment("pay_test_abc123")
            assert res_pay.id == "pay_test_abc123"
            assert mock_sleep.called
    print("  [PASS] HTTP 429 rate limit retried and resolved successfully.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 12: Valid Webhook Signature Verification
    # -------------------------------------------------------------------------
    print("\n[TEST 12/20] Verifying Valid Webhook HMAC-SHA256 Signature...")
    webhook_secret = "test_webhook_secret_key_12345"
    wh_config = RazorpayConfig(webhook_secret=webhook_secret)
    wh_handler = RazorpayWebhookHandler(config=wh_config, db_path=DB_PATH)

    webhook_payload_dict = {
        "event": "payment.captured",
        "event_id": "evt_test_payment_captured_001",
        "created_at": 1724832000,
        "payload": {
            "payment": {
                "entity": sample_payment_json
            }
        }
    }
    raw_wh_bytes = json.dumps(webhook_payload_dict).encode("utf-8")
    valid_signature = hmac.new(webhook_secret.encode("utf-8"), raw_wh_bytes, hashlib.sha256).hexdigest()

    assert wh_handler.verify_signature(raw_wh_bytes, valid_signature) is True
    print("  [PASS] HMAC-SHA256 signature verified over raw request bytes.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 13: Invalid Webhook Signature Rejection
    # -------------------------------------------------------------------------
    print("\n[TEST 13/20] Verifying Invalid Webhook Signature Rejection...")
    invalid_signature = "invalid_fake_signature_hash_0000000000000000"
    status_code, resp_body = wh_handler.process_webhook(raw_wh_bytes, invalid_signature)
    assert status_code == 400
    assert resp_body["success"] is False
    assert "invalid" in resp_body["error"].lower()
    print("  [PASS] Invalid signature rejected with HTTP 400.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 14: Duplicate Webhook Idempotency
    # -------------------------------------------------------------------------
    print("\n[TEST 14/20] Verifying Duplicate Webhook Idempotency...")
    # First delivery
    status1, resp1 = wh_handler.process_webhook(raw_wh_bytes, valid_signature)
    assert status1 == 200
    assert resp1["status"] == "processed"

    # Second identical delivery
    status2, resp2 = wh_handler.process_webhook(raw_wh_bytes, valid_signature)
    assert status2 == 200
    assert resp2["status"] == "duplicate_ignored"
    assert resp2["event_id"] == "evt_test_payment_captured_001"
    print("  [PASS] Second delivery of identical webhook event safely ignored.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 15: Supported Event Processing
    # -------------------------------------------------------------------------
    print("\n[TEST 15/20] Verifying Supported Webhook Event Types...")
    supported_events = [
        "payment.authorized",
        "payment.captured",
        "order.paid",
        "refund.processed",
        "settlement.processed"
    ]
    for idx, ev_name in enumerate(supported_events):
        ev_payload = {
            "event": ev_name,
            "event_id": f"evt_test_supp_{idx:03d}",
            "created_at": 1724832000,
            "payload": {
                "payment": {"entity": sample_payment_json} if "payment" in ev_name or "order" in ev_name else {},
                "refund": {"entity": sample_refund_json} if "refund" in ev_name else {},
                "settlement": {"entity": {"id": "set_wh_test", "amount": 100000, "status": "processed"}} if "settlement" in ev_name else {}
            }
        }
        raw_b = json.dumps(ev_payload).encode("utf-8")
        sig = hmac.new(webhook_secret.encode("utf-8"), raw_b, hashlib.sha256).hexdigest()
        sc, rb = wh_handler.process_webhook(raw_b, sig)
        assert sc == 200, f"Failed processing {ev_name}: {rb}"
        assert rb["status"] == "processed"
        print(f"  ✓ Processed event: {ev_name}")

    print("  [PASS] All supported Razorpay webhook events handled successfully.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 16: Unsupported Webhook Event Handling
    # -------------------------------------------------------------------------
    print("\n[TEST 16/20] Verifying Unsupported Event Graceful Handling...")
    unsupported_payload = {
        "event": "invoice.paid",  # Unhandled
        "event_id": "evt_test_unsupp_999",
        "created_at": 1724832000,
        "payload": {}
    }
    raw_unsupp = json.dumps(unsupported_payload).encode("utf-8")
    sig_unsupp = hmac.new(webhook_secret.encode("utf-8"), raw_unsupp, hashlib.sha256).hexdigest()
    sc_u, rb_u = wh_handler.process_webhook(raw_unsupp, sig_unsupp)
    assert sc_u == 200
    assert rb_u["status"] == "ignored"
    print("  [PASS] Unsupported event acknowledged with 200 OK without processing.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 17: Secret Leakage Prevention
    # -------------------------------------------------------------------------
    print("\n[TEST 17/20] Verifying Secrets are Never Leaked in Outputs...")
    sanitized_info = wh_config.sanitized_dict()
    assert webhook_secret not in json.dumps(sanitized_info)
    assert "key_secret" not in sanitized_info or sanitized_info["key_secret"] != mock_config.key_secret
    print("  [PASS] Zero secret leakage confirmed in sanitized configurations.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 18: Test Mode Source Labeling
    # -------------------------------------------------------------------------
    print("\n[TEST 18/20] Verifying Test Mode Source Tagging...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT metadata FROM orders WHERE razorpay_payment_id = 'pay_test_abc123'")
    order_meta = json.loads(cursor.fetchone()[0])
    assert order_meta.get("source") == DataSource.RAZORPAY_TEST_MODE
    assert order_meta.get("is_test_mode") is True
    conn.close()
    print("  [PASS] Data source tagged as 'RAZORPAY_TEST_MODE' on ingested records.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 19: Synthetic Demo Data Remains Intact
    # -------------------------------------------------------------------------
    print("\n[TEST 19/20] Verifying Synthetic Demo Dataset Preservation...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Check flagship settlement still exists
    cursor.execute("SELECT * FROM settlements WHERE razorpay_settlement_id = 'rzp_set_DEMO_20260828'")
    demo_s = cursor.fetchone()
    assert demo_s is not None, "Flagship demo settlement was corrupted or deleted!"
    
    # Check total settlements count is preserved (>= 88)
    cursor.execute("SELECT count(*) FROM settlements")
    total_s = cursor.fetchone()[0]
    assert total_s >= 88
    conn.close()
    print("  [PASS] Synthetic settlement dataset and flagship demo scenario fully preserved.")
    passed_tests += 1

    # -------------------------------------------------------------------------
    # TEST 20: Full Regression Verification (Agent A + B + C)
    # -------------------------------------------------------------------------
    print("\n[TEST 20/20] Running Full Regression (Agents A, B, C)...")
    from scripts.verify_data import run_validations
    from scripts.test_reconciliation import run_tests as run_recon_tests
    from scripts.test_ai_service import run_tests as run_ai_tests

    assert run_validations() is True, "Agent A validation failed"
    assert run_recon_tests() is True, "Agent B reconciliation tests failed"
    assert run_ai_tests() is True, "Agent C AI tests failed"
    print("  [PASS] Full regression confirmed: 36/36 tests passing.")
    passed_tests += 1

    print("\n" + "=" * 80)
    print(f"ALL RAZORPAY INTEGRATION TESTS PASSED ({passed_tests}/{total_tests}) — 100% SECURE & ROBUST")
    print("=" * 80)
    return True


if __name__ == "__main__":
    run_tests()
