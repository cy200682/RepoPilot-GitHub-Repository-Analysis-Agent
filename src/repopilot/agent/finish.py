"""Minimum quality and Observation-grounded Evidence checks."""

from dataclasses import dataclass

from repopilot.agent.actions import AgentAnalysisResult, AgentEvidence, AgentFinding
from repopilot.agent.state import AgentState, Observation


@dataclass(slots=True)
class FinishValidation:
    accepted: bool
    analysis: AgentAnalysisResult
    reasons: list[str]


class FinishGate:
    _SOURCE_TOOLS = {
        "read": {"read_file"},
        "search": {"search_code", "find_symbol"},
        "ast_symbol": {"find_symbol", "inspect_python"},
        "ast_import": {"inspect_python", "get_relationships"},
        "ast_inheritance": {"inspect_python", "get_relationships"},
        "ast_call": {"inspect_python", "get_relationships"},
        "ast_reference": {"inspect_python", "find_references", "get_relationships"},
        "map_query": {"get_relationships"},
    }
    _AST_RECORD_KEYS = {
        "ast_symbol": ("symbols", "candidates"),
        "ast_import": ("imports", "relationships"),
        "ast_inheritance": ("inheritances", "relationships"),
        "ast_call": ("calls", "relationships"),
        "ast_reference": ("references", "relationships"),
        "map_query": ("relationships",),
    }
    _RELATIONSHIP_TYPES = {
        "ast_import": "imports",
        "ast_inheritance": "inherits",
        "ast_call": "calls",
        "ast_reference": "references",
    }

    def validate(self, analysis: AgentAnalysisResult, state: AgentState) -> FinishValidation:
        validated = analysis.model_copy(deep=True)
        observations = {item.id: item for item in state.observations}
        for evidence in validated.evidence:
            observation = observations.get(evidence.observation_id)
            evidence.verified = bool(
                observation
                and observation.status == "success"
                and observation.tool_name in self._SOURCE_TOOLS[evidence.source_kind]
                and any(
                    location.path == evidence.path
                    and location.start_line <= evidence.start_line
                    and location.end_line >= evidence.end_line
                    for location in observation.evidence_locations
                )
                and self._resolution_matches(evidence, observation)
            )

        reasons: list[str] = []
        useful = [
            item
            for item in state.observations
            if item.status == "success" and item.evidence_locations
        ]
        if not useful:
            reasons.append("Use at least one read or search tool before finishing.")
        if not any(item.verified for item in validated.evidence):
            reasons.append(
                "At least one final Evidence item must reference an observed line range."
            )
        invalid_evidence = [item for item in validated.evidence if not item.verified]
        incompatible_sources = []
        incompatible_resolutions = []
        for evidence in invalid_evidence:
            observation = observations.get(evidence.observation_id)
            if (
                observation
                and observation.status == "success"
                and observation.tool_name not in self._SOURCE_TOOLS[evidence.source_kind]
            ):
                incompatible_sources.append(
                    f"{evidence.evidence_id}:{evidence.source_kind}<-{observation.tool_name}"
                )
            elif (
                observation
                and observation.status == "success"
                and observation.tool_name in self._SOURCE_TOOLS[evidence.source_kind]
                and evidence.source_kind in self._AST_RECORD_KEYS
                and not self._resolution_matches(evidence, observation)
            ):
                incompatible_resolutions.append(f"{evidence.evidence_id}:{evidence.resolution}")
        if incompatible_sources:
            reasons.append(
                "Evidence source_kind must match its producing tool. Invalid sources: "
                + ", ".join(incompatible_sources[:5])
                + "."
            )
        if incompatible_resolutions:
            reasons.append(
                "AST Evidence resolution must match the returned record at the exact span. "
                "Invalid resolutions: " + ", ".join(incompatible_resolutions[:5]) + "."
            )
        if invalid_evidence:
            invalid_refs = ", ".join(
                f"{item.observation_id}:{item.path}:{item.start_line}-{item.end_line}"
                for item in invalid_evidence[:5]
            )
            reasons.append(
                "Every submitted Evidence item must reference a matching observed line range. "
                f"Invalid Evidence: {invalid_refs}."
            )
        evidence_by_id = {item.evidence_id: item for item in validated.evidence}
        if len(evidence_by_id) != len(validated.evidence):
            reasons.append("Every Evidence item must have a unique evidence_id.")

        findings = self._critical_findings(validated)
        if not findings:
            reasons.append(
                "Add at least one evidence-grounded Finding for entrypoints, core modules, "
                "execution flows, or module relationships."
            )
        for section, finding in findings:
            if not finding.evidence_ids:
                reasons.append(f"Finding in {section} has no evidence_ids: {finding.claim[:120]}")
                continue
            invalid_ids = [
                evidence_id
                for evidence_id in finding.evidence_ids
                if evidence_id not in evidence_by_id or not evidence_by_id[evidence_id].verified
            ]
            if invalid_ids:
                reasons.append(
                    f"Finding in {section} references missing or unverified Evidence "
                    f"{invalid_ids}: {finding.claim[:120]}"
                )
                continue
            if section == "execution_flows" and finding.confidence == "confirmed":
                reasons.append(
                    "Execution-flow Findings derived from repository inspection must be "
                    f"inferred, not confirmed: {finding.claim[:120]}"
                )
            if finding.confidence == "confirmed":
                weak_ids = [
                    evidence_id
                    for evidence_id in finding.evidence_ids
                    if evidence_by_id[evidence_id].resolution
                    in {"candidate", "ambiguous", "unresolved"}
                ]
                if weak_ids:
                    reasons.append(
                        f"Confirmed Finding in {section} relies on unresolved Evidence "
                        f"{weak_ids}: {finding.claim[:120]}"
                    )
        if not validated.limitations:
            reasons.append("The final analysis must state its limitations.")
        return FinishValidation(accepted=not reasons, analysis=validated, reasons=reasons)

    @classmethod
    def _resolution_matches(
        cls,
        evidence: AgentEvidence,
        observation: Observation,
    ) -> bool:
        keys = cls._AST_RECORD_KEYS.get(evidence.source_kind)
        if not keys:
            return True
        observed: set[str] = set()
        expected_relationship = cls._RELATIONSHIP_TYPES.get(evidence.source_kind)
        for key in keys:
            records = observation.data.get(key, [])
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                if (
                    expected_relationship
                    and key == "relationships"
                    and record.get("relationship_type") != expected_relationship
                ):
                    continue
                if not cls._record_contains_evidence(record, evidence):
                    continue
                resolution = record.get("resolution")
                if evidence.source_kind == "ast_symbol":
                    resolution = (
                        "candidate" if record.get("source") == "text_fallback" else "resolved"
                    )
                if resolution == "exact":
                    resolution = "resolved"
                if isinstance(resolution, str):
                    observed.add(resolution)
        return evidence.resolution in observed

    @staticmethod
    def _record_contains_evidence(record: dict[object, object], evidence: AgentEvidence) -> bool:
        span = record.get("span")
        if isinstance(span, dict):
            return bool(
                span.get("path") == evidence.path
                and isinstance(span.get("start_line"), int)
                and isinstance(span.get("end_line"), int)
                and int(span["start_line"]) <= evidence.start_line
                and int(span["end_line"]) >= evidence.end_line
            )
        line = record.get("line")
        return bool(
            record.get("path") == evidence.path
            and isinstance(line, int)
            and line == evidence.start_line == evidence.end_line
        )

    @staticmethod
    def _critical_findings(analysis: AgentAnalysisResult) -> list[tuple[str, AgentFinding]]:
        findings: list[tuple[str, AgentFinding]] = []
        for section in (
            "entrypoints",
            "core_modules",
            "execution_flows",
            "module_relationships",
        ):
            findings.extend((section, finding) for finding in getattr(analysis, section))
        return findings
