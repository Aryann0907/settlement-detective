"""
Settlement Detective — Google Gemini LLM Provider
Interacts with Google Gemini REST API using standard library urllib (zero external dependencies).
"""

import os
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

from .base import BaseLLMProvider


class GeminiLLMProvider(BaseLLMProvider):
    """
    Production Google Gemini LLM Provider.
    Configured via GEMINI_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-1.5-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = os.environ.get("GEMINI_MODEL", model)
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def _call_gemini(self, system_instruction: str, prompt: str) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured in environment variables.")

        url = f"{self.endpoint}?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {"text": system_instruction}
                ]
            },
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                response_json = json.loads(resp.read().decode("utf-8"))
                text = response_json["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
        except Exception as e:
            raise RuntimeError(f"Gemini API invocation failed: {str(e)}")

    def generate_investigation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        system_instruction = (
            "You are the AI Finance Controller for Settlement Detective. "
            "You are provided with a pre-computed reconciliation evidence snapshot from the deterministic engine. "
            "STRICT RULES:\n"
            "1. You MUST NOT calculate or alter financial amounts.\n"
            "2. You MUST cite only the exact payment/order/line-item IDs provided in the context.\n"
            "3. If evidence is empty, state 'Insufficient evidence — human review required.' and set requires_human_review to true.\n"
            "4. Return strictly structured JSON matching the Investigation schema."
        )

        prompt = (
            f"Analyze the following deterministic variance evidence and produce a clear, plain-English explanation:\n"
            f"CONTEXT:\n{json.dumps(context, indent=2)}\n\n"
            "Return JSON with fields: summary, root_cause, root_cause_tree, affected_transactions, evidence, recommended_action, confidence, requires_human_review."
        )

        return self._call_gemini(system_instruction, prompt)

    def generate_chat_response(self, query: str, grounded_context: Dict[str, Any]) -> Dict[str, Any]:
        system_instruction = (
            "You are the AI Finance Controller for Razorpay Merchants. "
            "Answer the merchant's financial question using ONLY the provided grounded data.\n"
            "STRICT RULES:\n"
            "1. State exact numbers in rupees (e.g. ₹17.00) based on the supplied paise values.\n"
            "2. Never guess or invent unsupplied settlements or amounts.\n"
            "3. If the requested information is not in the data, explicitly state so.\n"
            "4. Return JSON with: answer, evidence, confidence, requires_human_review."
        )

        prompt = (
            f"MERCHANT QUESTION: {query}\n\n"
            f"GROUNDED FINANCIAL DATA:\n{json.dumps(grounded_context, indent=2)}\n\n"
            "Provide an accurate, grounded answer in JSON."
        )

        return self._call_gemini(system_instruction, prompt)
