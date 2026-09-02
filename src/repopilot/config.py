"""Application settings loaded from environment variables and optional .env."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """RepoPilot runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REPOPILOT_",
        extra="ignore",
    )

    llm_api_key: str | None = Field(default=None, repr=False)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0, le=600)
    llm_max_retries: int = Field(default=1, ge=0, le=10)
    llm_temperature: float = Field(default=0.1, ge=0, le=2)
    llm_max_output_tokens: int = Field(default=6_000, gt=0, le=100_000)

    clone_timeout_seconds: int = Field(default=120, gt=0, le=3600)
    max_repo_mb: int = Field(default=100, gt=0)
    max_files: int = Field(default=10_000, gt=0)
    max_depth: int = Field(default=20, gt=0)
    max_file_bytes: int = Field(default=200_000, gt=0)
    max_tree_chars: int = Field(default=30_000, gt=0)
    context_char_budget: int = Field(default=60_000, gt=1_000)
    workspace_dir: Path | None = None

    agent_max_iterations: int = Field(default=12, gt=0, le=100)
    agent_max_tool_calls: int = Field(default=10, gt=0, le=100)
    agent_max_consecutive_errors: int = Field(default=3, gt=0, le=20)
    agent_max_identical_repeats: int = Field(default=2, gt=0, le=10)
    agent_max_unique_files: int = Field(default=20, gt=0, le=500)
    agent_max_total_read_chars: int = Field(default=100_000, gt=0)
    agent_max_search_results_total: int = Field(default=150, gt=0)
    agent_max_total_tokens: int = Field(default=80_000, gt=0, le=10_000_000)
    agent_context_char_budget: int = Field(default=40_000, gt=5_000)
    agent_recent_observations: int = Field(default=4, gt=0, le=20)
    tool_max_read_lines: int = Field(default=200, gt=0, le=2_000)
    tool_max_read_chars: int = Field(default=20_000, gt=100)
    tool_max_search_results: int = Field(default=30, gt=0, le=500)
    tool_search_timeout_seconds: float = Field(default=10, gt=0, le=120)

    ast_max_files_per_run: int = Field(default=30, gt=0, le=1_000)
    ast_max_files_per_tool: int = Field(default=10, gt=0, le=200)
    ast_max_nodes_per_file: int = Field(default=5_000, gt=0, le=100_000)
    ast_max_symbols_per_file: int = Field(default=1_000, gt=0, le=20_000)
    ast_max_relationships_per_file: int = Field(default=5_000, gt=0, le=100_000)
    ast_max_tool_results: int = Field(default=60, gt=0, le=2_000)
    repository_map_max_nodes: int = Field(default=20_000, gt=0, le=1_000_000)
    repository_map_max_edges: int = Field(default=50_000, gt=0, le=2_000_000)
    reference_max_candidate_files: int = Field(default=15, gt=0, le=500)
    ast_docstring_max_chars: int = Field(default=500, ge=0, le=10_000)

    memory_enabled: bool = True
    memory_database: Path = Path(".repopilot/memory.db")
    memory_fts_enabled: bool = True
    memory_max_results: int = Field(default=10, gt=0, le=100)
    memory_max_result_chars: int = Field(default=12_000, gt=500, le=100_000)
    memory_max_calls_per_run: int = Field(default=6, ge=0, le=50)
    memory_max_saves_per_run: int = Field(default=20, ge=0, le=100)
    conversation_recent_messages: int = Field(default=6, gt=0, le=50)
    conversation_summary_trigger_chars: int = Field(default=20_000, gt=1_000)
    conversation_summary_max_chars: int = Field(default=8_000, gt=500, le=50_000)
