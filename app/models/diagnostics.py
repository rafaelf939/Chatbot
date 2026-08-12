from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DiagnosticRequest(BaseModel):
    fecha_hora_utc: datetime
    metodo: str
    path: str
    query_string: str
    status_code: int
    content_type: str | None = None
    content_length: str | None = None
    user_agent: str | None = None
    host: str | None = None
    x_forwarded_for: str | None = None
    body_size: int
    body: Any | None = None
    body_truncated: bool = False
