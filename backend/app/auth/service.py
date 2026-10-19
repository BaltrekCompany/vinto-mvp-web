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
                             InvalidReasonError, InvalidUsernameError, LastAdministratorError, ProfileNotFoundError,
                             UserAlreadyExistsError, UserNotFoundError)
from app.auth.passwords import (HASH_ALGORITHM, MAX_PASSWORD_LENGTH, dummy_hash, hash_password, validate_password_policy,
                                verify_password)
from app.auth.grants import grant_sector, sector_codes_for_user
from app.auth.permissions import PROFILE_PERMISSIONS, USER_MANAGE, permissions_for_profiles
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
    sectors: frozenset = frozenset()  # sectores concedidos explícitamente (vinto_master.user_sector); vacío = ninguno

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


def create_user(connection, *, username, display_name, profile_code, password, request_id=None, sectors=()) -> CreatedUser:
    """Crea user + user_profile + credential en UNA transacción, con exactamente un perfil existente y activo.

    No crea perfiles. `created_by` queda NULL mientras no exista un actor autenticado.

    `sectors`: códigos de sector concedidos explícitamente en la misma transacción. Por defecto NINGUNO: un usuario sin concesiones no accede
    a ningún sector (ver app/auth/grants.py). Un sector inexistente revierte la creación completa.
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
        for sector_code in dict.fromkeys(sectors):  # sin repetidos; el orden de entrada se conserva
            grant_sector(connection, user_id=user_id, sector_code=sector_code, request_id=request_id)
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


def attempt_authentication(connection, username, password, request_id):
    """Una sola transacción: contador, bloqueo y evento quedan atómicos. Devuelve el resultado o un AuthError
    (que el llamador lanza DESPUÉS de confirmar la transacción, para no revertir los eventos). Es pública para
    que el login HTTP pueda componerla con la creación de la sesión en una transacción exterior."""
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
                                 permissions_for_profiles(profiles), row["must_change"], sector_codes_for_user(connection, user_id))


def authenticate(connection, username, password, *, request_id=None) -> AuthenticatedUser:
    """Verifica username + password. Lanza InvalidCredentialsError o AccountLockedError; no crea sesión."""
    outcome = attempt_authentication(connection, username, password, request_id)
    if isinstance(outcome, AuthError):
        raise outcome
    return outcome


# ---------------------------------------------------------------------------------------------------
# deactivate_user / reactivate_user (CLOUD-DEP-02B.2-G.12-B2)
# ---------------------------------------------------------------------------------------------------

# Perfiles que HOY otorgan user.manage, derivado de PROFILE_PERMISSIONS en vez de nombrar DATA_BALTREK
# directamente: si el modelo de permisos cambiara, la protección de "última cuenta administrativa" sigue
# siendo correcta sin tocar este módulo.
ADMIN_PROFILE_CODES = frozenset(code for code, perms in PROFILE_PERMISSIONS.items() if USER_MANAGE in perms)


@dataclass(frozen=True)
class UserStateChange:
    """Resultado de deactivate_user/reactivate_user. `active` es el estado resultante; `changed` es False
    en una llamada idempotente (el usuario ya estaba en ese estado): no se escribió nada ni se generó un
    evento de auditoría nuevo."""

    user_id: uuid.UUID
    username: str
    active: bool
    changed: bool


def _clean_reason(reason) -> str:
    cleaned = reason.strip() if isinstance(reason, str) else ""
    if not cleaned:
        raise InvalidReasonError("Debe indicarse un motivo")
    return cleaned


def _resolve_admin_actor_id(connection, actor_username) -> uuid.UUID:
    """Verifica que el actor exista, esté activo y conserve (hoy) un perfil con user.manage; devuelve su id.

    El límite real de privilegio de esta operación es el mismo que el de create_user.py (acceso directo a
    la base de datos vía --target); exigir además un actor administrativo real hace que `audit_event.actor_id`
    sea significativo y evita que una desactivación/reactivación quede atribuida a una cuenta inexistente,
    inactiva o sin privilegios administrativos.
    """
    normalized = normalize_username(actor_username)
    row = connection.execute(
        """SELECT u.id FROM vinto_master."user" u JOIN vinto_auth.credential c ON c.user_id = u.id
           WHERE lower(c.username) = %s AND u.active
             AND EXISTS (SELECT 1 FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id
                         WHERE up.user_id = u.id AND p.active AND p.code = ANY(%s))""",
        (normalized, list(ADMIN_PROFILE_CODES))).fetchone()
    if row is None:
        raise UserNotFoundError(f"El actor {normalized!r} no existe, está inactivo o no conserva un perfil con user.manage")
    return row[0]


def _set_change_context(connection, *, actor_id, request_id, reason):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _find_user_id_by_username(connection, normalized) -> uuid.UUID:
    row = connection.execute(
        'SELECT u.id FROM vinto_master."user" u JOIN vinto_auth.credential c ON c.user_id = u.id WHERE lower(c.username) = %s',
        (normalized,)).fetchone()
    if row is None:
        raise UserNotFoundError(f"El usuario {normalized!r} no existe")
    return row[0]


def deactivate_user(connection, *, username, actor_username, reason, request_id=None) -> UserStateChange:
    """Desactiva una cuenta: active=false y revocación PERMANENTE de sus sesiones vigentes, en UNA
    transacción. Idempotente (no-op si ya estaba inactiva, sin fila de auditoría nueva). Nunca toca
    credential, user_profile ni user_sector: el perfil y los sectores quedan intactos para una eventual
    reactivación.

    Protección de la última cuenta administrativa: si el usuario objetivo conserva (hoy) un perfil con
    user.manage, la transacción bloquea con `SELECT ... FOR UPDATE` el conjunto COMPLETO de cuentas
    activas con ese perfil, siempre en el mismo orden (ORDER BY u.id). Bajo READ COMMITTED, una fila que
    deja de cumplir el WHERE porque otra transacción concurrente la desactivó y confirmó mientras esta
    esperaba el bloqueo queda EXCLUIDA al reevaluarse el filtro tras desbloquear (comportamiento estándar
    de Postgres para UPDATE/SELECT FOR UPDATE bajo READ COMMITTED): dos desactivaciones concurrentes de
    administradores distintos nunca pueden dejar el conjunto en cero, porque la segunda en confirmar ve
    siempre el recuento ya actualizado por la primera. Dos intentos sobre el MISMO usuario se serializan
    por la fila de `_find_user_id_by_username`. Si dos administradores DISTINTOS se desactivan entre sí al
    mismo tiempo, el orden de bloqueo cruzado puede producir un deadlock que PostgreSQL detecta y aborta
    en una de las dos transacciones con un error claro: ninguna corrompe el estado ni deja cero
    administradores; la transacción abortada simplemente debe reintentarse.
    """
    normalized = normalize_username(username)
    clean_reason = _clean_reason(reason)
    request_id = request_id or f"deactivate_user:{uuid.uuid4()}"
    with connection.transaction():
        actor_id = _resolve_admin_actor_id(connection, actor_username)
        _set_change_context(connection, actor_id=actor_id, request_id=request_id, reason=clean_reason)
        user_id = _find_user_id_by_username(connection, normalized)
        holds_admin = connection.execute(
            """SELECT EXISTS(SELECT 1 FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id
                             WHERE up.user_id = %s AND p.active AND p.code = ANY(%s))""",
            (user_id, list(ADMIN_PROFILE_CODES))).fetchone()[0]
        if holds_admin:
            admin_ids = [row[0] for row in connection.execute(
                """SELECT u.id FROM vinto_master."user" u JOIN vinto_master.user_profile up ON up.user_id = u.id
                   JOIN vinto_master.profile p ON p.id = up.profile_id
                   WHERE u.active AND p.active AND p.code = ANY(%s) ORDER BY u.id FOR UPDATE OF u""",
                (list(ADMIN_PROFILE_CODES),)).fetchall()]
            is_active = user_id in admin_ids
            if is_active and len(admin_ids) <= 1:
                raise LastAdministratorError(
                    "No puede desactivarse la última cuenta activa con un perfil que otorga user.manage")
        else:
            is_active = connection.execute('SELECT active FROM vinto_master."user" WHERE id=%s FOR UPDATE', (user_id,)).fetchone()[0]
        if not is_active:
            return UserStateChange(user_id, normalized, False, False)
        connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (user_id,))
        connection.execute(
            "UPDATE vinto_auth.session SET revoked_at = clock_timestamp() WHERE user_id = %s AND revoked_at IS NULL", (user_id,))
    return UserStateChange(user_id, normalized, False, True)


def reactivate_user(connection, *, username, actor_username, reason, request_id=None) -> UserStateChange:
    """Reactiva una cuenta: active=true, SIN tocar credential/user_profile/user_sector y SIN restaurar
    sesiones previas (`revoked_at` nunca se modifica aquí: el usuario debe iniciar sesión de nuevo para
    recuperar acceso). Idempotente (no-op si ya estaba activa). No necesita proteger "la última cuenta
    administrativa": reactivar un perfil con user.manage solo puede AUMENTAR ese conjunto, nunca reducirlo.
    """
    normalized = normalize_username(username)
    clean_reason = _clean_reason(reason)
    request_id = request_id or f"reactivate_user:{uuid.uuid4()}"
    with connection.transaction():
        actor_id = _resolve_admin_actor_id(connection, actor_username)
        _set_change_context(connection, actor_id=actor_id, request_id=request_id, reason=clean_reason)
        row = connection.execute(
            'SELECT u.id, u.active FROM vinto_master."user" u JOIN vinto_auth.credential c ON c.user_id = u.id '
            'WHERE lower(c.username) = %s FOR UPDATE OF u', (normalized,)).fetchone()
        if row is None:
            raise UserNotFoundError(f"El usuario {normalized!r} no existe")
        user_id, active = row
        if active:
            return UserStateChange(user_id, normalized, True, False)
        connection.execute('UPDATE vinto_master."user" SET active=true WHERE id=%s', (user_id,))
    return UserStateChange(user_id, normalized, True, True)
