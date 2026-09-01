"""OpenAI-compatible chat-completions adapter."""

import json
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from repopilot.config import Settings
from repopilot.exceptions import ConfigurationError, LLMRequestError, LLMResponseError
from repopilot.llm.prompts import build_messages
from repopilot.models.analysis import AnalysisRequest, AnalysisResult


class OpenAICompatibleClient:
    """Keep OpenAI-compatible SDK details behind the LLMClient protocol."""

    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        if not settings.llm_api_key:
            raise ConfigurationError("REPOPILOT_LLM_API_KEY is required for analysis.")
        if not settings.llm_model:
            raise ConfigurationError("REPOPILOT_LLM_MODEL is required for analysis.")
        self.settings = settings
        self.client = client or OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def analyze_repository(self, request: AnalysisRequest) -> AnalysisResult:
        try:
            messages: Any = build_messages(request)
            arguments: dict[str, Any] = {
                "model": self.settings.llm_model or "",
                "messages": messages,
                "temperature": self.settings.llm_temperature,
                "max_tokens": self.settings.llm_max_output_tokens,
            }
            if "minimax" in self.settings.llm_base_url.lower():
                arguments["extra_body"] = {"reasoning_split": True}
            else:
                arguments["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**arguments)
        except Exception as exc:
            raise LLMRequestError(f"The LLM request failed: {self._safe_error(exc)}") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise LLMResponseError("The LLM returned an empty response.")

        try:
            payload: Any = self._decode_json_object(content)
            return AnalysisResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise LLMResponseError("The LLM response did not match AnalysisResult.") from exc

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            return "\n".join(lines[1:-1]).strip()
        return stripped

    @classmethod
    def _decode_json_object(cls, content: str) -> dict[str, Any]:
        stripped = cls._strip_code_fence(content)
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder()
        candidates: list[tuple[int, dict[str, Any]]] = []
        for index, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                payload, consumed = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                candidates.append((consumed, payload))
        if not candidates:
            raise json.JSONDecodeError("No JSON object found", stripped, 0)
        return max(candidates, key=lambda item: item[0])[1]

    def _safe_error(self, exc: Exception) -> str:
        text = str(exc)
        if self.settings.llm_api_key:
            text = text.replace(self.settings.llm_api_key, "[REDACTED]")
        return text[-500:] if text else exc.__class__.__name__
