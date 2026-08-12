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


def test_valid_form_webhook_extracts_real_kommo_fields():
    app, repository = app_and_repository()
    form_payload = (
        "leads%5Badd%5D%5B0%5D%5Bid%5D=41265326&"
        "leads%5Badd%5D%5B0%5D%5Bstatus_id%5D=93511488&"
        "leads%5Badd%5D%5B0%5D%5Bpipeline_id%5D=12112928&"
        "account%5Bid%5D=35297208&"
        "account%5Bsubdomain%5D=aafp-test"
    )

    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/events/bot-faq-aafp/estado-cuenta?token=test-secret",
        content=form_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ))
    latest_response = asyncio.run(request(app, "GET", "/api/v1/debug/events/latest"))

    assert response.status_code == 202
    assert len(repository.events) == 1
    event = repository.events[0]
    assert event.lead_id_kommo == "41265326"
    assert event.status_id_kommo == "93511488"
    assert event.pipeline_id_kommo == "12112928"
    assert event.account_id_kommo == "35297208"
    assert event.bot_codigo == "bot-faq-aafp"
    assert event.opcion_codigo == "estado-cuenta"
    assert event.payload_original == {
        "leads[add][0][id]": "41265326",
        "leads[add][0][status_id]": "93511488",
        "leads[add][0][pipeline_id]": "12112928",
        "account[id]": "35297208",
        "account[subdomain]": "aafp-test",
    }
    assert latest_response.status_code == 200
    assert latest_response.json()["lead_id_kommo"] == "41265326"
    assert latest_response.json()["status_id_kommo"] == "93511488"
    assert latest_response.json()["pipeline_id_kommo"] == "12112928"
    assert latest_response.json()["account_id_kommo"] == "35297208"


def test_form_webhook_accepts_missing_lead_and_discards_personal_data():
    app, repository = app_and_repository()
    form_payload = (
        "account%5Bid%5D=35297208&"
        "account%5Bsubdomain%5D=aafp-test&"
        "contacts%5Badd%5D%5B0%5D%5Bname%5D=Persona+Ejemplo&"
        "contacts%5Badd%5D%5B0%5D%5Bphone%5D=%2B51999999999&"
        "contacts%5Badd%5D%5B0%5D%5Bemail%5D=persona%40example.com"
    )

    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/events/bot-faq-aafp/estado-cuenta?token=test-secret",
        content=form_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
    ))
    diagnostic_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests/latest"))

    assert response.status_code == 202
    event = repository.events[0]
    assert event.lead_id_kommo is None
    assert event.status_id_kommo is None
    assert event.pipeline_id_kommo is None
    assert event.account_id_kommo == "35297208"
    assert event.payload_original == {
        "account[id]": "35297208",
        "account[subdomain]": "aafp-test",
    }
    assert diagnostic_response.json()["body"] == event.payload_original
    assert "Persona Ejemplo" not in diagnostic_response.text
    assert "+51999999999" not in diagnostic_response.text
    assert "persona@example.com" not in diagnostic_response.text


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
    requests_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests"))
    latest_request_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests/latest"))
    openapi_response = asyncio.run(request(app, "GET", "/openapi.json"))

    assert events_response.status_code == 404
    assert latest_response.status_code == 404
    assert requests_response.status_code == 404
    assert latest_request_response.status_code == 404
    assert "/api/v1/debug/events" not in openapi_response.json()["paths"]
    assert "/api/v1/debug/events/latest" not in openapi_response.json()["paths"]
    assert "/api/v1/debug/requests" not in openapi_response.json()["paths"]
    assert "/api/v1/debug/requests/latest" not in openapi_response.json()["paths"]
    assert not hasattr(app.state, "diagnostic_repository")


def test_diagnostics_register_valid_post():
    app, _ = app_and_repository()
    payload = {"lead_id": 123, "message": "diagnostic test"}

    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/events/faq/estado-cuenta?token=test-secret",
        json=payload,
        headers={"User-Agent": "kommo-test-agent"},
    ))
    diagnostic_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests/latest"))

    assert response.status_code == 202
    assert diagnostic_response.status_code == 200
    diagnostic = diagnostic_response.json()
    assert diagnostic["metodo"] == "POST"
    assert diagnostic["path"] == "/api/v1/kommo/events/faq/estado-cuenta"
    assert diagnostic["query_string"] == "?token=REDACTED"
    assert diagnostic["status_code"] == 202
    assert diagnostic["content_type"] == "application/json"
    assert diagnostic["content_length"] is not None
    assert diagnostic["user_agent"] == "kommo-test-agent"
    assert diagnostic["host"] == "test"
    assert diagnostic["body_size"] > 0
    assert diagnostic["body"] == payload
    assert diagnostic["body_truncated"] is False


def test_diagnostics_register_get_that_returns_method_not_allowed():
    app, _ = app_and_repository()

    response = asyncio.run(request(
        app, "GET", "/api/v1/kommo/events/faq/estado-cuenta",
    ))
    diagnostic_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests/latest"))

    assert response.status_code == 405
    assert diagnostic_response.json()["metodo"] == "GET"
    assert diagnostic_response.json()["status_code"] == 405


def test_diagnostics_register_wrong_token_and_redact_it():
    app, _ = app_and_repository()

    response = asyncio.run(request(
        app, "POST", "/api/v1/kommo/events/faq/x?token=wrong-token&source=kommo", json={},
    ))
    diagnostic_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests/latest"))

    assert response.status_code == 401
    diagnostic = diagnostic_response.json()
    assert diagnostic["status_code"] == 401
    assert diagnostic["query_string"] == "?token=REDACTED&source=kommo"
    assert "wrong-token" not in diagnostic_response.text


def test_diagnostics_do_not_expose_sensitive_headers_or_body_fields():
    app, _ = app_and_repository()
    sensitive_values = ["bearer-private", "cookie-private", "header-private", "body-private", "password-private"]

    response = asyncio.run(request(
        app,
        "POST",
        "/api/v1/kommo/not-an-endpoint",
        json={"token": "body-private", "password": "password-private", "safe": "visible"},
        headers={
            "Authorization": "Bearer bearer-private",
            "Cookie": "session=cookie-private",
            "X-Webhook-Secret": "header-private",
            "X-Forwarded-For": "test-secret",
        },
    ))
    diagnostic_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests/latest"))

    assert response.status_code == 404
    diagnostic = diagnostic_response.json()
    assert diagnostic["body"] == {"token": "REDACTED", "password": "REDACTED", "safe": "visible"}
    assert diagnostic["x_forwarded_for"] == "REDACTED"
    assert "authorization" not in diagnostic
    assert "cookie" not in diagnostic
    assert "x_webhook_secret" not in diagnostic
    for value in sensitive_values:
        assert value not in diagnostic_response.text


def test_diagnostics_keep_only_last_50_requests():
    app, _ = app_and_repository()

    async def send_requests():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for index in range(55):
                response = await client.get(f"/api/v1/kommo/unknown/{index}")
                assert response.status_code == 404

    asyncio.run(send_requests())
    diagnostic_response = asyncio.run(request(app, "GET", "/api/v1/debug/requests"))

    assert diagnostic_response.status_code == 200
    diagnostics = diagnostic_response.json()
    assert len(diagnostics) == 50
    assert diagnostics[0]["path"] == "/api/v1/kommo/unknown/5"
    assert diagnostics[-1]["path"] == "/api/v1/kommo/unknown/54"
