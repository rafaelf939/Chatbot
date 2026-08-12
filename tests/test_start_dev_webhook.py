import os
import stat
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import start_dev_webhook


def test_load_or_create_token_creates_restrictive_file(tmp_path):
    secret_path = tmp_path / "kommo_secret"

    token = start_dev_webhook.load_or_create_token(secret_path, lambda length: f"generated-{length}")

    assert token == "generated-32"
    assert secret_path.read_text(encoding="utf-8") == token
    if os.name == "posix":
        assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600


def test_existing_token_removes_newlines_and_reuses_clean_value(tmp_path):
    secret_path = tmp_path / "kommo_secret"
    secret_path.write_text("  existing-\r\ntoken\n", encoding="utf-8")

    token = start_dev_webhook.load_or_create_token(
        secret_path,
        lambda _: pytest.fail("No debe generar otro token"),
    )

    assert token == "existing-token"
    assert secret_path.read_text(encoding="utf-8") == "existing-token"


def test_detect_codespace_name():
    environment = {"CODESPACE_NAME": "special-funicular-wrjrq64vw99vf5j4j"}

    assert start_dev_webhook.detect_codespace_name(environment) == "special-funicular-wrjrq64vw99vf5j4j"
    assert start_dev_webhook.detect_codespace_name({}) is None


def test_detect_public_url_prefers_explicit_configuration():
    environment = {
        "CODESPACE_PUBLIC_URL": "https://configured.example.test/",
        "CODESPACE_NAME": "ignored",
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev",
    }

    assert start_dev_webhook.detect_public_url(environment) == "https://configured.example.test"


def test_generates_public_url_from_codespaces_environment():
    environment = {
        "CODESPACE_NAME": "special-funicular-wrjrq64vw99vf5j4j",
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev",
    }

    assert start_dev_webhook.detect_public_url(environment) == (
        "https://special-funicular-wrjrq64vw99vf5j4j-8000.app.github.dev"
    )


def test_detect_public_url_requires_safe_configuration():
    with pytest.raises(ValueError, match="CODESPACE_PUBLIC_URL"):
        start_dev_webhook.detect_public_url({})

    with pytest.raises(ValueError, match="HTTPS"):
        start_dev_webhook.detect_public_url({"CODESPACE_PUBLIC_URL": "http://insecure.example.test"})


def test_build_public_urls_encodes_token_without_newline_sequences():
    urls = start_dev_webhook.build_public_urls("https://codespace.example.test", " token+/=\r\nvalue\n")

    assert urls["health"] == "https://codespace.example.test/health"
    assert urls["docs"] == "https://codespace.example.test/docs"
    parsed_webhook = urlsplit(urls["webhook"])
    assert parsed_webhook.path == "/api/v1/kommo/events/bot-faq-aafp/estado-cuenta"
    assert parse_qs(parsed_webhook.query) == {"token": ["token+/=value"]}
    assert "%0a" not in urls["webhook"].lower()
    assert "%0d" not in urls["webhook"].lower()


def test_configure_environment_forces_memory_mode():
    environment = {"WEBHOOK_SECRET": "old", "DATABASE_ENABLED": "true"}

    start_dev_webhook.configure_environment("new-token\n", environment)

    assert environment == {"WEBHOOK_SECRET": "new-token", "DATABASE_ENABLED": "false"}


@pytest.mark.parametrize(("status_code", "expected"), [
    (200, "ready"),
    (401, "private"),
    (302, "private"),
    (502, "bad_gateway"),
])
def test_interpret_public_health(status_code, expected):
    assert start_dev_webhook.interpret_public_health(status_code) == expected


def test_local_health_failure_has_clear_error():
    statuses = []

    def unavailable(url, timeout):
        statuses.append((url, timeout))
        return None

    with pytest.raises(RuntimeError, match="health local"):
        start_dev_webhook.ensure_local_health(fetch_status=unavailable, attempts=2)

    assert len(statuses) == 2


def test_port_occupied_is_not_stopped(monkeypatch):
    monkeypatch.setattr(start_dev_webhook, "port_is_occupied", lambda: True)
    monkeypatch.setattr(start_dev_webhook, "_is_same_application", lambda: False)

    with pytest.raises(RuntimeError, match="otro proceso"):
        start_dev_webhook.ensure_port_available()


def test_port_occupied_by_same_application_is_reported(monkeypatch):
    monkeypatch.setattr(start_dev_webhook, "port_is_occupied", lambda: True)
    monkeypatch.setattr(start_dev_webhook, "_is_same_application", lambda: True)

    with pytest.raises(RuntimeError, match="misma aplicación"):
        start_dev_webhook.ensure_port_available()


def test_absence_of_github_cli_returns_manual_instructions(monkeypatch):
    monkeypatch.setattr(start_dev_webhook.shutil, "which", lambda command: None)

    result = start_dev_webhook.ensure_codespace_port_public("example-codespace")

    assert result.gh_available is False
    assert result.public is None
    assert "manualmente" in result.message


def test_github_cli_keeps_public_forwarded_port():
    calls = []

    def runner(arguments):
        calls.append(arguments)
        return subprocess.CompletedProcess(
            arguments, 0, stdout='[{"sourcePort":8000,"visibility":"public"}]', stderr="",
        )

    result = start_dev_webhook.ensure_codespace_port_public(
        "example-codespace", gh_path="/usr/bin/gh", runner=runner,
    )

    assert result.forwarded is True
    assert result.public is True
    assert len(calls) == 1


def test_github_cli_attempts_to_make_private_port_public():
    calls = []

    def runner(arguments):
        calls.append(arguments)
        if "visibility" in arguments:
            return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            arguments, 0, stdout='[{"sourcePort":8000,"visibility":"private"}]', stderr="",
        )

    result = start_dev_webhook.ensure_codespace_port_public(
        "example-codespace", gh_path="/usr/bin/gh", runner=runner,
    )

    assert result.public is True
    assert calls[1][-3:] == ["8000:public", "-c", "example-codespace"]


def test_start_server_uses_expected_uvicorn_command(monkeypatch):
    calls = []
    sentinel = object()
    monkeypatch.setattr(
        start_dev_webhook.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or sentinel,
    )

    assert start_dev_webhook.start_server() is sentinel
    command, options = calls[0]
    assert command[1:] == [
        "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--workers", "1",
        "--no-access-log",
    ]
    assert options["cwd"] == start_dev_webhook.PROJECT_ROOT
