"""Validation gate preventing unsupported claims from entering long-term memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import ValidationError

from repopilot.agent.actions import AgentAnalysisResult, AgentEvidence, AgentFinding
from repopilot.agent.finish import FinishGate
from repopilot.agent.state import AgentState
from repopilot.memory.models import MemoryCandidate, MemoryEvidence
from repopilot.memory.safety import contains_possible_secret


@dataclass(slots=True)
class MemoryValidation:
    accepted: bool
    candidate: MemoryCandidate
    reasons: list[str]


class MemoryValidator:
    """Reuse the final Evidence rules before persisting an Agent-proposed memory."""

    def __init__(self, finish_gate: FinishGate | None = None) -> None:
        self.finish_gate = finish_gate or FinishGate()

    def validate(self, candidate: MemoryCandidate, state: AgentState) -> MemoryValidation:
        validated = candidate.model_copy(deep=True)
        reasons: list[str] = []
        if not validated.evidence:
            reasons.append("A saved repository memory must include source Evidence.")
        if validated.memory_type == "execution_flow" and validated.confidence == "confirmed":
            reasons.append("Execution-flow memory must be inferred, not confirmed.")
        if contains_possible_secret(validated.title) or contains_possible_secret(validated.content):
            reasons.append("Memory content appears to contain a secret and was rejected.")
        for path in validated.paths:
            pure = PurePosixPath(path)
            if pure.is_absolute() or ".." in pure.parts:
                reasons.append(f"Memory path must remain repository-relative: {path}")

        agent_evidence: list[AgentEvidence] = []
        if not reasons:
            try:
                agent_evidence = [self._agent_evidence(item) for item in validated.evidence]
            except ValidationError as exc:
                reasons.append(f"Memory Evidence is invalid: {exc}")

        if agent_evidence:
            finding = AgentFinding(
                claim=validated.content,
                confidence=validated.confidence,
                evidence_ids=[item.evidence_id for item in agent_evidence],
            )
            analysis = AgentAnalysisResult(
                project_summary=validated.title,
                execution_flows=[finding] if validated.memory_type == "execution_flow" else [],
                core_modules=[] if validated.memory_type == "execution_flow" else [finding],
                evidence=agent_evidence,
                limitations=["This validation only checks the submitted memory candidate."],
            )
            result = self.finish_gate.validate(analysis, state)
            if not result.accepted:
                reasons.extend(result.reasons)
            else:
                verified_by_id = {item.evidence_id: item for item in result.analysis.evidence}
                validated.evidence = [
                    item.model_copy(update={"verified": verified_by_id[item.evidence_id].verified})
                    for item in validated.evidence
                ]
        return MemoryValidation(accepted=not reasons, candidate=validated, reasons=reasons)

    @staticmethod
    def _agent_evidence(evidence: MemoryEvidence) -> AgentEvidence:
        return AgentEvidence.model_validate(
            {
                "evidence_id": evidence.evidence_id,
                "claim": "Evidence supporting a repository memory.",
                "path": evidence.path,
                "start_line": evidence.start_line,
                "end_line": evidence.end_line,
                "observation_id": evidence.observation_id,
                "confidence": "confirmed" if evidence.verified else "candidate",
                "source_kind": evidence.source_kind,
                "resolution": evidence.resolution,
            }
        )
