"""API administrativa de concesiones por sector (/api/admin). Solo GET y POST (la configuración CORS no se amplía).

Autorización: sesión válida + permiso `user.manage` (nunca `catalog.manage`). El actor de cada cambio es SIEMPRE el usuario autenticado.
Las respuestas llevan Cache-Control: no-store.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.admin import service
from app.admin.errors import OriginNotAllowed, UnsupportedMediaType
from app.admin.schemas import SectorChangeIn, SectorChangeOut, SectorGrantOut, UserAdminOut, UserSectorsOut
from app.auth.dependencies import require_permission
from app.auth.permissions import USER_MANAGE
from app.auth.service import AuthenticatedUser
from app.config import settings
from app.database import get_connection

NO_STORE = {"Cache-Control": "no-store"}
_ERRORS = {401: {"description": "No autenticado"}, 403: {"description": "Permiso insuficiente (user.manage) u origen no autorizado"},
           404: {"description": "Usuario o sector inexistente"}, 422: {"description": "Solicitud inválida"}, 503: {"description": "PostgreSQL no disponible"}}


def trusted_origin(request: Request) -> None:
    """Protección CSRF de los cambios administrativos, independiente de CORS: el `Origin` es OBLIGATORIO y debe ser uno de los orígenes configurados.

    Se rechaza con 403 un `Origin` ausente, vacío, `null` o no autorizado, ANTES de resolver la sesión y de cualquier escritura. Los navegadores siempre envían
    `Origin` en un POST; un cliente no navegador (script) debe enviar explícitamente uno de los orígenes permitidos Y la cookie de sesión, así que no hay una vía
    sin origen. Capas adicionales: cookie HttpOnly + SameSite=Lax, cuerpo `application/json` obligatorio (obliga a un preflight CORS entre sitios) y `user.manage`.
    """
    origin = request.headers.get("origin")
    if not origin or origin not in settings.cors_origins:
        raise OriginNotAllowed()


def json_body(request: Request) -> None:
    """El cuerpo de los cambios debe declararse application/json (con o sin charset); cualquier otro tipo es 415 y no se interpreta."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise UnsupportedMediaType()


router = APIRouter(prefix="/api/admin", tags=["Administración"])


@router.get("/users", response_model=list[UserAdminOut], responses=_ERRORS)
def list_users(response: Response, limit: int = Query(default=service.DEFAULT_LIST_LIMIT, ge=1, le=service.MAX_LIST_LIMIT),
               _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_connection)):
    response.headers.update(NO_STORE)
    return service.list_users(connection, limit)


@router.get("/sectors", response_model=list[SectorGrantOut], responses=_ERRORS)
def list_sectors(response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_connection)):
    """Catálogo central de sectores (solo lectura) para administrar concesiones: nunca se inventan sectores en el cliente."""
    response.headers.update(NO_STORE)
    return service.list_sectors(connection)


@router.get("/users/{user_id}/sectors", response_model=UserSectorsOut, responses=_ERRORS)
def get_user_sectors(user_id: UUID, response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_connection)):
    response.headers.update(NO_STORE)
    return service.get_user_sectors(connection, user_id)


@router.post("/users/{user_id}/sectors/grant", response_model=SectorChangeOut, responses=_ERRORS, dependencies=[Depends(trusted_origin), Depends(json_body)])
def grant(user_id: UUID, body: SectorChangeIn, response: Response, user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_connection)):
    """Concede el sector (idempotente). Una concesión sobre un sector no operativo es inerte: no lo habilita."""
    response.headers.update(NO_STORE)
    return service.change_grant(connection, operation="grant", user_id=user_id, sector_code=body.sector_code, actor_id=user.user_id)


@router.post("/users/{user_id}/sectors/revoke", response_model=SectorChangeOut, responses=_ERRORS, dependencies=[Depends(trusted_origin), Depends(json_body)])
def revoke(user_id: UUID, body: SectorChangeIn, response: Response, user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_connection)):
    """Revoca el sector (idempotente). Efectivo en la siguiente petición autenticada del usuario, incluso con sesiones abiertas."""
    response.headers.update(NO_STORE)
    return service.change_grant(connection, operation="revoke", user_id=user_id, sector_code=body.sector_code, actor_id=user.user_id)
