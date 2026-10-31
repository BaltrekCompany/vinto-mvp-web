"""Informe de preparación para activar el motor de autorización (MF-13-01D.1). SOLO LECTURA: no escribe, no concede, no revoca y no altera privilegios.

Responde dos preguntas del plan de activación:
  1. ¿Qué usuarios operativos quedarían BLOQUEADOS al activar el motor? Para cada operación, las ternas (usuario, máquina, formulario) que HOY cumplen todo menos la concesión
     explícita: usuario activo con el permiso de sus perfiles activos, sector activo/operativo concedido, máquina y formulario activos, formulario admitido por la ruta y ofrecido por
     la versión publicada vigente. Cada una necesita una concesión previa; el informe no la crea (sembrar concesiones es una decisión humana, con actor y motivo).
  2. ¿Puede el rol de la aplicación escribir DIRECTAMENTE en la tabla de concesiones? Una escritura directa se salta el servicio (validaciones y auditoría con actor) y deja la
     autorización en manos de quien pueda ejecutar SQL: se informa para endurecer ANTES de activar (propuesta en docs/MF-13-01D1-motor-autorizacion-efectiva.md).
"""

from collections import defaultdict

import psycopg

from app.auth.permissions import permissions_for_profiles
from app.authz.policies import POLICIES
from app.sectors import is_operational_sector

_CANDIDATES = """
SELECT u.id, c.username, m.code, f.code, s.code, (g.id IS NOT NULL) AS has_grant
FROM vinto_master."user" u
JOIN vinto_auth.credential c ON c.user_id = u.id
JOIN vinto_master.user_sector us ON us.user_id = u.id
JOIN vinto_master.sector s ON s.id = us.sector_id AND s.active
JOIN vinto_master.machine m ON m.sector_id = s.id AND m.active
JOIN vinto_config.form f ON f.code = ANY(%(forms)s) AND f.active
JOIN vinto_config.form_version fv ON fv.form_id = f.id AND fv.status = 'published' AND fv.area = %(area)s
 AND fv.version_number = (SELECT max(x.version_number) FROM vinto_config.form_version x WHERE x.form_id = f.id AND x.status = 'published')  -- la vigente de CUALQUIER área, como el motor y el catálogo
JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id = fv.id AND fvm.machine_id = m.id
LEFT JOIN vinto_master.user_machine_form_grant g ON g.user_id = u.id AND g.machine_id = m.id AND g.form_id = f.id AND g.revoked_at IS NULL
WHERE u.active
ORDER BY c.username, m.code, f.code
"""


def _profiles_by_user(connection) -> dict:
    rows = connection.execute("SELECT up.user_id, p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id WHERE p.active").fetchall()
    by_user = defaultdict(list)
    for user_id, code in rows:
        by_user[user_id].append(code)
    return by_user


def coverage_report(connection) -> dict:
    """Por operación: ternas ya cubiertas por una concesión activa y ternas que quedarían bloqueadas (sin concesión), con el total por usuario."""
    profiles = _profiles_by_user(connection)
    report = {}
    for operation, policy in POLICIES.items():
        rows = connection.execute(_CANDIDATES, {"forms": sorted(policy.admitted()), "area": policy.area}).fetchall()
        covered, blocked = [], []
        for user_id, username, machine, form, sector, has_grant in rows:
            if not is_operational_sector(sector):
                continue
            if policy.permission not in permissions_for_profiles(profiles.get(user_id, [])):
                continue  # sin el permiso funcional nunca habría operado: no es un bloqueo causado por el motor
            (covered if has_grant else blocked).append({"username": username, "machine": machine, "form": form})
        per_user = defaultdict(int)
        for item in blocked:
            per_user[item["username"]] += 1
        report[operation.value] = {"route": policy.route, "covered": len(covered), "would_be_blocked": len(blocked), "blocked_by_user": dict(sorted(per_user.items())), "blocked": blocked}
    return report


def privilege_report(connection) -> dict:
    """Privilegios del rol ACTUAL sobre la tabla de concesiones. `direct_write` es True si puede insertar, actualizar, borrar o truncar saltándose el servicio."""
    table = "vinto_master.user_machine_form_grant"
    try:
        flags = {privilege: connection.execute("SELECT has_table_privilege(current_user, %s, %s)", (table, privilege)).fetchone()[0]
                 for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")}
    except psycopg.Error as error:  # tabla ausente o sin privilegio de catálogo: se informa como desconocido, nunca como "sin riesgo"
        return {"available": False, "cause": error.sqlstate or type(error).__name__}
    return {"available": True, "role_bypasses_privileges": connection.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0],
            "privileges": flags, "direct_write": any(flags[p] for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"))}


def build_report(connection) -> dict:
    coverage = coverage_report(connection)
    return {"mode": "read-only", "coverage": coverage, "privileges": privilege_report(connection),
            "total_would_be_blocked": sum(item["would_be_blocked"] for item in coverage.values())}
