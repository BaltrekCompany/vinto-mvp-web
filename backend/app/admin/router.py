"""API administrativa de concesiones por sector (/api/admin). Solo GET y POST (la configuración CORS no se amplía).

Autorización: sesión válida + permiso `user.manage` (nunca `catalog.manage`). El actor de cada cambio es SIEMPRE el usuario autenticado.
Las respuestas llevan Cache-Control: no-store.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.admin import catalog, grants_read, grants_write, service
from app.admin.errors import OriginNotAllowed, UnsupportedMediaType
from app.admin.schemas import (CatalogOut, FormsCatalogOut, GrantChangeIn, GrantChangeOut, SectorChangeIn, SectorChangeOut, SectorGrantOut, UserAdminOut,
                               UserDetailOut, UserGrantsOut, UserSectorsOut)
from app.auth.dependencies import require_permission
from app.auth.permissions import USER_MANAGE
from app.auth.service import AuthenticatedUser
from app.config import settings
from app.database import get_identity_connection

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
               _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    response.headers.update(NO_STORE)
    return service.list_users(connection, limit)


@router.get("/sectors", response_model=list[SectorGrantOut], responses=_ERRORS)
def list_sectors(response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Catálogo central de sectores (solo lectura) para administrar concesiones: nunca se inventan sectores en el cliente."""
    response.headers.update(NO_STORE)
    return service.list_sectors(connection)


@router.get("/users/{user_id}/sectors", response_model=UserSectorsOut, responses=_ERRORS)
def get_user_sectors(user_id: UUID, response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    response.headers.update(NO_STORE)
    return service.get_user_sectors(connection, user_id)


@router.post("/users/{user_id}/sectors/grant", response_model=SectorChangeOut, responses=_ERRORS, dependencies=[Depends(trusted_origin), Depends(json_body)])
def grant(user_id: UUID, body: SectorChangeIn, response: Response, user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Concede el sector (idempotente). Una concesión sobre un sector no operativo es inerte: no lo habilita."""
    response.headers.update(NO_STORE)
    return service.change_grant(connection, operation="grant", user_id=user_id, sector_code=body.sector_code, actor_id=user.user_id)


@router.post("/users/{user_id}/sectors/revoke", response_model=SectorChangeOut, responses=_ERRORS, dependencies=[Depends(trusted_origin), Depends(json_body)])
def revoke(user_id: UUID, body: SectorChangeIn, response: Response, user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Revoca el sector (idempotente). Efectivo en la siguiente petición autenticada del usuario, incluso con sesiones abiertas."""
    response.headers.update(NO_STORE)
    return service.change_grant(connection, operation="revoke", user_id=user_id, sector_code=body.sector_code, actor_id=user.user_id)


# ---- MF-13-01C.1: consulta (solo GET) del catálogo y de las concesiones máquina-formulario. Mismo permiso user.manage y mismas sesiones; sin escrituras. ------------------------------

@router.get("/catalog", response_model=CatalogOut, responses=_ERRORS)
def get_catalog(response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Sectores, máquinas y formularios que la versión publicada vigente vincula a cada máquina, con áreas, versión efectiva y estado (publicado, ofrecido, habilitado para captura)."""
    response.headers.update(NO_STORE)
    return catalog.catalog_tree(connection)


@router.get("/catalog/forms", response_model=FormsCatalogOut, responses=_ERRORS)
def get_catalog_forms(response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Formularios con su versión publicada vigente y las máquinas que esa versión vincula; incluye los que no tienen versión publicada."""
    response.headers.update(NO_STORE)
    return catalog.catalog_forms(connection)


@router.get("/users/{user_id}", response_model=UserDetailOut, responses=_ERRORS)
def get_user(user_id: UUID, response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Perfil(es), permisos derivados y sectores concedidos de un usuario."""
    response.headers.update(NO_STORE)
    return grants_read.user_detail(connection, user_id)


@router.get("/users/{user_id}/grants", response_model=UserGrantsOut, responses=_ERRORS)
def get_user_grants(user_id: UUID, response: Response, _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Concesiones ACTIVAS del usuario por máquina y formulario (MP1 y MP3 son filas distintas), con el estado actual de cada par en el catálogo."""
    response.headers.update(NO_STORE)
    return grants_read.user_grants(connection, user_id)


@router.get("/users/{user_id}/grants/history", response_model=UserGrantsOut, responses=_ERRORS)
def get_user_grants_history(user_id: UUID, response: Response, limit: int = Query(default=grants_read.DEFAULT_HISTORY_LIMIT, ge=1, le=grants_read.MAX_HISTORY_LIMIT),
                            _user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Historial completo (activas y revocadas), de la más reciente a la más antigua, con quién concedió y quién revocó."""
    response.headers.update(NO_STORE)
    return grants_read.user_grants(connection, user_id, include_revoked=True, limit=limit)


# ---- MF-13-01C.2: conceder y revocar el acceso a un formulario de una máquina. Mismas defensas que los POST de sector (Origin, application/json, user.manage, no-store). ------------------
# El actor es la sesión autenticada y el request_id lo genera el servidor: el cuerpo solo admite machine_code y form_code. NO activa ninguna autorización efectiva.
_WRITE_ERRORS = {**_ERRORS, 404: {"description": "Usuario, máquina o formulario inexistente"}, 409: {"description": "El par máquina-formulario no se ofrece hoy (solo al conceder)"},
                 415: {"description": "El cuerpo debe ser application/json"}}


@router.post("/users/{user_id}/grants/grant", response_model=GrantChangeOut, responses=_WRITE_ERRORS, dependencies=[Depends(trusted_origin), Depends(json_body)])
def grant_form(user_id: UUID, body: GrantChangeIn, response: Response, user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Concede (idempotente) el acceso del usuario a UN formulario de UNA máquina. No toca otras máquinas ni otros formularios ni concede perfiles o sectores."""
    response.headers.update(NO_STORE)
    return grants_write.change_machine_form_grant(connection, operation="grant", user_id=user_id, machine_code=body.machine_code, form_code=body.form_code, actor_id=user.user_id)


@router.post("/users/{user_id}/grants/revoke", response_model=GrantChangeOut, responses=_WRITE_ERRORS, dependencies=[Depends(trusted_origin), Depends(json_body)])
def revoke_form(user_id: UUID, body: GrantChangeIn, response: Response, user: AuthenticatedUser = Depends(require_permission(USER_MANAGE)), connection=Depends(get_identity_connection)):
    """Revoca (idempotente) esa concesión conservando el historial. Se permite también sobre un par que ya no se ofrece, para poder retirar una concesión inerte."""
    response.headers.update(NO_STORE)
    return grants_write.change_machine_form_grant(connection, operation="revoke", user_id=user_id, machine_code=body.machine_code, form_code=body.form_code, actor_id=user.user_id)
