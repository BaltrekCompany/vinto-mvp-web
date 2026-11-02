"""MF-13-02: ELEGIBILIDAD de un usuario para iniciar una captura, calculada con el motor de autorización y SIN mirar el modo de ninguna compuerta.

Elegible = el motor (app/authz/engine.py) permite la operación sobre (máquina, formulario): perfil ACTIVO con el permiso funcional, sector concedido y operativo, máquina y
formulario activos, versión publicada vigente vinculada a la máquina y concesión máquina-formulario ACTIVA. Es la misma decisión que `enforce` aplicaría, por eso NO depende de
`off`/`observe`/`enforce`: el modo solo decide si el POST de una captura la exige (`capture_gate`); esta elegibilidad existe para que la interfaz oculte lo que el usuario no podría usar.

IMPORTANTE: eligibilidad NO es autorización. Ocultar un botón no sustituye al backend, que sigue decidiendo cada captura según su modo. Con la compuerta en `off`/`observe` un usuario NO elegible
podría seguir capturando por API (comportamiento anterior); la habilitación operativa exige `enforce` tras verificar las concesiones iniciales (docs/MF-13-02-frontend-por-permisos.md).
Solo se devuelve un booleano: ninguna razón interna del motor sale al cliente."""

from app.authz.engine import authorize
from app.authz.policies import Operation


def is_eligible(connection, user, operation: Operation, machine_code: str, form_code: str) -> bool:
    """True solo si el motor permite la operación. Si no se puede decidir se propaga AuthorizationUnavailable (503): nunca un True por defecto."""
    return authorize(connection, user, operation, machine_code, form_code, lock=False).allowed


def published_forms_by_machine(connection, machine_ids, codes, area) -> dict:
    """Versión publicada MÁS ALTA de cada formulario activo de `codes` en el área, solo si está vinculada a la máquina (la misma regla que la lectura y el POST): {machine_id: [{code, name, version_number}]}."""
    forms: dict = {}
    codes = sorted(codes)
    if not machine_ids or not codes:
        return forms
    for machine_id, code, name, version in connection.execute(
            """WITH latest AS (SELECT DISTINCT ON (f.id) f.code, fv.id AS version_id, fv.name, fv.version_number
                               FROM vinto_config.form f JOIN vinto_config.form_version fv ON fv.form_id = f.id
                               WHERE f.active AND fv.status = 'published' AND fv.area = %s AND f.code = ANY(%s) ORDER BY f.id, fv.version_number DESC)
               SELECT fvm.machine_id, l.code, l.name, l.version_number FROM latest l JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id = l.version_id
               WHERE fvm.machine_id = ANY(%s) ORDER BY fvm.machine_id, l.code""", (area, codes, list(machine_ids))).fetchall():
        forms.setdefault(machine_id, []).append({"code": code, "name": name, "version_number": version})
    return forms
