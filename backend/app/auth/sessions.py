"""Sesiones de servidor con token opaco. Sin HTTP: el router solo traduce a cookies y códigos de estado.

Diseño:
- El cliente recibe únicamente un token aleatorio (`secrets.token_urlsafe(32)`, 256 bits). PostgreSQL guarda
  solo su SHA-256 en hexadecimal minúscula; el token original nunca se almacena, registra ni se muestra
  (`NewSession.raw_token` está excluido del repr).
- La expiración es FIJA (`AUTH_SESSION_HOURS`): resolver una sesión actualiza `last_seen_at`, nunca `expires_at`.
- Varias sesiones por usuario están permitidas; hacer login no revoca las anteriores.
- Token inexistente, expirado, revocado o de un usuario inactivo producen el mismo `InvalidSessionError`.
- Los datos de zona horaria/tiempo usan el reloj de PostgreSQL (`clock_timestamp()`), no el del proceso.
"""

import hashlib
import secrets
from dataclasses import dataclass, field

from app.auth.errors import AuthError, InvalidSessionError
from app.auth.permissions import permissions_for_profiles
from app.auth.service import AuthenticatedUser, attempt_authentication
from app.config import settings

TOKEN_BYTES = 32  # 256 bits de entropía
MAX_TOKEN_LENGTH = 200  # un token legítimo mide 43 caracteres; descarta basura antes de consultar


@dataclass(frozen=True)
class NewSession:
    raw_token: str = field(repr=False)  # solo para la cookie; nunca persistirlo ni registrarlo
    session_id: object
    expires_at: object
    max_age_seconds: int


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """SHA-256 en hexadecimal minúscula (64 caracteres), la única forma en que el token toca la base de datos."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(connection, user_id) -> NewSession:
    """Inserta una sesión nueva: created_at/last_seen_at ahora, expires_at = ahora + TTL, revoked_at NULL."""
    raw_token = generate_token()
    hours = settings.auth_session_hours
    session_id, expires_at = connection.execute(
        """INSERT INTO vinto_auth.session (user_id,token_hash,expires_at)
           VALUES (%s,%s,clock_timestamp() + make_interval(hours => %s)) RETURNING id,expires_at""",
        (user_id, hash_token(raw_token), hours)).fetchone()
    return NewSession(raw_token, session_id, expires_at, hours * 3600)


def resolve_session(connection, raw_token) -> AuthenticatedUser:
    """Devuelve el usuario de una sesión válida (no revocada, no expirada, usuario activo) y actualiza last_seen_at."""
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > MAX_TOKEN_LENGTH:
        raise InvalidSessionError()
    with connection.transaction():
        row = connection.execute(
            """UPDATE vinto_auth.session s SET last_seen_at = clock_timestamp()
               FROM vinto_master."user" u, vinto_auth.credential c
               WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > clock_timestamp()
                 AND u.id = s.user_id AND u.active AND c.user_id = s.user_id
               RETURNING s.user_id, c.username, u.display_name, c.must_change""", (hash_token(raw_token),)).fetchone()
        if row is None:
            raise InvalidSessionError()
        user_id, username, display_name, must_change = row
        profiles = tuple(r[0] for r in connection.execute(
            """SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id
               WHERE up.user_id = %s AND p.active ORDER BY p.code""", (user_id,)).fetchall())
    return AuthenticatedUser(user_id, username, display_name, profiles, permissions_for_profiles(profiles), must_change)


def revoke_session(connection, raw_token, *, request_id=None) -> bool:
    """Revoca una sesión válida una sola vez y registra `logout`. Idempotente: sin sesión válida no hace nada.

    Devuelve True solo si esta llamada revocó la sesión. token_hash no cambia.
    """
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > MAX_TOKEN_LENGTH:
        return False
    with connection.transaction():
        row = connection.execute(
            """UPDATE vinto_auth.session SET revoked_at = clock_timestamp()
               WHERE token_hash = %s AND revoked_at IS NULL AND expires_at > clock_timestamp() RETURNING user_id""",
            (hash_token(raw_token),)).fetchone()
        if row is None:
            return False
        connection.execute("INSERT INTO vinto_auth.auth_event (user_id,event,request_id) VALUES (%s,'logout',%s)", (row[0], request_id))
    return True


def login_with_session(connection, username, password, *, request_id=None):
    """Autentica y crea la sesión en UNA transacción exterior.

    - Fallo de credenciales: los eventos y contadores de `attempt_authentication` se confirman y después se lanza
      el error (igual que `authenticate`).
    - Éxito: `login_ok`, el reinicio del contador y la sesión se confirman juntos. Si crear la sesión falla, se
      revierte todo (incluido `login_ok`) y el error de base de datos sube al llamador: no hay login ni cookie.
    """
    session = None
    with connection.transaction():
        outcome = attempt_authentication(connection, username, password, request_id)
        if not isinstance(outcome, AuthError):
            session = create_session(connection, outcome.user_id)
    if isinstance(outcome, AuthError):
        raise outcome
    return outcome, session
