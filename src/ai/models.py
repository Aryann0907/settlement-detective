"""
Settlement Detective — AI Service Data Models
Defines structured request and response schemas for investigation and chat endpoints.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class EvidenceItem:
    type: str                # 'settlement', 'payment', 'order', 'line_item', 'fee_rule'
    id: str                  # entity identifier e.g. pay_xxx, set_xxx
    reason: str              # plain explanation of how this entity proves the claim
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RootCauseNode:
    name: str
    description: str
    children: List['RootCauseNode'] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "children": [c.to_dict() for c in self.children]
        }


@dataclass
class InvestigationRequest:
    variance_id: str


@dataclass
class InvestigationResponse:
    summary: str
    root_cause: str
    root_cause_tree: Dict[str, Any]
    financial_impact_paise: int
    financial_impact_inr: float
    severity: str                         # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    confidence: int                       # 0 to 100
    affected_transactions: List[str]      # list of validated payment IDs
    evidence: List[Dict[str, Any]]        # grounded evidence items
    recommended_action: str
    requires_human_review: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChatRequest:
    query: str
    session_id: Optional[str] = None


@dataclass
class ChatResponse:
    answer: str
    evidence: List[Dict[str, Any]]
    confidence: int
    requires_human_review: bool
    grounded_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
