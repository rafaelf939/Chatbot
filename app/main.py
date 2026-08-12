from fastapi import FastAPI

from app.api.debug_routes import router as debug_router
from app.api.routes import router
from app.core.config import Settings
from app.middleware.diagnostics import KommoDiagnosticMiddleware
from app.repositories.diagnostics import InMemoryDiagnosticRepository
from app.repositories.factory import create_event_repository
from app.services.events import EventService


def create_app(settings: Settings | None = None, repository=None) -> FastAPI:
    settings = settings or Settings.from_env()
    if repository is None:
        repository = create_event_repository(settings)

    application = FastAPI(title="AAFP Chatbot Analytics API", version="0.1.0")
    application.state.settings = settings
    application.state.event_service = EventService(repository)
    application.include_router(router)
    if not settings.database_enabled:
        diagnostic_repository = InMemoryDiagnosticRepository(max_requests=50)
        application.state.diagnostic_repository = diagnostic_repository
        application.add_middleware(
            KommoDiagnosticMiddleware,
            repository=diagnostic_repository,
            webhook_secret=settings.webhook_secret,
        )
        application.include_router(debug_router)
    return application


app = create_app()
