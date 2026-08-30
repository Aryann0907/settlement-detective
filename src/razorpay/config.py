"""
Settlement Detective — Razorpay Integration Configuration
Safely loads credentials and endpoints from environment variables.
"""

import os
from typing import Optional


class RazorpayConfig:
    """
    Configuration manager for Razorpay API integration.
    Guarantees secrets are loaded from environment and never exposed in logs or errors.
    """

    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        webhook_secret: Optional[str] = None
    ):
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "")
        self.webhook_secret = webhook_secret or os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
        self.is_test_mode = self.key_id.startswith("rzp_test_") if self.key_id else True

    @property
    def is_configured(self) -> bool:
        """Returns True if minimum required API keys are present."""
        return bool(self.key_id and self.key_secret)

    def sanitized_dict(self) -> dict:
        """Returns sanitized configuration metadata without exposing secret keys."""
        masked_secret = f"...{self.key_secret[-4:]}" if len(self.key_secret) >= 4 else "NOT_SET"
        return {
            "key_id": self.key_id if self.key_id else "NOT_SET",
            "key_secret_configured": bool(self.key_secret),
            "webhook_secret_configured": bool(self.webhook_secret),
            "is_test_mode": self.is_test_mode,
            "base_url": self.BASE_URL
        }
