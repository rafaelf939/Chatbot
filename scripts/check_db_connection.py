#!/usr/bin/env python3
"""Comprueba conectividad con SQL Server sin ejecutar DDL ni escrituras."""
from __future__ import annotations

import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings  # noqa: E402


def _default_connect(connection_string: str):
    import pyodbc

    return pyodbc.connect(connection_string, autocommit=True)


def check_connection(
    settings: Settings,
    connect: Callable[[str], Any] | None = None,
) -> None:
    connection = None
    cursor = None
    try:
        connection = (connect or _default_connect)(settings.build_sqlserver_connection_string())
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
    finally:
        if cursor is not None:
            with suppress(Exception):
                cursor.close()
        if connection is not None:
            with suppress(Exception):
                connection.close()


def main() -> int:
    try:
        check_connection(Settings.from_env())
    except Exception:
        print(
            "SQL Server connection failed. Verify DB_* variables, network access, "
            "TLS settings and the installed ODBC driver.",
            file=sys.stderr,
        )
        return 1
    print("SQL Server connection OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
