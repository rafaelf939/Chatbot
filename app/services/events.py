from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.models.events import ChatbotEvent
from app.repositories.events import EventRepository


ID_KEYS = {
    "lead_id": "lead_id_kommo",
    "contact_id": "contact_id_kommo",
    "conversation_id": "conversation_id",
    "callback_data": "callback_data",
}


def _find_first(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict):
        if key in payload and payload[key] is not None:
            return str(payload[key])
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
        extracted = {target: _find_first(payload, source) for source, target in ID_KEYS.items()}
        event = ChatbotEvent(
            id_evento=uuid4(), fecha_evento_utc=now, bot_codigo=bot_codigo,
            opcion_codigo=opcion_codigo, payload_original=payload,
            fecha_creacion=now, **extracted,
        )
        self.repository.save(event)
        return event

