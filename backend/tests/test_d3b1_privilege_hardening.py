"""MF-13-01D.3B.1: primer endurecimiento de privilegios (vinto_app pierde INSERT/UPDATE de tabla sobre profile, machine y sector).

Se prueban en PostgreSQL aislado los scripts REALES (backend/roles/03b_d3b1_restrict_catalog_writes.sql y rollback/ROLLBACK_D3B1.sql) sobre roles construidos con los
GRANT reales de backend/roles/02, 03 y 04 (+ la 0007): un rol de negocio (vinto_app), un rol de referencia (vinto_reference) y, para una prueba, un propietario no
superusuario (vinto_migrator). Los roles son temporales (el nombre real se sustituye) y se eliminan al terminar: no se cambia ningún privilegio persistente.
La línea base histórica de MF-13-01D.3B (tests/test_grants_hardening_design.py) no se modifica: 03_table_grants.sql sigue concediendo el conjunto amplio.
"""

import contextlib
import io
import re
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app.auth.service import create_user, deactivate_user, reactivate_user
from app.auth.sessions import InvalidSessionError, login_with_session, resolve_session, revoke_session
from app.authz import authorize
from app.authz.policies import Operation
from app.config import settings
from app.db_guard import UnsafeDatabaseError, resolve_role_url
from pydantic import SecretStr
from app.ephemeral_db import build_reference_template, connect, create_database, drop_database

try:
    import test_f3_bobbins_api as f3
    import test_grants_hardening_design as d3b
    import test_sector_revocation_sync as sync
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    import tests.test_grants_hardening_design as d3b
    import tests.test_sector_revocation_sync as sync

BACKEND = Path(__file__).resolve().parent.parent
ROLES = BACKEND / "roles"
APPLY = ROLES / "03b_d3b1_restrict_catalog_writes.sql"
ROLLBACK = ROLES / "rollback/ROLLBACK_D3B1.sql"
VERIFICATION = ROLES / "07_verification_queries.sql"
DEPLOY = BACKEND.parent / "deploy/mvp/scripts/deploy.sh"
TABLES = ("vinto_master.profile", "vinto_master.machine", "vinto_master.sector")
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d3b1_tpl")
    f3.STATE["template"] = STATE["template"]
    d3b.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


# ---- utilidades: scripts reales con el nombre de rol sustituido ----------------------------------------------------------------------------------------------------

def sql_statements(path, **roles):
    """Sentencias de un script SQL real, sin comentarios de línea completa ni meta-comandos de psql, con los nombres de rol sustituidos
    (app= para vinto_app, reference= para vinto_reference, migrator= para vinto_migrator, identity= para vinto_identity)."""
    text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(("--", "\\")))
    for placeholder, name in (("vinto_app", roles.get("app")), ("vinto_reference", roles.get("reference")), ("vinto_migrator", roles.get("migrator")),
                              ("vinto_identity", roles.get("identity"))):
        if name:
            text = re.sub(rf"\b{placeholder}\b", name, text)
    return d3b.split_sql(text)


def run(connection, statements):
    """Equivale a psql con ON_ERROR_STOP: ante el primer error se revierte la transacción abierta y se relanza."""
    try:
        for statement in statements:
            connection.execute(statement)
    except psycopg.Error:
        connection.execute("ROLLBACK")
        raise


def reference_statements(role):
    """Los privilegios REALES de vinto_reference: USAGE de 02 + la sección vinto_reference de 03."""
    schemas = re.search(r"GRANT USAGE ON SCHEMA [^;]+TO vinto_reference;", (ROLES / "02_schema_grants.sql").read_text(encoding="utf-8")).group(0)
    tables = (ROLES / "03_table_grants.sql").read_text(encoding="utf-8")
    section = tables[tables.index("-- ===== vinto_reference"):]
    body = "\n".join(line for line in section.splitlines() if not line.lstrip().startswith(("--", "\\")))
    return [s.replace("vinto_reference", role) for s in d3b.split_sql(schemas) + d3b.split_sql(body)]


def acl_snapshot(connection, role):
    """Todo privilegio concedido DIRECTAMENTE al rol sobre tablas vinto_* : {(tabla, columna|None, privilegio)}."""
    rows = connection.execute("""
        SELECT n.nspname || '.' || c.relname, NULL::text, a.privilege_type
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, LATERAL aclexplode(c.relacl) a
         WHERE n.nspname LIKE 'vinto\\_%%' AND c.relkind IN ('r', 'p') AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = %(role)s)
        UNION ALL
        SELECT n.nspname || '.' || c.relname, att.attname::text, a.privilege_type
          FROM pg_attribute att JOIN pg_class c ON c.oid = att.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace, LATERAL aclexplode(att.attacl) a
         WHERE n.nspname LIKE 'vinto\\_%%' AND att.attnum > 0 AND NOT att.attisdropped AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = %(role)s)""",
                              {"role": role}).fetchall()
    return {tuple(row) for row in rows}


class D3B1Case(d3b.RolesCase):
    FORWARD = ()  # el prototipo de D.3B.2+ no interviene: aquí solo D.3B.1, con el script real

    async def asyncSetUp(self):
        await super().asyncSetUp()  # self.current / self.business con los GRANT reales (línea base) y self.identity sin privilegios
        self.reference = f"d3b1_ref_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {self.reference} NOLOGIN NOINHERIT")
        self.addCleanup(lambda: (self.connection.execute(f"DROP OWNED BY {self.reference}"), self.connection.execute(f"DROP ROLE IF EXISTS {self.reference}")))
        for statement in reference_statements(self.reference):
            self.connection.execute(statement)

    def harden(self, role=None):
        run(self.connection, sql_statements(APPLY, app=role or self.business))

    def roll_back(self, role=None):
        run(self.connection, sql_statements(ROLLBACK, app=role or self.business))

    def columns(self, table):
        return [r[0] for r in self.connection.execute("SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum", (table,))]

    def drift_report(self):
        statement = next(s for s in sql_statements(VERIFICATION, app=self.business, reference=self.reference) if "d3b1_compliant" in s)
        cursor = self.connection.execute(statement)
        names = [d.name for d in cursor.description]
        return {row[0]: dict(zip(names, row)) for row in cursor.fetchall()}


# ---- 1. matriz de privilegios antes y después --------------------------------------------------------------------------------------------------------------------

class PrivilegeMatrixTests(D3B1Case):
    async def test_matrix_before_and_after_for_the_three_tables(self):
        before = d3b.matrix(self.connection, self.business, TABLES)
        self.assertEqual(before, {t: "SIU" for t in TABLES})  # línea base real: 03_table_grants.sql
        self.harden()
        self.assertEqual(d3b.matrix(self.connection, self.business, TABLES), {t: "S;u=(updated_at)" for t in TABLES})

    async def test_only_those_privileges_change_and_nothing_else_for_any_role(self):
        snapshots = {role: acl_snapshot(self.connection, role) for role in (self.business, self.current, self.reference, self.identity)}
        self.harden()
        after = {role: acl_snapshot(self.connection, role) for role in snapshots}
        for role in (self.current, self.reference, self.identity):
            self.assertEqual(after[role], snapshots[role], role)  # vinto_reference (y cualquier otro rol) intactos
        removed, added = snapshots[self.business] - after[self.business], after[self.business] - snapshots[self.business]
        self.assertEqual(removed, {(t, None, p) for t in TABLES for p in ("INSERT", "UPDATE")})
        self.assertEqual(added, {(t, "updated_at", "UPDATE") for t in TABLES})

    async def test_every_other_table_keeps_exactly_the_baseline_matrix(self):
        others = tuple(t for t in d3b.SENSITIVE if t not in TABLES) + ("vinto_txn.capture", "vinto_txn.bobbin", "vinto_master.device", "vinto_config.form")
        before = d3b.matrix(self.connection, self.business, others)
        self.harden()
        self.assertEqual(d3b.matrix(self.connection, self.business, others), before)

    async def test_script_reruns_leave_the_same_state(self):
        self.harden()
        first = acl_snapshot(self.connection, self.business)
        self.harden()
        self.assertEqual(acl_snapshot(self.connection, self.business), first)


# ---- 2/3. denegaciones, FOR SHARE y bloqueos del motor ---------------------------------------------------------------------------------------------------------------

class DeniedWritesTests(D3B1Case):
    async def test_insert_is_denied_on_the_three_tables_by_privilege_for_the_business_role_only(self):
        self.harden()
        for table in TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.try_as(self.business, f"INSERT INTO {table} DEFAULT VALUES"), "privilege")
                self.assertNotEqual(self.try_as(self.reference, f"INSERT INTO {table} DEFAULT VALUES"), "privilege")  # el catálogo sigue siendo de vinto_reference (falla por datos, no por permiso)

    async def test_update_of_every_functional_column_is_denied_and_only_updated_at_is_allowed(self):
        self.harden()
        for table in TABLES:
            for column in self.columns(table):
                if column == "updated_at":
                    continue
                with self.subTest(table=table, column=column):
                    self.assertEqual(self.try_as(self.business, f'UPDATE {table} SET "{column}" = "{column}"'), "privilege")
                    self.assertEqual(self.try_as(self.reference, f'UPDATE {table} SET "{column}" = "{column}"'), "allowed")
        for table in TABLES:
            with self.subTest(table=table, column="updated_at"):
                # residual conocido: la columna permitida se puede tocar (el trigger z_touch la fija y audit_changes lo registra); no cambia ningún dato de negocio
                self.assertEqual(self.try_as(self.business, f"UPDATE {table} SET updated_at = updated_at"), "allowed")

    async def test_the_named_functional_columns_are_denied(self):
        self.harden()
        for sql in ("UPDATE vinto_master.profile SET active = active", "UPDATE vinto_master.profile SET code = code", "UPDATE vinto_master.machine SET sector_id = sector_id",
                    "UPDATE vinto_master.machine SET active = active", "UPDATE vinto_master.sector SET active = active", "UPDATE vinto_master.sector SET code = code",
                    "DELETE FROM vinto_master.profile", "TRUNCATE vinto_master.sector"):
            with self.subTest(sql=sql):
                self.assertEqual(self.try_as(self.business, sql), "privilege")

    async def test_the_pre_hardening_exposure_of_the_three_tables_is_gone_but_identity_escalation_remains(self):
        """D.3B.1 NO protege todavía frente a la escalada por identidad/sesiones/concesiones: eso es D.3B.2–D.3B.4."""
        self.harden()
        results = {name: self.try_as(self.business, sql) for name, sql in self.ATTACKS.items()}
        self.assertEqual({n for n, r in results.items() if r == "privilege"}, {"profile_active", "machine_update"})
        for name in ("grant", "sector", "admin_profile", "password_hash", "forged_session", "user_active", "sector_delete"):
            self.assertEqual(results[name], "allowed", name)  # sigue pendiente, a propósito


class RowLockTests(D3B1Case):
    async def test_row_locks_still_work_with_the_column_privilege(self):
        self.harden()
        for table in TABLES:
            for clause in ("FOR SHARE", "FOR KEY SHARE", "FOR NO KEY UPDATE", "FOR UPDATE"):  # los dos últimos ya eran posibles con la línea base
                with self.subTest(table=table, clause=clause):
                    self.assertEqual(self.try_as(self.business, f"SELECT 1 FROM {table} {clause}"), "allowed")

    async def test_engine_locks_are_kept_and_block_writers_until_the_capture_ends(self):
        self.harden()
        from app.auth.service import AuthenticatedUser
        principal = AuthenticatedUser(self.operator, "u", "U", ("OPERACION",), frozenset(), False, frozenset({"BOBINAS"}))
        holder, writer = connect(self.database), connect(self.database)
        self.addCleanup(holder.close)
        self.addCleanup(writer.close)
        holder.execute(f"SET ROLE {self.business}")
        writer.execute(f"SET ROLE {self.reference}")
        writer.execute("SET lock_timeout = '400ms'")
        blocked = ("UPDATE vinto_master.profile SET active = active WHERE code = 'OPERACION'", "UPDATE vinto_master.machine SET active = active WHERE code = 'MP1'",
                   "UPDATE vinto_master.sector SET active = active WHERE id = (SELECT sector_id FROM vinto_master.machine WHERE code = 'MP1')")
        holder.execute("BEGIN")
        try:
            decision = authorize(holder, principal, Operation.PRODUCTION_CAPTURE, "MP1", "VINTO-P1-06", lock=True)  # FOR SHARE en usuario, perfiles, máquina+sector y concesión
            self.assertEqual((decision.allowed, decision.reason), (True, "ALLOWED"))
            for sql in blocked:
                with self.subTest(sql=sql):
                    with self.assertRaises(psycopg.errors.LockNotAvailable):
                        writer.execute(sql)  # la edición del catálogo espera mientras la captura mantiene sus bloqueos
        finally:
            holder.execute("COMMIT")
        for sql in blocked:
            writer.execute(sql)  # terminada la captura, el catálogo vuelve a poder editarse


class ConcurrencyTests(D3B1Case):
    async def test_concurrent_captures_catalog_writes_and_sector_revocations_never_deadlock(self):
        self.harden()
        shared = (await self.assignment())[1]
        targets = [await self.target(op, shared=shared) for op in sync.OPERATIONS]
        stop, errors = threading.Event(), []

        def catalog_writer():
            conn = connect(self.database)
            try:
                conn.execute(f"SET ROLE {self.reference}")
                conn.execute("SET lock_timeout = '5s'")
                while not stop.is_set():
                    for table in ("vinto_master.profile", "vinto_master.machine", "vinto_master.sector"):
                        try:
                            conn.execute(f"UPDATE {table} SET active = active")
                        except psycopg.Error as error:
                            errors.append(error)
                    time.sleep(0.01)
            finally:
                conn.close()
        writer = threading.Thread(target=catalog_writer)
        writer.start()
        results, threads = [], []
        for _user, runner, _http in targets:
            threads.append(self.threaded(runner, results, role=self.business))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(90)
        stop.set()
        writer.join(30)
        self.assertEqual(len(results), len(targets), results)
        self.assertTrue(all(getattr(r, "created", False) for r in results), results)
        self.assertEqual([e for e in errors if isinstance(e, psycopg.errors.DeadlockDetected)], [])
        self.assertEqual([e for e in results if isinstance(e, psycopg.errors.DeadlockDetected)], [])


# ---- 7. las cuatro capturas, autenticación y administración con el rol de negocio endurecido (rol único) ------------------------------------------------------------

class ApplicationFlowsTests(D3B1Case):
    async def test_the_four_captures_run_in_enforce(self):
        self.harden()
        for op in sync.OPERATIONS:
            with self.subTest(operation=op):
                user, runner, _ = await self.target(op)
                results = []
                thread = self.threaded(runner, results, role=self.business)
                thread.start()
                thread.join(60)
                self.assertTrue(results and getattr(results[0], "created", False), (op, results))

    async def test_login_logout_and_session_resolution_and_renewal(self):
        self.harden()
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {self.business}")
        password = "pw-" + uuid4().hex
        created = create_user(app, username=f"d3b1.{uuid4().hex[:8]}", display_name="D3B1", profile_code="OPERACION", password=password, sectors=("BOBINAS",))
        user, session = login_with_session(app, created.username, password)  # login correcto
        self.assertEqual(user.user_id, created.user_id)
        before = app.execute("SELECT last_seen_at FROM vinto_auth.session WHERE user_id = %s", (created.user_id,)).fetchone()[0]
        self.assertEqual(resolve_session(app, session.raw_token).user_id, created.user_id)  # resolución (con renovación de last_seen_at)
        after = app.execute("SELECT last_seen_at FROM vinto_auth.session WHERE user_id = %s", (created.user_id,)).fetchone()[0]
        self.assertGreaterEqual(after, before)
        self.assertTrue(revoke_session(app, session.raw_token))  # logout
        with self.assertRaises(InvalidSessionError):
            resolve_session(app, session.raw_token)

    async def test_user_administration_and_sector_and_machine_form_grants(self):
        self.harden()
        self.assertTrue(self.can_administer(self.business))  # crear usuarios, conceder/revocar sectores y máquina-formulario, login y sesión (flujo completo)
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {self.business}")
        created = create_user(app, username=f"d3b1a.{uuid4().hex[:8]}", display_name="Admin", profile_code="OPERACION", password="pw-" + uuid4().hex, sectors=("BOBINAS",))
        admin = self.users["DATA_BALTREK"][0]
        self.assertTrue(deactivate_user(app, username=created.username, actor_username=admin.username, reason="d3b1").changed)
        self.assertTrue(reactivate_user(app, username=created.username, actor_username=admin.username, reason="d3b1").changed)

    async def test_sector_revocation_still_waits_for_business_captures(self):
        self.harden()
        from app import capture_service as cs
        from app.auth.grants import grant_sector
        for op in sync.OPERATIONS:
            with self.subTest(operation=op):
                grant_sector(self.connection, user_id=self.operator, sector_code="BOBINAS", actor_id=self.admin)
                grant_sector(self.connection, user_id=self.quality_user, sector_code="BOBINAS", actor_id=self.admin)
                user, runner, _ = await self.target(op)
                inside, release, captured = threading.Event(), threading.Event(), []
                real = cs._resolve_device

                def paused(connection, device_key, machine_id, _real=real):
                    inside.set()
                    release.wait(30)
                    return _real(connection, device_key, machine_id)
                with patch.object(cs, "_resolve_device", paused):
                    capture = self.threaded(runner, captured, role=self.business)
                    capture.start()
                    self.assertTrue(inside.wait(20))
                    revoker, revoked = self.revoke(user, role=self.business)
                    revoker.start()
                    revoker.join(1.0)
                    self.assertTrue(revoker.is_alive(), "la revocación debe esperar la captura")
                    release.set()
                    capture.join(30)
                    revoker.join(30)
                self.assertTrue(captured and getattr(captured[0], "created", False), captured)
                self.assertEqual(revoked, [True])


# ---- 14. importación de referencias con vinto_reference ---------------------------------------------------------------------------------------------------------------

class ReferenceImportTests(unittest.TestCase):
    def test_vinto_reference_still_imports_the_catalog_after_the_hardening(self):
        from app.seed import reference
        from app.seed.bundle import load_bundle
        from migrate import apply as apply_migrations
        from migrate import read_migrations
        suffix = uuid4().hex[:6]
        app_role, reference_role = f"d3b1_iapp_{suffix}", f"d3b1_iref_{suffix}"
        name = create_database_name = None
        admin = connect(STATE["template"])
        self.addCleanup(admin.close)
        for role in (app_role, reference_role):
            admin.execute(f"CREATE ROLE {role} NOLOGIN NOINHERIT")
        name = f"vinto_d3b1_imp_{suffix}_test"
        create_database(name)
        self.addCleanup(lambda: drop_database(name))
        self.addCleanup(lambda: [admin.execute(f"DROP ROLE IF EXISTS {r}") for r in (app_role, reference_role)])
        with connect(name) as conn:
            with contextlib.redirect_stdout(io.StringIO()):
                apply_migrations(conn, read_migrations())
            for statement in d3b.baseline_statements(app_role) + reference_statements(reference_role):
                conn.execute(statement)
            run(conn, sql_statements(APPLY, app=app_role))
            self.assertEqual(d3b.matrix(conn, app_role, TABLES), {t: "S;u=(updated_at)" for t in TABLES})
            conn.execute(f"SET ROLE {app_role}")  # el fallback silencioso a vinto_app: la importación real NO puede ejecutarse
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                reference.apply(conn, load_bundle())
            self.assertEqual(conn.execute("SELECT count(*) FROM vinto_master.sector").fetchone()[0], 0)  # sin importación parcial
            conn.execute("RESET ROLE")
            conn.execute(f"SET ROLE {reference_role}")
            result = reference.apply(conn, load_bundle())  # importación REAL de profile, machine y sector con el rol de referencia, sobre un catálogo vacío y ya endurecido
            conn.execute("RESET ROLE")
            for table in TABLES:
                self.assertGreater(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0, table)
            conn.execute("DROP OWNED BY " + app_role)
            conn.execute("DROP OWNED BY " + reference_role)
        self.assertIsNotNone(result)


class ReferenceConnectionReadinessTests(unittest.TestCase):
    """Antes de D.3B.1 la conexión que escribe referencias debe ser vinto_reference (REFERENCE_DATABASE_URL / REFERENCE_TEST_DATABASE_URL).
    Una URL ausente que cae a vinto_app (DATABASE_URL / TEST_DATABASE_URL) NO es un despliegue listo. import_reference.py no cambia en este PR."""

    APP, REFERENCE = "postgresql://app-account@h/db", "postgresql://reference-account@h/db"  # URLs sintéticas, sin secretos

    def resolve(self, mode, reference, app, label="REFERENCE_DATABASE_URL"):
        with patch.object(settings, "pg_privilege_mode", mode):
            return resolve_role_url(SecretStr(reference) if reference else None, SecretStr(app), label=label)

    def test_legacy_mode_without_the_reference_url_silently_falls_back_to_the_application_account(self):
        resolved = self.resolve("legacy", None, self.APP)
        self.assertEqual(resolved, self.APP)  # caracterización: es exactamente el escenario que D.3B.1 rompe
        self.assertNotEqual(resolved, self.REFERENCE)

    def test_a_dedicated_reference_url_is_honoured_in_both_modes(self):
        for mode in ("legacy", "hardened"):
            with self.subTest(mode=mode):
                self.assertEqual(self.resolve(mode, self.REFERENCE, self.APP), self.REFERENCE)

    def test_hardened_mode_refuses_to_fall_back_and_does_not_leak_either_url(self):
        for reference in (None, ""):
            with self.subTest(reference=reference):
                with self.assertRaises(UnsafeDatabaseError) as raised:
                    self.resolve("hardened", reference, self.APP)
                self.assertNotIn(self.APP, str(raised.exception))
                self.assertIn("REFERENCE_DATABASE_URL", str(raised.exception))
        with self.assertRaises(UnsafeDatabaseError):
            self.resolve("hardened", None, self.APP, label="REFERENCE_TEST_DATABASE_URL")

    def test_the_importer_still_resolves_its_connection_through_the_unchanged_helper(self):
        text = (BACKEND / "import_reference.py").read_text(encoding="utf-8")
        self.assertIn('resolve_role_url(settings.reference_database_url, settings.database_url, label="REFERENCE_DATABASE_URL")', text)
        self.assertIn('resolve_role_url(settings.reference_test_database_url, settings.test_database_url,', text)
        self.assertIn('label="REFERENCE_TEST_DATABASE_URL"', text)


# ---- 15/16. guardas del script, reversión y reaprovisionamiento ----------------------------------------------------------------------------------------------------

class ScriptGuardTests(D3B1Case):
    def assert_blocked_without_changes(self, role, message, **roles):
        before = {r: acl_snapshot(self.connection, r) for r in (self.business, self.reference)}
        with self.assertRaisesRegex(psycopg.errors.RaiseException, message):
            run(self.connection, sql_statements(APPLY, app=role, **roles))
        self.assertEqual({r: acl_snapshot(self.connection, r) for r in before}, before)

    async def test_it_fails_safely_when_the_role_does_not_exist(self):
        self.assert_blocked_without_changes(f"d3b1_missing_{uuid4().hex[:6]}", "does not exist")

    async def test_it_fails_safely_for_a_superuser_role(self):
        name = f"d3b1_su_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {name} NOLOGIN SUPERUSER")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {name}"))
        self.assert_blocked_without_changes(name, "superuser")

    async def test_it_fails_safely_for_an_owner_of_the_tables(self):
        name = f"d3b1_own_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {name} NOLOGIN")
        owner = self.connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'vinto_master.sector'::regclass").fetchone()[0]
        self.addCleanup(lambda: (self.connection.execute(f"DROP OWNED BY {name}"), self.connection.execute(f"DROP ROLE IF EXISTS {name}")))  # tras devolver la propiedad
        self.connection.execute(f"ALTER TABLE vinto_master.sector OWNER TO {name}")
        self.addCleanup(lambda: self.connection.execute(f'ALTER TABLE vinto_master.sector OWNER TO "{owner}"'))
        self.connection.execute(f"GRANT SELECT ON vinto_master.profile, vinto_master.machine, vinto_master.sector TO {name}")
        self.assert_blocked_without_changes(name, "owns")

    async def test_it_requires_the_03_table_grants_to_have_run_first(self):
        name = f"d3b1_bare_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {name} NOLOGIN")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {name}"))
        self.assert_blocked_without_changes(name, "run 03_table_grants.sql first")

    async def test_it_fails_safely_when_the_updated_at_column_is_missing(self):
        self.connection.execute("ALTER TABLE vinto_master.machine RENAME COLUMN updated_at TO updated_at_x")
        self.addCleanup(lambda: self.connection.execute("ALTER TABLE vinto_master.machine RENAME COLUMN updated_at_x TO updated_at"))
        self.assert_blocked_without_changes(self.business, "no updated_at column")

    async def test_it_fails_safely_when_a_table_is_missing(self):
        self.connection.execute("ALTER TABLE vinto_master.sector RENAME TO sector_x")
        self.addCleanup(lambda: self.connection.execute("ALTER TABLE vinto_master.sector_x RENAME TO sector"))
        self.assert_blocked_without_changes(self.business, "does not exist")

    async def test_a_role_that_is_not_the_grantor_cannot_apply_a_partial_state(self):
        outsider = f"d3b1_out_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {outsider} NOLOGIN")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {outsider}"))
        before = acl_snapshot(self.connection, self.business)
        self.connection.execute(f"SET ROLE {outsider}")
        try:
            with self.assertRaises(psycopg.Error):
                run(self.connection, sql_statements(APPLY, app=self.business))
        finally:
            self.connection.execute("RESET ROLE")
        self.assertEqual(acl_snapshot(self.connection, self.business), before)


class OwnerExecutionTests(D3B1Case):
    async def test_the_scripts_run_as_a_non_superuser_owner_like_vinto_migrator(self):
        migrator = f"d3b1_mig_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {migrator} NOLOGIN")
        originals = {t: self.connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = %s::regclass", (t,)).fetchone()[0] for t in TABLES}
        self.addCleanup(lambda: (self.connection.execute(f"DROP OWNED BY {migrator}"), self.connection.execute(f"DROP ROLE IF EXISTS {migrator}")))
        for table, owner in originals.items():
            self.connection.execute(f"ALTER TABLE {table} OWNER TO {migrator}")
            self.addCleanup(lambda t=table, o=owner: self.connection.execute(f'ALTER TABLE {t} OWNER TO "{o}"'))
        self.connection.execute(f"GRANT USAGE ON SCHEMA vinto_master TO {migrator}")
        before = acl_snapshot(self.connection, self.business)
        self.connection.execute(f"SET ROLE {migrator}")
        try:
            self.harden()
            self.assertEqual(d3b.matrix(self.connection, self.business, TABLES), {t: "S;u=(updated_at)" for t in TABLES})
            self.roll_back()
        finally:
            self.connection.execute("RESET ROLE")
        self.assertEqual(acl_snapshot(self.connection, self.business), before)


class RollbackTests(D3B1Case):
    async def test_rollback_restores_the_exact_original_acl(self):
        before = {role: acl_snapshot(self.connection, role) for role in (self.business, self.reference, self.current)}
        self.harden()
        self.roll_back()
        self.assertEqual({role: acl_snapshot(self.connection, role) for role in before}, before)
        self.assertEqual(d3b.matrix(self.connection, self.business, TABLES), {t: "SIU" for t in TABLES})
        self.assertEqual({n: self.try_as(self.business, sql) for n, sql in self.ATTACKS.items()}, {n: self.try_as(self.current, sql) for n, sql in self.ATTACKS.items()})

    async def test_rollback_is_idempotent_and_harmless_when_nothing_was_hardened(self):
        before = acl_snapshot(self.connection, self.business)
        self.roll_back()
        self.roll_back()
        self.assertEqual(acl_snapshot(self.connection, self.business), before)

    async def test_hardening_and_rollback_can_alternate(self):
        for _ in range(2):
            self.harden()
            self.assertEqual(d3b.matrix(self.connection, self.business, TABLES), {t: "S;u=(updated_at)" for t in TABLES})
            self.roll_back()
            self.assertEqual(d3b.matrix(self.connection, self.business, TABLES), {t: "SIU" for t in TABLES})


def deploy_guard_query(role):
    """La consulta de solo lectura de deploy.sh::assert_identity_hardening_not_reverted_by_03, con el nombre de rol sustituido. Devuelve el texto «<d3b1> <d3b4>»."""
    match = re.search(r'pg_run_sql_inline vinto_migrator "\$migrator_pw" vinto_piloto \\\n\s+"(SELECT \(SELECT count.+?;)"\)"; then', DEPLOY.read_text(encoding="utf-8"), re.S)
    return re.sub(r"\bvinto_app\b", role, match.group(1))


class ReprovisioningDriftTests(D3B1Case):
    async def test_rerunning_03_alone_reintroduces_the_privileges_and_the_verification_query_detects_it(self):
        self.assertFalse(any(row["d3b1_compliant"] for row in self.drift_report().values()))  # antes de adoptar: no cumple
        self.harden()
        report = self.drift_report()
        self.assertEqual(sorted(report), sorted(TABLES))
        self.assertTrue(all(row["d3b1_compliant"] and not row["app_insert_tabla"] and not row["app_update_tabla"] and row["app_update_updated_at"]
                            and row["app_columnas_con_escritura_extra"] == 0 and row["reference_insert_update"] for row in report.values()))
        for statement in d3b.baseline_statements(self.business):  # re-ejecutar el procedimiento de aprovisionamiento SIN 03b (deriva)
            self.connection.execute(statement)
        drifted = self.drift_report()
        self.assertFalse(any(row["d3b1_compliant"] for row in drifted.values()))
        self.assertTrue(all(row["app_insert_tabla"] and row["app_update_tabla"] for row in drifted.values()))
        self.assertNotEqual(self.try_as(self.business, "INSERT INTO vinto_master.sector DEFAULT VALUES"), "privilege")  # el privilegio retirado volvió

    async def test_the_deploy_guard_query_counts_hardened_tables_in_each_state(self):
        """El SQL que deploy.sh ejecuta ANTES de los GRANT: 0 sin endurecer (despliegue heredado), 3 endurecido, 1 parcial, 0 si el rol no existe."""
        def count(role=None):
            a, b = self.connection.execute(deploy_guard_query(role or self.business)).fetchone()[0].split(" ")
            return int(a)  # D.3B.1; la columna D.3B.4 se prueba en test_d3b3_two_role_gate.py
        self.assertEqual(count(), 0)
        self.harden()
        self.assertEqual(count(), 3)
        self.connection.execute(f"GRANT INSERT, UPDATE ON vinto_master.sector TO {self.business}")
        self.assertEqual(count(), 2)
        self.connection.execute(f"GRANT INSERT, UPDATE ON vinto_master.machine, vinto_master.profile TO {self.business}")
        self.assertEqual(count(), 0)
        self.connection.execute(f"REVOKE UPDATE ON vinto_master.machine FROM {self.business}")  # solo UPDATE retirado también cuenta
        self.assertEqual(count(), 1)
        self.assertEqual(count(f"d3b1_absent_{uuid4().hex[:6]}"), 0)
        fresh = f"d3b1_fresh_{uuid4().hex[:6]}"  # primera ejecución de postgres-grants: el rol existe pero 03 aún no le concedió NADA => NO es «D.3B.1 aplicado»
        self.connection.execute(f"CREATE ROLE {fresh} NOLOGIN")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {fresh}"))
        self.assertEqual(count(fresh), 0)
        self.assertRegex(self.connection.execute(deploy_guard_query(self.business)).fetchone()[0], r"^[0-9]+ [0-9]+$")

    async def test_the_documented_procedure_03_then_03b_is_convergent_and_repeatable(self):
        for _ in range(2):
            for statement in d3b.baseline_statements(self.business):
                self.connection.execute(statement)
            self.harden()
            self.assertTrue(all(row["d3b1_compliant"] for row in self.drift_report().values()))
            self.assertEqual(d3b.matrix(self.connection, self.business, TABLES), {t: "S;u=(updated_at)" for t in TABLES})
        self.assertEqual(self.try_as(self.business, "INSERT INTO vinto_master.profile DEFAULT VALUES"), "privilege")


# ---- archivos: consistencia con el prototipo, la línea base histórica y el aprovisionamiento ------------------------------------------------------------------------

class ProvisioningFilesTests(unittest.TestCase):
    def test_the_script_matches_the_approved_prototype_phase(self):
        prototype = [s.replace("__BUSINESS__", "vinto_app") for s in d3b.proposal_phases()["D3B1"]]
        script = [s for s in sql_statements(APPLY) if re.match(r"(REVOKE|GRANT)\b", s)]
        self.assertEqual([re.sub(r"\s+", " ", s) for s in script], [re.sub(r"\s+", " ", s) for s in prototype])

    def test_the_scripts_only_change_privileges_of_vinto_app_and_never_data_roles_or_objects(self):
        for path in (APPLY, ROLLBACK):
            text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
            with self.subTest(script=path.name):
                self.assertNotRegex(text, r"(?i)\b(CREATE\s+ROLE|ALTER\s+ROLE|DROP\s|TRUNCATE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+vinto_|ALTER\s+TABLE|ALTER\s+DEFAULT)")
                self.assertNotIn("vinto_reference", text)
                for statement in re.findall(r"(?is)\b(?:REVOKE|GRANT)\b.*?;", text):
                    self.assertRegex(statement, r"(?i)\b(?:FROM|TO)\s+vinto_app\s*;")
                self.assertRegex(text, r"(?m)^BEGIN;$")
                self.assertRegex(text, r"(?m)^COMMIT;$")
                self.assertIn("ON_ERROR_STOP", text)

    def test_03_table_grants_still_holds_the_historical_baseline(self):
        """No se modificó 03: las pruebas de exposición de MF-13-01D.3B (y el estado anterior) dependen de que siga concediendo el conjunto amplio."""
        section = "\n".join(d3b.baseline_statements("vinto_app"))
        for table in TABLES:
            self.assertIn(table, section)
        grants = re.findall(r"GRANT SELECT, INSERT, UPDATE ON\s+(.+?)\s+TO vinto_app", section, re.S)
        self.assertTrue(any(all(t in grant for t in TABLES) for grant in grants), grants)

    def test_the_readme_orders_03b_right_after_03_and_documents_the_drift_rule(self):
        readme = (ROLES / "README.md").read_text(encoding="utf-8")
        steps = re.findall(r"^\| ([0-9]+b?) \| `([^`]+)`", readme, re.M)
        names = [name for _, name in steps]
        self.assertEqual(names[names.index("03_table_grants.sql") + 1], "03b_d3b1_restrict_catalog_writes.sql")
        self.assertIn("ROLLBACK_D3B1", readme)
        self.assertIn("d3b1_compliant", readme)
        self.assertRegex(readme, r"03\s*\+\s*03b")

    def test_the_manual_end_to_end_harness_provisions_03b_right_after_03(self):
        harness = (BACKEND / "tests/roles_e2e.py").read_text(encoding="utf-8")
        self.assertRegex(harness, r'"03_table_grants\.sql",\s*"03b_d3b1_restrict_catalog_writes\.sql"')

    def test_deploy_cannot_silently_reintroduce_or_skip_the_hardening(self):
        """deploy.sh (postgres-grants) ejecuta una lista fija de scripts. Hoy D.3B.1 NO está adoptado en el despliegue (este PR no lo toca); si alguien lo añade,
        debe ir inmediatamente después de 03 (de lo contrario 03 deshace el endurecimiento en cada re-aprovisionamiento)."""
        loop = re.search(r"for step in ([^;]+); do", DEPLOY.read_text(encoding="utf-8"))
        steps = loop.group(1).split()
        self.assertIn("03_table_grants", steps)
        if "03b_d3b1_restrict_catalog_writes" in steps:
            self.assertEqual(steps[steps.index("03_table_grants") + 1], "03b_d3b1_restrict_catalog_writes")
        # la reversión, 03b y las propuestas nunca las ejecuta el despliegue: ninguna llamada pg_run_sql_* (la guarda solo las NOMBRA en su mensaje de ayuda)
        executing = [line for line in DEPLOY.read_text(encoding="utf-8").splitlines() if "pg_run_sql_" in line and not line.lstrip().startswith("#")]
        self.assertTrue(executing)
        for line in executing:
            self.assertNotRegex(line, r"(?i)03b|rollback|proposals")
        self.assertIn("assert_identity_hardening_not_reverted_by_03", DEPLOY.read_text(encoding="utf-8"))


class Postgres17WorkflowTests(unittest.TestCase):
    """El flujo de GitHub Actions que valida en PostgreSQL 17: sin secretos, sin VPS, solo lectura y con comprobación de versión (no se ejecuta aquí)."""

    WORKFLOW = BACKEND.parent / ".github/workflows/d3b1-postgres17.yml"

    def code(self):
        return "\n".join(line for line in self.WORKFLOW.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))

    def test_it_runs_the_d3b1_tests_against_a_postgres_17_service_and_fails_on_any_other_version(self):
        code = self.code()
        self.assertRegex(code, r"(?m)image:\s*postgres:17\s*$")
        self.assertNotRegex(code, r"postgres:(1[0-6]|18|latest)")
        self.assertIn("170000 <= number < 180000", code)
        for target in ("tests.test_d3b1_privilege_hardening", "tests.test_d3b2_identity_role", "tests.test_d3b3_two_role_gate", "tests.test_grants_hardening_design", "test_postgres_grants_d3b1_guard.sh"):
            self.assertIn(target, code)
        self.assertIn('D3B3_REQUIRE_PG17: "1"', code)  # la puerta D.3B.3 solo es aprobación válida con PostgreSQL 17
        self.assertIn("upload-artifact", code)  # la evidencia de aprobación o rechazo se publica como artefacto

    def test_it_has_no_secrets_no_deployment_and_only_read_permissions(self):
        code = self.code()
        self.assertNotIn("secrets.", code)
        self.assertRegex(code, r"permissions:\s*\n\s+contents: read")
        self.assertNotRegex(code, r"(?i)\b(ssh|scp|rsync|vps|systemctl|docker login|aws |gcloud )")
        for line in code.splitlines():
            if "deploy.sh" in line:  # solo como nombre de paso o filtro de rutas; nunca ejecutado
                self.assertRegex(line.strip(), r'^(- name:|- "deploy/mvp/scripts/deploy\.sh"$)')
        self.assertNotRegex(code, r"(?i)contents:\s*write|id-token|pull_request_target")
        self.assertIn("persist-credentials: false", code)


if __name__ == "__main__":
    unittest.main()
