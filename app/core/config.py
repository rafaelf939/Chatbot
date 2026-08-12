from dataclasses import dataclass
import os


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


@dataclass(frozen=True)
class Settings:
    webhook_secret: str
    database_enabled: bool
    db_server: str | None = None
    db_port: int = 1433
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    db_driver: str = "ODBC Driver 18 for SQL Server"
    db_encrypt: bool = True
    db_trust_server_certificate: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            db_port = int(os.getenv("DB_PORT", "1433"))
        except ValueError as exc:
            raise RuntimeError("DB_PORT must be an integer") from exc
        if not 1 <= db_port <= 65535:
            raise RuntimeError("DB_PORT must be between 1 and 65535")
        return cls(
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            database_enabled=_environment_bool("DATABASE_ENABLED", False),
            db_server=os.getenv("DB_SERVER"),
            db_port=db_port,
            db_name=os.getenv("DB_NAME"),
            db_user=os.getenv("DB_USER"),
            db_password=os.getenv("DB_PASSWORD"),
            db_driver=os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server"),
            db_encrypt=_environment_bool("DB_ENCRYPT", True),
            db_trust_server_certificate=_environment_bool("DB_TRUST_SERVER_CERTIFICATE", False),
        )

    def build_sqlserver_connection_string(self) -> str:
        required = {
            "DB_SERVER": self.db_server,
            "DB_NAME": self.db_name,
            "DB_USER": self.db_user,
            "DB_PASSWORD": self.db_password,
            "DB_DRIVER": self.db_driver,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required database configuration: {', '.join(missing)}")

        server = f"tcp:{self.db_server},{self.db_port}"
        parts = (
            f"DRIVER={_odbc_value(self.db_driver)}",
            f"SERVER={_odbc_value(server)}",
            f"DATABASE={_odbc_value(self.db_name)}",
            f"UID={_odbc_value(self.db_user)}",
            f"PWD={_odbc_value(self.db_password)}",
            f"Encrypt={'yes' if self.db_encrypt else 'no'}",
            f"TrustServerCertificate={'yes' if self.db_trust_server_certificate else 'no'}",
        )
        return ";".join(parts)
