import hmac
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.models.events import EventAccepted
from app.services.events import EventService
from app.services.kommo_payloads import parse_kommo_form_payload

router = APIRouter()


async def get_event_service(request: Request) -> EventService:
    return request.app.state.event_service


def _remove_token_from_query_string(request: Request) -> None:
    query_string = request.scope.get("query_string", b"").decode("latin-1")
    query_parameters = parse_qsl(query_string, keep_blank_values=True)
    sanitized_parameters = [(key, value) for key, value in query_parameters if key != "token"]
    request.scope["query_string"] = urlencode(sanitized_parameters, doseq=True).encode("ascii")


def _matches_secret(candidate: str | None, expected: str) -> bool:
    return candidate is not None and hmac.compare_digest(candidate.encode(), expected.encode())


async def verify_secret(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    _remove_token_from_query_string(request)
    expected = request.app.state.settings.webhook_secret
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook secret is not configured")
    valid_header = _matches_secret(x_webhook_secret, expected)
    valid_token = _matches_secret(token, expected)
    if not valid_header and not valid_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(
    "/api/v1/kommo/events/{bot_codigo}/{opcion_codigo}",
    response_model=EventAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_secret)],
)
async def receive_event(
    bot_codigo: str,
    opcion_codigo: str,
    request: Request,
    service: EventService = Depends(get_event_service),
) -> EventAccepted:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            payload: Any = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    elif media_type == "application/x-www-form-urlencoded":
        payload = parse_kommo_form_payload(await request.body())
    else:
        raw = await request.body()
        payload = {"raw_body": raw.decode("utf-8", errors="replace"), "content_type": content_type}
    event = service.register(bot_codigo, opcion_codigo, payload)
    return EventAccepted(id_evento=event.id_evento)
