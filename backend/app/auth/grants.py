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
    """Revoca la concesión. Idempotente: devuelve True solo si esta llamada la eliminó."""
    with connection.transaction():
        sector_id = _lookup(connection, user_id, sector_code)
        _context(connection, actor_id, request_id, "sector revoke")
        row = connection.execute(
            "DELETE FROM vinto_master.user_sector WHERE user_id = %s AND sector_id = %s RETURNING user_id", (user_id, sector_id)).fetchone()
    return row is not None
