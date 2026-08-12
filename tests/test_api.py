import asyncio

import httpx

from app.core.config import Settings
from app.main import create_app
from app.repositories.events import InMemoryEventRepository


def app_and_repository():
    repository = InMemoryEventRepository()
    settings = Settings("test-secret", False, None)
    return create_app(settings, repository), repository


async def request(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_health():
    app, _ = app_and_repository()
    response = asyncio.run(request(app, "GET", "/health"))
    assert response.json() == {"status": "ok"}


def test_valid_webhook_is_persisted():
    app, repository = app_and_repository()
    payload = {"lead": {"lead_id": 123}, "contact_id": 456, "conversation_id": "c-1", "callback_data": "cb"}
    response = asyncio.run(request(app, "POST", "/api/v1/kommo/events/faq/estado-cuenta", json=payload, headers={"X-Webhook-Secret": "test-secret"}))
    assert response.status_code == 202
    assert len(repository.events) == 1
    event = repository.events[0]
    assert event.bot_codigo == "faq"
    assert event.lead_id_kommo == "123"
    assert event.payload_original == payload


def test_wrong_secret_is_rejected_without_persistence():
    app, repository = app_and_repository()
    response = asyncio.run(request(app, "POST", "/api/v1/kommo/events/faq/x", json={}, headers={"X-Webhook-Secret": "wrong"}))
    assert response.status_code == 401
    assert repository.events == []


def test_valid_webhook_token_is_accepted_without_being_persisted():
    app, repository = app_and_repository()
    query_strings_after_request = []

    @app.middleware("http")
    async def capture_sanitized_query_string(request, call_next):
        response = await call_next(request)
        query_strings_after_request.append(request.scope["query_string"])
        return response

    payload = {"lead_id": 789, "message": "token is not part of this payload"}
    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/events/faq/estado-cuenta?token=test-secret&source=kommo",
        json=payload,
    ))

    assert response.status_code == 202
    assert len(repository.events) == 1
    assert repository.events[0].payload_original == payload
    assert query_strings_after_request == [b"source=kommo"]


def test_wrong_webhook_token_is_rejected_without_persistence():
    app, repository = app_and_repository()

    response = asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/faq/x?token=wrong", json={},
    ))

    assert response.status_code == 401
    assert repository.events == []


def test_valid_header_is_accepted_even_when_token_is_wrong():
    app, repository = app_and_repository()

    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/events/faq/x?token=wrong",
        json={},
        headers={"X-Webhook-Secret": "test-secret"},
    ))

    assert response.status_code == 202
    assert len(repository.events) == 1


def test_missing_header_and_token_are_rejected_without_persistence():
    app, repository = app_and_repository()

    response = asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/faq/x", json={},
    ))

    assert response.status_code == 401
    assert repository.events == []


def test_unconfigured_webhook_secret_keeps_service_unavailable_response():
    repository = InMemoryEventRepository()
    app = create_app(Settings("", False, None), repository)

    response = asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/faq/x?token=anything", json={},
    ))

    assert response.status_code == 503
    assert response.json() == {"detail": "Webhook secret is not configured"}
    assert repository.events == []


def test_debug_events_returns_all_received_events():
    app, _ = app_and_repository()
    first_payload = {"lead_id": 123, "callback_data": "first"}
    second_payload = {"contact_id": 456, "callback_data": "second"}

    asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/faq/first-option",
        json=first_payload, headers={"X-Webhook-Secret": "test-secret"},
    ))
    asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/faq/second-option",
        json=second_payload, headers={"X-Webhook-Secret": "test-secret"},
    ))

    response = asyncio.run(request(app, "GET", "/api/v1/debug/events"))

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2
    assert events[0]["opcion_codigo"] == "first-option"
    assert events[0]["payload_original"] == first_payload
    assert events[1]["opcion_codigo"] == "second-option"
    assert events[1]["payload_original"] == second_payload


def test_debug_latest_returns_last_received_event():
    app, _ = app_and_repository()
    asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/faq/first-option",
        json={"callback_data": "first"}, headers={"X-Webhook-Secret": "test-secret"},
    ))
    latest_response = asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/protection/latest-option",
        json={"conversation_id": "conversation-2", "callback_data": "latest"},
        headers={"X-Webhook-Secret": "test-secret"},
    ))

    response = asyncio.run(request(app, "GET", "/api/v1/debug/events/latest"))

    assert response.status_code == 200
    event = response.json()
    assert event["id_evento"] == latest_response.json()["id_evento"]
    assert event["bot_codigo"] == "protection"
    assert event["opcion_codigo"] == "latest-option"
    assert event["conversation_id"] == "conversation-2"
    assert event["callback_data"] == "latest"


def test_debug_latest_returns_not_found_without_events():
    app, _ = app_and_repository()

    response = asyncio.run(request(app, "GET", "/api/v1/debug/events/latest"))

    assert response.status_code == 404
    assert response.json() == {"detail": "No events received"}


def test_debug_routes_are_not_registered_when_database_is_enabled():
    settings = Settings("test-secret", True, "unused-in-test")
    app = create_app(settings, InMemoryEventRepository())

    events_response = asyncio.run(request(app, "GET", "/api/v1/debug/events"))
    latest_response = asyncio.run(request(app, "GET", "/api/v1/debug/events/latest"))
    openapi_response = asyncio.run(request(app, "GET", "/openapi.json"))

    assert events_response.status_code == 404
    assert latest_response.status_code == 404
    assert "/api/v1/debug/events" not in openapi_response.json()["paths"]
    assert "/api/v1/debug/events/latest" not in openapi_response.json()["paths"]
