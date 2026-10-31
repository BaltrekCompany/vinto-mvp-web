"""Lectura administrativa de un usuario y de sus concesiones máquina-formulario (MF-13-01C.1). SOLO LECTURA: no concede, revoca ni escribe nada.

- Reutiliza `app.auth.machine_form_grants.machine_form_grants_for_user` (la única fuente de las concesiones) y el catálogo de `app.admin.catalog`.
- Cada concesión se acompaña de su estado ACTUAL en el catálogo (`published_version`, `offered`, `enabled_for_capture`): una concesión guardada cuyo par ya no se ofrece sigue
  apareciendo (es historia), marcada como no ofrecida; nunca se oculta ni se reescribe.
- Los permisos que se muestran se DERIVAN de los perfiles con la matriz existente (app/auth/permissions.py); no hay un sistema paralelo.
- Nunca se leen ni devuelven credenciales, hashes, sesiones ni tokens.
"""

from app.admin.catalog import load_catalog, read_only_snapshot
from app.admin.errors import UserNotFound
from app.admin.service import _grants
from app.auth.grants import sector_codes_for_user
from app.auth.machine_form_grants import machine_form_grants_for_user
from app.auth.permissions import permissions_for_profiles
from app.sectors import is_operational_sector

DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT = 200, 500


def _user_row(connection, user_id):
    row = connection.execute('SELECT u.id, c.username, u.display_name, u.active FROM vinto_master."user" u LEFT JOIN vinto_auth.credential c ON c.user_id = u.id WHERE u.id = %s', (user_id,)).fetchone()
    if row is None:
        raise UserNotFound()
    return row


def user_detail(connection, user_id) -> dict:
    """Perfil(es), permisos derivados y sectores concedidos (con su carácter operativo) de un usuario."""
    with read_only_snapshot(connection):
        uid, username, display_name, active = _user_row(connection, user_id)
        profiles = connection.execute(
            """SELECT p.code, p.name FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id WHERE up.user_id = %s AND p.active ORDER BY p.code""", (uid,)).fetchall()
        sectors = _grants(connection, [uid])[uid]
    codes = [code for code, _ in profiles]
    return {"id": uid, "username": username, "display_name": display_name, "active": active, "profiles": [{"code": c, "name": n} for c, n in profiles],
            "permissions": sorted(permissions_for_profiles(codes)), "sectors": sectors}


def _people(connection, ids) -> dict:
    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    return {uid: {"id": uid, "display_name": name} for uid, name in connection.execute('SELECT id, display_name FROM vinto_master."user" WHERE id = ANY(%s)', (ids,)).fetchall()}


def _grant_row(g, catalog, people) -> dict:
    machine, form = catalog.machine_by_code.get(g.machine_code), catalog.forms.get(g.form_code)
    return {
        "id": g.id, "state": "active" if g.active else "revoked",
        "machine": {"code": g.machine_code, "name": machine["name"] if machine else None, "sector_code": machine["sector_code"] if machine else None},
        "form": {"code": g.form_code, "name": form["name"] if form else None, "area": form["area"] if form else None},
        "granted_at": g.granted_at, "granted_by": people.get(g.granted_by),
        "revoked_at": g.revoked_at, "revoked_by": people.get(g.revoked_by),
        "catalog": catalog.pair(g.machine_code, g.form_code),
    }


def user_grants(connection, user_id, *, include_revoked=False, limit=None) -> dict:
    """Concesiones del usuario. Activas por defecto, ordenadas por máquina y formulario (MP1 y MP3 son filas distintas); con `include_revoked` el historial completo, de la más reciente a la más antigua.

    `limit` solo se aplica al historial; `total` es el número de filas que existen y `truncated` indica si `limit` recortó la respuesta.
    """
    with read_only_snapshot(connection):
        _user_row(connection, user_id)
        grants = machine_form_grants_for_user(connection, user_id, include_revoked=include_revoked)
        catalog = load_catalog(connection)
        people = _people(connection, [g.granted_by for g in grants] + [g.revoked_by for g in grants])
    if include_revoked:
        grants = tuple(sorted(grants, key=lambda g: (g.granted_at, str(g.id)), reverse=True))
    total = len(grants)
    if include_revoked:
        limit = max(1, min(int(limit or DEFAULT_HISTORY_LIMIT), MAX_HISTORY_LIMIT))
        grants = grants[:limit]
    rows = [_grant_row(g, catalog, people) for g in grants]
    return {"user_id": user_id, "total": total, "truncated": len(rows) < total, "grants": rows}


def pair_state(connection, user_id, machine_code, form_code) -> dict:
    """Estado de UNA terna (usuario, máquina, formulario) tras un cambio: la fila más reciente (activa, o la última revocada), si queda activa, el estado actual del par en el catálogo y el
    contexto del usuario (activo, sector concedido y operativo). Solo lectura, en una instantánea coherente. El contexto es informativo: no cambia ninguna regla."""
    with read_only_snapshot(connection):
        _, _, _, user_active = _user_row(connection, user_id)
        rows = [g for g in machine_form_grants_for_user(connection, user_id, include_revoked=True) if (g.machine_code, g.form_code) == (machine_code, form_code)]
        catalog = load_catalog(connection)
        people = _people(connection, [g.granted_by for g in rows] + [g.revoked_by for g in rows])
        granted_sectors = sector_codes_for_user(connection, user_id)
    latest = max(rows, key=lambda g: (g.granted_at, str(g.id)), default=None)
    machine = catalog.machine_by_code.get(machine_code)
    sector = machine["sector_code"] if machine else None
    return {"grant": _grant_row(latest, catalog, people) if latest else None, "active": any(g.active for g in rows), "catalog": catalog.pair(machine_code, form_code),
            "context": {"user_active": user_active, "sector_code": sector, "sector_granted": sector in granted_sectors,
                        "sector_operational": bool(machine and machine["sector_active"] and is_operational_sector(sector))}}
