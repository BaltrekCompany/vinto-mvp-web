"""Concesiones de sector: a qué sectores puede acceder un usuario (vinto_master.user_sector).

Una concesión solo acota DÓNDE puede trabajar el usuario; QUÉ puede hacer sigue dependiendo de su perfil (app/auth/permissions.py). No hay
concesión implícita: sin filas el usuario no ve ni opera ningún sector, y DATA_BALTREK no recibe alcance operativo por su perfil. Conceder un
sector que el producto no tiene habilitado es inerte: el backend intersecta las concesiones con los sectores operativos (módulo de sectores).

Las concesiones se leen de la base de datos en cada petición (junto con la sesión), de modo que revocar una tiene efecto inmediato sin cerrar
sesiones. No hay ningún perfil ni bandera de «administrador» que las omita. Este módulo no importa el módulo de sectores.
"""

import uuid

from app.auth.errors import SectorNotFoundError, UserNotFoundError


def sector_codes_for_user(connection, user_id) -> frozenset:
    """Códigos de los sectores ACTIVOS concedidos explícitamente al usuario (puede ser vacío)."""
    rows = connection.execute(
        """SELECT s.code FROM vinto_master.user_sector us JOIN vinto_master.sector s ON s.id = us.sector_id
           WHERE us.user_id = %s AND s.active""", (user_id,)).fetchall()
    return frozenset(r[0] for r in rows)


def _lookup(connection, user_id, sector_code):
    user = connection.execute('SELECT id FROM vinto_master."user" WHERE id = %s', (user_id,)).fetchone()
    if user is None:
        raise UserNotFoundError("El usuario no existe")
    sector = connection.execute("SELECT id FROM vinto_master.sector WHERE code = %s", (sector_code,)).fetchone() if isinstance(sector_code, str) else None
    if sector is None:
        raise SectorNotFoundError(f"El sector {sector_code!r} no existe")
    return sector[0]


def _context(connection, actor_id, request_id, reason):
    if actor_id is not None:
        connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id or f"sector_grant:{uuid.uuid4()}",))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def grant_sector(connection, *, user_id, sector_code, actor_id=None, request_id=None) -> bool:
    """Concede el sector al usuario. Idempotente: devuelve True si creó la concesión, False si ya existía (nunca duplica)."""
    with connection.transaction():
        sector_id = _lookup(connection, user_id, sector_code)
        _context(connection, actor_id, request_id, "sector grant")
        row = connection.execute(
            "INSERT INTO vinto_master.user_sector (user_id, sector_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING user_id", (user_id, sector_id)).fetchone()
    return row is not None


def revoke_sector(connection, *, user_id, sector_code, actor_id=None, request_id=None) -> bool:
    """Revoca la concesión. Idempotente: devuelve True solo si esta llamada la eliminó.

    SINCRONIZACIÓN CON LA AUTORIZACIÓN EFECTIVA (MF-13-01D.3A): antes de borrar, esta transacción toma `FOR NO KEY UPDATE` sobre la fila del USUARIO. El motor (app/authz) toma `FOR SHARE`
    sobre esa misma fila durante toda la transacción de una captura, y ambos modos entran en conflicto: (1) una captura autorizada en curso hace esperar a la revocación hasta su COMMIT; (2) una
    revocación en curso hace esperar a la captura, que al confirmarse la revocación relee `user_sector` y se deniega. `user_sector` no es bloqueable por `vinto_app` (sin UPDATE), pero `user` sí.
    Se usa NO KEY UPDATE y no UPDATE porque el primero no choca con `FOR KEY SHARE`, el bloqueo que PostgreSQL toma en las comprobaciones de clave foránea de otras transacciones (capturas,
    sesiones, auditoría que referencian al usuario): sincroniza lo necesario sin bloquearlas. Conceder (`grant_sector`) no necesita sincronizarse: añadir un sector solo puede hacer que una captura
    concurrente se deniegue de más (falla cerrado), nunca que se permita de más. Un SQL directo de un rol con privilegios suficientes no pasa por aquí (MF-13-01D.3B).
    """
    with connection.transaction():
        sector_id = _lookup(connection, user_id, sector_code)
        _context(connection, actor_id, request_id, "sector revoke")
        connection.execute('SELECT 1 FROM vinto_master."user" WHERE id = %s FOR NO KEY UPDATE', (user_id,))  # orden: usuario → user_sector (el motor: usuario → perfiles → máquina+sector → concesión)
        row = connection.execute(
            "DELETE FROM vinto_master.user_sector WHERE user_id = %s AND sector_id = %s RETURNING user_id", (user_id, sector_id)).fetchone()
    return row is not None
