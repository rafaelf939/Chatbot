from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.models.events import ChatbotEvent
from app.repositories.events import EventRepository


ID_SOURCES = {
    "lead_id_kommo": ("lead_id", "leads[add][0][id]"),
    "status_id_kommo": ("status_id", "leads[add][0][status_id]"),
    "pipeline_id_kommo": ("pipeline_id", "leads[add][0][pipeline_id]"),
    "account_id_kommo": ("account_id", "account[id]"),
    "contact_id_kommo": ("contact_id",),
    "conversation_id": ("conversation_id",),
    "callback_data": ("callback_data",),
}


def _find_first(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict):
        if key in payload and payload[key] is not None:
            value = payload[key]
            if isinstance(value, list):
                return next((str(item) for item in value if item is not None), None)
            if not isinstance(value, dict):
                return str(value)
        for value in payload.values():
            found = _find_first(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_first(value, key)
            if found is not None:
                return found
    return None


class EventService:
    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    def register(self, bot_codigo: str, opcion_codigo: str, payload: Any) -> ChatbotEvent:
        now = datetime.now(timezone.utc)
        extracted = {
            target: next(
                (value for source in sources if (value := _find_first(payload, source)) is not None),
                None,
            )
            for target, sources in ID_SOURCES.items()
        }
        event = ChatbotEvent(
            id_evento=uuid4(), fecha_evento_utc=now, bot_codigo=bot_codigo,
            opcion_codigo=opcion_codigo, payload_original=payload,
            fecha_creacion=now, **extracted,
        )
        self.repository.save(event)
        return event
