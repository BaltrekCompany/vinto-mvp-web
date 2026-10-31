"""MF-13-01B.4: una revocación de concesión debe llevar el actor de la sesión (migración 0009).

Con la 0008, un UPDATE directo SIN actor de sesión podía revocar atribuyendo la revocación a cualquier usuario (revoked_by, y por el guarda también updated_by); la auditoría de ese UPDATE
llevaba actor_id NULL. La 0009 solo añade al guarda la exigencia del actor; no cambia filas, restricciones, privilegios ni auditoría ya guardados.

Se verifica contra PostgreSQL REAL (bases efímeras *_test). Nada aquí toca endpoints, capturas, perfiles, catálogo ni concesiones de sector."""

import contextlib
import io
import re
import threading
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg

from app.auth.machine_form_grants import grant_machine_form, machine_form_grants_for_user, revoke_machine_form
from app.auth.service import create_user
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, drop_database
from app.seed import reference
from app.seed.bundle import load_bundle
from migrate import apply as apply_migrations
from migrate import applied_migrations, read_migrations, validate_history

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
P101 = "VINTO-P1-01"
STATE = {}
REVOKE = "UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE id = %s"
# Consulta de revisión (docs/MF-13-01B4-atribucion-revocaciones.md): revocaciones guardadas con un revoked_by pero sin actor de sesión (solo posibles con la 0008).
UNATTRIBUTED = """SELECT id, entity_key->>'id', database_actor, new_data->>'revoked_by' FROM vinto_audit.audit_event
                  WHERE entity_table = 'user_machine_form_grant' AND action = 'UPDATE' AND actor_id IS NULL AND new_data->>'revoked_by' IS NOT NULL ORDER BY id"""


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mfa_tpl")


def tearDownModule():
    drop_database(STATE["template"])


class Db(unittest.TestCase):
    def setUp(self):
        self.db = copy_database(STATE["template"], "vinto_mfa")
        self.addCleanup(drop_database, self.db)
        self.c = connect(self.db)
        self.addCleanup(self.c.close)
        self.admin, self.victim, self.operator = self.user("DATA_BALTREK"), self.user("SUPERVISION"), self.user()

    def user(self, profile="OPERACION"):
        return create_user(self.c, username=f"mfa.{uuid4().hex[:12]}", display_name=profile, profile_code=profile, password="pw-" + uuid4().hex).user_id

    def scalar(self, sql, params=()):
        return self.c.execute(sql, params).fetchone()[0]

    def granted(self, machine="MP1"):
        """Concesión activa creada por el servicio (con actor); devuelve (usuario, id de la fila)."""
        user = self.user()
        grant_machine_form(self.c, user_id=user, machine_code=machine, form_code=P101, actor_id=self.admin)
        return user, self.scalar("SELECT id FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (user,))

    def update(self, grant_id, revoked_by, actor="unset", **settings):
        """UPDATE directo de revocación. actor: 'unset' (sin GUC), '' (GUC vacío) o un id. settings: request_id / reason."""
        with self.c.transaction():
            if actor != "unset":
                self.c.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor),))
            for key, value in settings.items():
                self.c.execute("SELECT set_config(%s, %s, true)", (f"vinto.{key}", value))
            self.c.execute(REVOKE, (revoked_by, grant_id))

    def row(self, grant_id):
        return self.c.execute("SELECT * FROM vinto_master.user_machine_form_grant WHERE id = %s", (grant_id,)).fetchone()

    def audit(self):
        return self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'")


class RevocationActorTests(Db):
    def test_a_revocation_without_the_session_actor_is_rejected_whoever_it_names(self):
        _, g = self.granted()
        before, events = self.row(g), self.audit()
        for actor in ("unset", ""):  # sin GUC y con GUC vacío (nullif lo trata como ausente)
            for named in (self.victim, self.admin, self.operator):
                with self.assertRaises(psycopg.errors.CheckViolation, msg=(actor, named)) as raised:
                    self.update(g, named, actor=actor)
                self.assertIn("must carry the session actor", str(raised.exception))
        self.assertEqual(self.row(g), before, "la concesión sigue activa y la fila es idéntica")
        self.assertEqual(self.audit(), events, "los intentos rechazados no dejaron eventos")
        self.assertEqual(self.c.execute(UNATTRIBUTED).fetchall(), [], "la consulta de revisión no encuentra nada")

    def test_the_actor_must_still_be_the_one_named_and_then_both_stamps_follow_it(self):
        _, g = self.granted()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.update(g, self.victim, actor=self.admin)
        self.update(g, self.admin, actor=self.admin)
        row = self.c.execute("SELECT revoked_by, updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (g,)).fetchone()
        self.assertEqual(row, (self.admin, self.admin))
        event = self.c.execute("SELECT actor_id, new_data->>'revoked_by' FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant' AND action = 'UPDATE' AND entity_key->>'id' = %s", (str(g),)).fetchone()
        self.assertEqual(event, (self.admin, str(self.admin)))

    def test_the_documented_manual_procedure_works_and_is_fully_audited(self):
        """Un operador que revoca a mano declara quién es responsable en la misma transacción (actor + request_id + reason)."""
        _, g = self.granted()
        self.update(g, self.admin, actor=self.admin, request_id="manual:ticket-123", reason="manual revoke requested by Jefatura")
        event = self.c.execute("SELECT actor_id, database_actor, request_id, reason FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant' AND action = 'UPDATE' AND entity_key->>'id' = %s", (str(g),)).fetchone()
        self.assertEqual((event[0], event[2], event[3]), (self.admin, "manual:ticket-123", "manual revoke requested by Jefatura"))
        self.assertTrue(event[1], "database_actor (session_user) queda siempre registrado")

    def test_the_normal_service_still_grants_revokes_and_stays_idempotent(self):
        user = self.user()
        self.assertTrue(grant_machine_form(self.c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin, request_id="svc:grant"))
        self.assertFalse(grant_machine_form(self.c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin))
        self.assertTrue(revoke_machine_form(self.c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin, request_id="svc:revoke"))
        self.assertFalse(revoke_machine_form(self.c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin))
        self.assertTrue(grant_machine_form(self.c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin), "volver a conceder crea una fila nueva")
        self.assertEqual([g.active for g in machine_form_grants_for_user(self.c, user, include_revoked=True)], [False, True])
        (revoked, _) = machine_form_grants_for_user(self.c, user, include_revoked=True)
        self.assertEqual(revoked.revoked_by, self.admin)
        self.assertEqual(self.c.execute(UNATTRIBUTED).fetchall(), [])

    def test_an_unattributed_grant_stays_visible_as_null_not_forged(self):
        """El alta directa sin actor no atribuye a nadie (sellos NULL, auditoría con actor_id NULL): la asimetría con la revocación es deliberada porque una revocación sin responsable no es representable (CHECK de 0007)."""
        user = self.user()
        machine_id = self.scalar("SELECT id FROM vinto_master.machine WHERE code = 'MP1'")
        form_id = self.scalar("SELECT id FROM vinto_config.form WHERE code = %s", (P101,))
        g = self.c.execute("INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id) VALUES (%s,%s,%s) RETURNING id", (user, machine_id, form_id)).fetchone()[0]
        self.assertEqual(self.c.execute("SELECT created_by, updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (g,)).fetchone(), (None, None))
        self.assertIsNone(self.scalar("SELECT actor_id FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant' AND action = 'INSERT' AND entity_key->>'id' = %s", (str(g),)))

    def test_known_limit_the_actor_is_asserted_by_the_session_so_the_audit_trail_not_the_trigger_is_the_evidence(self):
        """Documenta el límite, no lo aprueba: vinto.actor_id lo escribe el cliente, así que una sesión con UPDATE puede afirmar cualquier actor. Lo que queda verdadero es
        database_actor = session_user (y request_id / reason). Probar QUIÉN pidió exige autenticación fuera de PostgreSQL (la API administrativa futura tomará el actor de la sesión autenticada)."""
        _, g = self.granted()
        self.update(g, self.victim, actor=self.victim, request_id="asserted-by-session")
        event = self.c.execute("SELECT actor_id, database_actor, request_id FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant' AND action = 'UPDATE' AND entity_key->>'id' = %s", (str(g),)).fetchone()
        self.assertEqual((event[0], event[2]), (self.victim, "asserted-by-session"))
        self.assertEqual(event[1], self.scalar("SELECT session_user"), "el usuario de base de datos real no se puede afirmar desde la sesión")


class ConcurrencyTests(Db):
    def run_threads(self, jobs):
        barrier, results, errors = threading.Barrier(len(jobs)), [None] * len(jobs), []

        def worker(index, job):
            try:
                with connect(self.db) as connection:
                    barrier.wait(timeout=20)
                    results[index] = job(connection)
            except BaseException as error:  # el rechazo esperado lo devuelve el trabajo; cualquier otra excepción falla la prueba
                errors.append(repr(error))
        threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        return results

    def test_unattributed_attempts_racing_a_service_revocation_never_win(self):
        user, g = self.granted()

        def forged(connection):
            try:
                connection.execute(REVOKE, (self.victim, g))
                return "ACCEPTED"
            except psycopg.errors.CheckViolation:
                return "rejected"

        def service(connection):
            return revoke_machine_form(connection, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin)
        results = self.run_threads([forged] * 5 + [service])
        self.assertEqual(results[:5], ["rejected"] * 5)
        self.assertIs(results[5], True)
        (only,) = machine_form_grants_for_user(self.c, user, include_revoked=True)
        self.assertEqual((only.revoked_by, self.scalar("SELECT updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (only.id,))), (self.admin, self.admin))
        self.assertEqual(self.c.execute(UNATTRIBUTED).fetchall(), [])

    def test_simultaneous_service_revocations_by_different_actors_still_record_the_winner(self):
        user, _ = self.granted()
        actors = [self.user("SUPERVISION") for _ in range(5)]
        results = self.run_threads([(lambda c, a=a: revoke_machine_form(c, user_id=user, machine_code="MP1", form_code=P101, actor_id=a)) for a in actors])
        self.assertEqual(results.count(True), 1)
        (only,) = machine_form_grants_for_user(self.c, user, include_revoked=True)
        self.assertEqual(only.revoked_by, actors[results.index(True)])


class MigrationTests(unittest.TestCase):
    def body(self, name):
        text = (MIGRATIONS / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        return re.search(r"AS \$\$(.*?)\$\$;", text, re.S).group(1)

    def test_it_is_the_ninth_migration_and_only_replaces_the_guard_function_body(self):
        migrations = read_migrations()
        self.assertEqual(migrations[8].filename, "0009_user_machine_form_grant_revocation_actor.sql")
        sql = "\n".join(line for line in (MIGRATIONS / migrations[8].filename).read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
        outside = re.sub(r"\$\$.*?\$\$", "$$", sql, flags=re.S)
        statements = [s.strip() for s in outside.split(";") if s.strip()]
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("CREATE OR REPLACE FUNCTION vinto_audit.guard_user_machine_form_grant()"))
        for forbidden in (r"\bDROP\b", r"\bALTER\b", r"\bCREATE TRIGGER\b", r"\bGRANT\b", r"\bTRUNCATE\b"):
            self.assertIsNone(re.search(forbidden, sql), forbidden)

    def test_the_new_body_is_the_old_one_plus_exactly_the_actor_requirement(self):
        added = (" IF actor IS NULL THEN\n   RAISE EXCEPTION 'A revocation must carry the session actor: %.% needs vinto.actor_id set to the user who revokes', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '23514';\n"
                 " END IF;\n")
        old, new = self.body("0008_user_machine_form_grant_integrity.sql"), self.body("0009_user_machine_form_grant_revocation_actor.sql")
        self.assertIn(added, new)
        self.assertEqual(new.replace(added, "", 1).replace(" IF NEW.revoked_by IS DISTINCT FROM actor THEN", " IF actor IS NOT NULL AND NEW.revoked_by IS DISTINCT FROM actor THEN"), old,
                         "el resto del guarda (identidad, congelado, hora del servidor, sellos) es idéntico a la 0008")

    def test_it_leaves_stored_rows_and_audit_untouched_including_a_legacy_unattributed_revocation(self):
        name = f"vinto_mfa_mig_{uuid4().hex[:10]}_test"
        create_database(name)
        self.addCleanup(drop_database, name)
        migrations = read_migrations()
        with connect(name) as c:
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(c, migrations[:8])
            reference.apply(c, load_bundle())
            mk = lambda p="OPERACION": create_user(c, username=f"mig.{uuid4().hex[:10]}", display_name=p, profile_code=p, password="pw-" + uuid4().hex).user_id  # noqa: E731
            admin, victim, a, b, d = mk("DATA_BALTREK"), mk("SUPERVISION"), mk(), mk(), mk()
            for u in (a, b, d):
                grant_machine_form(c, user_id=u, machine_code="MP1", form_code=P101, actor_id=admin)
            revoke_machine_form(c, user_id=a, machine_code="MP1", form_code=P101, actor_id=admin)  # revocación legítima
            legacy = c.execute("SELECT id FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (b,)).fetchone()[0]
            c.execute(REVOKE, (victim, legacy))  # lo que permitía la 0008: sin actor, atribuida a VICTIM
            snapshot = lambda: (c.execute("SELECT * FROM vinto_master.user_machine_form_grant ORDER BY id").fetchall(), c.execute("SELECT * FROM vinto_audit.audit_event ORDER BY id").fetchall())  # noqa: E731
            before = snapshot()
            self.assertEqual([r[1] for r in c.execute(UNATTRIBUTED).fetchall()], [str(legacy)], "bajo 0008 la consulta de revisión encuentra exactamente el caso legado")
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(c, migrations)
            validate_history(migrations, applied_migrations(c))
            self.assertEqual(snapshot(), before, "0009 no reescribe filas ni auditoría (la historia no se corrige a escondidas)")
            self.assertEqual([r[1] for r in c.execute(UNATTRIBUTED).fetchall()], [str(legacy)], "el caso legado sigue localizable para su revisión")
            active = c.execute("SELECT id FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (d,)).fetchone()[0]
            with self.assertRaises(psycopg.errors.CheckViolation), c.transaction():
                c.execute(REVOKE, (victim, active))
            self.assertTrue(revoke_machine_form(c, user_id=d, machine_code="MP1", form_code=P101, actor_id=admin), "el servicio sigue revocando")


if __name__ == "__main__":
    unittest.main()
