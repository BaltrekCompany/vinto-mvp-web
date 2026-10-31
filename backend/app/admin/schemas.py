"""Esquemas HTTP de la API administrativa. Ninguno incluye credenciales, hashes, tokens ni sesiones."""

from datetime import datetime
from typing import Literal
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


# ---- MF-13-01C.1: consulta de catálogo y concesiones máquina-formulario (solo lectura). Ninguno incluye credenciales, hashes, tokens ni sesiones. ----------------------------------

class CatalogFormOut(BaseModel):
    """Un formulario que la versión publicada VIGENTE vincula a una máquina. `offered` y `enabled_for_capture` son cosas distintas (ver app/admin/catalog.py)."""

    code: str
    name: str | None
    area: str | None  # production | quality, tal como está en la versión publicada
    active: bool
    effective_version: int
    published: bool  # siempre true aquí: solo se listan formularios con versión publicada vigente
    capture_policies: list[str]  # políticas en código que aceptan el formulario; vacío = ninguna
    offered: bool  # se puede conceder hoy (formulario, máquina y sector activos y vínculo en la versión vigente)
    enabled_for_capture: bool  # además hay política de captura y el sector es operativo


class CatalogMachineOut(BaseModel):
    code: str
    name: str
    active: bool
    forms: list[CatalogFormOut]


class CatalogSectorOut(BaseModel):
    code: str
    name: str
    active: bool
    operational: bool
    machines: list[CatalogMachineOut]


class CatalogOut(BaseModel):
    sectors: list[CatalogSectorOut]


class FormMachineOut(BaseModel):
    code: str
    sector_code: str
    active: bool
    offered: bool
    enabled_for_capture: bool


class FormCatalogOut(BaseModel):
    code: str
    name: str | None
    area: str | None
    active: bool
    published: bool  # tiene una versión publicada vigente
    effective_version: int | None
    capture_policies: list[str]
    enabled_for_capture: bool  # habilitado para capturar en al menos una máquina
    machines: list[FormMachineOut]  # las que vincula la versión publicada vigente (nunca una versión histórica)


class FormsCatalogOut(BaseModel):
    forms: list[FormCatalogOut]


class ProfileOut(BaseModel):
    code: str
    name: str


class UserDetailOut(BaseModel):
    id: UUID
    username: str | None
    display_name: str
    active: bool
    profiles: list[ProfileOut]
    permissions: list[str]  # derivados de los perfiles con la matriz existente; no se guardan aparte
    sectors: list[SectorGrantOut]


class PersonOut(BaseModel):
    id: UUID
    display_name: str


class GrantMachineOut(BaseModel):
    code: str
    name: str | None
    sector_code: str | None


class GrantFormOut(BaseModel):
    code: str
    name: str | None
    area: str | None


class GrantCatalogStatusOut(BaseModel):
    """Estado ACTUAL del par en el catálogo (no el de cuando se concedió)."""

    published_version: int | None
    offered: bool
    enabled_for_capture: bool
    capture_policies: list[str]


class GrantOut(BaseModel):
    id: UUID
    state: Literal["active", "revoked"]
    machine: GrantMachineOut
    form: GrantFormOut
    granted_at: datetime
    granted_by: PersonOut | None
    revoked_at: datetime | None
    revoked_by: PersonOut | None
    catalog: GrantCatalogStatusOut


class UserGrantsOut(BaseModel):
    user_id: UUID
    total: int  # filas que existen para la consulta (activas, o todas en el historial)
    truncated: bool  # `limit` recortó la respuesta
    grants: list[GrantOut]


# ---- MF-13-01C.2: conceder y revocar el acceso a un formulario de una máquina ----------------------------------------------------------------------------------------------

class GrantChangeIn(BaseModel):
    """Únicos campos admitidos. Cualquier otro (actor_id, revoked_by, request_id, permisos, perfiles, user_id…) es 422: el actor sale de la sesión, el usuario de la ruta y el
    request_id lo genera el servidor. Los códigos se validan por FORMA aquí y por EXISTENCIA contra PostgreSQL (404); no hay listas de máquinas ni de formularios en el código."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    machine_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9][A-Z0-9_]{0,63}$")
    form_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_-]{0,63}$")


class GrantChangeContextOut(BaseModel):
    """Contexto informativo del usuario. NO cambia las reglas existentes: conceder no exige que el usuario esté activo ni que tenga el sector; solo se informa."""

    user_active: bool
    sector_code: str | None  # sector de la máquina
    sector_granted: bool  # el usuario tiene concedido ese sector (user_sector)
    sector_operational: bool


class GrantChangeOut(BaseModel):
    user_id: UUID
    machine_code: str
    form_code: str
    operation: Literal["grant", "revoke"]
    changed: bool  # False = ya estaba así: no se escribió ni se auditó nada
    active: bool  # ¿queda una concesión activa de esa terna tras la operación?
    request_id: str | None  # id de auditoría del cambio efectivo (None si no hubo cambio)
    grant: GrantOut | None  # la fila más reciente de la terna (activa, o la última revocada); None si nunca existió
    catalog: GrantCatalogStatusOut  # publicado / ofrecido / habilitado para captura AHORA
    context: GrantChangeContextOut
