import json
from contextlib import suppress
from datetime import timezone
from typing import Any, Callable, Protocol

from app.models.events import ChatbotEvent


INSERT_EVENT_SQL = """
INSERT INTO dbo.ChatbotEvento
    (IdEvento, FechaEventoUtc, BotCodigo, OpcionCodigo,
     LeadIdKommo, StatusIdKommo, PipelineIdKommo, AccountIdKommo,
     PayloadOriginal)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class EventPersistenceError(RuntimeError):
    """Error seguro y controlado al persistir un evento."""


class EventRepository(Protocol):
    def save(self, event: ChatbotEvent) -> None: ...


class InMemoryEventRepository:
    def __init__(self) -> None:
        self.events: list[ChatbotEvent] = []

    def save(self, event: ChatbotEvent) -> None:
        self.events.append(event)


def _default_connect(connection_string: str):
    import pyodbc

    return pyodbc.connect(connection_string, autocommit=False)


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EventPersistenceError("Event contains an invalid identifier") from exc


class SqlServerEventRepository:
    def __init__(
        self,
        connection_string: str,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self._connection_string = connection_string
        self._connect = connect or _default_connect

    def save(self, event: ChatbotEvent) -> None:
        connection = None
        cursor = None
        try:
            payload_json = json.dumps(
                event.payload_original,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            fecha_evento_utc = event.fecha_evento_utc.astimezone(timezone.utc).replace(tzinfo=None)
            parameters = (
                str(event.id_evento),
                fecha_evento_utc,
                event.bot_codigo,
                event.opcion_codigo,
                _optional_int(event.lead_id_kommo),
                _optional_int(event.status_id_kommo),
                _optional_int(event.pipeline_id_kommo),
                _optional_int(event.account_id_kommo),
                payload_json,
            )
            connection = self._connect(self._connection_string)
            cursor = connection.cursor()
            cursor.execute(INSERT_EVENT_SQL, parameters)
            connection.commit()
        except EventPersistenceError:
            if connection is not None:
                with suppress(Exception):
                    connection.rollback()
            raise
        except Exception as exc:
            if connection is not None:
                with suppress(Exception):
                    connection.rollback()
            raise EventPersistenceError("Could not persist event") from exc
        finally:
            if cursor is not None:
                with suppress(Exception):
                    cursor.close()
            if connection is not None:
                with suppress(Exception):
                    connection.close()
