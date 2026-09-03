import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from repopilot.agent.actions import AgentDecision, AgentEvidence, FinishAction, ToolAction
from repopilot.config import Settings
from repopilot.exceptions import AgentDecisionError
from repopilot.llm.agent_model import OpenAICompatibleAgentModel


class FakeCompletions:
    def __init__(self, content: str | list[str], usage: object | None = None) -> None:
        self.contents = content if isinstance(content, list) else [content]
        self.usage = usage
        self.last_request: dict[str, object] = {}
        self.calls = 0

    def create(self, **kwargs: object) -> object:
        self.last_request = kwargs
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=self.usage,
        )


def fake_sdk(content: str) -> object:
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(content)))


def test_agent_model_records_provider_token_usage() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    content = (
        '{"rationale":"inspect tree","action":{"type":"tool",'
        '"tool_name":"get_tree","arguments":{"path":"src"}}}'
    )
    completions = FakeCompletions(
        content,
        SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150),
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    model = OpenAICompatibleAgentModel(settings, client=client)  # type: ignore[arg-type]

    model.decide("context", [])

    assert model.usage_snapshot() == {
        "request_count": 1,
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
        "estimated": False,
    }


def test_agent_model_uses_minimax_reasoning_split_without_json_object() -> None:
    settings = Settings(
        llm_api_key="test",
        llm_base_url="https://api.minimaxi.com/v1",
        llm_model="MiniMax-M2.7",
    )
    content = (
        '{"rationale":"inspect tree","action":{"type":"tool",'
        '"tool_name":"get_tree","arguments":{"path":"src"}}}'
    )
    completions = FakeCompletions(content)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    model = OpenAICompatibleAgentModel(settings, client=client)  # type: ignore[arg-type]

    model.decide("context", [])

    assert completions.last_request["extra_body"] == {"reasoning_split": True}
    assert "response_format" not in completions.last_request


def test_agent_model_extracts_final_json_after_minimax_thinking_text() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    content = (
        '<think>I may mention {"draft": true} while planning.</think>\n'
        '{"rationale":"inspect tree","action":{"type":"tool",'
        '"tool_name":"get_tree","arguments":{"path":"src"}}}'
    )
    model = OpenAICompatibleAgentModel(settings, client=fake_sdk(content))  # type: ignore[arg-type]

    decision = model.decide("context", [])

    assert isinstance(decision.action, ToolAction)
    assert decision.action.tool_name == "get_tree"


def test_agent_model_parses_provider_neutral_json_action() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    content = (
        '{"rationale":"inspect tree","action":{"type":"tool",'
        '"tool_name":"get_tree","arguments":{"path":"src"}}}'
    )
    model = OpenAICompatibleAgentModel(settings, client=fake_sdk(content))  # type: ignore[arg-type]

    decision = model.decide("context", [])

    assert isinstance(decision, AgentDecision)
    assert isinstance(decision.action, ToolAction)
    assert decision.action.tool_name == "get_tree"
    usage = model.usage_snapshot()
    assert usage["request_count"] == 1
    assert usage["total_tokens"] > 0
    assert usage["estimated"] is True


def test_agent_model_normalizes_common_tool_action_aliases() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    content = json.dumps(
        {
            "reason": "inspect entrypoint",
            "action": {"tool": "read_file", "args": {"path": "main.py"}},
        }
    )
    model = OpenAICompatibleAgentModel(
        settings,
        client=fake_sdk(content),  # type: ignore[arg-type]
    )

    decision = model.decide("context", [])

    assert decision.rationale == "inspect entrypoint"
    assert isinstance(decision.action, ToolAction)
    assert decision.action.tool_name == "read_file"
    assert decision.action.arguments == {"path": "main.py"}


def test_agent_model_normalizes_common_finish_action_aliases() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    content = json.dumps(
        {
            "reason": "finish from collected evidence",
            "action": "finish",
            "result": {
                "summary": "Fixture project",
                "entry_points": [
                    {
                        "description": "main.py is the entrypoint",
                        "confidence": "high",
                        "evidence": ["ev_entry"],
                    }
                ],
                "evidence": {
                    "id": "ev_entry",
                    "claim": "Entrypoint source",
                    "file": "main.py",
                    "line": 1,
                    "observation": "obs_read",
                },
                "limitations": ["Fixture only"],
            },
        }
    )
    model = OpenAICompatibleAgentModel(
        settings,
        client=fake_sdk(content),  # type: ignore[arg-type]
    )

    decision = model.decide("context", [])

    assert isinstance(decision.action, FinishAction)
    assert decision.action.analysis.project_summary == "Fixture project"
    assert decision.action.analysis.entrypoints[0].confidence == "confirmed"
    assert decision.action.analysis.evidence[0].start_line == 1
    assert decision.action.analysis.evidence[0].end_line == 1


def test_agent_model_repairs_invalid_decision_with_compact_second_request() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    valid = (
        '{"rationale":"inspect tree","action":{"type":"tool",'
        '"tool_name":"get_tree","arguments":{"path":"src"}}}'
    )
    completions = FakeCompletions(["not valid json", valid])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    model = OpenAICompatibleAgentModel(settings, client=client)  # type: ignore[arg-type]

    decision = model.decide("large original context", [])

    assert isinstance(decision.action, ToolAction)
    assert completions.calls == 2
    assert completions.last_request["temperature"] == 0
    messages = completions.last_request["messages"]
    assert isinstance(messages, list)
    assert "Repair an invalid RepoPilot AgentDecision" in messages[0]["content"]
    assert "large original context" not in messages[1]["content"]


def test_agent_model_reports_schema_paths_without_storing_response_content() -> None:
    settings = Settings(
        llm_api_key="test",
        llm_model="model",
        agent_decision_repair_attempts=0,
    )
    invalid = '{"rationale":"contains sk-never-log-this","action":{"type":"tool"}}'
    model = OpenAICompatibleAgentModel(
        settings,
        client=fake_sdk(invalid),  # type: ignore[arg-type]
    )

    with pytest.raises(AgentDecisionError) as error:
        model.decide("context", [])

    message = str(error.value)
    assert "schema=" in message
    assert "tool_name" in message
    assert "response_sha256=" in message
    assert "sk-never-log-this" not in message


def test_agent_model_rejects_invalid_action() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    model = OpenAICompatibleAgentModel(settings, client=fake_sdk("{}"))  # type: ignore[arg-type]

    with pytest.raises(AgentDecisionError):
        model.decide("context", [])


def test_agent_model_parses_evidence_grounded_findings() -> None:
    settings = Settings(llm_api_key="test", llm_model="model")
    content = json.dumps(
        {
            "rationale": "finish with grounded entrypoint",
            "action": {
                "type": "finish",
                "analysis": {
                    "project_summary": "Fixture",
                    "entrypoints": [
                        {
                            "claim": "src/main.py creates the application",
                            "confidence": "confirmed",
                            "evidence_ids": ["ev_entry"],
                        }
                    ],
                    "evidence": [
                        {
                            "evidence_id": "ev_entry",
                            "claim": "Application construction",
                            "path": "src/main.py",
                            "start_line": 1,
                            "end_line": 3,
                            "observation_id": "obs_source",
                        }
                    ],
                    "limitations": ["Only the entrypoint was read."],
                },
            },
        }
    )
    model = OpenAICompatibleAgentModel(settings, client=fake_sdk(content))  # type: ignore[arg-type]

    decision = model.decide("context", [])

    assert isinstance(decision.action, FinishAction)
    assert decision.action.analysis.entrypoints[0].evidence_ids == ["ev_entry"]
    assert decision.action.analysis.evidence[0].evidence_id == "ev_entry"


def test_agent_evidence_rejects_inverted_line_range() -> None:
    with pytest.raises(ValidationError, match="end_line"):
        AgentEvidence(
            evidence_id="ev_invalid_range",
            claim="Invalid range",
            path="src/main.py",
            start_line=10,
            end_line=5,
            observation_id="obs_source",
        )


def test_agent_model_redacts_full_and_provider_masked_api_keys() -> None:
    settings = Settings(llm_api_key="sk-secret-value", llm_model="model")
    model = OpenAICompatibleAgentModel(settings, client=fake_sdk("{}"))  # type: ignore[arg-type]

    safe = model._safe_error(  # noqa: SLF001
        RuntimeError("Authentication failed for sk-secret-value; Your api key: ****alue is invalid")
    )

    assert "sk-secret-value" not in safe
    assert "****alue" not in safe
    assert "[REDACTED]" in safe
