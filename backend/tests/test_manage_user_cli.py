"""CLI manage_user.py: protección de destino (--target dev) y prueba de identidad del actor
(CLOUD-DEP-02B.2-G.12-B2-R1).

Las pruebas negativas de destino usan bases SINTÉTICAS en el MISMO PostgreSQL local y desechable que el
resto de la suite (nunca vinto_piloto real, nunca la base de TVC, nunca la VPS): una base literalmente
llamada "vinto_piloto" aquí es un señuelo local, nunca el sistema productivo real. No se adivina ni se
hardcodea el nombre real de la base de TVC: la defensa es "denegar por defecto todo lo no autorizado
explícitamente", lo que cubre a TVC sin necesidad de nombrarla.
"""

import contextlib
import io
import os
import uuid
from unittest import mock
import unittest
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo

import manage_user
from app.auth.errors import AccountLockedError, InvalidCredentialsError
from app.auth.service import create_user
from app.config import settings
from app.db_guard import connect_test_database, is_test_database_name
from app.seed import reference
from app.seed.bundle import load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

STATE = {}


def test_url(database=None):
    url = settings.test_database_url.get_secret_value()
    return url if database is None else make_conninfo(url, dbname=database)


def admin():
    return psycopg.connect(test_url("postgres"), autocommit=True, connect_timeout=5)


def create_database(name, template=None):
    assert is_test_database_name(name) and (template is None or is_test_database_name(template))
    with admin() as connection:
        statement = "CREATE DATABASE {} TEMPLATE {}" if template else "CREATE DATABASE {}"
        from psycopg import sql
        identifiers = [sql.Identifier(name)] + ([sql.Identifier(template)] if template else [])
        connection.execute(sql.SQL(statement).format(*identifiers))


def drop_database(name):
    assert is_test_database_name(name)
    with admin() as connection:
        from psycopg import sql
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def connect(name, **kwargs):
    return connect_test_database(test_url(name), autocommit=True, connect_timeout=5, **kwargs)


def new_password():
    import secrets
    return "pw-" + secrets.token_urlsafe(18)


def raw_create_database(name):
    """Crea una base SIN exigir el sufijo "_test": simula, en el MISMO Postgres local aislado, el tipo de
    base no efímera que --target dev apuntaría en un entorno real. Nunca sale de este contenedor local."""
    from psycopg import sql
    with admin() as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def raw_drop_database(name):
    from psycopg import sql
    with admin() as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def setUpModule():
    STATE["template"] = f"vinto_mucli_tpl_{uuid4().hex[:10]}_test"
    create_database(STATE["template"])
    with connect(STATE["template"]) as connection:
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(connection, read_migrations())
        reference.apply(connection, load_bundle())


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class DatabaseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mucli_{uuid4().hex[:12]}_test"
        create_database(cls.database, template=STATE["template"])
        cls.connection = connect(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def make_user(self, profile="OPERACION", username=None, password=None):
        password = password or new_password()
        username = username or f"mucli.{uuid4().hex[:12]}"
        created = create_user(self.connection, username=username, display_name="CLI Fixture", profile_code=profile, password=password)
        return created, password

    def make_admin(self, password=None):
        return self.make_user("DATA_BALTREK", password=password)

    def active(self, user_id):
        return self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (user_id,))


def run_cli(arguments, env=None, database=None):
    """Ejecuta manage_user.main() capturando stdout. Si `database` se da, redirige open_connection hacia
    una conexión NUEVA a esa base cada vez (mismo patrón que CreateUserCliTests en test_auth_service.py:
    `side_effect=lambda target: connect(self.database)`); manage_user.main() usa esa conexión con
    `with ... as connection:`, que psycopg CIERRA al salir, así que nunca debe ser la conexión de clase
    compartida (self.connection) o rompería las pruebas siguientes de la misma clase. Si `database` es
    None, se usa el open_connection REAL del módulo (necesario para probar la protección de destino)."""
    output = io.StringIO()
    patches = [contextlib.redirect_stdout(output), mock.patch.dict(os.environ, env or {}, clear=False)]
    if database is not None:
        patches.append(mock.patch.object(manage_user, "open_connection", side_effect=lambda target: connect(database)))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        code = manage_user.main(arguments)
    return code, output.getvalue()


class TargetIsMandatoryTests(unittest.TestCase):
    """C.1/C.2/C.6: argparse rechaza --target ausente, desconocido, o combinaciones incompletas; no
    requiere PostgreSQL (ni siquiera intenta abrir una conexión)."""

    def test_missing_target_is_rejected_before_any_connection(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            manage_user.main(["--action", "deactivate", "--username", "x", "--actor-username", "y", "--reason", "z", "--yes"])
        self.assertEqual(raised.exception.code, 2)

    def test_unknown_target_is_rejected_before_any_connection(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            manage_user.main(["--target", "prod", "--action", "deactivate", "--username", "x", "--actor-username", "y",
                              "--reason", "z", "--yes"])
        self.assertEqual(raised.exception.code, 2)

    def test_missing_actor_username_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            manage_user.main(["--target", "test", "--action", "deactivate", "--username", "x", "--reason", "z", "--yes"])
        self.assertEqual(raised.exception.code, 2)


class DevTargetProtectionTests(unittest.TestCase):
    """C.3/C.4/C.5/C.6/C.9: assert_dev_target_authorized/open_connection contra bases SINTÉTICAS locales.
    Ninguna de estas pruebas toca vinto_piloto real, TVC ni la VPS."""

    def setUp(self):
        self.suffix = uuid.uuid4().hex[:10]

    def _dev_db(self, name):
        full = f"{name}_{self.suffix}"
        raw_create_database(full)
        self.addCleanup(raw_drop_database, full)
        return full

    def test_unauthorized_unknown_database_is_rejected_by_default(self):
        """Sin MANAGE_USER_DEV_ALLOWED_TARGETS, --target dev no autoriza NADA por defecto: cubre también
        a un sistema desconocido como TVC sin necesidad de nombrarlo."""
        name = self._dev_db("some_other_system_synthetic")
        with mock.patch.object(settings, "database_url", _secret(make_conninfo(test_url(), dbname=name))), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(manage_user.DEV_ALLOWLIST_ENV, None)
            with self.assertRaises(manage_user.UnauthorizedDevTargetError):
                manage_user.open_connection("dev")

    def test_known_production_name_is_rejected_even_if_allowlisted_by_mistake(self):
        """C.4: un señuelo LOCAL con el nombre EXACTO de la base productiva real (vinto_piloto) se
        rechaza incondicionalmente, incluso si el operador lo añadiera por error al allowlist."""
        name = "vinto_piloto"  # nombre exacto a propósito: NO self._dev_db(), que añade un sufijo aleatorio
        raw_drop_database(name)  # defensivo: por si una corrida anterior lo dejó a medio limpiar
        raw_create_database(name)
        self.addCleanup(raw_drop_database, name)
        identity = f"127.0.0.1:5432/{name}"  # el operador se equivocó y lo autorizó; debe rechazarse igual
        with mock.patch.object(settings, "database_url", _secret(make_conninfo(test_url(), dbname=name))), \
                mock.patch.dict(os.environ, {manage_user.DEV_ALLOWLIST_ENV: identity}, clear=False):
            with self.assertRaises(manage_user.UnauthorizedDevTargetError) as raised:
                manage_user.open_connection("dev")
            self.assertIn("productiva conocida", str(raised.exception))

    def test_allowlist_requires_exact_match_not_substring_or_wrong_port(self):
        """C.6: un allowlist que casi coincide (puerto distinto) NO autoriza; no hay coincidencia difusa."""
        name = self._dev_db("almost_right")
        wrong_port_entry = "172.99.99.99:5433/" + name  # ni la IP ni el puerto son los reales
        with mock.patch.object(settings, "database_url", _secret(make_conninfo(test_url(), dbname=name))), \
                mock.patch.dict(os.environ, {manage_user.DEV_ALLOWLIST_ENV: wrong_port_entry}, clear=False):
            with self.assertRaises(manage_user.UnauthorizedDevTargetError):
                manage_user.open_connection("dev")

    def test_correctly_allowlisted_synthetic_dev_target_is_authorized(self):
        """C.9: con la identidad REAL (ya resuelta por psycopg) exactamente en el allowlist, --target dev
        SÍ conecta — demuestra que el mecanismo permite el uso legítimo en un entorno aislado real."""
        name = self._dev_db("synthetic_dev_ok")
        probe = psycopg.connect(make_conninfo(test_url(), dbname=name), autocommit=True)
        try:
            identity = manage_user._target_identity(probe)
        finally:
            probe.close()
        with mock.patch.object(settings, "database_url", _secret(make_conninfo(test_url(), dbname=name))), \
                mock.patch.dict(os.environ, {manage_user.DEV_ALLOWLIST_ENV: identity}, clear=False):
            connection = manage_user.open_connection("dev")
            try:
                self.assertEqual(connection.execute("SELECT current_database()").fetchone()[0], name)
            finally:
                connection.close()

    def test_no_secrets_in_rejection_message(self):
        """La conexión real usa la credencial legítima de TEST_DATABASE_URL (nunca una inyectada): el
        punto es que el mensaje de rechazo nunca repite el DSN completo ni la palabra "password=",
        solo identidad de red + nombre de base."""
        name = self._dev_db("secret_check")
        with mock.patch.object(settings, "database_url", _secret(make_conninfo(test_url(), dbname=name))), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(manage_user.DEV_ALLOWLIST_ENV, None)
            with self.assertRaises(manage_user.UnauthorizedDevTargetError) as raised:
                manage_user.open_connection("dev")
            message = str(raised.exception)
            self.assertNotIn("password", message.lower())


class ActorAuthenticationTests(DatabaseCase):
    """E.7/E.8: --actor-username por sí solo no debe bastar para actuar como ese administrador."""

    def test_wrong_actor_password_is_rejected_and_nothing_changes(self):
        admin_user, admin_password = self.make_admin()
        target, _ = self.make_user("OPERACION")
        code, output = run_cli(
            ["--target", "test", "--action", "deactivate", "--username", target.username,
             "--actor-username", admin_user.username, "--actor-password-env", "MUCLI_WRONG", "--reason", "x", "--yes"],
            env={"MUCLI_WRONG": "contraseña-incorrecta-" + uuid.uuid4().hex}, database=self.database)
        self.assertEqual(code, 1)
        self.assertIn("no aplicada", output)
        self.assertNotIn(admin_password, output)
        self.assertTrue(self.active(target.user_id))

    def test_correct_actor_password_authenticates_and_proceeds(self):
        admin_user, admin_password = self.make_admin()
        target, _ = self.make_user("OPERACION")
        code, output = run_cli(
            ["--target", "test", "--action", "deactivate", "--username", target.username,
             "--actor-username", admin_user.username, "--actor-password-env", "MUCLI_RIGHT", "--reason", "x", "--yes"],
            env={"MUCLI_RIGHT": admin_password}, database=self.database)
        self.assertEqual(code, 0)
        self.assertFalse(self.active(target.user_id))
        self.assertNotIn(admin_password, output)

    def test_actor_without_user_manage_is_rejected_even_with_correct_password(self):
        non_admin, non_admin_password = self.make_user("JEFATURA")
        target, _ = self.make_user("OPERACION")
        code, output = run_cli(
            ["--target", "test", "--action", "deactivate", "--username", target.username,
             "--actor-username", non_admin.username, "--actor-password-env", "MUCLI_NONADMIN", "--reason", "x", "--yes"],
            env={"MUCLI_NONADMIN": non_admin_password}, database=self.database)
        self.assertEqual(code, 1)
        self.assertIn("user.manage", output)
        self.assertTrue(self.active(target.user_id))

    def test_impersonation_attempt_is_recorded_as_a_failed_login_not_as_the_target_admin(self):
        """Nombrar a un administrador real sin su contraseña queda como login_fail de ESE admin, nunca
        como una acción atribuible a él en vinto_audit.audit_event."""
        admin_user, _ = self.make_admin()
        target, _ = self.make_user("OPERACION")
        before = self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id=%s AND event='login_fail'", (admin_user.user_id,))
        run_cli(["--target", "test", "--action", "deactivate", "--username", target.username,
                "--actor-username", admin_user.username, "--actor-password-env", "MUCLI_IMPOSTOR", "--reason", "x", "--yes"],
               env={"MUCLI_IMPOSTOR": "no-la-conozco-" + uuid.uuid4().hex}, database=self.database)
        after = self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id=%s AND event='login_fail'", (admin_user.user_id,))
        self.assertEqual(after, before + 1)
        update_rows = self.scalar(
            "SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='user' AND action='UPDATE' AND (entity_key->>'id')=%s",
            (str(target.user_id),))
        self.assertEqual(update_rows, 0)  # solo existe el INSERT de su creación; ninguna desactivación quedó atribuida


class DryRunAndConfirmationTests(DatabaseCase):
    """C.7/C.8/C.10."""

    def test_dry_run_without_yes_writes_nothing_and_never_connects(self):
        admin_user, admin_password = self.make_admin()
        target, _ = self.make_user("OPERACION")
        with mock.patch.object(manage_user, "open_connection", side_effect=AssertionError("no debería conectar en dry-run")):
            code, output = run_cli(["--target", "test", "--action", "deactivate", "--username", target.username,
                                    "--actor-username", admin_user.username, "--reason", "x"])
        self.assertEqual(code, 2)
        self.assertIn("Vista previa", output)
        self.assertTrue(self.active(target.user_id))

    def test_yes_is_required_to_actually_change_state(self):
        admin_user, admin_password = self.make_admin()
        target, _ = self.make_user("CALIDAD")
        code, _ = run_cli(["--target", "test", "--action", "deactivate", "--username", target.username,
                           "--actor-username", admin_user.username, "--actor-password-env", "MUCLI_YES",
                           "--reason", "x", "--yes"], env={"MUCLI_YES": admin_password}, database=self.database)
        self.assertEqual(code, 0)
        self.assertFalse(self.active(target.user_id))

    def test_empty_reason_is_rejected_before_connecting(self):
        with mock.patch.object(manage_user, "open_connection", side_effect=AssertionError("no debería conectar")):
            code, output = run_cli(["--target", "test", "--action", "deactivate", "--username", "x",
                                    "--actor-username", "y", "--reason", "   ", "--yes"])
        self.assertEqual(code, 1)
        self.assertIn("--reason", output)

    def test_no_secrets_anywhere_in_output_across_this_class(self):
        admin_user, admin_password = self.make_admin()
        target, _ = self.make_user("OPERACION")
        _, output_preview = run_cli(["--target", "test", "--action", "deactivate", "--username", target.username,
                                     "--actor-username", admin_user.username, "--reason", "x"])
        _, output_real = run_cli(["--target", "test", "--action", "reactivate", "--username", target.username,
                                  "--actor-username", admin_user.username, "--actor-password-env", "MUCLI_SECRET",
                                  "--reason", "x", "--yes"], env={"MUCLI_SECRET": admin_password}, database=self.database)
        for output in (output_preview, output_real):
            self.assertNotIn(admin_password, output)
            self.assertNotIn("argon2", output)


def _secret(value):
    from pydantic import SecretStr
    return SecretStr(value)


if __name__ == "__main__":
    unittest.main()
