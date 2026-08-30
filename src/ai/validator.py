"""
Settlement Detective — Anti-Hallucination & Evidence Validator
Enforces financial ground truth and validates LLM outputs against supplied context.
"""

from typing import Dict, Any, List, Set, Tuple
from .models import InvestigationResponse, EvidenceItem, RootCauseNode


class InvestigationValidator:
    """
    Post-processing validation engine that guards against AI hallucinations.
    Enforces deterministic financial numbers and strict entity reference validity.
    """

    @staticmethod
    def extract_valid_entity_ids(context: Dict[str, Any]) -> Set[str]:
        """Extracts all legitimate entity IDs present in the supplied evidence context."""
        valid_ids: Set[str] = set()

        if "settlement_id" in context:
            valid_ids.add(str(context["settlement_id"]))
        if "razorpay_settlement_id" in context:
            valid_ids.add(str(context["razorpay_settlement_id"]))
        if "order_id" in context and context["order_id"]:
            valid_ids.add(str(context["order_id"]))
        if "line_item_id" in context and context["line_item_id"]:
            valid_ids.add(str(context["line_item_id"]))

        evidence = context.get("evidence", {})
        if isinstance(evidence, dict):
            for k in ["payment_id", "order_id", "line_item_id", "entity_id", "target_settlement_id", "utr"]:
                if k in evidence and evidence[k]:
                    valid_ids.add(str(evidence[k]))

            if "affected_payments" in evidence and isinstance(evidence["affected_payments"], list):
                for p in evidence["affected_payments"]:
                    if isinstance(p, dict):
                        if "payment_id" in p and p["payment_id"]:
                            valid_ids.add(str(p["payment_id"]))
                        if "order_id" in p and p["order_id"]:
                            valid_ids.add(str(p["order_id"]))
                        if "line_item_id" in p and p["line_item_id"]:
                            valid_ids.add(str(p["line_item_id"]))

            if "duplicate_line_item_ids" in evidence and isinstance(evidence["duplicate_line_item_ids"], list):
                for lid in evidence["duplicate_line_item_ids"]:
                    valid_ids.add(str(lid))

        return valid_ids

    @classmethod
    def validate_and_sanitize_investigation(
        cls,
        llm_output: Dict[str, Any],
        ground_truth_context: Dict[str, Any]
    ) -> InvestigationResponse:
        """
        Validates LLM output against the ground truth context.
        Locks financial amounts to deterministic values and removes hallucinated entity references.
        """
        # 1. Check if ground truth evidence is empty
        evidence_dict = ground_truth_context.get("evidence", {})
        if not evidence_dict or not any(evidence_dict.values()):
            return InvestigationResponse(
                summary="Insufficient evidence — human review required.",
                root_cause="The deterministic reconciliation engine could not locate sufficient transaction records for this discrepancy.",
                root_cause_tree={"name": "Investigation Incomplete", "description": "Insufficient evidence available in transaction logs", "children": []},
                financial_impact_paise=abs(ground_truth_context.get("variance_paise", 0)),
                financial_impact_inr=abs(ground_truth_context.get("variance_paise", 0)) / 100.0,
                severity=ground_truth_context.get("severity", "HIGH"),
                confidence=0,
                affected_transactions=[],
                evidence=[],
                recommended_action="Manually inspect bank statement and payment gateway settlement files.",
                requires_human_review=True
            )

        valid_entity_ids = cls.extract_valid_entity_ids(ground_truth_context)
        
        # 2. Lock financial figures to deterministic ground truth
        deterministic_variance_paise = abs(ground_truth_context.get("variance_paise", 0))
        deterministic_severity = ground_truth_context.get("severity", "HIGH")

        # 3. Validate and filter affected_transactions (remove any hallucinated IDs)
        raw_affected = llm_output.get("affected_transactions", [])
        sanitized_affected: List[str] = []
        for pid in raw_affected:
            if str(pid) in valid_entity_ids:
                sanitized_affected.append(str(pid))

        # 4. Validate and filter evidence items
        raw_evidence = llm_output.get("evidence", [])
        sanitized_evidence: List[Dict[str, Any]] = []
        for ev in raw_evidence:
            if isinstance(ev, dict) and str(ev.get("id")) in valid_entity_ids:
                sanitized_evidence.append(ev)

        # 5. Extract or sanitize root cause tree
        root_cause_tree = llm_output.get("root_cause_tree", {})
        if not isinstance(root_cause_tree, dict) or "name" not in root_cause_tree:
            root_cause_tree = {
                "name": "Settlement Discrepancy",
                "description": llm_output.get("root_cause", "Discrepancy identified"),
                "children": []
            }

        # 6. Check confidence and review flag
        confidence = int(llm_output.get("confidence", 90))
        requires_human_review = bool(llm_output.get("requires_human_review", False))

        if confidence < 60 or len(sanitized_evidence) == 0:
            requires_human_review = True

        return InvestigationResponse(
            summary=llm_output.get("summary", "Investigation completed."),
            root_cause=llm_output.get("root_cause", "Root cause identified."),
            root_cause_tree=root_cause_tree,
            financial_impact_paise=deterministic_variance_paise,
            financial_impact_inr=deterministic_variance_paise / 100.0,
            severity=deterministic_severity,
            confidence=confidence,
            affected_transactions=sanitized_affected,
            evidence=sanitized_evidence,
            recommended_action=llm_output.get("recommended_action", "Review reconciliation records."),
            requires_human_review=requires_human_review
        )
