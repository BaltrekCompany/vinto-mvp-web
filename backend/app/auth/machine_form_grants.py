"""Concesiones por usuario, máquina y formulario (vinto_master.user_machine_form_grant): SOLO infraestructura de persistencia.

Este módulo todavía NO participa en la autorización: ningún endpoint, dependencia ni consulta de disponibilidad lo importa. Una concesión
solo acotará DÓNDE y CON QUÉ formulario puede trabajar un usuario que ya tiene el permiso de su perfil y el sector (app/auth/permissions.py,
app/auth/grants.py); no concede nada por sí sola. No hay concesión implícita: sin fila activa no hay concesión, y conceder un sector (o un
perfil) nunca crea una de estas filas, ni al revés.

Cada (usuario, máquina, formulario) es independiente: el mismo formulario en dos máquinas son dos concesiones (VINTO-P1-01 en MP1 y en MP3);
revocar una no toca la otra. El formulario se referencia por `vinto_config.form` (no por versión): publicar una versión nueva no exige
conceder de nuevo, y el catálogo oficial no se modifica.

El historial se conserva: revocar fija `revoked_at` / `revoked_by` en la fila (nunca se borra ni se edita) y volver a conceder crea una fila
NUEVA. Hay como máximo una fila activa por terna (índice único parcial); las operaciones son idempotentes y seguras ante concurrencia porque
la base de datos arbitra el conflicto, no una lectura previa. Este módulo no depende del módulo de sectores.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.errors import FormNotFoundError, FormNotLinkedToMachineError, MachineNotFoundError, UserNotFoundError


@dataclass(frozen=True)
class MachineFormGrant:
    id: uuid.UUID
    user_id: uuid.UUID
    machine_code: str
    form_code: str
    granted_at: datetime
    granted_by: uuid.UUID | None
    revoked_at: datetime | None
    revoked_by: uuid.UUID | None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


def _user_id(value) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise UserNotFoundError("El usuario no existe") from None


def _lookup(connection, user_id, machine_code, form_code):
    """(user_id, machine_id, form_id); lanza el error de dominio que corresponda. Los códigos se comparan exactos (sin mayúsculas ni espacios implícitos)."""
    user_id = _user_id(user_id)
    if connection.execute('SELECT 1 FROM vinto_master."user" WHERE id = %s', (user_id,)).fetchone() is None:
        raise UserNotFoundError("El usuario no existe")
    machine = connection.execute("SELECT id FROM vinto_master.machine WHERE code = %s", (machine_code,)).fetchone() if isinstance(machine_code, str) else None
    if machine is None:
        raise MachineNotFoundError(f"La máquina {machine_code!r} no existe")
    form = connection.execute("SELECT id FROM vinto_config.form WHERE code = %s", (form_code,)).fetchone() if isinstance(form_code, str) else None
    if form is None:
        raise FormNotFoundError(f"El formulario {form_code!r} no existe")
    return user_id, machine[0], form[0]


def _require_offered(connection, form_id, machine_id, machine_code, form_code) -> None:
    """Solo se concede un par que el catálogo OFRECE hoy, con el mismo criterio que `production_access.production_machines`: formulario activo, máquina y su
    sector activos, y la versión PUBLICADA MÁS RECIENTE del formulario vinculada a la máquina. Un vínculo que solo existe en una versión publicada anterior (p. ej. P1-05 v1
    en MP1 tras la v2 solo para MP3) NO cuenta: esa máquina ya no ofrece el formulario. Las versiones históricas no se tocan; una concesión ya guardada cuyo par deja de
    ofrecerse queda inerte y se puede revocar (revocar no exige que el par siga ofrecido)."""
    form_active, machine_active, sector_active, linked = connection.execute(
        """SELECT f.active, m.active, s.active,
                  EXISTS (SELECT 1 FROM (SELECT fv.id FROM vinto_config.form_version fv WHERE fv.form_id = f.id AND fv.status = 'published'
                                         ORDER BY fv.version_number DESC LIMIT 1) latest
                          JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id = latest.id AND fvm.machine_id = m.id)
           FROM vinto_config.form f, vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id
           WHERE f.id = %s AND m.id = %s""", (form_id, machine_id)).fetchone()
    if not form_active:
        raise FormNotLinkedToMachineError(f"El formulario {form_code!r} está inactivo")
    if not (machine_active and sector_active):
        raise FormNotLinkedToMachineError(f"La máquina {machine_code!r} o su sector está inactivo")
    if not linked:
        raise FormNotLinkedToMachineError(f"La versión publicada vigente de {form_code!r} no está vinculada a la máquina {machine_code!r}")


def _context(connection, actor_id, request_id, reason):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id or f"machine_form_grant:{uuid.uuid4()}",))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def grant_machine_form(connection, *, user_id, machine_code, form_code, actor_id, request_id=None) -> bool:
    """Concede el formulario en la máquina al usuario. Idempotente: True si creó la concesión, False si ya había una activa (nunca duplica).

    `actor_id` es obligatorio: toda concesión queda atribuida. Solo se concede un par que el catálogo ofrece HOY (ver `_require_offered`: formulario, máquina y sector
    activos y versión publicada más reciente vinculada); un par que no se ofrece se rechaza en vez de guardar una concesión que no podría usarse.
    """
    actor_id = _user_id(actor_id)
    with connection.transaction():
        user_id, machine_id, form_id = _lookup(connection, user_id, machine_code, form_code)
        _require_offered(connection, form_id, machine_id, machine_code, form_code)
        _context(connection, actor_id, request_id, "machine form grant")
        row = connection.execute(
            """INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id) VALUES (%s,%s,%s)
               ON CONFLICT (user_id, machine_id, form_id) WHERE revoked_at IS NULL DO NOTHING RETURNING id""", (user_id, machine_id, form_id)).fetchone()
    return row is not None


def revoke_machine_form(connection, *, user_id, machine_code, form_code, actor_id, request_id=None) -> bool:
    """Revoca la concesión activa. Idempotente: True solo si ESTA llamada la revocó. La fila se conserva con `revoked_at` y `revoked_by`."""
    actor_id = _user_id(actor_id)
    with connection.transaction():
        user_id, machine_id, form_id = _lookup(connection, user_id, machine_code, form_code)
        _context(connection, actor_id, request_id, "machine form revoke")
        row = connection.execute(
            """UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s
               WHERE user_id = %s AND machine_id = %s AND form_id = %s AND revoked_at IS NULL RETURNING id""", (actor_id, user_id, machine_id, form_id)).fetchone()
    return row is not None


def has_active_machine_form_grant(connection, user_id, machine_code, form_code) -> bool:
    """¿Tiene el usuario una concesión ACTIVA para ese formulario en esa máquina? Solo lectura; un código desconocido es False (no un error)."""
    try:
        user_id = _user_id(user_id)
    except UserNotFoundError:
        return False
    if not isinstance(machine_code, str) or not isinstance(form_code, str):
        return False
    return connection.execute(
        """SELECT 1 FROM vinto_master.user_machine_form_grant g JOIN vinto_master.machine m ON m.id = g.machine_id JOIN vinto_config.form f ON f.id = g.form_id
           WHERE g.user_id = %s AND m.code = %s AND f.code = %s AND g.revoked_at IS NULL""", (user_id, machine_code, form_code)).fetchone() is not None


def machine_form_grants_for_user(connection, user_id, *, include_revoked: bool = False) -> tuple[MachineFormGrant, ...]:
    """Concesiones del usuario ordenadas por máquina, formulario y fecha. Por defecto solo las activas; `include_revoked` añade el historial."""
    rows = connection.execute(
        """SELECT g.id, g.user_id, m.code, f.code, g.created_at, g.created_by, g.revoked_at, g.revoked_by
           FROM vinto_master.user_machine_form_grant g JOIN vinto_master.machine m ON m.id = g.machine_id JOIN vinto_config.form f ON f.id = g.form_id
           WHERE g.user_id = %s AND (%s OR g.revoked_at IS NULL) ORDER BY m.code, f.code, g.created_at, g.id""", (_user_id(user_id), include_revoked)).fetchall()
    return tuple(MachineFormGrant(*row) for row in rows)
