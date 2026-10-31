"""Grants per user, machine and form (migration 0007, MF-13-01B.1): persistence infrastructure only.

Pure tests cover the shape of the migration and that nothing in the application consumes the new table yet. The database tests run against
ephemeral *_test databases (a template with the reference bundle, so MP1, MP3 and the real published forms exist): integrity, audit, history,
idempotency, concurrency, independence of MP1 and MP3, and compatibility with 0006 and the RBAC matrix. Nothing here touches a non-test
database, a production endpoint, the form catalog or any existing grant.
"""

import contextlib
import io
import re
import threading
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg

from app.auth import permissions
from app.auth.errors import FormNotFoundError, FormNotLinkedToMachineError, MachineNotFoundError, UserNotFoundError
from app.auth.grants import grant_sector, sector_codes_for_user
from app.auth.machine_form_grants import (grant_machine_form, has_active_machine_form_grant, machine_form_grants_for_user,
                                          revoke_machine_form)
from app.auth.service import create_user
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, drop_database
from app.seed import reference
from app.seed.bundle import load_bundle
from migrate import apply as apply_migrations
from migrate import applied_migrations, read_migrations, validate_history
try:
    from test_sector_scope import PINNED_PROFILE_PERMISSIONS
except ModuleNotFoundError:
    from tests.test_sector_scope import PINNED_PROFILE_PERMISSIONS

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION = BACKEND / "migrations" / "0007_user_machine_form_grants.sql"
TABLE = "user_machine_form_grant"
P101, P102, P105 = "VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-05"  # P1-01 and P1-02 on MP1 and MP3; P1-05 only on MP3 (MF-12A)
TEMPLATE = None


def setUpModule():
    global TEMPLATE
    TEMPLATE = build_reference_template("vinto_mfg_tpl")


def tearDownModule():
    drop_database(TEMPLATE)


# ---- 1. migration shape and isolation (pure) ----------------------------------------------------------------------------------

class MigrationShapeTests(unittest.TestCase):
    def sql(self):
        return "\n".join(line for line in MIGRATION.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))

    def test_it_is_the_seventh_migration_and_nothing_before_it_moves(self):
        migrations = read_migrations()
        self.assertEqual(migrations[6].filename, "0007_user_machine_form_grants.sql")
        self.assertGreaterEqual(len(migrations), 7)  # MF-13-01B.3 adds 0008 after it; 0007 itself is never edited (its checksum is pinned in test_sector_scope)

    def test_it_is_additive_it_only_creates_and_touches_nothing_else(self):
        sql = self.sql()
        for forbidden in (r"\bDROP\b", r"\bINSERT\s+INTO\b", r"\bDELETE\s+FROM\b", r"\bUPDATE\s+\S+\s+SET\b", r"\bTRUNCATE\s+TABLE\b", r"\bCREATE\s+OR\s+REPLACE\b"):
            self.assertIsNone(re.search(forbidden, sql, re.I), forbidden)
        for statement in re.findall(r"ALTER\s+TABLE\s+(\S+)", sql, re.I):
            self.assertEqual(statement, 'vinto_master."user_machine_form_grant"')  # only the new table is ever altered

    def test_the_only_grant_is_select_insert_update_for_vinto_app_and_only_if_that_role_exists(self):
        sql = self.sql()
        grants = re.findall(r"GRANT\s+(.+?)\s+ON\s+(\S+)\s+TO\s+(\S+?);", sql, re.I)
        self.assertEqual(grants, [("SELECT, INSERT, UPDATE", 'vinto_master."user_machine_form_grant"', "vinto_app")])  # never DELETE, never another role
        self.assertRegex(sql, r"IF EXISTS \(SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app'\) THEN\s+GRANT")  # inert in legacy and *_test clusters

    def test_nothing_in_the_application_consumes_the_table_yet(self):
        consumers = []
        for path in (BACKEND / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if path.name != "machine_form_grants.py" and (TABLE in text or "machine_form_grants" in text):
                consumers.append(str(path.relative_to(BACKEND)))
        self.assertEqual(consumers, [])  # not wired to any endpoint, dependency or availability query

    def test_the_rbac_matrix_is_untouched(self):
        self.assertEqual({k: set(v) for k, v in permissions.PROFILE_PERMISSIONS.items()}, PINNED_PROFILE_PERMISSIONS)


# ---- 2. migration over an existing database (0006 -> 0007) --------------------------------------------------------------------

class MigrationOverExistingDataTests(unittest.TestCase):
    def snapshot(self, connection):
        return {
            "user_sector": connection.execute("SELECT user_id, sector_id FROM vinto_master.user_sector ORDER BY 1, 2").fetchall(),
            "user_profile": connection.execute("SELECT user_id, profile_id FROM vinto_master.user_profile ORDER BY 1, 2").fetchall(),
            "users": connection.execute('SELECT count(*) FROM vinto_master."user"').fetchone()[0],
            "audit_events": connection.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0],
            "form_version_machine": connection.execute("SELECT count(*) FROM vinto_config.form_version_machine").fetchone()[0],
        }

    def test_0007_applies_over_0006_without_changing_any_user_grant_or_row(self):
        name = f"vinto_mfg_mig_{uuid4().hex[:10]}_test"
        create_database(name)
        self.addCleanup(drop_database, name)
        migrations = read_migrations()
        with connect(name) as connection:
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(connection, migrations[:6])
            reference.apply(connection, load_bundle())
            user = create_user(connection, username=f"mig.{uuid4().hex[:8]}", display_name="Existing", profile_code="OPERACION", password="pw-" + uuid4().hex, sectors=("BOBINAS",))
            before = self.snapshot(connection)
            sectors_before = sector_codes_for_user(connection, user.user_id)
            self.assertEqual(len(applied_migrations(connection)), 6)
            self.assertIsNone(connection.execute("SELECT to_regclass('vinto_master.user_machine_form_grant')").fetchone()[0])
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(connection, migrations)
            self.assertEqual([row[0] for row in applied_migrations(connection)], list(range(1, len(migrations) + 1)))
            validate_history(migrations, applied_migrations(connection))  # checksums recorded match the files
            self.assertEqual(self.snapshot(connection), before)  # no grant, user, profile, link or audit row was added, changed or removed
            self.assertEqual(sector_codes_for_user(connection, user.user_id), sectors_before)
            self.assertEqual(connection.execute("SELECT count(*) FROM vinto_master.user_machine_form_grant").fetchone()[0], 0)  # starts empty: no implicit grants
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                apply_migrations(connection, migrations)  # re-running is a no-op
            self.assertIn("Sin migraciones pendientes", buffer.getvalue())


# ---- 3. database fixtures -----------------------------------------------------------------------------------------------------

class DatabaseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = copy_database(TEMPLATE, "vinto_mfg")
        cls.addClassCleanup(drop_database, cls.db)
        cls.connection = connect(cls.db)
        cls.addClassCleanup(cls.connection.close)
        cls.admin = cls.new_user("DATA_BALTREK")

    @classmethod
    def new_user(cls, profile="OPERACION", sectors=()):
        return create_user(cls.connection, username=f"mfg.{uuid4().hex[:12]}", display_name=f"{profile} test", profile_code=profile,
                           password="pw-" + uuid4().hex, sectors=sectors).user_id

    def scalar(self, sql, params=()):
        return self.connection.execute(sql, params).fetchone()[0]

    def rows(self, user_id):
        return self.scalar("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (user_id,))

    def grant(self, user_id, machine="MP1", form=P101, **kwargs):
        return grant_machine_form(self.connection, user_id=user_id, machine_code=machine, form_code=form, actor_id=kwargs.pop("actor_id", self.admin), **kwargs)

    def revoke(self, user_id, machine="MP1", form=P101, **kwargs):
        return revoke_machine_form(self.connection, user_id=user_id, machine_code=machine, form_code=form, actor_id=kwargs.pop("actor_id", self.admin), **kwargs)

    def ids(self, machine, form):
        return (self.scalar("SELECT id FROM vinto_master.machine WHERE code = %s", (machine,)), self.scalar("SELECT id FROM vinto_config.form WHERE code = %s", (form,)))

    def raw_revoke(self, grant_id):
        """Revocación directa como la hace un operador: con el actor de la sesión (desde la 0009 una revocación sin actor se rechaza)."""
        with self.connection.transaction():
            self.connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.admin),))
            self.connection.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE id = %s", (self.admin, grant_id))

    def raw_insert(self, user_id, machine="MP1", form=P101):
        machine_id, form_id = self.ids(machine, form)
        return self.connection.execute("INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id) VALUES (%s,%s,%s) RETURNING id",
                                       (user_id, machine_id, form_id)).fetchone()[0]


# ---- 4. integrity enforced by the database -----------------------------------------------------------------------------------

class IntegrityTests(DatabaseCase):
    def test_structure_foreign_keys_restrict_and_the_partial_unique_index(self):
        fks = self.connection.execute(
            """SELECT conname, confdeltype FROM pg_constraint WHERE conrelid = 'vinto_master.user_machine_form_grant'::regclass AND contype = 'f' ORDER BY 1""").fetchall()
        self.assertEqual(len(fks), 6)  # user, machine, form, created_by, updated_by, revoked_by
        self.assertEqual({row[1] for row in fks}, {"r"})  # ON DELETE RESTRICT everywhere
        index = self.scalar("SELECT indexdef FROM pg_indexes WHERE indexname = 'user_machine_form_grant_active_uq'")
        self.assertIn("UNIQUE", index)
        self.assertIn("(user_id, machine_id, form_id)", index)
        self.assertIn("WHERE (revoked_at IS NULL)", index)
        triggers = {row[0] for row in self.connection.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'vinto_master.user_machine_form_grant'::regclass AND NOT tgisinternal").fetchall()}
        self.assertEqual(triggers, {"a_guard", "a_guard_insert", "immutable_truncate", "z_touch", "audit_changes"})  # a_guard_insert: MF-13-01B.3 (migración 0008)

    def test_a_second_active_grant_of_the_same_triple_is_rejected_but_another_machine_or_form_is_not(self):
        user = self.new_user()
        self.raw_insert(user)
        with self.assertRaises(psycopg.errors.UniqueViolation), self.connection.transaction():
            self.raw_insert(user)
        self.raw_insert(user, "MP3", P101)  # same form, other machine
        self.raw_insert(user, "MP1", P102)  # same machine, other form
        self.assertEqual(self.rows(user), 3)

    def test_after_a_revocation_the_same_triple_can_be_granted_again_as_a_new_row(self):
        user = self.new_user()
        first = self.raw_insert(user)
        self.raw_revoke(first)
        second = self.raw_insert(user)
        self.assertNotEqual(first, second)
        self.assertEqual(self.rows(user), 2)

    def test_foreign_keys_reject_unknown_references(self):
        machine_id, form_id = self.ids("MP1", P101)
        user = self.new_user()
        for args in ((uuid4(), machine_id, form_id), (user, uuid4(), form_id), (user, machine_id, uuid4())):
            with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.connection.transaction():
                self.connection.execute("INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id) VALUES (%s,%s,%s)", args)

    def test_revoked_at_and_revoked_by_go_together(self):
        user = self.new_user()
        grant_id = self.raw_insert(user)
        for assignment, params in (("revoked_at = clock_timestamp()", ()), ("revoked_by = %s", (self.admin,))):
            with self.assertRaises(psycopg.errors.CheckViolation), self.connection.transaction():
                self.connection.execute(f"UPDATE vinto_master.user_machine_form_grant SET {assignment} WHERE id = %s", (*params, grant_id))

    def test_history_cannot_be_deleted_truncated_or_rewritten(self):
        user = self.new_user()
        grant_id = self.raw_insert(user)
        other_user = self.new_user()
        machine_id, form_id = self.ids("MP3", P102)
        for sql, params in (("DELETE FROM vinto_master.user_machine_form_grant WHERE id = %s", (grant_id,)),
                            ("TRUNCATE vinto_master.user_machine_form_grant", ()),
                            ("UPDATE vinto_master.user_machine_form_grant SET user_id = %s WHERE id = %s", (other_user, grant_id)),
                            ("UPDATE vinto_master.user_machine_form_grant SET machine_id = %s WHERE id = %s", (machine_id, grant_id)),
                            ("UPDATE vinto_master.user_machine_form_grant SET form_id = %s WHERE id = %s", (form_id, grant_id))):
            with self.assertRaises(psycopg.errors.CheckViolation, msg=sql), self.connection.transaction():
                self.connection.execute(sql, params)
        self.raw_revoke(grant_id)
        for sql in ("UPDATE vinto_master.user_machine_form_grant SET revoked_at = NULL, revoked_by = NULL WHERE id = %s",  # a revocation is final
                    "UPDATE vinto_master.user_machine_form_grant SET revoked_by = created_by WHERE id = %s"):
            with self.assertRaises(psycopg.errors.CheckViolation, msg=sql), self.connection.transaction():
                self.connection.execute(sql, (grant_id,))
        self.assertEqual(self.scalar("SELECT revoked_by FROM vinto_master.user_machine_form_grant WHERE id = %s", (grant_id,)), self.admin)


# ---- 5. service: grant, revoke, history, audit --------------------------------------------------------------------------------

class ServiceTests(DatabaseCase):
    def test_grant_is_idempotent_and_never_duplicates(self):
        user = self.new_user()
        self.assertTrue(self.grant(user))
        self.assertFalse(self.grant(user))
        self.assertEqual(self.rows(user), 1)
        self.assertTrue(has_active_machine_form_grant(self.connection, user, "MP1", P101))

    def test_revoke_is_idempotent_keeps_the_row_and_records_who_and_when(self):
        user = self.new_user()
        self.grant(user)
        self.assertTrue(self.revoke(user))
        self.assertFalse(self.revoke(user))
        self.assertFalse(has_active_machine_form_grant(self.connection, user, "MP1", P101))
        (history,) = machine_form_grants_for_user(self.connection, user, include_revoked=True)
        self.assertFalse(history.active)
        self.assertEqual((history.granted_by, history.revoked_by), (self.admin, self.admin))
        self.assertIsNotNone(history.revoked_at)
        self.assertEqual(machine_form_grants_for_user(self.connection, user), ())

    def test_granting_again_after_a_revocation_adds_a_new_row_and_keeps_the_history(self):
        user = self.new_user()
        self.grant(user)
        self.revoke(user)
        self.assertTrue(self.grant(user))
        everything = machine_form_grants_for_user(self.connection, user, include_revoked=True)
        self.assertEqual([g.active for g in everything], [False, True])
        self.assertEqual(len(machine_form_grants_for_user(self.connection, user)), 1)
        self.assertEqual(self.rows(user), 2)

    def test_p1_01_on_mp1_and_on_mp3_are_independent_grants(self):
        user = self.new_user()
        self.assertTrue(self.grant(user, "MP1", P101))
        self.assertFalse(has_active_machine_form_grant(self.connection, user, "MP3", P101))  # granting MP1 never grants MP3
        self.assertTrue(self.grant(user, "MP3", P101))
        self.assertTrue(self.revoke(user, "MP1", P101))
        self.assertFalse(has_active_machine_form_grant(self.connection, user, "MP1", P101))
        self.assertTrue(has_active_machine_form_grant(self.connection, user, "MP3", P101))  # revoking MP1 leaves MP3 intact
        self.assertEqual([(g.machine_code, g.form_code) for g in machine_form_grants_for_user(self.connection, user)], [("MP3", P101)])
        self.assertTrue(self.revoke(user, "MP3", P101))
        self.assertEqual(machine_form_grants_for_user(self.connection, user), ())

    def test_grants_are_independent_between_users_and_between_forms(self):
        first, second = self.new_user(), self.new_user()
        self.grant(first, "MP1", P101)
        self.assertFalse(has_active_machine_form_grant(self.connection, second, "MP1", P101))
        self.assertFalse(has_active_machine_form_grant(self.connection, first, "MP1", P102))  # P1-02 is not implied by P1-01 (and stays published on both machines)
        self.grant(second, "MP1", P101)
        self.revoke(first, "MP1", P101)
        self.assertTrue(has_active_machine_form_grant(self.connection, second, "MP1", P101))

    def test_unknown_references_are_rejected_without_leaving_a_row(self):
        user = self.new_user()
        with self.assertRaises(UserNotFoundError):
            self.grant(uuid4())
        with self.assertRaises(UserNotFoundError):
            self.grant("not-a-uuid")
        with self.assertRaises(MachineNotFoundError):
            self.grant(user, machine="NOPE")
        with self.assertRaises(MachineNotFoundError):
            self.grant(user, machine=None)
        with self.assertRaises(FormNotFoundError):
            self.grant(user, form="VINTO-P9-99")
        with self.assertRaises(FormNotFoundError):
            self.grant(user, form="vinto-p1-01")  # exact match: no implicit case folding
        with self.assertRaises(UserNotFoundError):
            self.grant(user, actor_id="not-a-uuid")
        with self.assertRaises(MachineNotFoundError):
            self.revoke(user, machine="NOPE")
        self.assertEqual(self.rows(user), 0)

    def test_a_pair_the_catalog_does_not_offer_is_rejected(self):
        user = self.new_user()
        with self.assertRaises(FormNotLinkedToMachineError):
            self.grant(user, "MP1", P105)  # P1-05 is published only for MP3 (MF-12A)
        self.assertTrue(self.grant(user, "MP3", P105))
        self.assertEqual(self.rows(user), 1)

    def test_the_actor_is_mandatory(self):
        user = self.new_user()
        with self.assertRaises(TypeError):
            grant_machine_form(self.connection, user_id=user, machine_code="MP1", form_code=P101)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            revoke_machine_form(self.connection, user_id=user, machine_code="MP1", form_code=P101)  # type: ignore[call-arg]
        self.assertEqual(self.rows(user), 0)

    def test_queries_with_unknown_values_are_false_not_errors(self):
        user = self.new_user()
        self.assertFalse(has_active_machine_form_grant(self.connection, user, "NOPE", P101))
        self.assertFalse(has_active_machine_form_grant(self.connection, "not-a-uuid", "MP1", P101))
        self.assertFalse(has_active_machine_form_grant(self.connection, user, None, None))

    def test_every_grant_and_revocation_is_audited_with_actor_request_and_reason(self):
        user = self.new_user()
        request = f"test:{uuid4().hex}"
        self.grant(user, request_id=request)
        self.revoke(user, request_id=request + ":revoke")
        events = self.connection.execute(
            """SELECT action, actor_id, request_id, reason, new_data->>'user_id', new_data->>'revoked_by' FROM vinto_audit.audit_event
               WHERE entity_table = 'user_machine_form_grant' AND new_data->>'user_id' = %s ORDER BY id""", (str(user),)).fetchall()
        self.assertEqual([(e[0], e[1], e[2], e[3]) for e in events],
                         [("INSERT", self.admin, request, "machine form grant"), ("UPDATE", self.admin, request + ":revoke", "machine form revoke")])
        self.assertEqual(events[1][5], str(self.admin))
        created_by = self.scalar("SELECT created_by FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (user,))
        self.assertEqual(created_by, self.admin)  # touch_row stamps the actor

    def test_a_rejected_grant_is_not_audited(self):
        user = self.new_user()
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'")
        with self.assertRaises(FormNotLinkedToMachineError):
            self.grant(user, "MP1", P105)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'"), before)


# ---- 6. compatibility with 0006 and the RBAC model (no implicit authorization) ------------------------------------------------

class NoImplicitAuthorizationTests(DatabaseCase):
    def test_a_new_user_has_no_machine_form_grants(self):
        self.assertEqual(machine_form_grants_for_user(self.connection, self.new_user("OPERACION", sectors=("BOBINAS",))), ())

    def test_sector_grants_do_not_create_machine_form_grants_and_the_other_way_round(self):
        user = self.new_user()
        grant_sector(self.connection, user_id=user, sector_code="BOBINAS", actor_id=self.admin)
        self.assertEqual(self.rows(user), 0)  # a sector grant implies no machine/form grant
        sectors_before = sector_codes_for_user(self.connection, user)
        self.grant(user, "MP3", P101)
        self.assertEqual(sector_codes_for_user(self.connection, user), sectors_before)  # a machine/form grant implies no sector
        lonely = self.new_user()
        self.grant(lonely, "MP1", P101)
        self.assertEqual(sector_codes_for_user(self.connection, lonely), frozenset())  # and by itself opens no sector

    def test_granting_does_not_change_profiles_or_permissions(self):
        user = self.new_user("CALIDAD")
        profiles = lambda: self.connection.execute(  # noqa: E731
            "SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id WHERE up.user_id = %s ORDER BY 1", (user,)).fetchall()
        before = profiles()
        self.grant(user, "MP1", P101)
        self.revoke(user, "MP1", P101)
        self.assertEqual(profiles(), before)
        self.assertEqual({k: set(v) for k, v in permissions.PROFILE_PERMISSIONS.items()}, PINNED_PROFILE_PERMISSIONS)

    def test_the_catalog_and_the_user_sector_table_are_not_touched_by_granting(self):
        user = self.new_user("OPERACION", sectors=("BOBINAS",))
        queries = ("SELECT count(*) FROM vinto_config.form", "SELECT count(*) FROM vinto_config.form_version", "SELECT count(*) FROM vinto_config.form_version_machine",
                   "SELECT count(*) FROM vinto_master.user_sector")
        before = [self.scalar(q) for q in queries]
        self.grant(user, "MP1", P101)
        self.grant(user, "MP3", P101)
        self.revoke(user, "MP1", P101)
        self.assertEqual([self.scalar(q) for q in queries], before)


# ---- 7. concurrency (separate connections, released at the same instant) ------------------------------------------------------

class ConcurrencyTests(DatabaseCase):
    def run_threads(self, jobs):
        barrier, results, errors = threading.Barrier(len(jobs)), [None] * len(jobs), []

        def worker(index, job):
            try:
                with connect(self.db) as connection:
                    barrier.wait(timeout=20)
                    results[index] = job(connection)
            except BaseException as error:  # collected, not swallowed: the test fails on any
                errors.append(repr(error))
        threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        return results

    def grant_job(self, user, machine="MP1", form=P101):
        return lambda c: grant_machine_form(c, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin)

    def revoke_job(self, user, machine="MP1", form=P101):
        return lambda c: revoke_machine_form(c, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin)

    def test_simultaneous_identical_grants_create_exactly_one_active_row(self):
        user = self.new_user()
        results = self.run_threads([self.grant_job(user)] * 8)
        self.assertEqual(sorted(results), [False] * 7 + [True])
        self.assertEqual(self.rows(user), 1)

    def test_simultaneous_identical_revocations_succeed_exactly_once(self):
        user = self.new_user()
        self.grant(user)
        results = self.run_threads([self.revoke_job(user)] * 8)
        self.assertEqual(sorted(results), [False] * 7 + [True])
        (only,) = machine_form_grants_for_user(self.connection, user, include_revoked=True)
        self.assertFalse(only.active)

    def test_concurrent_grants_on_mp1_and_mp3_do_not_interfere(self):
        user = self.new_user()
        results = self.run_threads([self.grant_job(user, "MP1")] * 4 + [self.grant_job(user, "MP3")] * 4)
        self.assertEqual(sorted(results), [False] * 6 + [True] * 2)
        self.assertEqual([(g.machine_code, g.form_code) for g in machine_form_grants_for_user(self.connection, user)], [("MP1", P101), ("MP3", P101)])

    def test_revoking_one_machine_while_granting_the_other_keeps_both_consistent(self):
        user = self.new_user()
        self.grant(user, "MP1")
        self.run_threads([self.revoke_job(user, "MP1")] * 3 + [self.grant_job(user, "MP3")] * 3)
        active = [(g.machine_code, g.form_code) for g in machine_form_grants_for_user(self.connection, user)]
        self.assertEqual(active, [("MP3", P101)])  # MP1 revoked, MP3 granted, nothing else

    def test_a_grant_revoke_race_never_leaves_two_active_rows_or_an_unattributed_revocation(self):
        for _ in range(5):
            user = self.new_user()
            results = self.run_threads([self.grant_job(user)] * 4 + [self.revoke_job(user)] * 4)
            granted = results[:4].count(True)
            active = self.scalar("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id = %s AND revoked_at IS NULL", (user,))
            self.assertLessEqual(active, 1)
            self.assertEqual(self.rows(user), granted)  # every successful grant is exactly one row
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id = %s AND (revoked_at IS NULL) <> (revoked_by IS NULL)", (user,)), 0)


if __name__ == "__main__":
    unittest.main()
