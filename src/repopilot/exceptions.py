"""Domain exceptions exposed by RepoPilot services."""


class RepoPilotError(Exception):
    """Base class for expected user-facing failures."""


class ConfigurationError(RepoPilotError):
    """Required application configuration is invalid or missing."""


class InvalidRepositoryUrlError(RepoPilotError):
    """The repository URL is outside the supported public GitHub URL format."""


class RepositoryNotFoundError(RepoPilotError):
    """The requested public repository was not found or is inaccessible."""


class CloneTimeoutError(RepoPilotError):
    """Repository cloning exceeded its time budget."""


class CloneFailedError(RepoPilotError):
    """Repository cloning failed for another reason."""


class RepositoryTooLargeError(RepoPilotError):
    """A configured repository resource limit was exceeded."""


class RepositoryScanError(RepoPilotError):
    """The cloned repository could not be scanned safely."""


class RepositoryReadError(RepoPilotError):
    """A repository file could not be read within the configured safety boundary."""


class LLMRequestError(RepoPilotError):
    """The configured LLM request failed."""


class LLMResponseError(RepoPilotError):
    """The configured LLM returned an invalid analysis result."""


class ReportWriteError(RepoPilotError):
    """The rendered report could not be written."""


class AgentDecisionError(RepoPilotError):
    """The model did not return a valid Agent decision."""


class UnknownToolError(RepoPilotError):
    """An Agent requested a tool that is not registered."""


class ToolArgumentError(RepoPilotError):
    """Tool arguments did not satisfy the tool input schema."""


class ToolExecutionError(RepoPilotError):
    """A registered tool failed during execution."""


class AgentRunFailedError(RepoPilotError):
    """The Agent could not complete or produce a partial report."""
