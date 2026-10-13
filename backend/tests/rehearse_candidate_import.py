"""Ensayo MANUAL (no es una prueba unittest) de la importación del bundle CANDIDATO de Rebobinado en bases efímeras NUEVAS *_test (M4-B1).

  python tests/rehearse_candidate_import.py <directorio-del-bundle-candidato>

Escenario A: base migrada vacía.  Escenario B: base migrada con el bundle aprobado (Bobinas), que es el estado de partida de DEV.
En cada uno: dry-run -> apply -> verificación de cardinalidad -> segundo apply (idempotente) -> dry-run consistente. En B además comprueba que los
maestros de Bobinas no cambiaron. Finalmente comprueba las barreras hacia DEV SIN abrir ninguna conexión a DEV. Elimina las bases al terminar.
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
BOBINAS_SQL = """SELECT md5(string_agg(m.code || '|' || m.name || '|' || m.active::text, ',' ORDER BY m.code))
                   FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id WHERE s.code = 'BOBINAS'"""
BOBINAS_LINKS_SQL = """SELECT md5(string_agg(a.code || '>' || m.code, ',' ORDER BY a.code, m.code))
                         FROM vinto_master.article_machine am JOIN vinto_master.article a ON a.id = am.article_id JOIN vinto_master.machine m ON m.id = am.machine_id
                         JOIN vinto_master.sector s ON s.id = m.sector_id WHERE s.code = 'BOBINAS'"""


def counts(connection):
    return {name: connection.execute(query).fetchone()[0] for name, query in COUNT_SQL.items()}


def summary(result):
    return {entity: f"crear={n['create']} presentes={n['present']}" for entity, n in result.counts.items()}


def scenario(label, with_approved, candidate):
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
            before, bob_before, links_before = counts(connection), connection.execute(BOBINAS_SQL).fetchone()[0], connection.execute(BOBINAS_LINKS_SQL).fetchone()[0]
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
            if with_approved:
                same_bob = connection.execute(BOBINAS_SQL).fetchone()[0] == bob_before and connection.execute(BOBINAS_LINKS_SQL).fetchone()[0] == links_before
                print(f"maestros de Bobinas intactos (máquinas y relaciones artículo-máquina): {same_bob}")
                ok &= same_bob
            linked = connection.execute("""SELECT count(*) FROM vinto_config.form_version_machine fvm JOIN vinto_master.machine m ON m.id = fvm.machine_id
                                           JOIN vinto_master.sector s ON s.id = m.sector_id WHERE s.code = 'REBOBINADO'""").fetchone()[0]
            print(f"formularios vinculados a máquinas de Rebobinado tras importar: {linked} (el candidato no habilita ningún formulario)")
            ok &= linked == 0
    finally:
        drop_database(name)
        print(f"base {name} eliminada")
    return ok


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
    results = [scenario("A", False, candidate), scenario("B", True, candidate), guards(directory, candidate)]
    print("\nRESULTADO:", "TODO OK" if all(results) else "HAY FALLOS")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
