class BaseService:
    """Base service contract."""

    def execute(self, value: str) -> str:
        raise NotImplementedError
