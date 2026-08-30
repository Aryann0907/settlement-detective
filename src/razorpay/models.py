"""
Settlement Detective — Razorpay Normalized Data Contract
Defines typed dataclasses for payments, refunds, settlements, and recon items.
Ensures strict integer paise monetary representation and data source tagging.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


class DataSource:
    RAZORPAY_TEST_MODE = "RAZORPAY_TEST_MODE"
    SYNTHETIC_DEMO_DATA = "SYNTHETIC_DEMO_DATA"


@dataclass
class RazorpayPayment:
    id: str                               # rzp payment ID (e.g. pay_xxx)
    order_id: Optional[str]               # rzp order ID (e.g. order_xxx)
    amount_paise: int                     # gross payment amount in integer paise
    currency: str = "INR"
    status: str = "captured"              # authorized, captured, refunded, failed
    method: str = "upi"                   # upi, card, netbanking, wallet
    fee_paise: int = 0                    # gateway fee in integer paise
    tax_paise: int = 0                    # GST on fee in integer paise
    net_paise: int = 0                    # amount - fee - tax
    amount_refunded_paise: int = 0
    refund_status: Optional[str] = "none" # none, partial, full
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    created_at: str = ""
    captured_at: Optional[str] = None
    source: str = DataSource.RAZORPAY_TEST_MODE
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'RazorpayPayment':
        """Parses a Razorpay API payment object into the normalized model."""
        amount_paise = int(data.get("amount", 0))
        fee_paise = int(data.get("fee", 0))
        tax_paise = int(data.get("tax", 0))
        net_paise = amount_paise - fee_paise - tax_paise
        amount_refunded = int(data.get("amount_refunded", 0))
        
        # Convert unix timestamp to ISO format
        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, (int, float)):
            created_at_iso = datetime.fromtimestamp(created_at_raw, tz=timezone.utc).isoformat()
        else:
            created_at_iso = str(created_at_raw or datetime.now(timezone.utc).isoformat())

        captured = data.get("captured", False)
        captured_at_iso = created_at_iso if captured else None

        refund_status = "none"
        if amount_refunded >= amount_paise and amount_paise > 0:
            refund_status = "full"
        elif amount_refunded > 0:
            refund_status = "partial"

        return cls(
            id=data.get("id", ""),
            order_id=data.get("order_id"),
            amount_paise=amount_paise,
            currency=data.get("currency", "INR"),
            status=data.get("status", "captured"),
            method=data.get("method", "upi"),
            fee_paise=fee_paise,
            tax_paise=tax_paise,
            net_paise=net_paise,
            amount_refunded_paise=amount_refunded,
            refund_status=refund_status,
            customer_email=data.get("email"),
            customer_phone=data.get("contact"),
            created_at=created_at_iso,
            captured_at=captured_at_iso,
            source=DataSource.RAZORPAY_TEST_MODE,
            raw_data=data
        )


@dataclass
class RazorpayRefund:
    id: str                               # rzp refund ID (e.g. rfnd_xxx)
    payment_id: str                       # linked payment ID (pay_xxx)
    amount_paise: int                     # refund amount in paise
    currency: str = "INR"
    status: str = "processed"             # pending, processed, failed
    fee_paise: int = 0
    tax_paise: int = 0
    created_at: str = ""
    source: str = DataSource.RAZORPAY_TEST_MODE
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'RazorpayRefund':
        amount_paise = int(data.get("amount", 0))
        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, (int, float)):
            created_at_iso = datetime.fromtimestamp(created_at_raw, tz=timezone.utc).isoformat()
        else:
            created_at_iso = str(created_at_raw or datetime.now(timezone.utc).isoformat())

        return cls(
            id=data.get("id", ""),
            payment_id=data.get("payment_id", ""),
            amount_paise=amount_paise,
            currency=data.get("currency", "INR"),
            status=data.get("status", "processed"),
            fee_paise=int(data.get("fee", 0)),
            tax_paise=int(data.get("tax", 0)),
            created_at=created_at_iso,
            source=DataSource.RAZORPAY_TEST_MODE,
            raw_data=data
        )


@dataclass
class RazorpayReconItem:
    entity_id: str                        # payment / refund / adjustment ID
    entity_type: str                      # 'payment', 'refund', 'adjustment'
    amount_paise: int
    fee_paise: int = 0
    tax_paise: int = 0
    debit_paise: int = 0
    credit_paise: int = 0
    settlement_id: str = ""
    settled_at: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any], settlement_id: str = "") -> 'RazorpayReconItem':
        entity_type = data.get("type", "payment")
        amount_paise = int(data.get("amount", 0))
        fee_paise = int(data.get("fee", 0))
        tax_paise = int(data.get("tax", 0))
        debit_paise = int(data.get("debit", 0))
        credit_paise = int(data.get("credit", 0))

        # If debit/credit is not explicitly set in response, compute based on type
        if credit_paise == 0 and debit_paise == 0:
            if entity_type == "payment":
                credit_paise = amount_paise
            elif entity_type == "refund":
                debit_paise = amount_paise

        settled_at_raw = data.get("settled_at") or data.get("created_at")
        if isinstance(settled_at_raw, (int, float)):
            settled_at_iso = datetime.fromtimestamp(settled_at_raw, tz=timezone.utc).isoformat()
        else:
            settled_at_iso = str(settled_at_raw or datetime.now(timezone.utc).isoformat())

        return cls(
            entity_id=data.get("entity_id") or data.get("id", ""),
            entity_type=entity_type,
            amount_paise=amount_paise,
            fee_paise=fee_paise,
            tax_paise=tax_paise,
            debit_paise=debit_paise,
            credit_paise=credit_paise,
            settlement_id=settlement_id or data.get("settlement_id", ""),
            settled_at=settled_at_iso,
            raw_data=data
        )


@dataclass
class RazorpaySettlement:
    id: str                               # rzp settlement ID (e.g. set_xxx)
    amount_paise: int                     # net payout amount
    fees_paise: int = 0
    tax_paise: int = 0
    utr: Optional[str] = None
    status: str = "processed"
    created_at: str = ""
    source: str = DataSource.RAZORPAY_TEST_MODE
    line_items: List[RazorpayReconItem] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["line_items"] = [item.to_dict() for item in self.line_items]
        return d

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'RazorpaySettlement':
        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, (int, float)):
            created_at_iso = datetime.fromtimestamp(created_at_raw, tz=timezone.utc).isoformat()
        else:
            created_at_iso = str(created_at_raw or datetime.now(timezone.utc).isoformat())

        return cls(
            id=data.get("id", ""),
            amount_paise=int(data.get("amount", 0)),
            fees_paise=int(data.get("fees", 0)),
            tax_paise=int(data.get("tax", 0)),
            utr=data.get("utr"),
            status=data.get("status", "processed"),
            created_at=created_at_iso,
            source=DataSource.RAZORPAY_TEST_MODE,
            raw_data=data
        )


@dataclass
class WebhookEvent:
    event_id: str
    event_type: str                       # payment.captured, refund.processed, settlement.processed
    payload: Dict[str, Any]
    created_at: str
    is_test_mode: bool = True
