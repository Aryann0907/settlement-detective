"""
Settlement Detective — AI Investigation Service
Orchestrates context preparation, LLM generation, and anti-hallucination validation.
"""

import os
from typing import Dict, Any, Optional

from .models import (
    InvestigationRequest,
    InvestigationResponse,
    ChatRequest,
    ChatResponse
)
from .providers.base import BaseLLMProvider
from .providers.gemini import GeminiLLMProvider
from .providers.mock import MockLLMProvider
from .context_builder import ContextBuilder
from .validator import InvestigationValidator


class AIInvestigationService:
    """
    Main AI Service managing deterministic grounding and explanation workflows.
    """

    def __init__(self, provider: Optional[BaseLLMProvider] = None, context_builder: Optional[ContextBuilder] = None):
        self.context_builder = context_builder or ContextBuilder()
        
        # Determine provider (Default: Mock if no API key, or Gemini if configured)
        if provider:
            self.provider = provider
        elif os.environ.get("GEMINI_API_KEY") and os.environ.get("LLM_PROVIDER", "").lower() == "gemini":
            self.provider = GeminiLLMProvider()
        else:
            self.provider = MockLLMProvider()

    def investigate_variance(self, request: InvestigationRequest) -> InvestigationResponse:
        """
        Executes a grounded investigation for a variance.
        1. Retrieves ground-truth context from database.
        2. Calls LLM provider for structured explanation.
        3. Validates LLM output against evidence, locking financial amounts.
        """
        # Step 1: Fetch deterministic ground-truth context
        ground_truth_context = self.context_builder.build_investigation_context(request.variance_id)

        # Step 2: Invoke LLM provider
        raw_llm_output = self.provider.generate_investigation(ground_truth_context)

        # Step 3: Anti-Hallucination & Evidence Validation
        validated_response = InvestigationValidator.validate_and_sanitize_investigation(
            raw_llm_output,
            ground_truth_context
        )

        return validated_response

    def answer_chat_query(self, request: ChatRequest) -> ChatResponse:
        """
        Answers a merchant finance question using grounded database context.
        """
        # Step 1: Retrieve grounded financial context
        grounded_context = self.context_builder.build_chat_context(request.query)

        # Step 2: Invoke LLM provider
        raw_output = self.provider.generate_chat_response(request.query, grounded_context)

        # Step 3: Format and validate response
        return ChatResponse(
            answer=raw_output.get("answer", "No data available for this query."),
            evidence=raw_output.get("evidence", []),
            confidence=raw_output.get("confidence", 90),
            requires_human_review=raw_output.get("requires_human_review", False),
            grounded_data=raw_output.get("grounded_data")
        )
