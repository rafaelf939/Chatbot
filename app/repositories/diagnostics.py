from collections import deque

from app.models.diagnostics import DiagnosticRequest


class InMemoryDiagnosticRepository:
    def __init__(self, max_requests: int = 50) -> None:
        self.requests: deque[DiagnosticRequest] = deque(maxlen=max_requests)

    def save(self, request: DiagnosticRequest) -> None:
        self.requests.append(request)
