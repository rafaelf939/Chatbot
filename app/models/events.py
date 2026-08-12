from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ChatbotEvent(BaseModel):
    id_evento: UUID
    fecha_evento_utc: datetime
    bot_codigo: str
    opcion_codigo: str
    callback_data: str | None = None
    lead_id_kommo: str | None = None
    status_id_kommo: str | None = None
    pipeline_id_kommo: str | None = None
    account_id_kommo: str | None = None
    contact_id_kommo: str | None = None
    conversation_id: str | None = None
    payload_original: Any
    fecha_creacion: datetime


class EventAccepted(BaseModel):
    id_evento: UUID
    status: str = "accepted"
