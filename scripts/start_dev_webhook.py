#!/usr/bin/env python3
"""Prepara e inicia el webhook de Kommo para desarrollo en Codespaces."""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRET_PATH = Path("/tmp/kommo_secret")
HOST = "0.0.0.0"
LOCAL_HOST = "127.0.0.1"
PORT = 8000
BOT_CODIGO = "bot-faq-aafp"
OPCION_CODIGO = "estado-cuenta"
APP_TITLE = "AAFP Chatbot Analytics API"
LOCAL_HEALTH_ATTEMPTS = 12
PUBLIC_HEALTH_ATTEMPTS = 10
HEALTH_RETRY_DELAY_SECONDS = 1.0
_SAFE_HOST_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


@dataclass(frozen=True)
class PortForwardingResult:
    gh_available: bool
    forwarded: bool | None
    public: bool | None
    message: str


def _restrict_permissions(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Algunos sistemas de archivos no implementan permisos POSIX.
        pass


def sanitize_token(raw_token: str) -> str:
    token = raw_token.strip().replace("\r", "").replace("\n", "")
    if not token:
        raise RuntimeError("El archivo de secreto está vacío")
    return token


def _read_existing_token(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{path} debe ser un archivo regular, no un enlace simbólico")
    raw_token = path.read_text(encoding="utf-8")
    token = sanitize_token(raw_token)
    if raw_token != token:
        path.write_text(token, encoding="utf-8")
    _restrict_permissions(path)
    return token


def load_or_create_token(
    path: Path = SECRET_PATH,
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
) -> str:
    try:
        file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_existing_token(path)

    try:
        token = sanitize_token(token_factory(32))
        secret_file = os.fdopen(file_descriptor, "w", encoding="utf-8")
        file_descriptor = -1
        with secret_file:
            secret_file.write(token)
    except BaseException:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        path.unlink(missing_ok=True)
        raise
    _restrict_permissions(path)
    return token


def _normalize_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("La URL pública debe ser una URL HTTPS absoluta")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("La URL pública no puede contener credenciales, query string ni fragmento")
    if parsed.path not in {"", "/"}:
        raise ValueError("La URL pública debe ser una URL base sin path")
    return f"https://{parsed.netloc}"


def detect_codespace_name(environment: MutableMapping[str, str]) -> str | None:
    name = environment.get("CODESPACE_NAME", "").strip()
    if not name:
        return None
    if not _SAFE_HOST_COMPONENT.fullmatch(name):
        raise ValueError("CODESPACE_NAME contiene caracteres no válidos")
    return name


def detect_public_url(environment: MutableMapping[str, str], port: int = PORT) -> str:
    configured_url = environment.get("CODESPACE_PUBLIC_URL")
    if configured_url:
        return _normalize_public_url(configured_url)

    codespace_name = detect_codespace_name(environment)
    forwarding_domain = environment.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "").strip()
    if codespace_name and forwarding_domain:
        if not _SAFE_HOST_COMPONENT.fullmatch(forwarding_domain):
            raise ValueError("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN no es válido")
        return _normalize_public_url(f"https://{codespace_name}-{port}.{forwarding_domain}")

    raise ValueError(
        "No se pudo detectar la URL pública. Configure CODESPACE_PUBLIC_URL con la URL HTTPS del puerto 8000."
    )


def build_public_urls(base_url: str, token: str) -> dict[str, str]:
    token = sanitize_token(token)
    base_url = _normalize_public_url(base_url)
    webhook_path = f"/api/v1/kommo/events/{BOT_CODIGO}/{OPCION_CODIGO}"
    webhook_url = f"{base_url}{webhook_path}?{urlencode({'token': token})}"
    if "%0a" in webhook_url.lower() or "%0d" in webhook_url.lower():
        raise RuntimeError("El token contiene saltos de línea no permitidos")
    return {
        "health": f"{base_url}/health",
        "docs": f"{base_url}/docs",
        "webhook": webhook_url,
    }


def configure_environment(token: str, environment: MutableMapping[str, str]) -> None:
    environment["WEBHOOK_SECRET"] = sanitize_token(token)
    environment["DATABASE_ENABLED"] = "false"


def port_is_occupied(port: int = PORT) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((HOST, port))
    except OSError:
        return True
    finally:
        probe.close()
    return False


def _fetch_status(url: str, timeout: float) -> int | None:
    opener = build_opener(_NoRedirect)
    request = Request(url, headers={"User-Agent": "kommo-dev-webhook-health-check"})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (OSError, URLError):
        return None


def wait_for_health(
    url: str,
    attempts: int,
    timeout: float = 2.0,
    delay: float = HEALTH_RETRY_DELAY_SECONDS,
    fetch_status: Callable[[str, float], int | None] | None = None,
) -> int | None:
    fetch_status = fetch_status or _fetch_status
    last_status: int | None = None
    for attempt in range(attempts):
        last_status = fetch_status(url, timeout)
        if last_status == 200:
            return 200
        if attempt + 1 < attempts:
            time.sleep(delay)
    return last_status


def interpret_public_health(status_code: int | None) -> str:
    if status_code == 200:
        return "ready"
    if status_code in {302, 401}:
        return "private"
    if status_code == 502:
        return "bad_gateway"
    if status_code is None:
        return "unreachable"
    return "unexpected"


def ensure_local_health(
    fetch_status: Callable[[str, float], int | None] | None = None,
    attempts: int = LOCAL_HEALTH_ATTEMPTS,
) -> None:
    status_code = wait_for_health(
        f"http://{LOCAL_HOST}:{PORT}/health",
        attempts=attempts,
        fetch_status=fetch_status,
    )
    if status_code != 200:
        raise RuntimeError("FastAPI no pudo iniciar: el health local no respondió HTTP 200.")


def _run_gh(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def ensure_codespace_port_public(
    codespace_name: str,
    port: int = PORT,
    gh_path: str | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] = _run_gh,
) -> PortForwardingResult:
    gh_path = gh_path or shutil.which("gh")
    if not gh_path:
        return PortForwardingResult(
            gh_available=False,
            forwarded=None,
            public=None,
            message=f"GitHub CLI no está disponible. Marque manualmente el puerto {port} como Public en la vista Ports.",
        )

    list_command = [
        gh_path, "codespace", "ports", "-c", codespace_name,
        "--json", "sourcePort,visibility",
    ]
    try:
        listed = runner(list_command)
    except (OSError, subprocess.SubprocessError):
        return PortForwardingResult(True, None, None, "No se pudo consultar el forwarding mediante GitHub CLI.")
    if listed.returncode != 0:
        return PortForwardingResult(
            True, None, None,
            f"GitHub CLI no pudo consultar el puerto. Marque manualmente el puerto {port} como Public en la vista Ports.",
        )

    try:
        ports = json.loads(listed.stdout or "[]")
    except json.JSONDecodeError:
        return PortForwardingResult(True, None, None, "GitHub CLI devolvió un estado de puertos no reconocible.")
    current = next((item for item in ports if int(item.get("sourcePort", -1)) == port), None)
    if current and current.get("visibility") == "public":
        return PortForwardingResult(True, True, True, f"El puerto {port} ya está público.")

    visibility_command = [
        gh_path, "codespace", "ports", "visibility", f"{port}:public", "-c", codespace_name,
    ]
    try:
        changed = runner(visibility_command)
    except (OSError, subprocess.SubprocessError):
        return PortForwardingResult(True, current is not None, False, "No se pudo cambiar la visibilidad del puerto.")
    if changed.returncode != 0:
        return PortForwardingResult(
            True, current is not None, False,
            f"No fue posible hacer público el puerto {port}. Cámbielo manualmente en la vista Ports.",
        )
    return PortForwardingResult(True, True, True, f"El puerto {port} se configuró como público.")


def _is_same_application() -> bool:
    if _fetch_status(f"http://{LOCAL_HOST}:{PORT}/health", timeout=1.0) != 200:
        return False
    try:
        opener = build_opener(_NoRedirect)
        with opener.open(f"http://{LOCAL_HOST}:{PORT}/openapi.json", timeout=1.0) as response:
            document: Any = json.load(response)
        return document.get("info", {}).get("title") == APP_TITLE
    except (OSError, URLError, HTTPError, ValueError, AttributeError):
        return False


def ensure_port_available() -> None:
    if not port_is_occupied():
        return
    if _is_same_application():
        raise RuntimeError(
            "El puerto 8000 ya está ocupado por otra instancia de esta misma aplicación. "
            "Deténgala con Ctrl+C antes de volver a ejecutar el script."
        )
    raise RuntimeError(
        "El puerto 8000 está ocupado por otro proceso. No se detendrá automáticamente; libere el puerto y vuelva a intentar."
    )


def start_server() -> subprocess.Popen[bytes]:
    command = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", HOST,
        "--port", str(PORT),
        "--workers", "1",
        "--no-access-log",
    ]
    return subprocess.Popen(command, cwd=PROJECT_ROOT, env=os.environ.copy())


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)


def _print_status(label: str, ok: bool) -> None:
    print(f"{label:<26}{'OK' if ok else 'FALLO'}")


def print_ready_summary(urls: dict[str, str], codespace_detected: bool) -> None:
    print()
    _print_status("FastAPI local", True)
    _print_status("Puerto 8000", True)
    _print_status("Codespace detectado", codespace_detected)
    _print_status("Puerto público", True)
    _print_status("Health público", True)
    _print_status("Webhook listo", True)
    print(f"\nDocs:\n{urls['docs']}")
    print(f"\nHealth:\n{urls['health']}")
    print("\nADVERTENCIA: la siguiente URL contiene un secreto de desarrollo.")
    print("No la copie al README, no la suba a GitHub, no la comparta y no la use en producción.")
    print(f"\nURL para copiar en Kommo:\n{urls['webhook']}")


def print_public_health_error(status_code: int | None, forwarding: PortForwardingResult) -> None:
    result = interpret_public_health(status_code)
    print()
    _print_status("FastAPI local", True)
    _print_status("Puerto 8000", True)
    _print_status("Puerto público", forwarding.public is True and result != "private")
    _print_status("Health público", False)
    _print_status("Webhook listo", False)
    if result == "private":
        print("\nEl puerto 8000 sigue siendo privado. Kommo no podrá acceder al webhook.")
    elif result == "bad_gateway":
        print("\nEl puerto 8000 está público pero el túnel aún no puede acceder a FastAPI.")
    elif result == "unreachable":
        print("\nNo fue posible conectar con la URL pública del Codespace.")
    else:
        print(f"\nEl health público respondió HTTP {status_code}; revise el forwarding del puerto 8000.")
    if forwarding.message:
        print(forwarding.message)
    print("FastAPI local continuará ejecutándose hasta que presione Ctrl+C.")


def main() -> int:
    server_process: subprocess.Popen[bytes] | None = None
    exit_code = 0
    try:
        ensure_port_available()
        token = load_or_create_token()
        configure_environment(token, os.environ)
        public_url = detect_public_url(os.environ)
        urls = build_public_urls(public_url, token)
        codespace_name = detect_codespace_name(os.environ)

        print("Iniciando FastAPI de desarrollo en 0.0.0.0:8000...")
        server_process = start_server()
        ensure_local_health()

        if codespace_name:
            forwarding = ensure_codespace_port_public(codespace_name)
        else:
            forwarding = PortForwardingResult(
                False, None, None,
                "No se detectó GitHub Codespaces; compruebe manualmente que la URL configurada sea pública.",
            )

        public_status = wait_for_health(
            urls["health"],
            attempts=PUBLIC_HEALTH_ATTEMPTS,
            timeout=5.0,
        )
        if public_status == 200:
            print_ready_summary(urls, codespace_detected=codespace_name is not None)
        else:
            print_public_health_error(public_status, forwarding)

        server_process.wait()
    except KeyboardInterrupt:
        print("\nDeteniendo el servidor de desarrollo...")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if server_process is not None:
            stop_server(server_process)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
