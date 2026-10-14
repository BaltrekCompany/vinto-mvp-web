"""Disponibilidad de formularios de Calidad (solo lectura), compartida por los controles POR MÁQUINA (DEV-Q1 / DEV-Q2) y los candidatos POR BOBINA (DEV-Q2).

Dada una lista de códigos que la política del llamador ya habilitó, devuelve las máquinas activas del alcance con la última versión PUBLICADA de área `quality` vinculada a cada máquina. Sin códigos no consulta
formularios: nada se ofrece. Esta función no decide qué formulario está habilitado (lo hace la política de cada servicio) ni escribe nada.
"""

from app.sectors import scoped_sector_codes


def available_quality_forms(connection, sectors, codes) -> list[dict]:
    codes = sorted(codes)
    scoped = list(scoped_sector_codes(sectors))
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        machines = connection.execute(
            """SELECT s.code, s.name, m.id, m.code, m.name FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id
               WHERE m.active AND s.active AND s.code = ANY(%s) ORDER BY s.code, m.code""", (scoped,)).fetchall()
        forms: dict = {}
        ids = [r[2] for r in machines]
        if ids and codes:
            for machine_id, code, name, version in connection.execute(
                    """WITH latest AS (SELECT DISTINCT ON (f.id) f.code, fv.id AS version_id, fv.name, fv.version_number
                                       FROM vinto_config.form f JOIN vinto_config.form_version fv ON fv.form_id = f.id
                                       WHERE f.active AND fv.status = 'published' AND fv.area = 'quality' AND f.code = ANY(%s) ORDER BY f.id, fv.version_number DESC)
                       SELECT fvm.machine_id, l.code, l.name, l.version_number FROM latest l JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id = l.version_id
                       WHERE fvm.machine_id = ANY(%s) ORDER BY fvm.machine_id, l.code""", (codes, ids)).fetchall():
                forms.setdefault(machine_id, []).append({"code": code, "name": name, "version_number": version})
    out: dict = {}
    for sector_code, sector_name, machine_id, machine_code, machine_name in machines:
        sector = out.setdefault(sector_code, {"code": sector_code, "name": sector_name, "machines": []})
        sector["machines"].append({"code": machine_code, "name": machine_name, "forms": forms.get(machine_id, [])})
    return list(out.values())
