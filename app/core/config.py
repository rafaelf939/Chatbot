from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    webhook_secret: str
    database_enabled: bool
    sqlserver_connection_string: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        enabled = os.getenv("DATABASE_ENABLED", "false").lower() in {"1", "true", "yes"}
        return cls(
            webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
            database_enabled=enabled,
            sqlserver_connection_string=os.getenv("SQLSERVER_CONNECTION_STRING"),
        )
