"""
Settlement Detective — AI Package
"""

from .models import (
    EvidenceItem,
    RootCauseNode,
    InvestigationRequest,
    InvestigationResponse,
    ChatRequest,
    ChatResponse
)
from .service import AIInvestigationService
from .validator import InvestigationValidator
from .context_builder import ContextBuilder
from .providers.base import BaseLLMProvider
from .providers.gemini import GeminiLLMProvider
from .providers.mock import MockLLMProvider
from .server import create_server

__all__ = [
    "EvidenceItem",
    "RootCauseNode",
    "InvestigationRequest",
    "InvestigationResponse",
    "ChatRequest",
    "ChatResponse",
    "AIInvestigationService",
    "InvestigationValidator",
    "ContextBuilder",
    "BaseLLMProvider",
    "GeminiLLMProvider",
    "MockLLMProvider",
    "create_server"
]
