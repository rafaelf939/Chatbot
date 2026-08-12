import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models.diagnostics import DiagnosticRequest
from app.repositories.diagnostics import InMemoryDiagnosticRepository
from app.services.kommo_payloads import parse_kommo_form_payload


KOMMO_PATH_PREFIX = "/api/v1/kommo/"
MAX_BODY_BYTES = 16 * 1024
REDACTED = "REDACTED"
SENSITIVE_NAMES = {
    "api-key",
    "apikey",
    "authorization",
    "client-secret",
    "cookie",
    "credential",
    "credentials",
    "password",
    "passwd",
    "refresh-token",
    "secret",
    "set-cookie",
    "token",
    "webhook-secret",
    "x-api-key",
    "x-webhook-secret",
}


def _normalized_name(name: str) -> str:
    return name.lower().replace("_", "-")


def _is_sensitive(name: str) -> bool:
    normalized = _normalized_name(name)
    return normalized in SENSITIVE_NAMES or normalized.endswith("-token") or normalized.endswith("-password")


def _redact_secret(value: str, webhook_secret: str) -> str:
    return value.replace(webhook_secret, REDACTED) if webhook_secret else value


def _sanitize_query_string(raw_query: bytes, webhook_secret: str) -> str:
    parameters = parse_qsl(raw_query.decode("latin-1"), keep_blank_values=True)
    sanitized = [
        (key, REDACTED if _is_sensitive(key) else _redact_secret(value, webhook_secret))
        for key, value in parameters
    ]
    encoded = urlencode(sanitized, doseq=True)
    return f"?{encoded}" if encoded else ""


def _query_string_for_access_log(raw_query: bytes, webhook_secret: str) -> bytes:
    parameters = parse_qsl(raw_query.decode("latin-1"), keep_blank_values=True)
    sanitized = [
        (key, _redact_secret(value, webhook_secret))
        for key, value in parameters
        if not _is_sensitive(key)
    ]
    return urlencode(sanitized, doseq=True).encode("ascii")


def _sanitize_json(value: Any, webhook_secret: str) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(str(key)) else _sanitize_json(item, webhook_secret)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json(item, webhook_secret) for item in value]
    if isinstance(value, str):
        return _redact_secret(value, webhook_secret)
    return value


def _sanitize_text(value: str, webhook_secret: str) -> str:
    sanitized = _redact_secret(value, webhook_secret)
    for name in SENSITIVE_NAMES:
        name_pattern = re.escape(name).replace(r"\-", "[-_]")
        pattern = rf"(?i)(\b{name_pattern}\b\s*[:=]\s*)([^\r\n&;,]+)"
        sanitized = re.sub(pattern, rf"\1{REDACTED}", sanitized)
    return sanitized


def _safe_header(headers: dict[str, str], name: str, webhook_secret: str) -> str | None:
    value = headers.get(name)
    return _redact_secret(value, webhook_secret) if value is not None else None


def _safe_body(body: bytes, content_type: str | None, webhook_secret: str) -> Any | None:
    if not body:
        return None
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            return _sanitize_json(json.loads(text), webhook_secret)
        except json.JSONDecodeError:
            return _sanitize_text(text, webhook_secret)
    if media_type == "application/x-www-form-urlencoded":
        return parse_kommo_form_payload(body)
    if media_type.startswith("text/"):
        return _sanitize_text(text, webhook_secret)
    return None


class KommoDiagnosticMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        repository: InMemoryDiagnosticRepository,
        webhook_secret: str,
        max_body_bytes: int = MAX_BODY_BYTES,
    ) -> None:
        self.app = app
        self.repository = repository
        self.webhook_secret = webhook_secret
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(KOMMO_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

        received_at = datetime.now(timezone.utc)
        original_query = scope.get("query_string", b"")
        sanitized_query = _sanitize_query_string(original_query, self.webhook_secret)
        access_log_query = _query_string_for_access_log(original_query, self.webhook_secret)
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        body_size = 0
        captured_body = bytearray()
        body_too_large = False
        request_complete = False
        status_code = 500

        async def observed_receive() -> Message:
            nonlocal body_size, body_too_large, request_complete
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                body_size += len(chunk)
                if not body_too_large:
                    if body_size <= self.max_body_bytes:
                        captured_body.extend(chunk)
                    else:
                        captured_body.clear()
                        body_too_large = True
                if not message.get("more_body", False):
                    request_complete = True
            elif message["type"] == "http.disconnect":
                request_complete = True
            return message

        async def observed_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                scope["query_string"] = access_log_query
            await send(message)

        try:
            await self.app(scope, observed_receive, observed_send)
            while not request_complete:
                await observed_receive()
        finally:
            scope["query_string"] = access_log_query
            self.repository.save(DiagnosticRequest(
                fecha_hora_utc=received_at,
                metodo=scope["method"],
                path=scope["path"],
                query_string=sanitized_query,
                status_code=status_code,
                content_type=_safe_header(headers, "content-type", self.webhook_secret),
                content_length=_safe_header(headers, "content-length", self.webhook_secret),
                user_agent=_safe_header(headers, "user-agent", self.webhook_secret),
                host=_safe_header(headers, "host", self.webhook_secret),
                x_forwarded_for=_safe_header(headers, "x-forwarded-for", self.webhook_secret),
                body_size=body_size,
                body=None if body_too_large else _safe_body(bytes(captured_body), headers.get("content-type"), self.webhook_secret),
                body_truncated=body_too_large,
            ))
