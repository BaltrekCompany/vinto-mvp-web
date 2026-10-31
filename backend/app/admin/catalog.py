"""Catálogo de sectores, máquinas y formularios para la API administrativa (MF-13-01C.1), SOLO LECTURA, leído de PostgreSQL.

Nada se duplica ni se inventa: máquinas, formularios, áreas y vínculos salen de la base; las políticas de captura salen de las constantes que ya usan los servicios de captura.
Para cada par (máquina, formulario) se distinguen cuatro cosas que no son lo mismo:

  published   el formulario tiene una versión PUBLICADA vigente (la de número más alto); se informa su número en `effective_version`.
  offered     el par se ofrece hoy: la versión publicada vigente (NO una anterior) está vinculada a la máquina y formulario, máquina y sector están activos. Es exactamente lo que
              exige `grant_machine_form` para conceder, y lo que `production_access` ofrece para los formularios de producción. Un vínculo que solo existe en una versión histórica no cuenta.
  enabled_for_capture
              además hay una política de captura en código que acepta el formulario (`capture_policies`) y el sector de la máquina es operativo (app/sectors.py). Un formulario puede estar
              publicado y ofrecido y aun así NO estar habilitado para capturar (p. ej. VINTO-P1-03 se registra por /api/bobbins, no por la captura central).
  granted     lo informa la vista de concesiones de un usuario, no este catálogo.

El catálogo no concede nada ni cambia ninguna regla: solo describe lo que la base y el código dicen hoy.
"""

import contextlib

from app import capture_service
from app.quality import capture_service as quality_capture_service
from app.quality import machine_capture_service
from app.sectors import KNOWN_SECTOR_CODES, is_operational_sector

POLICY_PRODUCTION_CENTRAL = "production_central"
POLICY_QUALITY_BY_BOBBIN = "quality_by_bobbin"
POLICY_QUALITY_BY_MACHINE = "quality_by_machine"


def capture_policies(form_code, area) -> list[str]:
    """Políticas de captura en código que aceptan el formulario, leídas de las constantes de los servicios de captura (no se copian aquí). Vacío = ninguna."""
    policies = []
    if area == "production" and form_code in capture_service.CENTRAL_FORM_CODES:
        policies.append(POLICY_PRODUCTION_CENTRAL)
    if area == "quality":
        bobbin = set(quality_capture_service.CENTRAL_BOBBIN_FORM_CODES) | (set(quality_capture_service.BOBBIN_CANDIDATE_FORM_CODES) & set(quality_capture_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES))
        if form_code in bobbin:
            policies.append(POLICY_QUALITY_BY_BOBBIN)
        if form_code in machine_capture_service.MACHINE_QUALITY_FORM_CODES:
            policies.append(POLICY_QUALITY_BY_MACHINE)
    return policies


class Catalog:
    """Instantánea del catálogo: formularios (con su versión publicada vigente), máquinas y vínculos de ESA versión."""

    def __init__(self, forms, machines, links):
        self.forms = forms          # code -> dict(id, code, name, area, active, effective_version, policies)
        self.machines = machines    # lista ordenada de dict(id, code, name, active, sector_code, sector_name, sector_active)
        self.links = links          # set de (machine_code, form_code) vinculados por la versión publicada VIGENTE
        self.machine_by_code = {m["code"]: m for m in machines}

    def pair(self, machine_code, form_code) -> dict:
        """Estado de un par (aunque no exista): published / offered / enabled_for_capture / capture_policies."""
        form, machine = self.forms.get(form_code), self.machine_by_code.get(machine_code)
        published = form is not None and form["effective_version"] is not None
        offered = bool(published and machine is not None and (machine_code, form_code) in self.links and form["active"] and machine["active"] and machine["sector_active"])
        policies = form["policies"] if form is not None else []
        enabled = bool(offered and policies and is_operational_sector(machine["sector_code"]))
        return {"published_version": form["effective_version"] if form is not None else None, "offered": offered, "enabled_for_capture": enabled, "capture_policies": list(policies)}


def load_catalog(connection) -> Catalog:
    """Lee el catálogo. Debe llamarse dentro de la transacción de solo lectura del llamador para que todas las consultas vean el mismo estado."""
    form_rows = connection.execute(
        """SELECT f.id, f.code, f.active, eff.id, eff.version_number, eff.area, eff.name, lat.area, lat.name
           FROM vinto_config.form f
           LEFT JOIN LATERAL (SELECT fv.id, fv.version_number, fv.area, fv.name FROM vinto_config.form_version fv
                              WHERE fv.form_id = f.id AND fv.status = 'published' ORDER BY fv.version_number DESC LIMIT 1) eff ON true
           LEFT JOIN LATERAL (SELECT fv.area, fv.name FROM vinto_config.form_version fv WHERE fv.form_id = f.id ORDER BY fv.version_number DESC LIMIT 1) lat ON true
           ORDER BY f.code""").fetchall()
    forms, effective_ids = {}, {}
    for form_id, code, active, version_id, number, area, name, latest_area, latest_name in form_rows:
        area, name = (area, name) if version_id is not None else (latest_area, latest_name)  # sin versión publicada se muestra la última conocida; `effective_version` sigue siendo None
        forms[code] = {"id": form_id, "code": code, "name": name, "area": area, "active": active, "effective_version": number if version_id is not None else None,
                       "policies": capture_policies(code, area)}
        if version_id is not None:
            effective_ids[version_id] = code
    machine_rows = connection.execute(
        """SELECT m.id, m.code, m.name, m.active, s.code, s.name, s.active FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id
           WHERE s.code = ANY(%s) ORDER BY s.code, m.code""", (sorted(KNOWN_SECTOR_CODES),)).fetchall()
    machines = [{"id": r[0], "code": r[1], "name": r[2], "active": r[3], "sector_code": r[4], "sector_name": r[5], "sector_active": r[6]} for r in machine_rows]
    code_of = {m["id"]: m["code"] for m in machines}
    links = set()
    if effective_ids:
        for version_id, machine_id in connection.execute("SELECT form_version_id, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = ANY(%s)", (list(effective_ids),)).fetchall():
            if machine_id in code_of:
                links.add((code_of[machine_id], effective_ids[version_id]))
    return Catalog(forms, machines, links)


@contextlib.contextmanager
def read_only_snapshot(connection):
    """Transacción de solo lectura con una única instantánea: todo lo que se devuelve es coherente aunque otra sesión conceda o revoque mientras tanto. Nada se puede escribir."""
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def catalog_tree(connection) -> dict:
    """Sectores -> máquinas -> formularios que la versión publicada vigente vincula a cada máquina."""
    with read_only_snapshot(connection):
        catalog = load_catalog(connection)
    sectors = {}
    for machine in catalog.machines:
        sector = sectors.setdefault(machine["sector_code"], {"code": machine["sector_code"], "name": machine["sector_name"], "active": machine["sector_active"],
                                                             "operational": bool(machine["sector_active"]) and is_operational_sector(machine["sector_code"]), "machines": []})
        forms = []
        for code in sorted(catalog.forms):
            if (machine["code"], code) in catalog.links:
                form, state = catalog.forms[code], catalog.pair(machine["code"], code)
                forms.append({"code": code, "name": form["name"], "area": form["area"], "active": form["active"], "effective_version": form["effective_version"],
                              "published": True, "capture_policies": state["capture_policies"], "offered": state["offered"], "enabled_for_capture": state["enabled_for_capture"]})
        sector["machines"].append({"code": machine["code"], "name": machine["name"], "active": machine["active"], "forms": forms})
    return {"sectors": list(sectors.values())}


def catalog_forms(connection) -> dict:
    """Formularios con su versión publicada vigente y las máquinas que ESA versión vincula. Incluye los que no tienen versión publicada (`published: false`)."""
    with read_only_snapshot(connection):
        catalog = load_catalog(connection)
    forms = []
    for code, form in catalog.forms.items():
        machines = []
        for machine in catalog.machines:
            if (machine["code"], code) in catalog.links:
                state = catalog.pair(machine["code"], code)
                machines.append({"code": machine["code"], "sector_code": machine["sector_code"], "active": machine["active"], "offered": state["offered"],
                                 "enabled_for_capture": state["enabled_for_capture"]})
        forms.append({"code": code, "name": form["name"], "area": form["area"], "active": form["active"], "published": form["effective_version"] is not None,
                      "effective_version": form["effective_version"], "capture_policies": form["policies"], "enabled_for_capture": any(m["enabled_for_capture"] for m in machines),
                      "machines": machines})
    return {"forms": forms}
