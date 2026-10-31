"""MF-13-01B.3: endurecimiento de las concesiones usuario-máquina-formulario (servicio + migración 0008) antes de exponer la API administrativa.

  1. Política de formularios concedibles: la MISMA que `production_access` (formulario activo, máquina y sector activos, versión publicada MÁS RECIENTE vinculada), no «alguna versión publicada».
  2. Integridad histórica: una fila revocada queda congelada, una fila activa solo cambia al revocarse, `revoked_at` es la hora del servidor, `revoked_by` es el actor de la sesión y
     `created_by` / `updated_by` no se pueden falsificar. La 0007 no se modifica: la 0008 solo reemplaza el cuerpo del trigger de guarda y añade el trigger de INSERT.

Se verifica contra PostgreSQL REAL (bases efímeras *_test) con los formularios REALES del bundle. Nada aquí toca el catálogo, un endpoint, una captura productiva, perfiles ni concesiones de sector."""

import contextlib
import dataclasses
import io
import re
import threading
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg

from app import capture_service
from app.auth.errors import FormNotLinkedToMachineError
from app.auth.machine_form_grants import (grant_machine_form, has_active_machine_form_grant, machine_form_grants_for_user,
                                          revoke_machine_form)
from app.auth.service import create_user
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, drop_database
from app.production_access import production_machines
from app.sectors import operational_sector_codes
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import applied_migrations, read_migrations, validate_history

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION_0008 = BACKEND / "migrations" / "0008_user_machine_form_grant_integrity.sql"
P101, P105, P106 = "VINTO-P1-01", "VINTO-P1-05", "VINTO-P1-06"
BUNDLE = load_bundle()
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mfh_tpl")


def tearDownModule():
    drop_database(STATE["template"])


def with_old_p105():
    """Producción tras MF-12A: P1-05 v1 publicada para MP1 y MP3 junto a la v2 (solo MP3), que es la vigente."""
    v1 = {**next(f for f in BUNDLE.forms if f["code"] == P105), "version_number": 1, "machines": ["MP1", "MP3"]}
    v1["definition_checksum"] = compute_definition_checksum(v1)
    return dataclasses.replace(BUNDLE, source_checksum="7" * 64, forms=tuple(v1 if f["code"] == P105 else f for f in BUNDLE.forms))


class Db(unittest.TestCase):
    """Una base efímera por prueba: las pruebas de política modifican el catálogo de la copia (nunca de la plantilla)."""

    old_p105 = False

    def setUp(self):
        self.db = copy_database(STATE["template"], "vinto_mfh")
        self.addCleanup(drop_database, self.db)
        self.c = connect(self.db)
        self.addCleanup(self.c.close)
        if self.old_p105:
            with contextlib.redirect_stdout(io.StringIO()):
                reference.apply(self.c, with_old_p105())
        self.admin, self.other = self.user("DATA_BALTREK"), self.user()

    def user(self, profile="OPERACION"):
        return create_user(self.c, username=f"mfh.{uuid4().hex[:12]}", display_name=profile, profile_code=profile, password="pw-" + uuid4().hex).user_id

    def scalar(self, sql, params=()):
        return self.c.execute(sql, params).fetchone()[0]

    def grant(self, user, machine="MP1", form=P101, **kw):
        return grant_machine_form(self.c, user_id=user, machine_code=machine, form_code=form, actor_id=kw.pop("actor_id", self.admin), **kw)

    def revoke(self, user, machine="MP1", form=P101, **kw):
        return revoke_machine_form(self.c, user_id=user, machine_code=machine, form_code=form, actor_id=kw.pop("actor_id", self.admin), **kw)

    def ids(self, machine="MP1", form=P101):
        return self.scalar("SELECT id FROM vinto_master.machine WHERE code = %s", (machine,)), self.scalar("SELECT id FROM vinto_config.form WHERE code = %s", (form,))

    def insert(self, user, machine="MP1", form=P101, actor=None, **columns):
        """INSERT directo; `actor` pone vinto.actor_id solo en esa transacción (sin él la sesión no tiene actor)."""
        machine_id, form_id = self.ids(machine, form)
        names = ["user_id", "machine_id", "form_id", *columns]
        with self.c.transaction():
            if actor:
                self.c.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor),))
            return self.c.execute(f"INSERT INTO vinto_master.user_machine_form_grant ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))}) RETURNING id",
                                  (user, machine_id, form_id, *columns.values())).fetchone()[0]

    def update(self, grant_id, assignment, params=(), actor=None):
        with self.c.transaction():
            if actor:
                self.c.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor),))
            self.c.execute(f"UPDATE vinto_master.user_machine_form_grant SET {assignment} WHERE id = %s", (*params, grant_id))

    def row(self, grant_id):
        return self.c.execute("SELECT * FROM vinto_master.user_machine_form_grant WHERE id = %s", (grant_id,)).fetchone()

    def audit(self):
        return self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'")


# ---- 1. política de formularios concedibles ------------------------------------------------------------------------------------------------

class GrantablePairPolicyTests(Db):
    old_p105 = True

    def test_a_link_that_only_an_older_published_version_has_does_not_count(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.status = 'published'", (P105,)), 2)
        with self.assertRaises(FormNotLinkedToMachineError) as raised:
            self.grant(self.other, "MP1", P105)  # la v1 (publicada) la vincula a MP1, pero la vigente (v2) solo a MP3
        self.assertIn("vigente", str(raised.exception))
        self.assertEqual(machine_form_grants_for_user(self.c, self.other, include_revoked=True), (), "el rechazo no dejó filas")
        self.assertTrue(self.grant(self.other, "MP3", P105))

    def test_the_effective_version_follows_the_published_state(self):
        with self.assertRaises(FormNotLinkedToMachineError):
            self.grant(self.other, "MP1", P105)
        self.c.execute("UPDATE vinto_config.form_version SET status = 'retired' WHERE id = (SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = 2)", (P105,))
        self.assertTrue(self.grant(self.other, "MP1", P105), "al retirarse la v2, la v1 pasa a ser la versión publicada vigente y vincula MP1")

    def test_a_form_without_any_published_version_cannot_be_granted(self):
        self.c.execute("UPDATE vinto_config.form_version SET status = 'retired' WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = %s)", (P105,))
        with self.assertRaises(FormNotLinkedToMachineError):
            self.grant(self.other, "MP3", P105)

    def test_an_inactive_form_machine_or_sector_cannot_be_granted(self):
        for statement, label in (("UPDATE vinto_config.form SET active = false WHERE code = 'VINTO-P1-06'", "formulario"), ("UPDATE vinto_master.machine SET active = false WHERE code = 'MP1'", "máquina"),
                                 ("UPDATE vinto_master.sector SET active = false WHERE code = 'BOBINAS'", "sector")):
            with self.subTest(label), self.c.transaction() as tx:
                self.c.execute(statement)
                with self.assertRaises(FormNotLinkedToMachineError):
                    self.grant(self.other, "MP1", P106)
                self.assertEqual(machine_form_grants_for_user(self.c, self.other, include_revoked=True), ())
                raise psycopg.Rollback(tx)  # deshace el cambio de catálogo de esta subprueba
        self.assertTrue(self.grant(self.other, "MP1", P106), "con todo activo vuelve a ser concedible")

    def test_it_is_exactly_what_production_access_offers_for_the_central_production_forms(self):
        offered = {(m.code, f.code) for s in production_machines(self.c, operational_sector_codes()).sectors for m in s.machines for f in m.forms}
        grantable = set()
        for machine in (m["code"] for m in BUNDLE.machines):
            for form in sorted(capture_service.CENTRAL_FORM_CODES):
                try:
                    if self.grant(self.other, machine, form):
                        grantable.add((machine, form))
                        self.revoke(self.other, machine, form)
                except FormNotLinkedToMachineError:
                    pass
        self.assertEqual(grantable, offered, "ni un par de más ni uno de menos que lo que ofrece /api/production/machines")
        self.assertNotIn(("MP1", P105), grantable)
        self.assertIn(("MP3", P105), grantable)

    def test_an_existing_grant_whose_pair_stops_being_offered_stays_stored_and_can_be_revoked(self):
        self.assertTrue(self.grant(self.other, "MP3", P105))
        self.c.execute("UPDATE vinto_master.machine SET active = false WHERE code = 'MP3'")
        self.assertTrue(has_active_machine_form_grant(self.c, self.other, "MP3", P105), "la fila no se borra ni se reescribe: queda inerte")
        self.assertTrue(self.revoke(self.other, "MP3", P105), "revocar no exige que el par siga ofrecido")
        (history,) = machine_form_grants_for_user(self.c, self.other, include_revoked=True)
        self.assertFalse(history.active)

    def test_checking_the_policy_never_changes_the_catalog_or_the_old_versions(self):
        queries = ("SELECT count(*) FROM vinto_config.form", "SELECT count(*) FROM vinto_config.form_version", "SELECT count(*) FROM vinto_config.form_version_machine",
                   "SELECT count(*) FROM vinto_config.form_version WHERE status = 'published'", "SELECT count(*) FROM vinto_config.field_definition")
        before = [self.scalar(q) for q in queries]
        for machine, form in (("MP1", P105), ("MP3", P105), ("MP1", P101), ("MP3", P101)):
            with contextlib.suppress(FormNotLinkedToMachineError):
                self.grant(self.other, machine, form)
        self.assertEqual([self.scalar(q) for q in queries], before)

    def test_mp1_and_mp3_stay_independent_for_the_same_form(self):
        self.assertTrue(self.grant(self.other, "MP1", P101))
        self.assertTrue(self.grant(self.other, "MP3", P101))
        self.assertTrue(self.revoke(self.other, "MP1", P101))
        self.assertTrue(has_active_machine_form_grant(self.c, self.other, "MP3", P101))
        self.assertFalse(has_active_machine_form_grant(self.c, self.other, "MP1", P101))


# ---- 2. integridad histórica (migración 0008) ----------------------------------------------------------------------------------------------

class HistoricalIntegrityTests(Db):
    def revoked_row(self):
        user = self.user()
        self.grant(user)
        self.revoke(user)
        (g,) = machine_form_grants_for_user(self.c, user, include_revoked=True)
        return user, g.id

    def test_a_grant_is_born_active(self):
        user = self.user()
        for columns in ({"revoked_at": "2999-01-01T00:00:00Z", "revoked_by": self.admin}, {"revoked_at": "2000-01-01T00:00:00Z", "revoked_by": self.admin}):
            for actor in (None, self.admin):
                with self.assertRaises(psycopg.errors.CheckViolation, msg=(columns, actor)):
                    self.insert(user, actor=actor, **columns)
        self.assertEqual(self.c.execute("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (user,)).fetchone()[0], 0)

    def test_created_by_and_updated_by_cannot_be_forged_on_insert(self):
        user = self.user()
        for columns, actor in (({"created_by": self.admin}, None), ({"updated_by": self.admin}, None), ({"created_by": self.other}, self.admin), ({"updated_by": self.other}, self.admin)):
            with self.assertRaises(psycopg.errors.CheckViolation, msg=(columns, actor)):
                self.insert(user, actor=actor, **columns)
        plain = self.insert(user)  # sin actor: nada que atribuir
        self.assertEqual(self.c.execute("SELECT created_by, updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (plain,)).fetchone(), (None, None))
        stamped = self.insert(self.user(), actor=self.admin, created_by=self.admin)  # coincide con el actor: válido
        self.assertEqual(self.c.execute("SELECT created_by, updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (stamped,)).fetchone(), (self.admin, self.admin))

    def test_the_revocation_instant_is_the_server_clock_never_the_callers(self):
        for offset in ("+ interval '10 years'", "- interval '10 years'", "+ interval '1 second'"):
            user = self.user()
            g = self.insert(user, actor=self.admin)
            t0 = self.scalar("SELECT clock_timestamp()")
            self.update(g, f"revoked_at = clock_timestamp() {offset}, revoked_by = %s", (self.admin,), actor=self.admin)
            t1 = self.scalar("SELECT clock_timestamp()")
            revoked_at, created_at = self.c.execute("SELECT revoked_at, created_at FROM vinto_master.user_machine_form_grant WHERE id = %s", (g,)).fetchone()
            self.assertTrue(t0 <= revoked_at <= t1 and revoked_at >= created_at, (offset, t0, revoked_at, t1))

    def test_revoked_by_must_be_the_session_actor(self):
        user = self.user()
        g = self.insert(user, actor=self.admin)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.update(g, "revoked_at = clock_timestamp(), revoked_by = %s", (self.other,), actor=self.admin)
        self.assertIsNone(self.scalar("SELECT revoked_at FROM vinto_master.user_machine_form_grant WHERE id = %s", (g,)), "el intento no revocó nada")
        self.update(g, "revoked_at = clock_timestamp(), revoked_by = %s", (self.admin,), actor=self.admin)
        self.assertEqual(self.c.execute("SELECT revoked_by, updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (g,)).fetchone(), (self.admin, self.admin))

    def test_a_revoked_row_cannot_change_in_any_column_and_leaves_no_trace(self):
        _, g = self.revoked_row()
        before, events = self.row(g), self.audit()
        for assignment, params in (("updated_by = %s", (self.other,)), ("updated_at = clock_timestamp()", ()), ("created_by = %s", (self.other,)), ("created_at = created_at - interval '1 day'", ()),
                                   ("revoked_at = revoked_at + interval '1 day'", ()), ("revoked_by = %s", (self.other,)), ("updated_by = updated_by", ())):
            for actor in (None, self.admin):
                with self.assertRaises(psycopg.errors.CheckViolation, msg=(assignment, actor)):
                    self.update(g, assignment, params, actor=actor)
        self.assertEqual(self.row(g), before, "la fila es idéntica, incluidas updated_at y updated_by")
        self.assertEqual(self.audit(), events, "los intentos rechazados no dejaron eventos")

    def test_an_active_row_only_changes_by_being_revoked(self):
        user = self.user()
        g = self.insert(user, actor=self.admin)
        before, events = self.row(g), self.audit()
        for assignment, params in (("updated_by = %s", (self.other,)), ("updated_at = clock_timestamp() - interval '1 day'", ()), ("created_by = %s", (self.other,)), ("created_at = created_at - interval '1 day'", ()),
                                   ("updated_by = updated_by", ())):
            with self.assertRaises(psycopg.errors.CheckViolation, msg=assignment):
                self.update(g, assignment, params, actor=self.admin)
        self.assertEqual(self.row(g), before)
        self.assertEqual(self.audit(), events)
        self.update(g, "revoked_at = clock_timestamp(), revoked_by = %s", (self.admin,), actor=self.admin)
        self.assertEqual(self.audit(), events + 1, "la revocación válida sí queda auditada")

    def test_identity_deletion_and_truncation_are_still_rejected(self):
        _, g = self.revoked_row()
        for statement in ("DELETE FROM vinto_master.user_machine_form_grant", "TRUNCATE vinto_master.user_machine_form_grant"):
            with self.assertRaises(psycopg.errors.CheckViolation), self.c.transaction():
                self.c.execute(statement)
        machine_id, _ = self.ids("MP3")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.update(g, "machine_id = %s", (machine_id,))

    def test_the_service_revocation_is_attributed_timed_and_audited_once(self):
        user = self.user()
        self.grant(user, request_id="mfh:grant")
        t0 = self.scalar("SELECT clock_timestamp()")
        self.revoke(user, request_id="mfh:revoke")
        t1 = self.scalar("SELECT clock_timestamp()")
        (g,) = machine_form_grants_for_user(self.c, user, include_revoked=True)
        self.assertEqual((g.granted_by, g.revoked_by), (self.admin, self.admin))
        self.assertTrue(t0 <= g.revoked_at <= t1)
        self.assertEqual(self.scalar("SELECT updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (g.id,)), self.admin)
        events = self.c.execute("SELECT action, actor_id, request_id, reason FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant' AND entity_key->>'id' = %s ORDER BY id", (str(g.id),)).fetchall()
        self.assertEqual(events, [("INSERT", self.admin, "mfh:grant", "machine form grant"), ("UPDATE", self.admin, "mfh:revoke", "machine form revoke")])

    def test_regranting_after_the_hardening_still_creates_a_new_row_and_keeps_the_history(self):
        user = self.user()
        self.grant(user)
        self.revoke(user)
        self.assertTrue(self.grant(user))
        self.assertEqual([g.active for g in machine_form_grants_for_user(self.c, user, include_revoked=True)], [False, True])


# ---- 3. concurrencia -----------------------------------------------------------------------------------------------------------------------

class ConcurrencyTests(Db):
    def run_threads(self, jobs):
        barrier, results, errors = threading.Barrier(len(jobs)), [None] * len(jobs), []

        def worker(index, job):
            try:
                with connect(self.db) as connection:
                    barrier.wait(timeout=20)
                    results[index] = job(connection)
            except BaseException as error:
                errors.append(repr(error))
        threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        return results

    def test_simultaneous_revocations_by_different_actors_record_exactly_the_winner(self):
        user = self.user()
        self.grant(user)
        actors = [self.user("SUPERVISION") for _ in range(6)]
        results = self.run_threads([(lambda c, a=a: revoke_machine_form(c, user_id=user, machine_code="MP1", form_code=P101, actor_id=a)) for a in actors])
        self.assertEqual(results.count(True), 1)
        (g,) = machine_form_grants_for_user(self.c, user, include_revoked=True)
        self.assertEqual(g.revoked_by, actors[results.index(True)], "revoked_by es el actor cuya llamada ganó, no el de otro hilo")
        self.assertEqual(self.scalar("SELECT updated_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (g.id,)), g.revoked_by)

    def test_simultaneous_grants_still_create_one_active_row_and_mp1_mp3_do_not_interfere(self):
        user = self.user()
        jobs = [lambda c: grant_machine_form(c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin)] * 4 \
            + [lambda c: grant_machine_form(c, user_id=user, machine_code="MP3", form_code=P101, actor_id=self.admin)] * 4
        results = self.run_threads(jobs)
        self.assertEqual(sorted(results), [False] * 6 + [True] * 2)
        self.assertEqual([(g.machine_code, g.form_code) for g in machine_form_grants_for_user(self.c, user)], [("MP1", P101), ("MP3", P101)])

    def test_a_grant_revoke_race_keeps_every_invariant(self):
        for _ in range(4):
            user = self.user()
            results = self.run_threads([(lambda c: grant_machine_form(c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin))] * 4
                                       + [(lambda c: revoke_machine_form(c, user_id=user, machine_code="MP1", form_code=P101, actor_id=self.admin))] * 4)
            rows = machine_form_grants_for_user(self.c, user, include_revoked=True)
            self.assertEqual(len(rows), results[:4].count(True))
            self.assertLessEqual(sum(g.active for g in rows), 1)
            self.assertTrue(all(g.revoked_by == self.admin for g in rows if not g.active))


# ---- 4. la migración 0008 sobre una base que ya tiene concesiones --------------------------------------------------------------------------

class MigrationTests(unittest.TestCase):
    def sql(self):
        return "\n".join(line for line in MIGRATION_0008.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))

    def test_it_is_the_eighth_migration_and_only_replaces_a_function_and_adds_a_trigger(self):
        migrations = read_migrations()
        self.assertEqual(migrations[7].filename, "0008_user_machine_form_grant_integrity.sql")
        outside_the_body = re.sub(r"\$\$.*?\$\$", "$$", self.sql(), flags=re.S)
        statements = [s.strip() for s in outside_the_body.split(";") if s.strip()]
        self.assertEqual(len(statements), 2)
        self.assertTrue(statements[0].startswith("CREATE OR REPLACE FUNCTION vinto_audit.guard_user_machine_form_grant()"))
        self.assertTrue(statements[1].startswith("CREATE TRIGGER a_guard_insert BEFORE INSERT ON vinto_master"))
        for forbidden in (r"\bDROP\b", r"\bALTER\b", r"\bTRUNCATE\b", r"\bGRANT\b", r"\bINSERT\s+INTO\b", r"\bDELETE\s+FROM\b", r"\bUPDATE\s+\S+\s+SET\b"):
            self.assertIsNone(re.search(forbidden, self.sql()), forbidden)  # mayúsculas: las sentencias SQL; los mensajes de error van en minúsculas

    def test_it_leaves_every_stored_grant_untouched_and_then_enforces_the_new_rules(self):
        name = f"vinto_mfh_mig_{uuid4().hex[:10]}_test"
        create_database(name)
        self.addCleanup(drop_database, name)
        migrations = read_migrations()
        with connect(name) as c:
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(c, migrations[:7])
            reference.apply(c, BUNDLE)
            mk = lambda p="OPERACION": create_user(c, username=f"mig.{uuid4().hex[:10]}", display_name=p, profile_code=p, password="pw-" + uuid4().hex).user_id  # noqa: E731
            admin, user = mk("DATA_BALTREK"), mk()
            for machine in ("MP1", "MP3"):
                grant_machine_form(c, user_id=user, machine_code=machine, form_code=P101, actor_id=admin)
            revoke_machine_form(c, user_id=user, machine_code="MP1", form_code=P101, actor_id=admin)
            # bajo 0007 la fila revocada aún se podía «retocar»: lo que ya está guardado debe seguir exactamente igual tras 0008
            snapshot = lambda: (c.execute("SELECT * FROM vinto_master.user_machine_form_grant ORDER BY id").fetchall(), c.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0])  # noqa: E731
            before = snapshot()
            self.assertEqual(len(before[0]), 2)
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(c, migrations)
            validate_history(migrations, applied_migrations(c))
            self.assertEqual(snapshot(), before, "0008 no cambia ninguna fila ni escribe auditoría")
            (revoked,) = [r for r in before[0] if r[8] is not None]  # revoked_at
            with self.assertRaises(psycopg.errors.CheckViolation), c.transaction():
                c.execute("UPDATE vinto_master.user_machine_form_grant SET updated_by = %s WHERE id = %s", (user, revoked[0]))
            self.assertTrue(grant_machine_form(c, user_id=user, machine_code="MP1", form_code=P101, actor_id=admin), "se puede volver a conceder (fila nueva)")
            self.assertEqual(len(machine_form_grants_for_user(c, user, include_revoked=True)), 3)


if __name__ == "__main__":
    unittest.main()
