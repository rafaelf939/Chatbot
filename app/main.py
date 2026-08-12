from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings
from app.repositories.events import InMemoryEventRepository, SqlServerEventRepository
from app.services.events import EventService


def create_app(settings: Settings | None = None, repository=None) -> FastAPI:
    settings = settings or Settings.from_env()
    if repository is None:
        if settings.database_enabled:
            if not settings.sqlserver_connection_string:
                raise RuntimeError("SQLSERVER_CONNECTION_STRING is required when DATABASE_ENABLED=true")
            repository = SqlServerEventRepository(settings.sqlserver_connection_string)
        else:
            repository = InMemoryEventRepository()

    application = FastAPI(title="AAFP Chatbot Analytics API", version="0.1.0")
    application.state.settings = settings
    application.state.event_service = EventService(repository)
    application.include_router(router)
    return application


app = create_app()

