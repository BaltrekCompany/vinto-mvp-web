"""Esquemas HTTP de la API administrativa. Ninguno incluye credenciales, hashes, tokens ni sesiones."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sectors import KNOWN_SECTOR_CODES


class SectorGrantOut(BaseModel):
    code: str
    name: str
    active: bool
    operational: bool  # concedido NO implica operativo: una concesión sobre un sector no operativo es inerte


class UserAdminOut(BaseModel):
    id: UUID
    username: str | None
    display_name: str
    active: bool
    profiles: list[str]
    sectors: list[SectorGrantOut]


class UserSectorsOut(BaseModel):
    user_id: UUID
    username: str | None
    active: bool
    sectors: list[SectorGrantOut]


class SectorChangeIn(BaseModel):
    """Único campo admitido. Cualquier otro (actor_id, sectors, user_id…) es 422: el actor sale de la sesión y el usuario, de la ruta."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    sector_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z][A-Z0-9_]{0,31}$")

    @field_validator("sector_code")
    @classmethod
    def known(cls, value: str) -> str:
        if value not in KNOWN_SECTOR_CODES:
            raise ValueError("Código de sector no reconocido")
        return value


class SectorChangeOut(BaseModel):
    user_id: UUID
    sector_code: str
    operation: str
    changed: bool  # False = ya estaba así: no se escribió ni se auditó nada
    sector: SectorGrantOut
    granted_sectors: list[SectorGrantOut]
    request_id: str | None  # id de auditoría del cambio efectivo (None si no hubo cambio)
