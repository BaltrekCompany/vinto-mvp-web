"""Dependencias FastAPI para proteger endpoints futuros (OT, asignaciones, capturas).

    @router.post("/algo")
    def algo(user: AuthenticatedUser = Depends(require_permission("work_order.manage"))): ...

Sin sesión válida -> 401 "No autenticado"; sesión válida sin el permiso -> 403.
"""

from fastapi import Depends, HTTPException, Request

from app.auth.errors import InvalidSessionError
from app.auth.permissions import ALL_PERMISSIONS
from app.auth.service import AuthenticatedUser
from app.auth.sessions import resolve_session
from app.config import settings
from app.database import get_connection

NOT_AUTHENTICATED = "No autenticado"
FORBIDDEN = "Permiso insuficiente"


def current_user(request: Request, connection=Depends(get_connection)) -> AuthenticatedUser:
    """Usuario de la cookie de sesión. Cookie ausente, inválida, expirada o revocada: el mismo 401."""
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED)
    try:
        return resolve_session(connection, token)
    except InvalidSessionError:
        raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED) from None


def require_permission(permission: str):
    """Fábrica de dependencias. Un permiso con nombre inexistente falla al definir la ruta, no en producción."""
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Permiso desconocido: {permission!r}")

    def dependency(user: AuthenticatedUser = Depends(current_user)) -> AuthenticatedUser:
        if not user.can(permission):
            raise HTTPException(status_code=403, detail=FORBIDDEN)
        return user

    return dependency
