"""Ensayo MANUAL (no es una prueba unittest) de la importación del bundle CANDIDATO de Rebobinado en bases efímeras NUEVAS *_test (M4-B1).

  python tests/rehearse_candidate_import.py <directorio-del-bundle-candidato>

Escenario A: base migrada vacía.  Escenario B: base migrada con el bundle aprobado (Bobinas), que es el estado de partida de DEV.
En cada uno: dry-run -> apply -> verificación de cardinalidad -> segundo apply (idempotente) -> dry-run consistente. En ambos comprueba, con huellas deterministas, que todo lo que existía antes (maestros, artículos y versiones, relaciones, turnos y horarios,
formularios con versiones, vínculos, grupos, campos y opciones) sigue presente e idéntico; en B esas filas son las de Bobinas. Finalmente comprueba las barreras hacia DEV SIN abrir ninguna conexión a DEV. Elimina las bases al terminar.
Nunca usa DATABASE_URL: solo TEST_DATABASE_URL (bases *_test creadas aquí).
"""

import contextlib
import io
import sys
from pathlib import Path

import import_reference
from app.db_guard import UnsafeDatabaseError
from app.ephemeral_db import connect, create_database, drop_database
from app.seed import reference
from app.seed.bundle import BUNDLE_DIR, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations
from uuid import uuid4

COUNT_SQL = {
    "sector": "SELECT count(*) FROM vinto_master.sector",
    "machine": "SELECT count(*) FROM vinto_master.machine",
    "article": "SELECT count(*) FROM vinto_master.article",
    "article_machine": "SELECT count(*) FROM vinto_master.article_machine",
    "shift": "SELECT count(*) FROM vinto_config.shift",
    "shift_schedule": "SELECT count(*) FROM vinto_config.shift_schedule",
    "form_version_machine": "SELECT count(*) FROM vinto_config.form_version_machine",
    "user_sector (concesiones)": "SELECT count(*) FROM vinto_master.user_sector",
    "capture": "SELECT count(*) FROM vinto_txn.capture",
}
# Huellas DETERMINISTAS (sin ids generados ni marcas de tiempo) de lo que existía antes de importar el candidato: cada consulta devuelve (clave natural, fila de texto);
# después de importar, cada fila previa debe seguir presente e idéntica (el candidato solo puede AÑADIR filas).
FINGERPRINTS = {
    "sector": "SELECT code, code || '|' || name FROM vinto_master.sector",
    "machine": "SELECT m.code, m.code || '|' || m.name || '|' || s.code || '|' || m.active FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id",
    "unit": "SELECT code, code || '|' || label FROM vinto_master.unit",
    "material_class": "SELECT code, code || '|' || name FROM vinto_master.material_class",
    "article + versiones": """SELECT a.code || '#' || v.version_number, a.code || '|' || a.is_product || '|' || a.is_material || '|' || a.active || '|' || v.version_number || '|' || v.description
                                 || '|' || u.code || '|' || coalesce(c.code, '-') || '|' || coalesce(v.nominal_weight_kg::text, '-')
                              FROM vinto_master.article a JOIN vinto_master.article_version v ON v.article_id = a.id JOIN vinto_master.unit u ON u.id = v.unit_id
                              LEFT JOIN vinto_master.material_class c ON c.id = v.material_class_id""",
    "relaciones artículo-máquina": """SELECT a.code || '>' || m.code, a.code || '>' || m.code FROM vinto_master.article_machine am JOIN vinto_master.article a ON a.id = am.article_id
                                      JOIN vinto_master.machine m ON m.id = am.machine_id""",
    "workflow": "SELECT code, code || '|' || name FROM vinto_config.workflow_definition",
    "turno": "SELECT code, code || '|' || name || '|' || active FROM vinto_config.shift",
    "horario de turno": """SELECT sh.code || '@' || se.code || '@' || x.valid_from, sh.code || '|' || se.code || '|' || x.starts_at || '|' || x.ends_at || '|' || x.timezone || '|' || x.valid_from || '|' || coalesce(x.valid_to::text, '-')
                           FROM vinto_config.shift_schedule x JOIN vinto_config.shift sh ON sh.id = x.shift_id JOIN vinto_master.sector se ON se.id = x.sector_id""",
    "formulario + versión": """SELECT f.code || '#' || v.version_number, f.code || '|' || f.legacy_key || '|' || f.active || '|' || v.version_number || '|' || v.name || '|' || v.area || '|' || w.code || '|' || v.status || '|' || v.definition_checksum
                               FROM vinto_config.form f JOIN vinto_config.form_version v ON v.form_id = f.id JOIN vinto_config.workflow_definition w ON w.id = v.workflow_id""",
    "formulario-máquina": """SELECT f.code || '#' || v.version_number || '>' || m.code, f.code || '#' || v.version_number || '>' || m.code FROM vinto_config.form_version_machine x
                             JOIN vinto_config.form_version v ON v.id = x.form_version_id JOIN vinto_config.form f ON f.id = v.form_id JOIN vinto_master.machine m ON m.id = x.machine_id""",
    "grupo de campos": """SELECT f.code || '#' || v.version_number || '/' || g.code, g.code || '|' || g.label || '|' || g.display_order || '|' || g.repeatable || '|' || g.min_rows || '|' || coalesce(g.max_rows::text, '-')
                          FROM vinto_config.field_group g JOIN vinto_config.form_version v ON v.id = g.form_version_id JOIN vinto_config.form f ON f.id = v.form_id""",
    "campo": """SELECT f.code || '#' || v.version_number || '/' || coalesce(g.code, '-') || '/' || d.key, d.key || '|' || d.label || '|' || d.value_type || '|' || d.source || '|' || d.required || '|'
                    || coalesce(u.code, '-') || '|' || d.display_order || '|' || coalesce(d.classification, '-') || '|' || d.needs_validation
                FROM vinto_config.field_definition d JOIN vinto_config.form_version v ON v.id = d.form_version_id JOIN vinto_config.form f ON f.id = v.form_id
                LEFT JOIN vinto_config.field_group g ON g.id = d.field_group_id LEFT JOIN vinto_master.unit u ON u.id = d.unit_id""",
    "opción de campo": """SELECT f.code || '#' || v.version_number || '/' || d.key || '/' || o.option_key, o.option_key || '|' || o.label || '|' || o.display_order
                          FROM vinto_config.field_option o JOIN vinto_config.field_definition d ON d.id = o.field_definition_id JOIN vinto_config.form_version v ON v.id = o.form_version_id
                          JOIN vinto_config.form f ON f.id = v.form_id""",
}


def fingerprint(connection):
    """{categoría: {clave natural: fila}} sin ids generados ni marcas de tiempo."""
    return {name: dict(connection.execute(query).fetchall()) for name, query in FINGERPRINTS.items()}


def preserved(before, after):
    """Categorías en las que alguna fila previa falta o cambió (vacío = todo intacto)."""
    return [name for name, rows in before.items() if any(after[name].get(key) != row for key, row in rows.items())]


def counts(connection):
    return {name: connection.execute(query).fetchone()[0] for name, query in COUNT_SQL.items()}


def summary(result):
    return {entity: f"crear={n['create']} presentes={n['present']}" for entity, n in result.counts.items()}


def scenario(label, with_approved, candidate, expected=None):
    """`expected`: huella de lo aprobado (la entrega el escenario B) para comprobar también en la base vacía que el candidato contiene lo aprobado idéntico."""
    name = f"vinto_m4b1_{label}_{uuid4().hex[:8]}_test"
    create_database(name)
    ok = True
    try:
        with connect(name) as connection:
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(connection, read_migrations())
            if with_approved:
                reference.apply(connection, load_bundle(BUNDLE_DIR))
            identity = connection.execute("SELECT current_database()").fetchone()[0]
            assert identity == name and identity.endswith("_test"), identity
            print(f"\n== Escenario {label}: base efímera {identity} ({'con bundle aprobado' if with_approved else 'migrada vacía'})")
            before, snapshot = counts(connection), fingerprint(connection)
            print("antes:", before)
            dry = reference.dry_run(connection, candidate)
            print(f"dry-run: estado={dry.state} conflictos={len(dry.conflicts)} filas_a_crear={dry.pending_creates}")
            assert counts(connection) == before, "el dry-run escribió"
            ok &= dry.state == "pending" and not dry.conflicts
            first = reference.apply(connection, candidate)
            after = counts(connection)
            print(f"apply: modo={first.mode} filas_creadas={first.pending_creates}")
            print("después:", after)
            second = reference.apply(connection, candidate)
            print(f"segundo apply: modo={second.mode} (idempotente: sin batch nuevo, base idéntica al bundle)")
            again = counts(connection)
            batches = connection.execute("SELECT count(*) FROM vinto_audit.import_batch WHERE status = 'completed' AND source_checksum = %s", (candidate.source_checksum,)).fetchone()[0]
            final = reference.dry_run(connection, candidate)
            print(f"dry-run final: estado={final.state}; batches completados del candidato={batches}")
            ok &= first.mode == "applied" and second.mode == "noop" and again == after and batches == 1 and final.state == "consistent"
            expect = {"sector": 2, "machine": 7, "article": 241, "article_machine": 242, "shift_schedule": 4}
            ok &= all(after[k] == v for k, v in expect.items())
            ok &= after["form_version_machine"] == 8 and after["user_sector (concesiones)"] == before["user_sector (concesiones)"] and after["capture"] == 0
            baseline = expected or snapshot
            changed = preserved(baseline, fingerprint(connection))
            rows_before = sum(len(rows) for rows in baseline.values())
            print(f"filas previas ({len(snapshot)} categorías, {rows_before} filas) presentes e idénticas tras importar: {not changed}" + (f" — DIFIEREN: {changed}" if changed else ""))
            ok &= not changed
            linked = connection.execute("""SELECT count(*) FROM vinto_config.form_version_machine fvm JOIN vinto_master.machine m ON m.id = fvm.machine_id
                                           JOIN vinto_master.sector s ON s.id = m.sector_id WHERE s.code = 'REBOBINADO'""").fetchone()[0]
            print(f"formularios vinculados a máquinas de Rebobinado tras importar: {linked} (el candidato no habilita ningún formulario)")
            ok &= linked == 0
    finally:
        drop_database(name)
        print(f"base {name} eliminada")
    return ok, snapshot


def guards(candidate_dir, candidate):
    print("\n== Barreras hacia DEV (sin abrir conexión)")
    results = []
    for what, call in (("directorio candidato en --target dev --apply", lambda: import_reference.assert_dev_apply_allowed(candidate_dir)),
                       ("manifest candidato en --target dev --apply", lambda: import_reference.assert_bundle_not_candidate_for_dev(candidate))):
        try:
            call()
            print(f"  FALLO: {what} NO fue rechazado")
            results.append(False)
        except UnsafeDatabaseError:
            print(f"  OK: {what} rechazado")
            results.append(True)
    return all(results)


def main():
    directory = Path(sys.argv[1]).resolve()
    candidate = load_bundle(directory)
    assert candidate.manifest["scope"].get("candidate") is True, "se esperaba un bundle candidato"
    ok_b, approved_snapshot = scenario("B", True, candidate)
    ok_a, _ = scenario("A", False, candidate, expected=approved_snapshot)
    results = [ok_a, ok_b, guards(directory, candidate)]
    print("\nRESULTADO:", "TODO OK" if all(results) else "HAY FALLOS")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
