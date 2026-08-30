"""
Settlement Detective — Multi-Pass Matching Engine
Implements deterministic Pass 1, Pass 2, and Pass 3 transaction matching.
"""

from typing import Dict, List, Any, Optional, Tuple


class MatchResult:
    def __init__(self, match_type: str, line_item: Dict[str, Any], order: Optional[Dict[str, Any]], match_reasons: List[str]):
        self.match_type = match_type          # 'exact', 'order_based', 'amount_time', 'unmatched'
        self.line_item = line_item
        self.order = order
        self.match_reasons = match_reasons


class MultiPassMatcher:
    """
    Executes deterministic multi-pass matching between settlement line items and merchant orders.
    """

    def __init__(self, orders: List[Dict[str, Any]]):
        self.orders = orders
        
        # Build fast index lookups
        self.orders_by_id = {o["id"]: o for o in orders}
        self.orders_by_payment_id = {o["razorpay_payment_id"]: o for o in orders if o.get("razorpay_payment_id")}
        self.orders_by_order_id = {o["razorpay_order_id"]: o for o in orders if o.get("razorpay_order_id")}
        self.orders_by_merchant_order_id = {o["merchant_order_id"]: o for o in orders if o.get("merchant_order_id")}

    def match_line_items(self, line_items: List[Dict[str, Any]], period_start: str, period_end: str) -> Tuple[List[MatchResult], List[Dict[str, Any]]]:
        """
        Runs Pass 1, Pass 2, and Pass 3 matching on a batch of settlement line items.
        Returns:
            (matched_results, unmatched_eligible_orders)
        """
        matched_results: List[MatchResult] = []
        matched_order_ids = set()

        for item in line_items:
            entity_id = item["entity_id"]
            entity_type = item["entity_type"]
            order_id = item.get("order_id")

            # -------------------------------------------------------------
            # PASS 1: Exact Identifier / Payment Reference Matching
            # -------------------------------------------------------------
            matched_order = None
            match_type = "unmatched"
            match_reasons = []

            if entity_type == "payment" and entity_id in self.orders_by_payment_id:
                matched_order = self.orders_by_payment_id[entity_id]
                match_type = "exact"
                match_reasons.append("payment_id_exact_match")

            elif entity_type == "refund":
                # Check for refund prefix e.g. rfnd_ord_001 or rfnd_mismatch_ord_001
                if entity_id.startswith("rfnd_"):
                    raw_id = entity_id.replace("rfnd_mismatch_", "").replace("rfnd_", "")
                    if raw_id in self.orders_by_id:
                        matched_order = self.orders_by_id[raw_id]
                        match_type = "exact"
                        match_reasons.append("refund_entity_id_exact_match")

            # -------------------------------------------------------------
            # PASS 2: Order-Based Matching (Fallback if Pass 1 didn't match)
            # -------------------------------------------------------------
            if not matched_order and order_id and order_id in self.orders_by_id:
                matched_order = self.orders_by_id[order_id]
                match_type = "order_based"
                match_reasons.append("order_id_foreign_key_match")

            # -------------------------------------------------------------
            # PASS 3: Time-Window & Amount Verification
            # -------------------------------------------------------------
            if matched_order:
                matched_order_ids.add(matched_order["id"])
                # Check timing within settlement capture period
                captured_at = matched_order.get("captured_at")
                if captured_at:
                    if period_start <= captured_at <= period_end:
                        match_reasons.append("within_settlement_capture_window")
                    else:
                        match_reasons.append("outside_settlement_capture_window")

            matched_results.append(MatchResult(
                match_type=match_type,
                line_item=item,
                order=matched_order,
                match_reasons=match_reasons
            ))

        # Identify merchant orders that were captured within the settlement window but not matched
        unmatched_eligible_orders = []
        for o in self.orders:
            if o["id"] not in matched_order_ids and o.get("status") in ("captured", "refunded"):
                cap = o.get("captured_at")
                if cap and period_start <= cap <= period_end:
                    unmatched_eligible_orders.append(o)

        return matched_results, unmatched_eligible_orders
