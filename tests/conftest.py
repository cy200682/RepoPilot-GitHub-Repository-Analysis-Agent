from pathlib import Path

import pytest

from repopilot.models.repository import RepositorySource


@pytest.fixture
def fixture_repository() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_python_repo"


@pytest.fixture
def ast_fixture_repository() -> Path:
    return Path(__file__).parent / "fixtures" / "ast_python_repo"


@pytest.fixture
def repository_source() -> RepositorySource:
    return RepositorySource(
        original_url="https://github.com/example/sample-service",
        normalized_url="https://github.com/example/sample-service",
        owner="example",
        name="sample-service",
        clone_url="https://github.com/example/sample-service.git",
    )
