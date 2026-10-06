from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
    )

    app_name: str = "VINTO API"
    app_env: str = "local"
    cors_origins: list[str] = ["http://127.0.0.1:8787"]
    database_url: SecretStr | None = None
    test_database_url: SecretStr | None = None
    db_connect_timeout: int = Field(default=3, ge=1, le=30)
    db_statement_timeout_ms: int = Field(default=2000, ge=1, le=30000)
    auth_max_failed_attempts: int = Field(default=5, ge=1, le=20)
    auth_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    auth_session_hours: int = Field(default=12, ge=1, le=72)
    auth_cookie_name: str = Field(default="vinto_session", pattern=r"^[A-Za-z0-9_-]{1,64}$")


settings = Settings()
