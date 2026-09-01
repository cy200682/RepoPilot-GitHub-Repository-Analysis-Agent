from .services import GreetingService, build_service


async def handle_request(name: str) -> str:
    service: GreetingService = build_service()
    return service.execute(name)
