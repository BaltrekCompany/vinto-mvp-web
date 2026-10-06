"""Servicio interno de autenticación: creación de usuarios y verificación de credenciales.

Todas las funciones esperan una conexión psycopg en modo autocommit y gestionan su propia transacción
(`connection.transaction()`). No hay endpoints ni sesiones todavía.

Seguridad:
- Nunca se registra ni se devuelve una contraseña, un hash o un token. Los mensajes de error son genéricos.
- `vinto_auth.credential` no tiene el trigger de auditoría genérico: ni la contraseña ni el hash llegan a
  `vinto_audit.audit_event`. Los eventos de seguridad se guardan en `vinto_auth.auth_event`.
- `authenticate` toma la fila de la credencial con SELECT ... FOR UPDATE: intentos concurrentes sobre la
  misma cuenta se serializan y no pierden incrementos de `failed_attempts`.
- Usuario inexistente, usuario inactivo y contraseña incorrecta producen el mismo `InvalidCredentialsError`
  y consumen un coste Argon2 comparable (contra un hash ficticio válido si el usuario no existe).
"""

import re
import uuid
from dataclasses import dataclass

import psycopg

from app.auth.errors import (AccountLockedError, AuthError, InvalidCredentialsError, InvalidDisplayNameError,
                             InvalidUsernameError, ProfileNotFoundError, UserAlreadyExistsError)
from app.auth.passwords import (HASH_ALGORITHM, MAX_PASSWORD_LENGTH, dummy_hash, hash_password, validate_password_policy,
                                verify_password)
from app.auth.permissions import permissions_for_profiles
from app.config import settings

USERNAME_PATTERN = re.compile(r"[a-z0-9._-]{1,64}")
MAX_DISPLAY_NAME_LENGTH = 200


@dataclass(frozen=True)
class CreatedUser:
    user_id: uuid.UUID
    username: str
    display_name: str
    profile_code: str


@dataclass(frozen=True)
class AuthenticatedUser:
    """Principal interno devuelto tras un login correcto."""

    user_id: uuid.UUID
    username: str
    display_name: str
    profile_codes: tuple
    permissions: frozenset
    must_change: bool

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def normalize_username(username) -> str:
    """strip + lowercase y valida ^[a-z0-9._-]{1,64}$. La BD garantiza además UNIQUE(lower(username))."""
    if not isinstance(username, str):
        raise InvalidUsernameError("El username debe ser texto")
    normalized = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidUsernameError("El username debe tener de 1 a 64 caracteres de [a-z0-9._-] (sin espacios)")
    return normalized


def _clean_display_name(display_name) -> str:
    cleaned = display_name.strip() if isinstance(display_name, str) else ""
    if not cleaned or len(cleaned) > MAX_DISPLAY_NAME_LENGTH:
        raise InvalidDisplayNameError(f"El nombre visible debe tener de 1 a {MAX_DISPLAY_NAME_LENGTH} caracteres")
    return cleaned


def create_user(connection, *, username, display_name, profile_code, password, request_id=None) -> CreatedUser:
    """Crea user + user_profile + credential en UNA transacción, con exactamente un perfil existente y activo.

    No crea perfiles. `created_by` queda NULL mientras no exista un actor autenticado.
    """
    normalized = normalize_username(username)
    name = _clean_display_name(display_name)
    validate_password_policy(password)
    if not isinstance(profile_code, str) or not profile_code:
        raise ProfileNotFoundError("Debe indicarse un perfil existente")
    password_hash = hash_password(password)  # CPU fuera de la transacción
    request_id = request_id or f"create_user:{uuid.uuid4()}"
    with connection.transaction():
        connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
        connection.execute("SELECT set_config('vinto.reason', %s, true)", ("user creation by create_user",))
        profile = connection.execute("SELECT id FROM vinto_master.profile WHERE code=%s AND active", (profile_code,)).fetchone()
        if profile is None:
            raise ProfileNotFoundError(f"El perfil {profile_code!r} no existe o está inactivo")
        user_id = connection.execute('INSERT INTO vinto_master."user" (display_name) VALUES (%s) RETURNING id', (name,)).fetchone()[0]
        connection.execute("INSERT INTO vinto_master.user_profile (user_id,profile_id) VALUES (%s,%s)", (user_id, profile[0]))
        try:
            connection.execute(
                """INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm,password_changed_at)
                   VALUES (%s,%s,%s,%s,clock_timestamp())""", (user_id, normalized, password_hash, HASH_ALGORITHM))
        except psycopg.errors.UniqueViolation:
            raise UserAlreadyExistsError(f"Ya existe un usuario con el username {normalized!r}") from None
    return CreatedUser(user_id, normalized, name, profile_code)


# ---------------------------------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------------------------------

def _event(connection, user_id, event, request_id):
    connection.execute("INSERT INTO vinto_auth.auth_event (user_id,event,request_id) VALUES (%s,%s,%s)", (user_id, event, request_id))


def _lock_credential(connection, key):
    cursor = connection.execute(
        """SELECT c.user_id, c.username, c.password_hash, c.failed_attempts, c.locked_until, c.must_change,
                  u.active, u.display_name,
                  coalesce(c.locked_until > clock_timestamp(), false) AS is_locked,
                  coalesce(c.locked_until <= clock_timestamp(), false) AS lock_expired
           FROM vinto_auth.credential c JOIN vinto_master."user" u ON u.id = c.user_id
           WHERE lower(c.username) = %s FOR UPDATE OF c""", (key,))
    row = cursor.fetchone()
    return None if row is None else dict(zip([column.name for column in cursor.description], row))


def _attempt(connection, username, password, request_id):
    """Una sola transacción: contador, bloqueo y evento quedan atómicos. Devuelve el resultado o un AuthError
    (que el llamador lanza DESPUÉS de confirmar la transacción, para no revertir los eventos)."""
    try:
        key = normalize_username(username)
    except InvalidUsernameError:
        key = None
    password_usable = isinstance(password, str) and len(password) <= MAX_PASSWORD_LENGTH
    candidate = password if password_usable else ""
    with connection.transaction():
        row = None if key is None else _lock_credential(connection, key)
        if row is None:
            verify_password(dummy_hash(), candidate)  # coste comparable al de un usuario real
            _event(connection, None, "login_fail", request_id)
            return InvalidCredentialsError()
        user_id = row["user_id"]
        if not row["active"]:
            verify_password(row["password_hash"], candidate)
            _event(connection, user_id, "login_fail", request_id)
            return InvalidCredentialsError()
        if row["is_locked"]:
            _event(connection, user_id, "login_fail", request_id)
            return AccountLockedError(row["locked_until"])
        # Un bloqueo vencido reinicia la cuenta: se cuentan 5 intentos nuevos.
        attempts_before = 0 if row["lock_expired"] else row["failed_attempts"]
        if not (password_usable and verify_password(row["password_hash"], password)):
            attempts = attempts_before + 1
            lock = attempts >= settings.auth_max_failed_attempts
            connection.execute(
                """UPDATE vinto_auth.credential SET failed_attempts=%s,
                          locked_until=CASE WHEN %s THEN clock_timestamp() + make_interval(mins => %s) ELSE NULL END
                   WHERE user_id=%s""", (attempts, lock, settings.auth_lockout_minutes, user_id))
            _event(connection, user_id, "login_fail", request_id)
            if lock:
                _event(connection, user_id, "lockout", request_id)
            return InvalidCredentialsError()
        if row["failed_attempts"] or row["locked_until"] is not None:
            connection.execute("UPDATE vinto_auth.credential SET failed_attempts=0,locked_until=NULL WHERE user_id=%s", (user_id,))
        _event(connection, user_id, "login_ok", request_id)
        profiles = tuple(r[0] for r in connection.execute(
            """SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id
               WHERE up.user_id = %s AND p.active ORDER BY p.code""", (user_id,)).fetchall())
        return AuthenticatedUser(user_id, row["username"], row["display_name"], profiles,
                                 permissions_for_profiles(profiles), row["must_change"])


def authenticate(connection, username, password, *, request_id=None) -> AuthenticatedUser:
    """Verifica username + password. Lanza InvalidCredentialsError o AccountLockedError; no crea sesión."""
    outcome = _attempt(connection, username, password, request_id)
    if isinstance(outcome, AuthError):
        raise outcome
    return outcome
