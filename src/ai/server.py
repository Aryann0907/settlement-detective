"""
Settlement Detective — Unified Backend HTTP Server
Provides REST API endpoints for:
- Dashboard Summary (/api/dashboard/summary)
- Settlements & Line Items (/api/settlements, /api/settlements/:id)
- Anomalies (/api/anomalies)
- AI Investigation (/api/investigate)
- Grounded Financial Chat (/api/chat)
- Razorpay Test Mode Integration (/api/razorpay/*)
- Razorpay Secure Webhook Receiver (/api/webhooks/razorpay)
- Health & OpenAPI Docs (/api/health, /api/docs)
- Static Frontend Dashboard (/)
"""

import os
import json
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from typing import Optional, Dict, Any, List

from .service import AIInvestigationService
from .models import InvestigationRequest, ChatRequest
from ..razorpay import (
    RazorpayConfig,
    RazorpayClient,
    RazorpayDataIngester,
    RazorpayWebhookHandler,
    RazorpayAPIError,
    DataSource
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = PROJECT_ROOT / "public"


class UnifiedServiceHTTPHandler(BaseHTTPRequestHandler):
    ai_service: Optional[AIInvestigationService] = None
    rzp_client: Optional[RazorpayClient] = None
    rzp_ingester: Optional[RazorpayDataIngester] = None
    rzp_webhook: Optional[RazorpayWebhookHandler] = None

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Razorpay-Signature")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # ---------------------------------------------------------------------
        # 1. System Health
        # ---------------------------------------------------------------------
        if path in ("/api/health", "/health"):
            ai_provider = self.ai_service.provider.__class__.__name__ if self.ai_service else "Unknown"
            payload = {
                "status": "healthy",
                "service": "Settlement Detective Unified Backend Service",
                "ai_provider": ai_provider,
                "razorpay_configured": self.rzp_client.config.is_configured if self.rzp_client else False,
                "version": "1.0.0"
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(payload, indent=2).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 2. Executive Dashboard Summary
        # ---------------------------------------------------------------------
        elif path == "/api/dashboard/summary":
            conn = self.ai_service.context_builder.get_connection()
            cursor = conn.cursor()

            # Orders count
            cursor.execute("SELECT count(*) FROM orders")
            total_orders = cursor.fetchone()[0]

            # Settlements stats
            cursor.execute("SELECT count(*) as total, sum(amount_paise) as total_payout FROM settlements")
            s_stats = cursor.fetchone()
            total_settlements = s_stats[0]
            total_payout_paise = s_stats[1] or 0

            # Variances & Anomalies
            cursor.execute("SELECT * FROM variances")
            variance_rows = [dict(r) for r in cursor.fetchall()]
            for v in variance_rows:
                if isinstance(v.get("evidence"), str):
                    try:
                        v["evidence"] = json.loads(v["evidence"])
                    except Exception:
                        v["evidence"] = {}

            anomalous_settlements_count = len(set(v["settlement_id"] for v in variance_rows if v.get("settlement_id")))
            clean_settlements_count = max(0, total_settlements - anomalous_settlements_count)
            clean_recon_rate = round((clean_settlements_count / total_settlements * 100), 1) if total_settlements > 0 else 100.0

            # Total leakage
            total_leakage_paise = sum(abs(v["variance_paise"]) for v in variance_rows if v["variance_paise"] < 0)
            
            # Leakage by category
            leakage_by_category = {}
            for v in variance_rows:
                cat = v["anomaly_type"]
                leakage_by_category[cat] = leakage_by_category.get(cat, 0) + abs(v["variance_paise"])

            # Flagship Demo Variance
            flagship_var = next((v for v in variance_rows if v.get("settlement_id") == "set_087"), None)
            if not flagship_var and variance_rows:
                flagship_var = variance_rows[0]

            # 90-day settlement timeline data
            cursor.execute("""
                SELECT s.id, s.razorpay_settlement_id, s.amount_paise, s.gross_paise, s.fees_paise, s.tax_paise, 
                       s.refunds_paise, s.status, s.settled_at, s.metadata
                FROM settlements s
                ORDER BY s.settled_at ASC
            """)
            settlement_trend = []
            for s in cursor.fetchall():
                sd = dict(s)
                meta = json.loads(sd["metadata"]) if sd.get("metadata") else {}
                # Check if this settlement has a variance
                var_for_s = next((v for v in variance_rows if v.get("settlement_id") == sd["id"]), None)
                sd["is_anomalous"] = var_for_s is not None
                sd["variance_paise"] = var_for_s["variance_paise"] if var_for_s else 0
                sd["variance_inr"] = round(sd["variance_paise"] / 100, 2)
                sd["anomaly_type"] = var_for_s["anomaly_type"] if var_for_s else "NONE"
                sd["severity"] = var_for_s["severity"] if var_for_s else "NONE"
                sd["source"] = meta.get("source", "SYNTHETIC_DEMO_DATA")
                settlement_trend.append(sd)

            conn.close()

            summary_payload = {
                "total_orders": total_orders,
                "total_settlements": total_settlements,
                "clean_settlements_count": clean_settlements_count,
                "anomalous_settlements_count": anomalous_settlements_count,
                "clean_recon_rate": clean_recon_rate,
                "total_payout_paise": total_payout_paise,
                "total_payout_inr": round(total_payout_paise / 100, 2),
                "total_leakage_paise": total_leakage_paise,
                "total_leakage_inr": round(total_leakage_paise / 100, 2),
                "leakage_by_category": [
                    {"category": k, "amount_paise": v, "amount_inr": round(v / 100, 2)}
                    for k, v in sorted(leakage_by_category.items(), key=lambda x: x[1], reverse=True)
                ],
                "flagship_variance": flagship_var,
                "settlements_trend": settlement_trend
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(summary_payload, indent=2).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 3. Settlements Explorer (/api/settlements)
        # ---------------------------------------------------------------------
        elif path == "/api/settlements":
            conn = self.ai_service.context_builder.get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM variances")
            all_variances = [dict(r) for r in cursor.fetchall()]
            variance_map = {v["settlement_id"]: v for v in all_variances if v.get("settlement_id")}

            cursor.execute("""
                SELECT id, razorpay_settlement_id, utr, amount_paise, gross_paise, fees_paise, tax_paise,
                       refunds_paise, adjustments_paise, currency, status, period_start, period_end,
                       settled_at, metadata
                FROM settlements
                ORDER BY settled_at DESC
            """)
            settlements = []
            for r in cursor.fetchall():
                sd = dict(r)
                meta = json.loads(sd["metadata"]) if sd.get("metadata") else {}
                var = variance_map.get(sd["id"])
                
                sd["is_anomalous"] = var is not None
                sd["variance_id"] = var["id"] if var else None
                sd["variance_paise"] = var["variance_paise"] if var else 0
                sd["variance_inr"] = round(sd["variance_paise"] / 100, 2)
                sd["anomaly_type"] = var["anomaly_type"] if var else "NONE"
                sd["severity"] = var["severity"] if var else "NONE"
                sd["source"] = meta.get("source", "SYNTHETIC_DEMO_DATA")
                sd["line_items_count"] = meta.get("line_items_count", 0)
                settlements.append(sd)

            conn.close()
            self._set_headers(200)
            self.wfile.write(json.dumps({"settlements": settlements}, indent=2).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 4. Settlement Detail View (/api/settlements/:id)
        # ---------------------------------------------------------------------
        elif path.startswith("/api/settlements/"):
            settle_id = path.replace("/api/settlements/", "").strip()
            conn = self.ai_service.context_builder.get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM settlements WHERE id = ? OR razorpay_settlement_id = ?", (settle_id, settle_id))
            s_row = cursor.fetchone()

            if not s_row:
                conn.close()
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"Settlement '{settle_id}' not found."}).encode("utf-8"))
                return

            settle_dict = dict(s_row)
            meta = json.loads(settle_dict["metadata"]) if settle_dict.get("metadata") else {}
            settle_dict["source"] = meta.get("source", "SYNTHETIC_DEMO_DATA")

            # Fetch line items
            cursor.execute("SELECT * FROM settlement_line_items WHERE settlement_id = ? ORDER BY id ASC", (settle_dict["id"],))
            line_items = []
            for li in cursor.fetchall():
                lid = dict(li)
                if isinstance(lid.get("metadata"), str):
                    try:
                        lid["metadata"] = json.loads(lid["metadata"])
                    except Exception:
                        lid["metadata"] = {}
                line_items.append(lid)

            # Fetch variances
            cursor.execute("SELECT * FROM variances WHERE settlement_id = ?", (settle_dict["id"],))
            var_rows = []
            for v in cursor.fetchall():
                vd = dict(v)
                if isinstance(vd.get("evidence"), str):
                    try:
                        vd["evidence"] = json.loads(vd["evidence"])
                    except Exception:
                        vd["evidence"] = {}
                var_rows.append(vd)

            settle_dict["line_items"] = line_items
            settle_dict["variances"] = var_rows
            settle_dict["is_anomalous"] = len(var_rows) > 0

            # Financial waterfall calculation
            expected_net = settle_dict["gross_paise"] - settle_dict["fees_paise"] - settle_dict["tax_paise"] - settle_dict["refunds_paise"] + settle_dict["adjustments_paise"]
            settle_dict["expected_net_paise"] = expected_net
            settle_dict["actual_net_paise"] = settle_dict["amount_paise"]
            settle_dict["variance_paise"] = settle_dict["actual_net_paise"] - expected_net
            settle_dict["variance_inr"] = round(settle_dict["variance_paise"] / 100, 2)

            conn.close()
            self._set_headers(200)
            self.wfile.write(json.dumps(settle_dict, indent=2).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 5. Anomalies Registry (/api/anomalies, /api/variances)
        # ---------------------------------------------------------------------
        elif path in ("/api/anomalies", "/api/variances"):
            conn = self.ai_service.context_builder.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT v.*, s.razorpay_settlement_id, s.settled_at, s.amount_paise as settlement_amount_paise
                FROM variances v
                LEFT JOIN settlements s ON v.settlement_id = s.id
                ORDER BY ABS(v.variance_paise) DESC
            """)
            rows = []
            for r in cursor.fetchall():
                d = dict(r)
                if isinstance(d.get("evidence"), str):
                    try:
                        d["evidence"] = json.loads(d["evidence"])
                    except Exception:
                        d["evidence"] = {}
                d["variance_inr"] = round(d["variance_paise"] / 100, 2)
                d["financial_impact_inr"] = round(abs(d["variance_paise"]) / 100, 2)
                rows.append(d)
            conn.close()
            self._set_headers(200)
            self.wfile.write(json.dumps({"anomalies": rows, "variances": rows}, indent=2).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 6. Razorpay Health & Status
        # ---------------------------------------------------------------------
        elif path == "/api/razorpay/health":
            rzp_status = self.rzp_client.config.sanitized_dict() if self.rzp_client else {}
            self._set_headers(200)
            self.wfile.write(json.dumps(rzp_status, indent=2).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 7. Fetch Razorpay Payment Detail
        # ---------------------------------------------------------------------
        elif path.startswith("/api/razorpay/payment/") and not path.endswith("/refunds"):
            payment_id = path.replace("/api/razorpay/payment/", "").strip()
            try:
                payment = self.rzp_client.fetch_payment(payment_id)
                self._set_headers(200)
                self.wfile.write(json.dumps(payment.to_dict(), indent=2).encode("utf-8"))
            except RazorpayAPIError as re:
                self._set_headers(re.status_code)
                self.wfile.write(json.dumps({"error": re.message, "code": re.error_code}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 8. Fetch Razorpay Payment Refunds
        # ---------------------------------------------------------------------
        elif path.startswith("/api/razorpay/payment/") and path.endswith("/refunds"):
            payment_id = path.replace("/api/razorpay/payment/", "").replace("/refunds", "").strip()
            try:
                refunds = self.rzp_client.fetch_payment_refunds(payment_id)
                self._set_headers(200)
                self.wfile.write(json.dumps({"refunds": [r.to_dict() for r in refunds]}, indent=2).encode("utf-8"))
            except RazorpayAPIError as re:
                self._set_headers(re.status_code)
                self.wfile.write(json.dumps({"error": re.message, "code": re.error_code}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 9. API Docs
        # ---------------------------------------------------------------------
        elif path in ("/api/docs", "/docs"):
            docs = {
                "title": "Settlement Detective Unified REST API",
                "version": "1.0.0",
                "endpoints": [
                    {"path": "/api/dashboard/summary", "method": "GET", "description": "Executive dashboard metrics and 90-day settlement trend"},
                    {"path": "/api/settlements", "method": "GET", "description": "List all settlements with reconciliation status"},
                    {"path": "/api/settlements/:id", "method": "GET", "description": "Detailed settlement financial waterfall and line items"},
                    {"path": "/api/anomalies", "method": "GET", "description": "List detected anomalies and financial variances"},
                    {"path": "/api/investigate", "method": "POST", "description": "AI investigation of reconciliation variance"},
                    {"path": "/api/chat", "method": "POST", "description": "Grounded natural language financial chat"},
                    {"path": "/api/webhooks/razorpay", "method": "POST", "description": "Secure HMAC-SHA256 Razorpay webhook ingestion"},
                    {"path": "/api/razorpay/health", "method": "GET", "description": "Razorpay connection and credentials status"}
                ]
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(docs, indent=2).encode("utf-8"))

        # ---------------------------------------------------------------------
        # 10. Frontend Static File Serving
        # ---------------------------------------------------------------------
        else:
            # Serve index.html for root or any SPA route
            index_path = STATIC_DIR / "index.html"
            if index_path.exists():
                self._set_headers(200, content_type="text/html; charset=utf-8")
                with open(index_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"Endpoint '{path}' not found."}).encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Read Raw Request Bytes
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"

        # 1. Razorpay Webhook Ingestion (Requires Raw Bytes for Signature Verification)
        if path in ("/api/webhooks/razorpay", "/webhooks/razorpay"):
            signature = self.headers.get("X-Razorpay-Signature", "")
            status_code, response_body = self.rzp_webhook.process_webhook(raw_body_bytes, signature)
            self._set_headers(status_code)
            self.wfile.write(json.dumps(response_body, indent=2).encode("utf-8"))
            return

        # For other JSON endpoints, parse JSON
        try:
            body = json.loads(raw_body_bytes.decode("utf-8")) if raw_body_bytes else {}
        except Exception:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "Invalid JSON in request body."}).encode("utf-8"))
            return

        # 2. AI Investigation
        if path == "/api/investigate":
            variance_id = body.get("variance_id")
            if not variance_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing required field: 'variance_id'"}).encode("utf-8"))
                return

            try:
                request = InvestigationRequest(variance_id=variance_id)
                response = self.ai_service.investigate_variance(request)
                self._set_headers(200)
                self.wfile.write(json.dumps(response.to_dict(), indent=2).encode("utf-8"))
            except ValueError as ve:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": str(ve)}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": f"Investigation failed: {str(e)}"}).encode("utf-8"))

        # 3. Grounded Financial Chat
        elif path == "/api/chat":
            query = body.get("query")
            if not query:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing required field: 'query'"}).encode("utf-8"))
                return

            try:
                request = ChatRequest(query=query, session_id=body.get("session_id"))
                response = self.ai_service.answer_chat_query(request)
                self._set_headers(200)
                self.wfile.write(json.dumps(response.to_dict(), indent=2).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": f"Chat query failed: {str(e)}"}).encode("utf-8"))

        # 4. Sync Payment from Razorpay API
        elif path.startswith("/api/razorpay/sync/payment/"):
            payment_id = path.replace("/api/razorpay/sync/payment/", "").strip()
            try:
                payment = self.rzp_client.fetch_payment(payment_id)
                internal_order_id = self.rzp_ingester.ingest_payment(payment)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "order_id": internal_order_id,
                    "payment": payment.to_dict(),
                    "source": DataSource.RAZORPAY_TEST_MODE
                }, indent=2).encode("utf-8"))
            except RazorpayAPIError as re:
                self._set_headers(re.status_code)
                self.wfile.write(json.dumps({"error": re.message, "code": re.error_code}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        # 5. Sync Recon Report from Razorpay API
        elif path == "/api/razorpay/sync/recon":
            year = int(body.get("year", 2026))
            month = int(body.get("month", 8))
            day = int(body.get("day")) if "day" in body else None
            settlement_id = body.get("settlement_id", f"set_recon_{year}{month:02d}")

            try:
                recon_items = self.rzp_client.fetch_settlement_recon(year=year, month=month, day=day)
                settlement = RazorpaySettlement(
                    id=settlement_id,
                    amount_paise=sum(it.credit_paise - it.debit_paise - it.fee_paise - it.tax_paise for it in recon_items),
                    fees_paise=sum(it.fee_paise for it in recon_items),
                    tax_paise=sum(it.tax_paise for it in recon_items),
                    utr=f"UTR-SYNC-{settlement_id}",
                    status="processed",
                    source=DataSource.RAZORPAY_TEST_MODE
                )
                internal_set_id = self.rzp_ingester.ingest_settlement(settlement, recon_items)
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    "success": True,
                    "settlement_id": internal_set_id,
                    "line_items_count": len(recon_items),
                    "source": DataSource.RAZORPAY_TEST_MODE
                }, indent=2).encode("utf-8"))
            except RazorpayAPIError as re:
                self._set_headers(re.status_code)
                self.wfile.write(json.dumps({"error": re.message, "code": re.error_code}).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": f"Endpoint '{path}' not found."}).encode("utf-8"))


def create_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    ai_service: Optional[AIInvestigationService] = None,
    rzp_client: Optional[RazorpayClient] = None,
    rzp_ingester: Optional[RazorpayDataIngester] = None,
    rzp_webhook: Optional[RazorpayWebhookHandler] = None
) -> HTTPServer:
    handler = UnifiedServiceHTTPHandler
    handler.ai_service = ai_service or AIInvestigationService()
    handler.rzp_client = rzp_client or RazorpayClient()
    handler.rzp_ingester = rzp_ingester or RazorpayDataIngester()
    handler.rzp_webhook = rzp_webhook or RazorpayWebhookHandler()
    server = HTTPServer((host, port), handler)
    return server


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[*] Starting Settlement Detective Unified Backend on port {port}...")
    srv = create_server(port=port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down server.")
        srv.server_close()
