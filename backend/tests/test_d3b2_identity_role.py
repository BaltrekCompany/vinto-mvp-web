"""MF-13-01D.3B.2: integración del rol de identidad (login, logout, administración de usuarios y concesiones, CLI) sin revocar todavía nada a vinto_app (eso es D.3B.4).

Se prueba contra PostgreSQL aislado con roles construidos con los GRANT REALES (backend/roles/02, 03, 03c y la 0007):
  - los scripts 00c / 03c / ROLLBACK_D3B2 (aditivos, idempotentes, con guardas) y su coincidencia con la fase D3B2 del prototipo aprobado;
  - la capa de conexión: IDENTITY_DATABASE_URL ausente = comportamiento anterior; presente = solo esa URL; con fallo, 503 seguro y NUNCA retroceso a DATABASE_URL;
  - el cableado: login/logout/admin con la conexión de identidad; resolución de sesiones y resto del negocio con la de negocio;
  - la revalidación del actor dentro de la transacción de la escritura (revocación concurrente) sin interbloqueos;
  - la API completa con ROLES LOGIN reales (session_user distinto en cada conexión) en tres estados: URL sin definir, URL definida, y URL definida con el corte D.3B.4 ya aplicado
    en la base de PRUEBA (la evidencia de que el corte no rompe nada; en el código y los scripts del repositorio el corte NO se aplica);
  - los CLI con la conexión de identidad.
Los roles son temporales y se eliminan al terminar.
"""

import ast
import contextlib
import io
import logging
import os
import re
import secrets
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from app import database
from app.admin import grants_write
from app.admin import service as admin_service
from app.admin.actor import require_actor_authorized
from app.admin.errors import ActorNotAuthorized
from app.auth.dependencies import current_user
from app.auth.permissions import USER_MANAGE
from app.auth.service import AuthenticatedUser, create_user, deactivate_user
from app.config import settings
from app.database import DatabaseUnavailable, get_identity_connection, identity_connection_mode, open_connection, open_identity_connection
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.main import app

try:
    import create_user as create_user_cli
    import manage_user as manage_user_cli
    import test_assignments_api as asg
    import test_d3b1_privilege_hardening as d1
    import test_f3_bobbins_api as f3
    import test_grants_hardening_design as d3b
    import test_sector_revocation_sync as sync
except ModuleNotFoundError:
    import create_user as create_user_cli
    import manage_user as manage_user_cli
    import tests.test_assignments_api as asg
    import tests.test_d3b1_privilege_hardening as d1
    import tests.test_f3_bobbins_api as f3
    import tests.test_grants_hardening_design as d3b
    import tests.test_sector_revocation_sync as sync

BACKEND = Path(__file__).resolve().parent.parent
ROLES = BACKEND / "roles"
CREATE_ROLE = ROLES / "00c_create_identity_role.sql"
GRANTS = ROLES / "03c_d3b2_identity_role_grants.sql"
ROLLBACK = ROLES / "rollback/ROLLBACK_D3B2.sql"
DEPLOY = BACKEND.parent / "deploy/mvp/scripts/deploy.sh"
ORIGIN = settings.cors_origins[0]
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d3b2_tpl")
    for module in (f3, d3b, d1):
        module.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


# ---- 1. capa de conexión (sin base de datos: psycopg.connect simulado, URLs sintéticas con centinelas) ---------------------------------------------------------------

APP_URL = "postgresql://app_acct:APP-SENTINEL-1@app-host/db"
IDN_URL = "postgresql://idn_acct:IDN-SENTINEL-2@idn-host/db"


class ConnectionLayerTests(unittest.TestCase):
    def patches(self, database_value=APP_URL, identity=IDN_URL):
        return (patch.object(settings, "database_url", SecretStr(database_value) if database_value is not None else None),
                patch.object(settings, "identity_database_url", SecretStr(identity) if identity is not None else None))

    def calls(self, function, database_value=APP_URL, identity=IDN_URL, side_effect=None):
        first, second = self.patches(database_value, identity)
        with first, second, patch.object(database.psycopg, "connect", side_effect=side_effect, return_value=MagicMock()) as connect_mock:
            try:
                function()
            except BaseException as error:  # noqa: BLE001
                return connect_mock.call_args_list, error
            return connect_mock.call_args_list, None

    def test_without_the_variable_the_identity_connection_is_exactly_the_previous_connection(self):
        for identity in (None, ""):
            with self.subTest(identity=identity):
                legacy, _ = self.calls(open_connection, identity=identity)
                shared, _ = self.calls(open_identity_connection, identity=identity)
                self.assertEqual(shared, legacy)
                self.assertEqual(shared[0].args[0], APP_URL)  # misma URL y mismos parámetros (timeouts, autocommit, statement_timeout)
                first, second = self.patches(identity=identity)
                with first, second:
                    self.assertEqual(identity_connection_mode(), "shared")

    def test_with_the_variable_only_that_url_is_used(self):
        calls, error = self.calls(open_identity_connection)
        self.assertIsNone(error)
        self.assertEqual([c.args[0] for c in calls], [IDN_URL])
        legacy, _ = self.calls(open_connection)
        self.assertEqual({k: v for k, v in calls[0].kwargs.items()}, {k: v for k, v in legacy[0].kwargs.items()})  # mismos timeouts y autocommit
        first, second = self.patches()
        with first, second:
            self.assertEqual(identity_connection_mode(), "dedicated")

    def test_a_failing_dedicated_url_never_falls_back_to_the_application_url_and_leaks_nothing(self):
        for side_effect in (psycopg.OperationalError("connection failed IDN-SENTINEL-2 APP-SENTINEL-1"), ValueError("bad conninfo IDN-SENTINEL-2")):
            with self.subTest(error=type(side_effect).__name__):
                first, second = self.patches()
                with first, second, patch.object(database.psycopg, "connect", side_effect=side_effect) as connect_mock, self.assertLogs("uvicorn.error", level="WARNING") as logs:
                    with self.assertRaises(DatabaseUnavailable) as raised:
                        open_identity_connection()
                self.assertEqual([c.args[0] for c in connect_mock.call_args_list], [IDN_URL])  # un solo intento, jamás con APP_URL
                text = str(raised.exception) + "\n".join(logs.output)
                for sentinel in ("IDN-SENTINEL-2", "APP-SENTINEL-1", "idn_acct", "app_acct", "idn-host"):
                    self.assertNotIn(sentinel, text)

    def test_the_dedicated_url_does_not_need_database_url_but_shared_mode_without_it_is_unavailable(self):
        calls, error = self.calls(open_identity_connection, database_value=None)
        self.assertIsNone(error)
        self.assertEqual([c.args[0] for c in calls], [IDN_URL])
        calls, error = self.calls(open_identity_connection, database_value=None, identity=None)
        self.assertIsInstance(error, DatabaseUnavailable)  # igual que open_connection sin DATABASE_URL
        self.assertEqual(calls, [])

    def test_the_dependency_yields_one_connection_and_always_closes_it(self):
        first, second = self.patches()
        with first, second, patch.object(database.psycopg, "connect", return_value=MagicMock()) as connect_mock:
            generator = get_identity_connection()
            connection = next(generator)
            self.assertIs(connection, connect_mock.return_value)
            with self.assertRaises(StopIteration):
                next(generator)
            connection.close.assert_called_once()

    def test_the_mode_is_logged_once_without_urls(self):
        database._identity_mode_logged.clear()
        first, second = self.patches()
        with first, second, patch.object(database.psycopg, "connect", return_value=MagicMock()), self.assertLogs("uvicorn.error", level="INFO") as logs:
            open_identity_connection()
            open_identity_connection()
        lines = [line for line in logs.output if "identity connection mode" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("dedicated", lines[0])
        self.assertNotIn("SENTINEL", lines[0])
        database._identity_mode_logged.clear()


# ---- 2. cableado: qué ruta usa qué conexión (análisis estático) ----------------------------------------------------------------------------------------------------

def connection_dependencies(path):
    """{función: nombre del Depends del parámetro `connection`} de un módulo."""
    found = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef):
            args = node.args
            defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults) + list(args.kw_defaults)
            for arg, default in zip(args.args + args.kwonlyargs, defaults[:len(args.args)] + list(args.kw_defaults)):
                if arg.arg == "connection" and isinstance(default, ast.Call) and getattr(default.func, "id", "") == "Depends" and default.args:
                    found[node.name] = getattr(default.args[0], "id", "?")
    return found


class WiringTests(unittest.TestCase):
    def test_login_and_every_admin_route_use_the_identity_connection(self):
        self.assertEqual(connection_dependencies(BACKEND / "app/auth/router.py"), {"login": "get_identity_connection"})
        admin = connection_dependencies(BACKEND / "app/admin/router.py")
        self.assertGreaterEqual(len(admin), 12)
        self.assertEqual(set(admin.values()), {"get_identity_connection"})

    def test_logout_opens_the_identity_connection_inside_the_handler(self):
        tree = ast.parse((BACKEND / "app/auth/router.py").read_text(encoding="utf-8"))
        logout = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "logout")
        called = {getattr(n.func, "id", "") for n in ast.walk(logout) if isinstance(n, ast.Call)}
        self.assertIn("open_identity_connection", called)
        self.assertNotIn("open_connection", called)

    def test_session_resolution_and_the_rest_of_the_business_keep_the_business_connection(self):
        self.assertEqual(connection_dependencies(BACKEND / "app/auth/dependencies.py"), {"current_user": "get_connection"})
        for relative in ("app/captures.py", "app/bobbins/router.py", "app/quality/router.py", "app/quality/machine_router.py", "app/work_orders/router.py", "app/assignments/router.py"):
            with self.subTest(module=relative):
                text = (BACKEND / relative).read_text(encoding="utf-8")
                self.assertNotIn("identity_connection", text)

    def test_identity_connections_are_only_requested_from_the_identity_entry_points(self):
        users = {str(p.relative_to(BACKEND)).replace("\\", "/") for p in (BACKEND / "app").rglob("*.py") if "identity_connection" in p.read_text(encoding="utf-8")}
        self.assertEqual(users, {"app/database.py", "app/auth/router.py", "app/admin/router.py"})

    def test_the_cli_use_the_identity_settings(self):
        for module in ("manage_user.py", "create_user.py"):
            text = (BACKEND / module).read_text(encoding="utf-8")
            self.assertIn("identity_database_url", text, module)
            self.assertIn("identity_test_database_url", text, module)

    def test_the_new_scripts_are_not_run_by_the_deployment(self):
        executing = [line for line in DEPLOY.read_text(encoding="utf-8").splitlines() if ("pg_run_sql_" in line or "for step in" in line) and not line.lstrip().startswith("#")]
        for line in executing:
            self.assertNotRegex(line, r"(?i)00c|03c|ROLLBACK_D3B2|identity")


class CliSelectionTests(unittest.TestCase):
    """Qué conexión abre cada CLI. psycopg y connect_test_database simulados; URLs sintéticas."""

    def test_dev_target_uses_the_identity_url_when_defined_and_the_application_url_otherwise(self):
        for module in (create_user_cli, manage_user_cli):
            for identity, expected in ((IDN_URL, IDN_URL), (None, APP_URL), ("", APP_URL)):
                with self.subTest(cli=module.__name__, identity=identity):
                    with patch.object(settings, "database_url", SecretStr(APP_URL)), \
                            patch.object(settings, "identity_database_url", SecretStr(identity) if identity is not None else None), \
                            patch.object(module.psycopg, "connect", return_value=MagicMock()) as connect_mock, \
                            patch.object(manage_user_cli, "assert_dev_target_authorized", return_value="x"):
                        module.open_connection("dev")
                    self.assertEqual([c.args[0] for c in connect_mock.call_args_list], [expected])

    def test_dev_target_with_a_failing_identity_url_does_not_fall_back(self):
        for module in (create_user_cli, manage_user_cli):
            with self.subTest(cli=module.__name__):
                with patch.object(settings, "database_url", SecretStr(APP_URL)), patch.object(settings, "identity_database_url", SecretStr(IDN_URL)), \
                        patch.object(module.psycopg, "connect", side_effect=psycopg.OperationalError("down")) as connect_mock:
                    with self.assertRaises(psycopg.OperationalError):
                        module.open_connection("dev")
                self.assertEqual([c.args[0] for c in connect_mock.call_args_list], [IDN_URL])

    def test_test_target_uses_identity_test_url_when_defined_and_test_database_url_otherwise(self):
        for module in (create_user_cli, manage_user_cli):
            for identity, expected in ((IDN_URL, IDN_URL), (None, None)):
                with self.subTest(cli=module.__name__, identity=identity):
                    with patch.object(settings, "identity_test_database_url", SecretStr(identity) if identity is not None else None), \
                            patch.object(module, "connect_test_database", return_value=MagicMock()) as guard:
                        module.open_connection("test")
                    self.assertEqual(guard.call_args.args[0] if guard.call_args.args else None, expected)  # None = TEST_DATABASE_URL, como antes


# ---- 3. scripts SQL: 00c, 03c y ROLLBACK_D3B2 ---------------------------------------------------------------------------------------------------------------------------

class IdentityScriptsTests(d1.D3B1Case):
    def grant(self, identity=None, business=None):
        d1.run(self.connection, d1.sql_statements(GRANTS, app=business or self.business, identity=identity or self.identity))

    def roll_back(self, identity=None):
        d1.run(self.connection, d1.sql_statements(ROLLBACK, app=self.business, identity=identity or self.identity))

    def explicit_connect(self, role):
        """CONNECT concedido EXPLÍCITAMENTE al rol (en estas bases PUBLIC conserva CONNECT por defecto; en producción 01_database_grants.sql lo revoca)."""
        return self.connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_database d, LATERAL aclexplode(d.datacl) a WHERE d.datname = current_database() AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = %s) AND a.privilege_type = 'CONNECT')",
            (role,)).fetchone()[0]

    async def test_the_grants_are_exactly_the_approved_prototype_phase_and_only_grants(self):
        prototype = [re.sub(r"\s+", " ", s.replace("__IDENTITY__", "vinto_identity")) for s in d3b.proposal_phases()["D3B2"]]
        statements = d1.sql_statements(GRANTS)
        top_level = [re.sub(r"\s+", " ", s) for s in statements if re.match(r"GRANT\b", s)]
        self.assertEqual([s for s in top_level if "CONNECT" not in s], prototype)
        for path in (GRANTS, CREATE_ROLE, ROLLBACK):
            text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
            self.assertNotRegex(text, r"(?i)\b(DROP\s|TRUNCATE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+vinto_|ALTER\s+TABLE|ALTER\s+DEFAULT)", path.name)
        grants_only = "\n".join(line for line in GRANTS.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
        self.assertNotRegex(grants_only, r"(?i)\bREVOKE\b")  # aditivo: no revoca nada (D.3B.4 es otra fase)

    async def test_it_gives_the_identity_role_exactly_the_prototype_privileges_and_changes_nothing_else(self):
        before = {role: d1.acl_snapshot(self.connection, role) for role in (self.business, self.current, self.reference)}
        prototype_role = f"d3b2_proto_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {prototype_role} NOLOGIN NOINHERIT")
        self.addCleanup(lambda: (self.connection.execute(f"DROP OWNED BY {prototype_role}"), self.connection.execute(f"DROP ROLE IF EXISTS {prototype_role}")))
        for statement in d3b.phase_statements(("D3B2",), self.business, prototype_role):
            self.connection.execute(statement)
        self.grant()
        self.assertEqual(d1.acl_snapshot(self.connection, self.identity), d1.acl_snapshot(self.connection, prototype_role))
        self.assertTrue(self.explicit_connect(self.identity))
        for role, snapshot in before.items():
            self.assertEqual(d1.acl_snapshot(self.connection, role), snapshot, role)  # vinto_app (y los demás) intactos: no se revoca nada

    async def test_it_is_idempotent(self):
        self.grant()
        first = d1.acl_snapshot(self.connection, self.identity)
        self.grant()
        self.assertEqual(d1.acl_snapshot(self.connection, self.identity), first)

    async def test_the_identity_role_can_run_the_flows_and_is_not_more_powerful_than_designed(self):
        self.grant()
        self.assertTrue(self.can_administer(self.identity))
        self.assertEqual(self.try_as(self.identity, "DELETE FROM vinto_audit.audit_event"), "privilege")
        self.assertEqual(self.try_as(self.identity, "UPDATE vinto_audit.audit_event SET reason = 'x'"), "privilege")
        self.assertEqual(self.try_as(self.identity, "DELETE FROM vinto_master.user_machine_form_grant"), "privilege")
        self.assertEqual(self.try_as(self.identity, "INSERT INTO vinto_txn.work_order (machine_id, order_number) VALUES (gen_random_uuid(), 'X')"), "privilege")
        self.assertEqual(self.try_as(self.identity, "INSERT INTO vinto_master.sector DEFAULT VALUES"), "privilege")

    async def test_the_scripts_fail_safely_without_the_role_or_with_a_powerful_one(self):
        before = d1.acl_snapshot(self.connection, self.business)
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "does not exist"):
            self.grant(identity=f"d3b2_missing_{uuid4().hex[:6]}")
        powerful = f"d3b2_pow_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {powerful} NOLOGIN CREATEDB")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {powerful}"))
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "must not be superuser"):
            self.grant(identity=powerful)
        self.assertEqual(d1.acl_snapshot(self.connection, powerful), set())
        self.assertEqual(d1.acl_snapshot(self.connection, self.business), before)

    async def test_rollback_removes_the_identity_privileges_and_is_idempotent(self):
        before = {role: d1.acl_snapshot(self.connection, role) for role in (self.business, self.reference)}
        self.grant()
        self.assertTrue(d1.acl_snapshot(self.connection, self.identity))
        self.roll_back()
        self.assertEqual(d1.acl_snapshot(self.connection, self.identity), set())
        self.assertFalse(self.explicit_connect(self.identity))
        self.roll_back()
        self.assertEqual({role: d1.acl_snapshot(self.connection, role) for role in before}, before)
        self.assertTrue(self.can_administer(self.business))  # la reversión nunca deja sin administración al sistema

    async def test_rollback_refuses_while_the_cut_is_applied_so_that_someone_can_always_administer(self):
        self.grant()
        self.apply("D3B4")  # el corte (solo en esta base de prueba)
        kept = d1.acl_snapshot(self.connection, self.identity)
        self.assertEqual((self.can_administer(self.business), self.can_administer(self.identity)), (False, True))
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "ROLLBACK_D3B4 first"):
            self.roll_back()
        self.assertEqual(d1.acl_snapshot(self.connection, self.identity), kept)
        self.assertTrue(self.can_administer(self.identity))
        self.apply("ROLLBACK_D3B4")
        self.roll_back()
        self.assertTrue(self.can_administer(self.business))

    async def test_creation_script_and_readme_are_consistent(self):
        text = CREATE_ROLE.read_text(encoding="utf-8")
        for required in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOINHERIT", "\\getenv identity_password IDENTITY_PASSWORD", "mf-13-01d3b2:"):
            self.assertIn(required, text)
        self.assertNotRegex(text, r"PASSWORD\s+'[^']")  # ninguna contraseña literal
        readme = (ROLES / "README.md").read_text(encoding="utf-8")
        names = [m.group(2) for m in re.finditer(r"^\| ([0-9]+[a-z]?) \| `([^`]+)`", readme, re.M)]
        self.assertIn("00c_create_identity_role.sql", names)
        self.assertEqual(names[names.index("03b_d3b1_restrict_catalog_writes.sql") + 1], "03c_d3b2_identity_role_grants.sql")
        self.assertIn("ROLLBACK_D3B2", readme)
        self.assertIn("IDENTITY_DATABASE_URL", readme)


# ---- 4. revocación concurrente del actor y bloqueos ---------------------------------------------------------------------------------------------------------------------

class ActorRecheckTests(d1.D3B1Case):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        d1.run(self.connection, d1.sql_statements(GRANTS, app=self.business, identity=self.identity))
        self.admin1 = self.users["DATA_BALTREK"][0]
        self.admin2 = create_user(self.connection, username=f"d3b2.admin2.{uuid4().hex[:6]}", display_name="Admin 2", profile_code="DATA_BALTREK",
                                  password="pw-" + uuid4().hex, sectors=("BOBINAS",))
        self.target_user = create_user(self.connection, username=f"d3b2.target.{uuid4().hex[:6]}", display_name="Target", profile_code="OPERACION",
                                       password="pw-" + uuid4().hex, sectors=("BOBINAS",)).user_id  # sin REBOBINADO ni concesiones de máquina-formulario

    def identity_connection(self):
        conn = connect(self.database)
        conn.execute(f"SET ROLE {self.identity}")
        self.addCleanup(conn.close)
        return conn

    def sector_rows(self, user_id):
        return self.connection.execute("SELECT count(*) FROM vinto_master.user_sector us JOIN vinto_master.sector s ON s.id = us.sector_id WHERE us.user_id = %s AND s.code = 'REBOBINADO'", (user_id,)).fetchone()[0]

    async def test_a_valid_administrator_still_changes_grants_with_the_identity_role(self):
        conn = self.identity_connection()
        result = admin_service.change_grant(conn, operation="grant", user_id=self.target_user, sector_code="REBOBINADO", actor_id=self.admin1.user_id)
        self.assertTrue(result["changed"])
        result = grants_write.change_machine_form_grant(conn, operation="grant", user_id=self.target_user, machine_code="MP1", form_code="VINTO-P1-03", actor_id=self.admin1.user_id)
        self.assertTrue(result["changed"])

    async def test_an_actor_without_user_manage_or_deactivated_is_rejected_and_nothing_is_written(self):
        conn = self.identity_connection()
        with self.assertRaises(ActorNotAuthorized):
            admin_service.change_grant(conn, operation="grant", user_id=self.admin2.user_id, sector_code="REBOBINADO", actor_id=self.operator)  # operación: sin user.manage
        self.assertEqual(self.sector_rows(self.admin2.user_id), 0)
        deactivate_user(self.connection, username=self.admin2.username, actor_username=self.admin1.username, reason="d3b2")
        with self.assertRaises(ActorNotAuthorized):
            admin_service.change_grant(conn, operation="grant", user_id=self.target_user, sector_code="REBOBINADO", actor_id=self.admin2.user_id)  # administrador desactivado
        with self.assertRaises(ActorNotAuthorized):
            grants_write.change_machine_form_grant(conn, operation="grant", user_id=self.target_user, machine_code="MP1", form_code="VINTO-P1-03", actor_id=self.admin2.user_id)
        self.assertEqual(self.sector_rows(self.target_user), 0)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id = %s AND revoked_at IS NULL", (self.target_user,)).fetchone()[0], 0)

    async def test_a_deactivation_waits_for_an_in_flight_administrative_write_and_the_next_write_is_rejected(self):
        inside, release, outcome = threading.Event(), threading.Event(), []

        def in_flight_write():
            conn = self.identity_connection()
            with conn.transaction():
                require_actor_authorized(conn, self.admin2.user_id)  # el actor está autorizado y su fila queda protegida hasta el COMMIT
                admin_service_write = conn.execute("SELECT 1").fetchone()  # (la escritura real sigue en esta misma transacción)
                inside.set()
                release.wait(30)
                outcome.append(admin_service_write)

        def deactivation():
            conn = self.identity_connection()
            outcome.append(("deactivated", deactivate_user(conn, username=self.admin2.username, actor_username=self.admin1.username, reason="d3b2 concurrent").changed))
        writer, deactivator = threading.Thread(target=in_flight_write), threading.Thread(target=deactivation)
        writer.start()
        self.assertTrue(inside.wait(20))
        deactivator.start()
        deactivator.join(1.5)
        self.assertTrue(deactivator.is_alive(), "la desactivación debe esperar a la escritura en curso del administrador")
        self.assertTrue(self.connection.execute('SELECT active FROM vinto_master."user" WHERE id = %s', (self.admin2.user_id,)).fetchone()[0])
        release.set()
        writer.join(30)
        deactivator.join(30)
        self.assertIn(("deactivated", True), outcome)
        conn = self.identity_connection()
        with self.assertRaises(ActorNotAuthorized):  # la desactivación ya confirmada: la siguiente escritura se rechaza
            admin_service.change_grant(conn, operation="grant", user_id=self.target_user, sector_code="REBOBINADO", actor_id=self.admin2.user_id)

    async def test_two_administrators_changing_each_other_concurrently_never_deadlock(self):
        errors, rounds = [], 12

        def worker(actor, target):
            conn = self.identity_connection()
            for index in range(rounds):
                try:
                    admin_service.change_grant(conn, operation="grant" if index % 2 == 0 else "revoke", user_id=target, sector_code="REBOBINADO", actor_id=actor)
                except BaseException as error:  # noqa: BLE001
                    errors.append(error)
        threads = [threading.Thread(target=worker, args=(self.admin1.user_id, self.admin2.user_id)), threading.Thread(target=worker, args=(self.admin2.user_id, self.admin1.user_id)),
                   threading.Thread(target=worker, args=(self.admin1.user_id, self.admin1.user_id))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        self.assertEqual(errors, [])

    async def test_the_four_captures_run_in_enforce_with_the_business_role_after_the_cut(self):
        """Evidencia de la puerta D.3B.3 (solo en la base de prueba): con 03c aplicado y el corte D3B4 del prototipo, el negocio sigue capturando."""
        self.apply("D3B4")
        self.assertEqual((self.can_administer(self.business), self.can_administer(self.identity)), (False, True))
        for op in sync.OPERATIONS:
            with self.subTest(operation=op):
                user, runner, _ = await self.target(op)
                results = []
                thread = self.threaded(runner, results, role=self.business)
                thread.start()
                thread.join(60)
                self.assertTrue(results and getattr(results[0], "created", False), (op, results))


# ---- 5. API completa con roles LOGIN reales: URL sin definir / definida / definida con el corte aplicado en la base de prueba ----------------------------------------------

class ApiBase(unittest.IsolatedAsyncioTestCase):
    DEDICATED = False
    CUT = False

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_d3b2")
        cls.connection = connect(cls.database)
        suffix = uuid4().hex[:6]
        cls.biz, cls.idn = f"d3b2_biz_{suffix}", f"d3b2_idn_{suffix}"
        cls.passwords = {cls.biz: "pw-" + secrets.token_urlsafe(12), cls.idn: "pw-" + secrets.token_urlsafe(12)}
        for role in (cls.biz, cls.idn):
            cls.connection.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{cls.passwords[role]}' NOSUPERUSER NOCREATEDB NOCREATEROLE")
        for statement in d3b.baseline_statements(cls.biz):
            cls.connection.execute(statement)
        d1.run(cls.connection, d1.sql_statements(GRANTS, app=cls.biz, identity=cls.idn))  # la identidad siempre tiene sus privilegios (aditivo)
        if cls.CUT:
            for statement in d3b.phase_statements(("D3B4",), cls.biz, cls.idn):
                cls.connection.execute(statement)
        cls.url = {role: make_conninfo(database_url(cls.database), user=role, password=cls.passwords[role]) for role in (cls.biz, cls.idn)}
        cls.patches = [patch.object(settings, "database_url", SecretStr(cls.url[cls.biz])),
                       patch.object(settings, "identity_database_url", SecretStr(cls.url[cls.idn]) if cls.DEDICATED else None)]
        cls.log = []
        real = psycopg.connect

        def recording(conninfo="", *args, **kwargs):
            cls.log.append(conninfo_to_dict(conninfo).get("user") if isinstance(conninfo, str) else None)
            return real(conninfo, *args, **kwargs)
        cls.patches.append(patch.object(psycopg, "connect", recording))
        for started in cls.patches:
            started.start()
        cls.users = {}
        for name, profile in (("ADMIN", "DATA_BALTREK"), ("OPERACION", "OPERACION")):
            password = "pw-" + secrets.token_urlsafe(12)
            created = create_user(cls.connection, username=f"d3b2.{name.lower()}.{uuid4().hex[:6]}", display_name=name.title(), profile_code=profile, password=password, sectors=("BOBINAS",))
            cls.users[name] = (created, password)

    @classmethod
    def tearDownClass(cls):
        for started in reversed(cls.patches):
            started.stop()
        for role in (cls.biz, cls.idn):
            cls.connection.execute(f"DROP OWNED BY {role}")
            cls.connection.execute(f"DROP ROLE IF EXISTS {role}")
        cls.connection.close()
        drop_database(cls.database)

    @property
    def identity_role(self):
        return self.idn if self.DEDICATED else self.biz

    def used_since(self, mark):
        return {user for user in self.log[mark:] if user in (self.biz, self.idn)}

    async def login(self, name):
        created, password = self.users[name]
        reply = await asg.call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual(reply.status, 200, name)
        return reply.set_cookie_value()

    def audit_actors(self, since, tables=("user_sector", "user_machine_form_grant")):
        return {row[0] for row in self.connection.execute(
            "SELECT DISTINCT database_actor FROM vinto_audit.audit_event WHERE entity_table = ANY(%s) AND request_id LIKE 'admin-%%' AND occurred_at >= %s", (list(tables), since)).fetchall()}

    def admin_audit_rows(self):
        return self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event WHERE request_id LIKE 'admin-%'").fetchone()[0]


class ApiScenarios:
    async def test_login_session_resolution_and_logout_use_the_expected_role_each(self):
        mark = len(self.log)
        cookie = await self.login("ADMIN")
        self.assertEqual(self.used_since(mark), {self.identity_role})  # login: conexión de identidad
        mark = len(self.log)
        reply = await asg.call("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.used_since(mark), {self.biz})  # resolución de sesión: SIEMPRE el rol de negocio
        mark = len(self.log)
        reply = await asg.call("POST", "/api/auth/logout", cookie=cookie, extra_headers=[("origin", ORIGIN)])
        self.assertEqual(reply.status, 204)
        self.assertEqual(self.used_since(mark), {self.identity_role})  # logout: conexión de identidad
        self.assertEqual((await asg.call("GET", "/api/auth/me", cookie=cookie)).status, 401)  # la sesión quedó revocada de verdad

    async def test_administration_changes_sectors_and_machine_form_grants_with_the_identity_role(self):
        cookie = await self.login("ADMIN")
        target = create_user(self.connection, username=f"d3b2.t.{uuid4().hex[:8]}", display_name="Target", profile_code="OPERACION", password="pw-" + uuid4().hex, sectors=("BOBINAS",)).user_id
        since = self.connection.execute("SELECT clock_timestamp()").fetchone()[0]
        mark = len(self.log)
        headers = [("origin", ORIGIN)]
        steps = (("sectors/grant", {"sector_code": "REBOBINADO"}), ("sectors/revoke", {"sector_code": "REBOBINADO"}),
                 ("grants/grant", {"machine_code": "MP1", "form_code": "VINTO-P1-03"}), ("grants/revoke", {"machine_code": "MP1", "form_code": "VINTO-P1-03"}))
        for path, body in steps:
            reply = await asg.call("POST", f"/api/admin/users/{target}/{path}", json_body=body, cookie=cookie, extra_headers=headers)
            self.assertEqual(reply.status, 200, (path, reply.body))
            self.assertTrue(reply.json()["changed"], path)
        self.assertEqual((await asg.call("GET", f"/api/admin/users/{target}/grants", cookie=cookie)).status, 200)
        self.assertEqual(self.used_since(mark), {self.biz, self.idn} if self.DEDICATED else {self.biz})  # sesión con negocio, escritura con identidad
        self.assertEqual(self.audit_actors(since), {self.identity_role})  # auditoría: quien escribió fue el rol de identidad (session_user)

    async def test_administration_still_demands_a_valid_session_and_the_user_manage_permission(self):
        target = self.users["OPERACION"][0].user_id
        rows = self.admin_audit_rows()
        body = {"sector_code": "REBOBINADO"}
        headers = [("origin", ORIGIN)]
        self.assertEqual((await asg.call("POST", f"/api/admin/users/{target}/sectors/grant", json_body=body, extra_headers=headers)).status, 401)
        operator = await self.login("OPERACION")
        self.assertEqual((await asg.call("POST", f"/api/admin/users/{target}/sectors/grant", json_body=body, cookie=operator, extra_headers=headers)).status, 403)
        self.assertEqual((await asg.call("GET", f"/api/admin/users/{target}", cookie=operator)).status, 403)
        self.assertEqual(self.admin_audit_rows(), rows)

    async def test_an_actor_who_loses_the_permission_between_the_check_and_the_write_is_rejected_and_nothing_is_written(self):
        admin = create_user(self.connection, username=f"d3b2.gone.{uuid4().hex[:6]}", display_name="Gone", profile_code="DATA_BALTREK", password="pw-" + uuid4().hex)
        deactivate_user(self.connection, username=admin.username, actor_username=self.users["ADMIN"][0].username, reason="d3b2")
        stale = AuthenticatedUser(admin.user_id, admin.username, "Gone", ("DATA_BALTREK",), frozenset({USER_MANAGE}), False, frozenset())  # la sesión ya había pasado la comprobación
        target = self.users["OPERACION"][0].user_id
        rows = self.admin_audit_rows()
        app.dependency_overrides[current_user] = lambda: stale
        try:
            reply = await asg.call("POST", f"/api/admin/users/{target}/sectors/grant", json_body={"sector_code": "REBOBINADO"}, extra_headers=[("origin", ORIGIN)])
        finally:
            app.dependency_overrides.pop(current_user, None)
        self.assertEqual((reply.status, reply.json()["code"]), (403, "ACTOR_NOT_AUTHORIZED"))
        self.assertEqual(self.admin_audit_rows(), rows)

    async def test_create_user_cli_writes_with_the_identity_role(self):
        since = self.connection.execute("SELECT clock_timestamp()").fetchone()[0]
        username = f"d3b2.cli.{uuid4().hex[:8]}"
        patches = [patch.object(settings, "test_database_url", SecretStr(self.url[self.biz])),  # el CLI NO debe usar esta URL cuando hay una de identidad
                   patch.object(settings, "identity_test_database_url", SecretStr(self.url[self.idn]) if self.DEDICATED else None),
                   patch.dict(os.environ, {"D3B2_CLI_PASSWORD": "pw-" + uuid4().hex})]
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(contextlib.redirect_stdout(out))
            code = create_user_cli.main(["--target", "test", "--username", username, "--display-name", "CLI", "--profile", "OPERACION", "--sector", "BOBINAS", "--password-env", "D3B2_CLI_PASSWORD"])
        self.assertEqual(code, 0, out.getvalue())
        actors = {row[0] for row in self.connection.execute(
            "SELECT DISTINCT database_actor FROM vinto_audit.audit_event WHERE entity_table IN ('user', 'user_profile', 'user_sector') AND occurred_at >= %s", (since,)).fetchall()}
        self.assertEqual(actors, {self.identity_role})

    async def test_manage_user_cli_deactivates_with_the_identity_role(self):
        target = create_user(self.connection, username=f"d3b2.mu.{uuid4().hex[:8]}", display_name="MU", profile_code="OPERACION", password="pw-" + uuid4().hex)
        admin, password = self.users["ADMIN"]
        since = self.connection.execute("SELECT clock_timestamp()").fetchone()[0]
        out = io.StringIO()
        with patch.object(settings, "test_database_url", SecretStr(self.url[self.biz])), \
                patch.object(settings, "identity_test_database_url", SecretStr(self.url[self.idn]) if self.DEDICATED else None), \
                patch.dict(os.environ, {"D3B2_ACTOR_PW": password}), contextlib.redirect_stdout(out):
            code = manage_user_cli.main(["--target", "test", "--action", "deactivate", "--username", target.username, "--actor-username", admin.username,
                                         "--actor-password-env", "D3B2_ACTOR_PW", "--reason", "d3b2", "--yes"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertFalse(self.connection.execute('SELECT active FROM vinto_master."user" WHERE id = %s', (target.user_id,)).fetchone()[0])
        actors = {row[0] for row in self.connection.execute(
            "SELECT DISTINCT database_actor FROM vinto_audit.audit_event WHERE entity_table = 'user' AND action = 'UPDATE' AND occurred_at >= %s", (since,)).fetchall()}
        self.assertEqual(actors, {self.identity_role})


class ApiSharedModeTests(ApiBase, ApiScenarios):
    """Sin IDENTITY_DATABASE_URL: el comportamiento anterior, todo con el rol de negocio."""


class ApiDedicatedModeTests(ApiBase, ApiScenarios):
    """Con IDENTITY_DATABASE_URL y SIN corte: cada ruta usa su rol."""
    DEDICATED = True


class ApiAfterTheCutTests(ApiBase, ApiScenarios):
    """Con IDENTITY_DATABASE_URL y el corte D.3B.4 aplicado en la base de PRUEBA: todo lo anterior sigue funcionando aunque vinto_app ya no escriba identidad."""
    DEDICATED = True
    CUT = True

    async def test_the_business_role_really_cannot_write_identity_in_this_state(self):
        with psycopg.connect(self.url[self.biz]) as conn:
            for sql in ("INSERT INTO vinto_auth.session (user_id, token_hash, expires_at) VALUES (gen_random_uuid(), 'x', now())", "UPDATE vinto_auth.credential SET failed_attempts = 0",
                        "INSERT INTO vinto_master.user_sector (user_id, sector_id) VALUES (gen_random_uuid(), gen_random_uuid())"):
                with self.subTest(sql=sql[:40]), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(sql)
                conn.rollback()


class ApiDedicatedFailureTests(ApiBase):
    """URL de identidad definida pero que falla: 503 seguro, sin retroceso silencioso, sin escrituras y sin filtrar credenciales."""
    DEDICATED = True

    def broken(self):
        return patch.object(settings, "identity_database_url", SecretStr(make_conninfo(database_url(self.database), user="d3b2_role_that_does_not_exist", password="BROKEN-SENTINEL")))

    def events(self):
        return self.connection.execute("SELECT count(*) FROM vinto_auth.auth_event").fetchone()[0]

    async def test_login_is_unavailable_and_never_tries_the_application_role(self):
        created, password = self.users["ADMIN"]
        mark, events = len(self.log), self.events()
        with self.broken(), self.assertLogs("uvicorn.error", level="WARNING") as logs:
            reply = await asg.call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))
        self.assertEqual(self.log[mark:], ["d3b2_role_that_does_not_exist"])  # un único intento, con la URL dedicada; ninguno con el rol de negocio
        self.assertEqual(self.events(), events)
        text = reply.body.decode() + "\n".join(logs.output)
        for secret in (password, "BROKEN-SENTINEL", self.passwords[self.biz], self.passwords[self.idn]):
            self.assertNotIn(secret, text)

    async def test_an_administrative_write_is_unavailable_after_the_session_check_and_writes_nothing(self):
        cookie = await self.login("ADMIN")
        target = self.users["OPERACION"][0].user_id
        rows, mark = self.admin_audit_rows(), len(self.log)
        with self.broken():
            reply = await asg.call("POST", f"/api/admin/users/{target}/sectors/grant", json_body={"sector_code": "REBOBINADO"}, cookie=cookie, extra_headers=[("origin", ORIGIN)])
        self.assertEqual(reply.status, 503)
        self.assertEqual(self.log[mark:], [self.biz, "d3b2_role_that_does_not_exist"])  # sesión con negocio, luego UN intento de identidad y nada más
        self.assertEqual(self.admin_audit_rows(), rows)

    async def test_logout_still_clears_the_cookie_and_does_not_revoke_through_another_role(self):
        cookie = await self.login("ADMIN")
        mark = len(self.log)
        with self.broken():
            reply = await asg.call("POST", "/api/auth/logout", cookie=cookie, extra_headers=[("origin", ORIGIN)])
        self.assertEqual(reply.status, 503)
        self.assertTrue(any(k == b"set-cookie" and b"Max-Age=0" in v for k, v in reply.headers))  # la cookie local se borra igualmente
        self.assertEqual(self.log[mark:], ["d3b2_role_that_does_not_exist"])
        self.assertEqual((await asg.call("GET", "/api/auth/me", cookie=cookie)).status, 200)  # la revocación NO se confirmó y no se hizo por otra vía


if __name__ == "__main__":
    unittest.main()
