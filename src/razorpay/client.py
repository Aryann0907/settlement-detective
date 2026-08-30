"""
Settlement Detective — Razorpay REST API Client
Implements secure HTTPS Basic Authentication, bounded retries, and documented endpoints.
Zero external dependencies (uses Python 3.12 urllib and base64).
"""

import time
import json
import base64
import urllib.request
import urllib.error
import urllib.parse
from typing import Dict, Any, List, Optional

from .config import RazorpayConfig
from .models import (
    RazorpayPayment,
    RazorpayRefund,
    RazorpayReconItem,
    RazorpaySettlement
)


class RazorpayAPIError(Exception):
    """Structured exception for Razorpay API errors (never leaks secrets)."""
    def __init__(self, status_code: int, message: str, error_code: Optional[str] = None):
        super().__init__(f"Razorpay API Error [{status_code}]: {message}")
        self.status_code = status_code
        self.message = message
        self.error_code = error_code


class RazorpayClient:
    """
    Clean, rate-limited Razorpay REST client for Test Mode data retrieval.
    """

    def __init__(self, config: Optional[RazorpayConfig] = None):
        self.config = config or RazorpayConfig()
        self._auth_header: Optional[str] = None
        if self.config.is_configured:
            auth_bytes = f"{self.config.key_id}:{self.config.key_secret}".encode("utf-8")
            self._auth_header = f"Basic {base64.b64encode(auth_bytes).decode('utf-8')}"

    def _ensure_configured(self):
        if not self.config.is_configured:
            raise RazorpayAPIError(
                status_code=401,
                message="Razorpay credentials not configured (RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET missing).",
                error_code="BAD_REQUEST_ERROR"
            )

    def _request(self, method: str, endpoint: str, query_params: Optional[Dict[str, Any]] = None, max_retries: int = 2) -> Dict[str, Any]:
        """Executes an HTTPS request to Razorpay with exponential backoff on 429."""
        self._ensure_configured()

        url = f"{self.config.BASE_URL}{endpoint}"
        if query_params:
            filtered_params = {k: v for k, v in query_params.items() if v is not None}
            if filtered_params:
                url = f"{url}?{urllib.parse.urlencode(filtered_params)}"

        headers = {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "User-Agent": "SettlementDetective/1.0.0"
        }

        req = urllib.request.Request(url, headers=headers, method=method)

        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw_bytes = resp.read()
                    return json.loads(raw_bytes.decode("utf-8"))
            except urllib.error.HTTPError as he:
                status = he.code
                error_body = {}
                try:
                    error_body = json.loads(he.read().decode("utf-8"))
                except Exception:
                    pass

                err_desc = error_body.get("error", {}).get("description", he.reason)
                err_code = error_body.get("error", {}).get("code", "HTTP_ERROR")

                # Handle Rate Limiting (429) with exponential backoff
                if status == 429 and attempt < max_retries:
                    sleep_time = (2 ** attempt) * 0.5
                    time.sleep(sleep_time)
                    continue

                raise RazorpayAPIError(status_code=status, message=err_desc, error_code=err_code)
            except urllib.error.URLError as ue:
                if attempt < max_retries:
                    time.sleep(0.5)
                    continue
                raise RazorpayAPIError(status_code=503, message=f"Network error connecting to Razorpay: {str(ue.reason)}")
            except Exception as e:
                raise RazorpayAPIError(status_code=500, message=f"Unexpected error: {str(e)}")

        raise RazorpayAPIError(status_code=500, message="Max retries exceeded.")

    # -------------------------------------------------------------------------
    # PAYMENT OPERATIONS
    # -------------------------------------------------------------------------
    def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        """GET /v1/payments/:id"""
        data = self._request("GET", f"/payments/{payment_id}")
        return RazorpayPayment.from_api_response(data)

    def fetch_order_payments(self, order_id: str) -> List[RazorpayPayment]:
        """GET /v1/orders/:id/payments"""
        data = self._request("GET", f"/orders/{order_id}/payments")
        items = data.get("items", []) if isinstance(data, dict) else []
        return [RazorpayPayment.from_api_response(item) for item in items]

    # -------------------------------------------------------------------------
    # REFUND OPERATIONS
    # -------------------------------------------------------------------------
    def fetch_payment_refunds(self, payment_id: str) -> List[RazorpayRefund]:
        """GET /v1/payments/:id/refunds"""
        data = self._request("GET", f"/payments/{payment_id}/refunds")
        items = data.get("items", []) if isinstance(data, dict) else []
        return [RazorpayRefund.from_api_response(item) for item in items]

    def fetch_refund(self, refund_id: str) -> RazorpayRefund:
        """GET /v1/refunds/:id"""
        data = self._request("GET", f"/refunds/{refund_id}")
        return RazorpayRefund.from_api_response(data)

    # -------------------------------------------------------------------------
    # SETTLEMENT OPERATIONS
    # -------------------------------------------------------------------------
    def fetch_settlements(self, count: int = 10, skip: int = 0, from_time: Optional[int] = None, to_time: Optional[int] = None) -> List[RazorpaySettlement]:
        """GET /v1/settlements"""
        params = {"count": count, "skip": skip, "from": from_time, "to": to_time}
        data = self._request("GET", "/settlements", query_params=params)
        items = data.get("items", []) if isinstance(data, dict) else []
        return [RazorpaySettlement.from_api_response(item) for item in items]

    def fetch_settlement(self, settlement_id: str) -> RazorpaySettlement:
        """GET /v1/settlements/:id"""
        data = self._request("GET", f"/settlements/{settlement_id}")
        return RazorpaySettlement.from_api_response(data)

    def fetch_settlement_recon(
        self,
        year: int,
        month: int,
        day: Optional[int] = None,
        count: int = 10,
        skip: int = 0
    ) -> List[RazorpayReconItem]:
        """
        GET /v1/settlements/recon/combined
        Documented Razorpay Combined Reconciliation endpoint.
        """
        params = {
            "year": year,
            "month": f"{month:02d}",
            "count": count,
            "skip": skip
        }
        if day is not None:
            params["day"] = f"{day:02d}"

        data = self._request("GET", "/settlements/recon/combined", query_params=params)
        items = data.get("items", []) if isinstance(data, dict) else []
        return [RazorpayReconItem.from_api_response(item) for item in items]
