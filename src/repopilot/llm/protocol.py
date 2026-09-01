"""LLM capability protocol."""

from typing import Protocol

from repopilot.models.analysis import AnalysisRequest, AnalysisResult


class LLMClient(Protocol):
    """Analyze a bounded repository context into a validated result."""

    def analyze_repository(self, request: AnalysisRequest) -> AnalysisResult: ...
