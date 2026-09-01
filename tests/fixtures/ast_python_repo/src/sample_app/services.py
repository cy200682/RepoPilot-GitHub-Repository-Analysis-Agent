from .base import BaseService


class GreetingService(BaseService):
    """Build greeting messages."""

    def execute(self, value: str) -> str:
        return self.format_message(value)

    def format_message(self, value: str) -> str:
        return f"Hello, {value}"


def build_service() -> GreetingService:
    return GreetingService()
