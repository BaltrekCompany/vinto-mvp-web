"""Esquemas HTTP de autenticación. Ningún esquema de salida contiene contraseñas, hashes ni tokens."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.auth.service import AuthenticatedUser


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: str
    password: str


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str
    profiles: list[str]
    permissions: list[str]
    must_change: bool


class SessionOut(BaseModel):
    user: UserOut


def user_out(principal: AuthenticatedUser) -> SessionOut:
    """Perfiles y permisos en orden estable (alfabético)."""
    return SessionOut(user=UserOut(
        id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        profiles=sorted(principal.profile_codes),
        permissions=sorted(principal.permissions),
        must_change=principal.must_change,
    ))
