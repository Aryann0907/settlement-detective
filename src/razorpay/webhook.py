"""
Settlement Detective — Razorpay Webhook Handler
Validates HMAC-SHA256 signatures over raw request bytes and processes supported webhook events idempotently.
"""

import hmac
import json
import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timezone

from .config import RazorpayConfig
from .models import RazorpayPayment, RazorpayRefund, RazorpaySettlement, DataSource
from .ingestion import RazorpayDataIngester

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "settlement_detective.db"

# Supported Razorpay webhook events
SUPPORTED_WEBHOOK_EVENTS = {
    "payment.authorized",
    "payment.captured",
    "order.paid",
    "refund.created",
    "refund.processed",
    "refund.failed",
    "settlement.processed"
}


class RazorpayWebhookHandler:
    """
    Handles incoming Razorpay webhooks securely with raw-byte signature verification and idempotency.
    """

    def __init__(self, config: Optional[RazorpayConfig] = None, ingester: Optional[RazorpayDataIngester] = None, db_path: Optional[Path] = None):
        self.config = config or RazorpayConfig()
        self.ingester = ingester or RazorpayDataIngester(db_path=db_path)
        self.db_path = db_path or DB_PATH

    def verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """
        Verifies Razorpay HMAC-SHA256 signature using raw request bytes.
        Uses constant-time comparison to prevent timing attacks.
        """
        if not self.config.webhook_secret or not signature_header:
            return False

        secret_bytes = self.config.webhook_secret.encode("utf-8")
        computed_signature = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed_signature, signature_header.strip())

    def _is_event_already_processed(self, event_id: str) -> bool:
        """Checks if event ID has already been recorded in audit_log."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM audit_log WHERE entity_id = ? AND event_type = 'RAZORPAY_WEBHOOK_PROCESSED'", (event_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    def _record_event_processed(self, event_id: str, event_type: str, details: Dict[str, Any]):
        """Records processed event in audit_log for idempotency."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        audit_id = f"aud_wh_{event_id}_{uuid.uuid4().hex[:8]}"
        cursor.execute("""
            INSERT INTO audit_log (id, event_type, entity_type, entity_id, description, actor, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            audit_id,
            "RAZORPAY_WEBHOOK_PROCESSED",
            "webhook_event",
            event_id,
            f"Processed webhook event '{event_type}'",
            "razorpay_webhook_receiver",
            json.dumps(details),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        conn.close()

    def process_webhook(self, raw_body: bytes, signature_header: str) -> Tuple[int, Dict[str, Any]]:
        """
        Validates signature, checks idempotency, and ingests webhook payload.
        Returns: (http_status_code, response_dict)
        """
        # 1. Signature Verification
        if not self.verify_signature(raw_body, signature_header):
            return 400, {"success": False, "error": "Invalid webhook signature."}

        # 2. Parse JSON
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as e:
            return 400, {"success": False, "error": f"Malformed JSON payload: {str(e)}"}

        event_type = payload.get("event", "")
        # Derive unique event identifier
        event_id = payload.get("event_id") or payload.get("id")
        if not event_id:
            # Fallback event key from payload entity + timestamp
            contains = payload.get("payload", {})
            entity_data = next(iter(contains.values()), {}).get("entity", {}) if contains else {}
            entity_id = entity_data.get("id", "evt")
            created_at = payload.get("created_at", int(datetime.now().timestamp()))
            event_id = f"{event_type}_{entity_id}_{created_at}"

        # 3. Idempotency Check
        if self._is_event_already_processed(event_id):
            return 200, {
                "success": True,
                "status": "duplicate_ignored",
                "message": f"Webhook event '{event_id}' was already processed.",
                "event_id": event_id
            }

        # 4. Check Supported Event
        if event_type not in SUPPORTED_WEBHOOK_EVENTS:
            return 200, {
                "success": True,
                "status": "ignored",
                "message": f"Event type '{event_type}' is unhandled but acknowledged.",
                "event_id": event_id
            }

        # 5. Process Event Payload
        entity_payload = payload.get("payload", {})
        result_details = {}

        if event_type in ("payment.authorized", "payment.captured"):
            payment_data = entity_payload.get("payment", {}).get("entity", {})
            if payment_data:
                norm_payment = RazorpayPayment.from_api_response(payment_data)
                target_order_id = self.ingester.ingest_payment(norm_payment)
                result_details["order_id"] = target_order_id
                result_details["payment_id"] = norm_payment.id

        elif event_type == "order.paid":
            order_data = entity_payload.get("order", {}).get("entity", {})
            payment_data = entity_payload.get("payment", {}).get("entity", {})
            if payment_data:
                norm_payment = RazorpayPayment.from_api_response(payment_data)
                target_order_id = self.ingester.ingest_payment(norm_payment)
                result_details["order_id"] = target_order_id

        elif event_type in ("refund.created", "refund.processed"):
            refund_data = entity_payload.get("refund", {}).get("entity", {})
            if refund_data:
                norm_refund = RazorpayRefund.from_api_response(refund_data)
                updated = self.ingester.ingest_refund(norm_refund)
                result_details["refund_id"] = norm_refund.id
                result_details["order_updated"] = updated

        elif event_type == "settlement.processed":
            settlement_data = entity_payload.get("settlement", {}).get("entity", {})
            if settlement_data:
                norm_settlement = RazorpaySettlement.from_api_response(settlement_data)
                settle_id = self.ingester.ingest_settlement(norm_settlement, [])
                result_details["settlement_id"] = settle_id

        # 6. Record in Idempotency Store
        self._record_event_processed(event_id, event_type, result_details)

        return 200, {
            "success": True,
            "status": "processed",
            "event_type": event_type,
            "event_id": event_id,
            "details": result_details
        }
