import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.models.events import EventAccepted
from app.services.events import EventService

router = APIRouter()


async def get_event_service(request: Request) -> EventService:
    return request.app.state.event_service


async def verify_secret(request: Request, x_webhook_secret: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.webhook_secret
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook secret is not configured")
    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, expected):
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
    if "application/json" in content_type:
        try:
            payload: Any = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    else:
        raw = await request.body()
        payload = {"raw_body": raw.decode("utf-8", errors="replace"), "content_type": content_type}
    event = service.register(bot_codigo, opcion_codigo, payload)
    return EventAccepted(id_evento=event.id_evento)
