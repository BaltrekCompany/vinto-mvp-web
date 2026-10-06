"""Endpoints HTTP de autenticación: login, logout y me. La lógica vive en service.py y sessions.py."""

import uuid

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.auth.dependencies import current_user
from app.auth.errors import AccountLockedError, InvalidCredentialsError
from app.auth.schemas import LoginRequest, SessionOut, user_out
from app.auth.service import AuthenticatedUser
from app.auth.sessions import login_with_session, revoke_session
from app.config import settings
from app.database import UNAVAILABLE_BODY, DatabaseUnavailable, get_connection, logger, open_connection

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])

INVALID_CREDENTIALS = {"detail": "Credenciales inválidas"}
NO_STORE = {"Cache-Control": "no-store"}


def cookie_options() -> dict:
    """HttpOnly, SameSite=Lax, Path=/, sin Domain. Secure salvo en APP_ENV=local."""
    return {"key": settings.auth_cookie_name, "path": "/", "httponly": True, "samesite": "lax", "secure": settings.app_env != "local"}


@router.post("/login", response_model=SessionOut, responses={401: {"description": "Credenciales inválidas"}, 503: {"description": "PostgreSQL no disponible"}})
def login(body: LoginRequest, response: Response, connection=Depends(get_connection)):
    """Credenciales inexistentes, incorrectas, cuenta bloqueada o usuario inactivo dan el MISMO 401 y el mismo cuerpo
    (sin Retry-After): la respuesta no revela el estado de la cuenta."""
    try:
        principal, session = login_with_session(connection, body.username, body.password, request_id=str(uuid.uuid4()))
    except (InvalidCredentialsError, AccountLockedError):
        return JSONResponse(status_code=401, content=INVALID_CREDENTIALS, headers=NO_STORE)
    response.set_cookie(value=session.raw_token, max_age=session.max_age_seconds, **cookie_options())
    response.headers.update(NO_STORE)
    return user_out(principal)


@router.get("/me", response_model=SessionOut, responses={401: {"description": "No autenticado"}})
def me(response: Response, principal: AuthenticatedUser = Depends(current_user)):
    response.headers.update(NO_STORE)
    return user_out(principal)


@router.post("/logout", status_code=204, responses={503: {"description": "PostgreSQL no disponible; la cookie local se borra igualmente"}})
def logout(request: Request):
    """Cierre de sesión best-effort. La cookie local se borra SIEMPRE.

    - Sin cookie: 204 (no hay nada que revocar; no se consulta la base de datos).
    - Cookie presente y PostgreSQL responde: la sesión válida se revoca y se registra `logout`; 204. Una cookie
      inválida, expirada o ya revocada también da 204 (idempotente).
    - Cookie presente y PostgreSQL falla: 503 con el cuerpo seguro de "base no disponible" Y cookie borrada. El 503
      indica que la revocación en el servidor NO pudo confirmarse: no se registra `logout` y la sesión del servidor
      puede seguir viva hasta su `expires_at`. Esta conexión se abre aquí (no como dependencia) para poder borrar
      la cookie también cuando la conexión misma falla.
    """
    token = request.cookies.get(settings.auth_cookie_name)
    reply: Response = Response(status_code=204, headers=NO_STORE)
    if token:
        try:
            connection = open_connection()
            try:
                revoke_session(connection, token, request_id=str(uuid.uuid4()))
            finally:
                connection.close()
        except (DatabaseUnavailable, psycopg.Error) as error:
            if isinstance(error, psycopg.Error):  # open_connection ya registra sus propios fallos
                logger.warning("PostgreSQL: error durante logout (%s)", type(error).__name__)
            reply = JSONResponse(status_code=503, content=UNAVAILABLE_BODY, headers=NO_STORE)
    reply.delete_cookie(**cookie_options())
    return reply
