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
