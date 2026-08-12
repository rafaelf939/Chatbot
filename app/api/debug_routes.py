from fastapi import APIRouter, HTTPException, Request, status

from app.models.diagnostics import DiagnosticRequest
from app.models.events import ChatbotEvent
from app.repositories.diagnostics import InMemoryDiagnosticRepository
from app.repositories.events import InMemoryEventRepository


router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


def _get_repository(request: Request) -> InMemoryEventRepository:
    repository = request.app.state.event_service.repository
    if not isinstance(repository, InMemoryEventRepository):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return repository


def _get_diagnostic_repository(request: Request) -> InMemoryDiagnosticRepository:
    repository = request.app.state.diagnostic_repository
    if not isinstance(repository, InMemoryDiagnosticRepository):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return repository


@router.get("/events", response_model=list[ChatbotEvent])
async def list_events(request: Request) -> list[ChatbotEvent]:
    return _get_repository(request).events


@router.get("/events/latest", response_model=ChatbotEvent)
async def latest_event(request: Request) -> ChatbotEvent:
    events = _get_repository(request).events
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No events received")
    return events[-1]


@router.get("/requests", response_model=list[DiagnosticRequest])
async def list_requests(request: Request) -> list[DiagnosticRequest]:
    return list(_get_diagnostic_repository(request).requests)


@router.get("/requests/latest", response_model=DiagnosticRequest)
async def latest_request(request: Request) -> DiagnosticRequest:
    requests = _get_diagnostic_repository(request).requests
    if not requests:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No requests received")
    return requests[-1]
