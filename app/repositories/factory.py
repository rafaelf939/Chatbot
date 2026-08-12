from app.core.config import Settings
from app.repositories.events import EventRepository, InMemoryEventRepository, SqlServerEventRepository


def create_event_repository(settings: Settings) -> EventRepository:
    if not settings.database_enabled:
        return InMemoryEventRepository()
    return SqlServerEventRepository(settings.build_sqlserver_connection_string())
