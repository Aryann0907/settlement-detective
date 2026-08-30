"""
Settlement Detective — Base LLM Provider Interface
Defines the contract for replaceable LLM providers (Gemini, Mock/Dev, OpenAI, etc.).
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseLLMProvider(ABC):
    """
    Abstract LLM Provider.
    All providers must accept structured context and return structured explanations.
    """

    @abstractmethod
    def generate_investigation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates an investigation summary, root-cause explanation, root-cause tree,
        and recommended action based strictly on the provided financial context.
        """
        pass

    @abstractmethod
    def generate_chat_response(self, query: str, grounded_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates a natural-language answer to a merchant question using only the
        supplied grounded financial data.
        """
        pass
