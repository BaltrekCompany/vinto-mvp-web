from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    # Identidades opcionales de CLOUD-01B-2 (modelo de privilegios mínimos). Si una no está configurada,
    # migrate.py / import_reference.py / ephemeral_db.py siguen usando database_url/test_database_url,
    # igual que antes de este cambio: no hay ruptura de compatibilidad para quien no las defina.
    migrator_database_url: SecretStr | None = None
    migrator_test_database_url: SecretStr | None = None
    reference_database_url: SecretStr | None = None
    reference_test_database_url: SecretStr | None = None
    test_admin_database_url: SecretStr | None = None
    # PG54-04: señal explícita de endurecimiento, NUNCA "hardened" por defecto (no se activa en este PR).
    # "legacy" (por defecto): comportamiento actual, con fallback silencioso a database_url/test_database_url
    # cuando una URL de identidad específica no está configurada — igual que antes de CLOUD-01B-2.
    # "hardened": cada operación exige su propia URL de identidad; si falta, falla de inmediato (nunca cae
    # de vuelta a database_url/test_database_url) y las operaciones de aprovisionamiento de pruebas
    # efímeras (app/ephemeral_db.py) se niegan a ejecutarse fuera de app_env en {"local","test","qa","ci"}.
    pg_privilege_mode: Literal["legacy", "hardened"] = "legacy"
    db_connect_timeout: int = Field(default=3, ge=1, le=30)
    db_statement_timeout_ms: int = Field(default=2000, ge=1, le=30000)
    auth_max_failed_attempts: int = Field(default=5, ge=1, le=20)
    auth_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    auth_session_hours: int = Field(default=12, ge=1, le=72)
    auth_cookie_name: str = Field(default="vinto_session", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # MF-13-01D.2A: modo de la autorización efectiva (app/authz) SOLO para POST /api/captures. Configuración exclusiva del servidor (variable de entorno
    # AUTHZ_CENTRAL_CAPTURES_MODE); el cliente HTTP no puede cambiarla y no existe un interruptor global: cada operación tendrá el suyo.
    #   off      comportamiento anterior, sin tocar el motor (valor inicial)
    #   observe  evalúa y registra la decisión sin cambiar datos ni respuesta
    #   enforce  exige la autorización efectiva: 403/404 si se deniega, 503 si no se puede decidir
    # Un valor no reconocido impide arrancar (falla cerrado, nunca "off" silencioso).
    authz_central_captures_mode: Literal["off", "observe", "enforce"] = "off"

    @field_validator("authz_central_captures_mode", mode="before")
    @classmethod
    def _normalize_authz_mode(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


settings = Settings()
