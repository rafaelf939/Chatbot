import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pyodbc
import pytest

from app.core.config import Settings
from app.main import create_app
from app.models.events import ChatbotEvent
from app.repositories.events import (
    EventPersistenceError,
    InMemoryEventRepository,
    SqlServerEventRepository,
)
from app.repositories.factory import create_event_repository


class FakeCursor:
    def __init__(self, execute_error=None):
        self.execute_error = execute_error
        self.calls = []
        self.closed = False

    def execute(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        if self.execute_error:
            raise self.execute_error
        return self

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, execute_error=None):
        self.cursor_instance = FakeCursor(execute_error)
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


def sql_settings() -> Settings:
    return Settings(
        webhook_secret="test-secret",
        database_enabled=True,
        db_server="sqlserver.example.test",
        db_name="chatbot",
        db_user="chatbot_app",
        db_password="db-test-password",
    )


def event(**overrides) -> ChatbotEvent:
    values = {
        "id_evento": uuid4(),
        "fecha_evento_utc": datetime(2026, 8, 12, 10, 11, 12, 123000, tzinfo=timezone.utc),
        "bot_codigo": "bot-faq-aafp",
        "opcion_codigo": "estado-cuenta",
        "lead_id_kommo": "41265326",
        "status_id_kommo": "93511488",
        "pipeline_id_kommo": "12112928",
        "account_id_kommo": "35297208",
        "payload_original": {"leads[add][0][id]": "41265326"},
        "fecha_creacion": datetime(2026, 8, 12, 10, 11, 12, 123000, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ChatbotEvent(**values)


async def request(app, method, path, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_database_disabled_selects_in_memory_repository():
    repository = create_event_repository(Settings("test-secret", False))

    assert isinstance(repository, InMemoryEventRepository)


def test_database_enabled_selects_sql_server_repository():
    repository = create_event_repository(sql_settings())

    assert isinstance(repository, SqlServerEventRepository)


def test_connection_string_uses_encryption_and_certificate_validation_by_default():
    connection_string = sql_settings().build_sqlserver_connection_string()

    assert "Encrypt=yes" in connection_string
    assert "TrustServerCertificate=no" in connection_string
    assert "ODBC Driver 18 for SQL Server" in connection_string


def test_default_repository_connector_uses_pyodbc_without_autocommit(monkeypatch):
    connection = FakeConnection()
    calls = []

    def fake_connect(connection_string, **kwargs):
        calls.append((connection_string, kwargs))
        return connection

    monkeypatch.setattr(pyodbc, "connect", fake_connect)
    repository = SqlServerEventRepository("safe-test-connection-string")

    repository.save(event())

    assert calls == [("safe-test-connection-string", {"autocommit": False})]


def test_missing_database_configuration_does_not_expose_password():
    settings = Settings("test-secret", True, db_password="do-not-expose")

    with pytest.raises(RuntimeError) as captured:
        settings.build_sqlserver_connection_string()

    assert "do-not-expose" not in str(captured.value)


def test_insert_is_parameterized_commits_and_serializes_valid_json():
    connection = FakeConnection()
    connection_strings = []
    repository = SqlServerEventRepository(
        "safe-test-connection-string",
        connect=lambda value: connection_strings.append(value) or connection,
    )

    repository.save(event())

    assert connection_strings == ["safe-test-connection-string"]
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert connection.closed is True
    assert connection.cursor_instance.closed is True
    sql, parameters = connection.cursor_instance.calls[0]
    assert "INSERT INTO dbo.ChatbotEvento" in sql
    assert sql.count("?") == 9
    assert "41265326" not in sql
    assert parameters[4:8] == (41265326, 93511488, 12112928, 35297208)
    assert parameters[1].tzinfo is None
    assert json.loads(parameters[8]) == {"leads[add][0][id]": "41265326"}


def test_optional_kommo_ids_are_inserted_as_null():
    connection = FakeConnection()
    repository = SqlServerEventRepository("safe", connect=lambda _: connection)

    repository.save(event(
        lead_id_kommo=None,
        status_id_kommo=None,
        pipeline_id_kommo=None,
        account_id_kommo=None,
    ))

    _, parameters = connection.cursor_instance.calls[0]
    assert parameters[4:8] == (None, None, None, None)


def test_insert_failure_rolls_back_closes_resources_and_hides_details():
    connection = FakeConnection(RuntimeError("server=db;password=do-not-expose"))
    repository = SqlServerEventRepository("PWD=do-not-expose", connect=lambda _: connection)

    with pytest.raises(EventPersistenceError) as captured:
        repository.save(event())

    assert str(captured.value) == "Could not persist event"
    assert "do-not-expose" not in str(captured.value)
    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert connection.cursor_instance.closed is True
    assert connection.closed is True


def test_sql_failure_returns_controlled_503_instead_of_false_202():
    connection = FakeConnection(RuntimeError("password=db-secret"))
    repository = SqlServerEventRepository("PWD=db-secret", connect=lambda _: connection)
    app = create_app(sql_settings(), repository)

    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/events/bot-faq-aafp/estado-cuenta",
        json={"lead_id": 41265326},
        headers={"X-Webhook-Secret": "test-secret"},
    ))

    assert response.status_code == 503
    assert response.json() == {"detail": "Event persistence unavailable"}
    assert "db-secret" not in response.text
    assert connection.commit_count == 0
    assert connection.rollback_count == 1


def test_webhook_token_is_not_persisted_in_payload_json():
    connection = FakeConnection()
    repository = SqlServerEventRepository("safe", connect=lambda _: connection)
    app = create_app(sql_settings(), repository)
    form_payload = "leads%5Badd%5D%5B0%5D%5Bid%5D=41265326&account%5Bid%5D=35297208"

    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/events/bot-faq-aafp/estado-cuenta?token=test-secret",
        content=form_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ))

    assert response.status_code == 202
    _, parameters = connection.cursor_instance.calls[0]
    assert "test-secret" not in parameters[8]
    assert "token" not in json.loads(parameters[8])


def test_debug_endpoints_are_not_registered_in_sql_mode():
    app = create_app(sql_settings(), SqlServerEventRepository("safe", connect=lambda _: FakeConnection()))

    events_response = asyncio.run(request(app, "GET", "/api/v1/debug/events"))
    requests_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests"))

    assert events_response.status_code == 404
    assert requests_response.status_code == 404
