"""Administración de concesiones de sector: lecturas y cambios sobre vinto_master.user_sector, reutilizando app.auth.grants.

Reglas:
- El perfil decide QUÉ puede hacer un usuario; la concesión decide DÓNDE. Aquí solo se administra el DÓNDE.
- Una concesión sobre un sector que no es operativo es INERTE: se informa (`operational: false`) y nunca habilita nada.
- No se crean sectores ni concesiones implícitas; cada cambio pasa por grant_sector / revoke_sector (idempotentes y auditados con el actor autenticado).
- Nunca se leen ni devuelven credenciales, hashes, sesiones ni tokens.
"""

import uuid

from app.admin.errors import SectorInactive, SectorNotFound, UserNotFound
from app.auth.errors import SectorNotFoundError, UserNotFoundError
from app.auth.grants import grant_sector, revoke_sector
from app.sectors import is_operational_sector

DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT = 200, 500


def _sector_view(code, name, active) -> dict:
    """`granted` y `operational` son cosas distintas: operativo = sector activo Y habilitado en app/sectors.py."""
    return {"code": code, "name": name, "active": active, "operational": bool(active) and is_operational_sector(code)}


def _grants(connection, user_ids) -> dict:
    grants = {user_id: [] for user_id in user_ids}
    if user_ids:
        rows = connection.execute(
            """SELECT us.user_id, s.code, s.name, s.active FROM vinto_master.user_sector us JOIN vinto_master.sector s ON s.id = us.sector_id
               WHERE us.user_id = ANY(%s) ORDER BY s.code""", (list(user_ids),)).fetchall()
        for user_id, code, name, active in rows:
            grants[user_id].append(_sector_view(code, name, active))
    return grants


def list_users(connection, limit=DEFAULT_LIST_LIMIT) -> list[dict]:
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    rows = connection.execute(
        """SELECT u.id, c.username, u.display_name, u.active,
                  coalesce((SELECT array_agg(p.code ORDER BY p.code) FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id
                            WHERE up.user_id = u.id AND p.active), '{}')
           FROM vinto_master."user" u LEFT JOIN vinto_auth.credential c ON c.user_id = u.id
           ORDER BY c.username NULLS LAST, u.id LIMIT %s""", (limit,)).fetchall()
    grants = _grants(connection, [r[0] for r in rows])
    return [{"id": r[0], "username": r[1], "display_name": r[2], "active": r[3], "profiles": list(r[4]), "sectors": grants[r[0]]} for r in rows]


def get_user_sectors(connection, user_id) -> dict:
    row = connection.execute(
        'SELECT u.id, c.username, u.active FROM vinto_master."user" u LEFT JOIN vinto_auth.credential c ON c.user_id = u.id WHERE u.id = %s', (user_id,)).fetchone()
    if row is None:
        raise UserNotFound()
    return {"user_id": row[0], "username": row[1], "active": row[2], "sectors": _grants(connection, [row[0]])[row[0]]}


def change_grant(connection, *, operation, user_id, sector_code, actor_id) -> dict:
    """operation: "grant" | "revoke". Idempotente: `changed` es False si no había nada que cambiar (y entonces no se escribe ni se audita nada).

    Conceder exige un sector existente y ACTIVO; revocar se permite también sobre un sector inactivo para poder limpiar concesiones antiguas.
    """
    assert operation in ("grant", "revoke")
    if connection.execute('SELECT 1 FROM vinto_master."user" WHERE id = %s', (user_id,)).fetchone() is None:
        raise UserNotFound()
    sector = connection.execute("SELECT active FROM vinto_master.sector WHERE code = %s", (sector_code,)).fetchone()
    if sector is None:
        raise SectorNotFound()
    if operation == "grant" and not sector[0]:
        raise SectorInactive()
    request_id = f"admin-sector-{operation}:{uuid.uuid4()}"  # generado por el servidor; el cliente no puede fijarlo ni fijar el actor
    try:
        action = grant_sector if operation == "grant" else revoke_sector
        changed = action(connection, user_id=user_id, sector_code=sector_code, actor_id=actor_id, request_id=request_id)
    except UserNotFoundError:
        raise UserNotFound() from None
    except SectorNotFoundError:
        raise SectorNotFound() from None
    granted = _grants(connection, [user_id])[user_id]
    current = next((s for s in granted if s["code"] == sector_code), None)
    if current is None:
        row = connection.execute("SELECT name, active FROM vinto_master.sector WHERE code = %s", (sector_code,)).fetchone()
        current = _sector_view(sector_code, row[0], row[1])
    return {"user_id": user_id, "sector_code": sector_code, "operation": operation, "changed": changed, "sector": current, "granted_sectors": granted,
            "request_id": request_id if changed else None}
