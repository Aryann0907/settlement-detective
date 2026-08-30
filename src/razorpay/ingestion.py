"""
Settlement Detective — Razorpay Ingestion Service
Normalizes and upserts live/test mode payments, refunds, and settlements into the local database.
Maintains clear data source labeling ("RAZORPAY_TEST_MODE" vs "SYNTHETIC_DEMO_DATA").
"""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from .models import (
    RazorpayPayment,
    RazorpayRefund,
    RazorpaySettlement,
    RazorpayReconItem,
    DataSource
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "settlement_detective.db"


class RazorpayDataIngester:
    """
    Normalizes Razorpay entities and persists them to SQLite while preserving synthetic datasets.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ingest_payment(self, payment: RazorpayPayment) -> str:
        """
        Upserts a Razorpay payment into the orders table.
        Labels the record with source='RAZORPAY_TEST_MODE'.
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        order_id = f"ord_rzp_{payment.id}"
        merchant_order_id = payment.order_id or f"MERCH-RZP-{payment.id}"
        meta = {
            "source": DataSource.RAZORPAY_TEST_MODE,
            "is_test_mode": True,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "gateway": "Razorpay"
        }

        # Check if record already exists by razorpay_payment_id
        cursor.execute("SELECT id FROM orders WHERE razorpay_payment_id = ?", (payment.id,))
        existing = cursor.fetchone()

        if existing:
            target_id = existing["id"]
            cursor.execute("""
                UPDATE orders SET
                    amount_paise = ?,
                    fee_paise = ?,
                    tax_paise = ?,
                    net_paise = ?,
                    refunded_amount_paise = ?,
                    status = ?,
                    payment_method = ?,
                    refund_status = ?,
                    customer_email = COALESCE(?, customer_email),
                    customer_phone = COALESCE(?, customer_phone),
                    captured_at = ?,
                    metadata = ?
                WHERE id = ?
            """, (
                payment.amount_paise,
                payment.fee_paise,
                payment.tax_paise,
                payment.net_paise,
                payment.amount_refunded_paise,
                payment.status,
                payment.method,
                payment.refund_status or "none",
                payment.customer_email,
                payment.customer_phone,
                payment.captured_at,
                json.dumps(meta),
                target_id
            ))
        else:
            target_id = order_id
            cursor.execute("""
                INSERT INTO orders (
                    id, merchant_order_id, razorpay_order_id, razorpay_payment_id,
                    amount_paise, fee_paise, tax_paise, net_paise, refunded_amount_paise,
                    currency, status, payment_method, refund_status, customer_email,
                    customer_phone, created_at, captured_at, refunded_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                target_id,
                merchant_order_id,
                payment.order_id,
                payment.id,
                payment.amount_paise,
                payment.fee_paise,
                payment.tax_paise,
                payment.net_paise,
                payment.amount_refunded_paise,
                payment.currency,
                payment.status,
                payment.method,
                payment.refund_status or "none",
                payment.customer_email,
                payment.customer_phone,
                payment.created_at,
                payment.captured_at,
                None,
                json.dumps(meta)
            ))

        # Record in audit_log
        audit_id = f"aud_ingest_pay_{payment.id}_{uuid.uuid4().hex[:8]}"
        cursor.execute("""
            INSERT INTO audit_log (id, event_type, entity_type, entity_id, description, actor, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            audit_id,
            "RAZORPAY_PAYMENT_INGESTED",
            "order",
            target_id,
            f"Ingested Razorpay Test Mode payment {payment.id} (INR {payment.amount_paise/100:.2f})",
            "razorpay_ingester",
            json.dumps({"source": DataSource.RAZORPAY_TEST_MODE, "payment_id": payment.id}),
            datetime.now(timezone.utc).isoformat()
        ))

        conn.commit()
        conn.close()
        return target_id

    def ingest_refund(self, refund: RazorpayRefund) -> bool:
        """Updates linked order with refund details."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, amount_paise FROM orders WHERE razorpay_payment_id = ?", (refund.payment_id,))
        order_row = cursor.fetchone()

        if order_row:
            order_id = order_row["id"]
            amount_paise = order_row["amount_paise"]
            refund_status = "full" if refund.amount_paise >= amount_paise else "partial"

            cursor.execute("""
                UPDATE orders SET
                    refunded_amount_paise = ?,
                    refund_status = ?,
                    status = 'refunded',
                    refunded_at = ?
                WHERE id = ?
            """, (
                refund.amount_paise,
                refund_status,
                refund.created_at,
                order_id
            ))
            conn.commit()
            conn.close()
            return True

        conn.close()
        return False

    def ingest_settlement(self, settlement: RazorpaySettlement, recon_items: List[RazorpayReconItem]) -> str:
        """
        Upserts a Razorpay settlement batch and its line items.
        Labels the records with source='RAZORPAY_TEST_MODE'.
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        settlement_internal_id = f"set_rzp_{settlement.id}"
        meta = {
            "source": DataSource.RAZORPAY_TEST_MODE,
            "is_test_mode": True,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "line_items_count": len(recon_items)
        }

        # Calculate totals from recon items if not present on header
        gross_paise = sum(item.credit_paise for item in recon_items)
        fees_paise = sum(item.fee_paise for item in recon_items)
        tax_paise = sum(item.tax_paise for item in recon_items)
        refunds_paise = sum(item.debit_paise for item in recon_items)

        cursor.execute("SELECT id FROM settlements WHERE razorpay_settlement_id = ?", (settlement.id,))
        existing = cursor.fetchone()

        if existing:
            target_id = existing["id"]
            cursor.execute("""
                UPDATE settlements SET
                    amount_paise = ?,
                    gross_paise = ?,
                    fees_paise = ?,
                    tax_paise = ?,
                    refunds_paise = ?,
                    utr = COALESCE(?, utr),
                    status = ?,
                    metadata = ?
                WHERE id = ?
            """, (
                settlement.amount_paise,
                gross_paise,
                fees_paise,
                tax_paise,
                refunds_paise,
                settlement.utr,
                settlement.status,
                json.dumps(meta),
                target_id
            ))
        else:
            target_id = settlement_internal_id
            cursor.execute("""
                INSERT INTO settlements (
                    id, razorpay_settlement_id, utr, amount_paise, gross_paise,
                    fees_paise, tax_paise, refunds_paise, adjustments_paise, currency,
                    status, period_start, period_end, settled_at, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                target_id,
                settlement.id,
                settlement.utr or f"UTR-RZP-{settlement.id}",
                settlement.amount_paise,
                gross_paise,
                fees_paise,
                tax_paise,
                refunds_paise,
                0,
                "INR",
                settlement.status,
                settlement.created_at,
                settlement.created_at,
                settlement.created_at,
                settlement.created_at,
                json.dumps(meta)
            ))

        # Ingest Line Items
        cursor.execute("DELETE FROM settlement_line_items WHERE settlement_id = ?", (target_id,))
        for idx, item in enumerate(recon_items):
            sli_id = f"sli_rzp_{settlement.id}_{idx+1:04d}"
            # Find matching order
            cursor.execute("SELECT id FROM orders WHERE razorpay_payment_id = ?", (item.entity_id,))
            linked_order = cursor.fetchone()
            linked_order_id = linked_order["id"] if linked_order else None

            cursor.execute("""
                INSERT INTO settlement_line_items (
                    id, settlement_id, entity_id, entity_type, order_id,
                    amount_paise, fee_paise, tax_paise, debit_paise, credit_paise,
                    currency, settled_at, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sli_id,
                target_id,
                item.entity_id,
                item.entity_type,
                linked_order_id,
                item.amount_paise,
                item.fee_paise,
                item.tax_paise,
                item.debit_paise,
                item.credit_paise,
                "INR",
                item.settled_at or settlement.created_at,
                settlement.created_at,
                json.dumps({"source": DataSource.RAZORPAY_TEST_MODE})
            ))

        conn.commit()
        conn.close()
        return target_id
