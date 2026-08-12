import json
from typing import Protocol

from app.models.events import ChatbotEvent


class EventRepository(Protocol):
    def save(self, event: ChatbotEvent) -> None: ...


class InMemoryEventRepository:
    def __init__(self) -> None:
        self.events: list[ChatbotEvent] = []

    def save(self, event: ChatbotEvent) -> None:
        self.events.append(event)


class SqlServerEventRepository:
    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string

    def save(self, event: ChatbotEvent) -> None:
        import pyodbc

        sql = """
        INSERT INTO dbo.CHATBOT_EVENTO
        (id_evento, fecha_evento_utc, bot_codigo, opcion_codigo, callback_data,
         lead_id_kommo, contact_id_kommo, conversation_id, payload_original, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with pyodbc.connect(self.connection_string) as connection:
            connection.cursor().execute(
                sql,
                str(event.id_evento), event.fecha_evento_utc, event.bot_codigo,
                event.opcion_codigo, event.callback_data, event.lead_id_kommo,
                event.contact_id_kommo, event.conversation_id,
                json.dumps(event.payload_original, ensure_ascii=False, default=str),
                event.fecha_creacion,
            )
            connection.commit()

