"""OpenAI-compatible structured JSON Agent decision adapter."""

import json
import re
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from repopilot.agent.actions import AgentDecision
from repopilot.agent.prompts import build_agent_messages
from repopilot.agent.protocol import AgentModelUsage
from repopilot.config import Settings
from repopilot.exceptions import AgentDecisionError, ConfigurationError
from repopilot.tools.base import ToolDefinition


class OpenAICompatibleAgentModel:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        if not settings.llm_api_key:
            raise ConfigurationError("REPOPILOT_LLM_API_KEY is required for Agent analysis.")
        if not settings.llm_model:
            raise ConfigurationError("REPOPILOT_LLM_MODEL is required for Agent analysis.")
        self.settings = settings
        self.client = client or OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self._request_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._usage_estimated = False

    def decide(self, context: str, tools: list[ToolDefinition]) -> AgentDecision:
        del tools  # Tool schemas are already embedded in the bounded Agent context.
        try:
            messages: Any = build_agent_messages(context)
            self._request_count += 1
            request: dict[str, Any] = {
                "model": self.settings.llm_model or "",
                "messages": messages,
                "temperature": self.settings.llm_temperature,
                "max_tokens": self.settings.llm_max_output_tokens,
            }
            if self._is_minimax():
                request["extra_body"] = {"reasoning_split": True}
            else:
                request["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**request)
            content = response.choices[0].message.content if response.choices else None
            if not content:
                raise AgentDecisionError("The Agent model returned an empty response.")
            self._record_usage(response, messages, content)
            payload: Any = self._decode_json_object(content)
            return AgentDecision.model_validate(payload)
        except AgentDecisionError:
            raise
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise AgentDecisionError("The Agent response did not match AgentDecision.") from exc
        except Exception as exc:
            raise AgentDecisionError(
                f"Agent model request failed: {self._safe_error(exc)}"
            ) from exc

    def usage_snapshot(self) -> AgentModelUsage:
        return {
            "request_count": self._request_count,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": self._total_tokens,
            "estimated": self._usage_estimated,
        }

    def _record_usage(self, response: Any, messages: Any, content: str) -> None:
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        if not prompt_tokens and not completion_tokens:
            serialized_messages = json.dumps(messages, ensure_ascii=False)
            prompt_tokens = max((len(serialized_messages) + 1) // 2, 1)
            completion_tokens = max((len(content) + 1) // 2, 1)
            total_tokens = prompt_tokens + completion_tokens
            self._usage_estimated = True
        elif not total_tokens:
            total_tokens = prompt_tokens + completion_tokens
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens
        self._total_tokens += total_tokens

    def _is_minimax(self) -> bool:
        return "minimax" in self.settings.llm_base_url.lower()

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            return "\n".join(stripped.splitlines()[1:-1]).strip()
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
        text = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", text)
        text = re.sub(
            r"(?i)(api[ _-]?key\s*[:=]\s*)[^,}\]]+",
            r"\1[REDACTED]",
            text,
        )
        return text[-500:] if text else exc.__class__.__name__
