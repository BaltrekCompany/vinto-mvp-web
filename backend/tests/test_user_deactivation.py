"""Desactivación/reactivación de usuarios internos (CLOUD-DEP-02B.2-G.12-B2).

Database tests run in ephemeral *_test databases copied from a migrated template that already contains
the reference profiles, so they do not depend on what vinto_test holds (same pattern as test_auth_service.py
and test_auth_sessions.py). Passwords used here are generated per run and never persisted in the repository.
"""

import contextlib
import io
import threading
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.auth import permissions
from app.auth.errors import InvalidReasonError, LastAdministratorError, UserNotFoundError
from app.auth.grants import grant_sector
from app.auth.service import (ADMIN_PROFILE_CODES, create_user, deactivate_user, reactivate_user)
from app.auth.sessions import create_session, resolve_session
from app.auth.errors import InvalidSessionError
from app.config import settings
from app.db_guard import connect_test_database, is_test_database_name
from app.seed import reference
from app.seed.bundle import load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

OPTIONS = "-c statement_timeout=60000 -c lock_timeout=30000"
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
        identifiers = [sql.Identifier(name)] + ([sql.Identifier(template)] if template else [])
        connection.execute(sql.SQL(statement).format(*identifiers))


def drop_database(name):
    assert is_test_database_name(name)
    with admin() as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def connect(name, **kwargs):
    return connect_test_database(test_url(name), autocommit=True, connect_timeout=5, options=OPTIONS, **kwargs)


def setUpModule():
    STATE["template"] = f"vinto_deact_tpl_{uuid4().hex[:10]}_test"
    create_database(STATE["template"])
    with connect(STATE["template"]) as connection:
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(connection, read_migrations())
        reference.apply(connection, load_bundle())  # provides the five reference profiles


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def new_password():
    import secrets
    return "pw-" + secrets.token_urlsafe(18)


class DatabaseCase(unittest.TestCase):
    @classmethod
    def make_database(cls):
        name = f"vinto_deact_{uuid4().hex[:12]}_test"
        create_database(name, template=STATE["template"])
        return name

    @classmethod
    def setUpClass(cls):
        cls.database = cls.make_database()
        cls.connection = connect(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def scalar(self, query, params=(), connection=None):
        return (connection or self.connection).execute(query, params).fetchone()[0]

    def make_user(self, profile="OPERACION", username=None, password=None, connection=None):
        password = password or new_password()
        username = username or f"deact.{uuid4().hex[:12]}"
        created = create_user(connection or self.connection, username=username, display_name="Deactivation Fixture",
                              profile_code=profile, password=password)
        return created, password

    def make_admin(self, username=None, connection=None):
        """DATA_BALTREK es hoy el único perfil con user.manage; ver ADMIN_PROFILE_CODES."""
        created, _ = self.make_user(profile="DATA_BALTREK", username=username, connection=connection)
        return created

    def active(self, user_id, connection=None):
        return self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (user_id,), connection)

    def session_row(self, session_id, connection=None):
        return (connection or self.connection).execute(
            "SELECT revoked_at FROM vinto_auth.session WHERE id=%s", (session_id,)).fetchone()

    def last_audit_row(self, entity_table, entity_id, connection=None):
        return (connection or self.connection).execute(
            """SELECT actor_id, reason, old_data, new_data FROM vinto_audit.audit_event
               WHERE entity_table=%s AND (entity_key->>'id') = %s ORDER BY occurred_at DESC LIMIT 1""",
            (entity_table, str(entity_id))).fetchone()


class IsolatedDatabaseCase(DatabaseCase):
    """Variante con una base NUEVA por cada método (setUp/tearDown, no setUpClass/tearDownClass).

    Necesaria para las pruebas de "última cuenta administrativa": dependen del recuento TOTAL de
    administradores activos en la base, así que compartir una base a nivel de clase (el patrón habitual
    de DatabaseCase, reutilizado en el resto de este archivo y en test_auth_service.py) contaminaría el
    recuento con los administradores que crean OTROS métodos de la misma clase.
    """

    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        self.database = self.make_database()
        self.connection = connect(self.database)

    def tearDown(self):
        self.connection.close()
        drop_database(self.database)


# ---------------------------------------------------------------------------------------------------
# pure / offline
# ---------------------------------------------------------------------------------------------------

class PermissionMatrixRegressionTests(unittest.TestCase):
    """G.12-B2 no debe alterar el modelo de permisos existente de los cinco perfiles (sección H.5)."""

    def test_profile_permissions_unchanged(self):
        self.assertEqual(permissions.PROFILE_PERMISSIONS, {
            permissions.JEFATURA: frozenset({permissions.WORK_ORDER_READ, permissions.WORK_ORDER_MANAGE,
                                             permissions.ASSIGNMENT_READ, permissions.CATALOG_READ}),
            permissions.SUPERVISION: frozenset({permissions.WORK_ORDER_READ, permissions.ASSIGNMENT_READ,
                                                permissions.ASSIGNMENT_MANAGE, permissions.CATALOG_READ}),
            permissions.OPERACION: frozenset({permissions.WORK_ORDER_READ, permissions.ASSIGNMENT_READ,
                                              permissions.PRODUCTION_CAPTURE, permissions.CATALOG_READ}),
            permissions.CALIDAD: frozenset({permissions.WORK_ORDER_READ, permissions.ASSIGNMENT_READ,
                                            permissions.QUALITY_CAPTURE, permissions.QUALITY_RELEASE, permissions.CATALOG_READ}),
            permissions.DATA_BALTREK: frozenset({permissions.WORK_ORDER_READ, permissions.ASSIGNMENT_READ,
                                                 permissions.CATALOG_READ, permissions.CATALOG_MANAGE, permissions.USER_MANAGE}),
        })

    def test_admin_profile_codes_is_exactly_data_baltrek_today(self):
        self.assertEqual(ADMIN_PROFILE_CODES, frozenset({"DATA_BALTREK"}))


class ReasonValidationTests(unittest.TestCase):
    """InvalidReasonError se lanza antes de abrir transacción alguna; no requiere base de datos."""

    def test_empty_or_non_string_reason_rejected(self):
        from app.auth.service import _clean_reason
        for bad in ("", "   ", None, 123):
            with self.assertRaises(InvalidReasonError):
                _clean_reason(bad)
        self.assertEqual(_clean_reason("  motivo real  "), "motivo real")


# ---------------------------------------------------------------------------------------------------
# database-backed
# ---------------------------------------------------------------------------------------------------

class DeactivationTests(DatabaseCase):
    def test_deactivate_active_user_succeeds(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        result = deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="prueba G.12-B2")
        self.assertEqual((result.active, result.changed), (False, True))
        self.assertFalse(self.active(target.user_id))

    def test_deactivate_twice_is_idempotent_noop(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("CALIDAD")
        first = deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="primera")
        second = deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="segunda")
        self.assertEqual((first.changed, second.changed), (True, False))
        self.assertFalse(second.active)
        audit_count = self.scalar(
            "SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='user' AND (entity_key->>'id')=%s AND action='UPDATE'",
            (str(target.user_id),))
        self.assertEqual(audit_count, 1)  # la llamada no-op no generó una segunda fila de auditoría

    def test_deactivate_unknown_user_raises(self):
        admin_user = self.make_admin()
        with self.assertRaises(UserNotFoundError):
            deactivate_user(self.connection, username="no.existe.nadie", actor_username=admin_user.username, reason="x")

    def test_unknown_or_non_admin_actor_rejected(self):
        target, _ = self.make_user("OPERACION")
        non_admin, _ = self.make_user("JEFATURA")
        with self.assertRaises(UserNotFoundError):
            deactivate_user(self.connection, username=target.username, actor_username="fantasma", reason="x")
        with self.assertRaises(UserNotFoundError):
            deactivate_user(self.connection, username=target.username, actor_username=non_admin.username, reason="x")
        self.assertTrue(self.active(target.user_id))  # ningún intento rechazado escribió nada

    def test_deactivated_user_cannot_authenticate(self):
        from app.auth.service import attempt_authentication
        from app.auth.errors import InvalidCredentialsError
        admin_user = self.make_admin()
        target, password = self.make_user("OPERACION")
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        outcome = attempt_authentication(self.connection, target.username, password, "req")
        self.assertIsInstance(outcome, InvalidCredentialsError)

    def test_existing_session_rejected_after_deactivation(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        session = create_session(self.connection, target.user_id)
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        with self.assertRaises(InvalidSessionError):
            resolve_session(self.connection, session.raw_token)

    def test_sessions_marked_revoked_explicitly(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        session_a = create_session(self.connection, target.user_id)
        session_b = create_session(self.connection, target.user_id)
        self.assertIsNone(self.session_row(session_a.session_id)[0])
        self.assertIsNone(self.session_row(session_b.session_id)[0])
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        self.assertIsNotNone(self.session_row(session_a.session_id)[0])
        self.assertIsNotNone(self.session_row(session_b.session_id)[0])

    def test_deactivating_non_admin_target_never_checks_admin_guard(self):
        """Un único DATA_BALTREK activo puede desactivar cuentas no administrativas sin disparar la guarda."""
        solo_admin = self.make_admin()
        target, _ = self.make_user("JEFATURA")
        result = deactivate_user(self.connection, username=target.username, actor_username=solo_admin.username, reason="x")
        self.assertTrue(result.changed)

    def test_deactivation_works_for_user_with_multiple_profiles(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("CALIDAD")
        supervision = self.connection.execute("SELECT id FROM vinto_master.profile WHERE code='SUPERVISION'").fetchone()[0]
        self.connection.execute("INSERT INTO vinto_master.user_profile (user_id,profile_id) VALUES (%s,%s)", (target.user_id, supervision))
        result = deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        self.assertTrue(result.changed)
        profile_count = self.scalar("SELECT count(*) FROM vinto_master.user_profile WHERE user_id=%s", (target.user_id,))
        self.assertEqual(profile_count, 2)  # ambos perfiles se conservan

    def test_no_secrets_leak_in_audit_or_errors(self):
        admin_user = self.make_admin()
        target, password = self.make_user("OPERACION")
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="motivo-sin-secretos")
        audit_text = " ".join(
            f"{a} {r} {o} {n}" for a, r, o, n in self.connection.execute(
                "SELECT actor_id::text,reason,old_data::text,new_data::text FROM vinto_audit.audit_event").fetchall())
        password_hash = self.connection.execute(
            "SELECT password_hash FROM vinto_auth.credential WHERE user_id=%s", (target.user_id,)).fetchone()[0]
        for secret in (password, password_hash):
            self.assertNotIn(secret, audit_text)


class ReactivationTests(DatabaseCase):
    def test_reactivate_inactive_user_succeeds(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        result = reactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="vuelve al piloto")
        self.assertEqual((result.active, result.changed), (True, True))
        self.assertTrue(self.active(target.user_id))

    def test_reactivate_already_active_is_idempotent_noop(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        result = reactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="ya estaba activo")
        self.assertEqual((result.active, result.changed), (True, False))

    def test_reactivate_unknown_user_raises(self):
        admin_user = self.make_admin()
        with self.assertRaises(UserNotFoundError):
            reactivate_user(self.connection, username="no.existe.nadie", actor_username=admin_user.username, reason="x")

    def test_old_token_stays_invalid_after_reactivation(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        session = create_session(self.connection, target.user_id)
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        reactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        with self.assertRaises(InvalidSessionError):
            resolve_session(self.connection, session.raw_token)
        self.assertIsNotNone(self.session_row(session.session_id)[0])  # revoked_at sigue puesto; nunca se revive

    def test_new_login_allowed_after_reactivation(self):
        from app.auth.service import authenticate
        admin_user = self.make_admin()
        target, password = self.make_user("OPERACION")
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        reactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        principal = authenticate(self.connection, target.username, password)
        self.assertEqual(principal.username, target.username)
        new_session = create_session(self.connection, principal.user_id)
        resolve_session(self.connection, new_session.raw_token)  # no lanza

    def test_profiles_preserved_across_deactivate_reactivate(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("SUPERVISION")
        before = self.connection.execute(
            "SELECT profile_id FROM vinto_master.user_profile WHERE user_id=%s ORDER BY profile_id", (target.user_id,)).fetchall()
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        reactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        after = self.connection.execute(
            "SELECT profile_id FROM vinto_master.user_profile WHERE user_id=%s ORDER BY profile_id", (target.user_id,)).fetchall()
        self.assertEqual(before, after)

    def test_sectors_preserved_across_deactivate_reactivate(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        grant_sector(self.connection, user_id=target.user_id, sector_code="BOBINAS")
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        reactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        sectors = self.connection.execute("SELECT sector_id FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,)).fetchall()
        self.assertEqual(len(sectors), 1)

    def test_reactivation_never_restores_revoked_sessions_even_if_still_valid(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        session = create_session(self.connection, target.user_id)  # TTL de 12h por defecto, no ha expirado
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        reactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="x")
        with self.assertRaises(InvalidSessionError):
            resolve_session(self.connection, session.raw_token)


class AuditTests(DatabaseCase):
    def test_audit_event_records_actor_and_reason(self):
        admin_user = self.make_admin()
        target, _ = self.make_user("OPERACION")
        deactivate_user(self.connection, username=target.username, actor_username=admin_user.username, reason="motivo verificable G.12-B2")
        actor_id, reason, old_data, new_data = self.last_audit_row("user", target.user_id)
        self.assertEqual(actor_id, admin_user.user_id)
        self.assertEqual(reason, "motivo verificable G.12-B2")
        self.assertTrue(old_data["active"])
        self.assertFalse(new_data["active"])


class LastAdministratorGuardTests(IsolatedDatabaseCase):
    """Cada método corre en su PROPIA base (ver IsolatedDatabaseCase): el recuento de administradores
    activos debe reflejar únicamente lo que crea el propio método."""

    def test_deactivation_and_session_revocation_are_atomic_on_failure(self):
        """Dos admins activos; intentar desactivar al último administrador debe fallar ANTES de tocar nada:
        ni active ni revoked_at cambian."""
        admin_a = self.make_admin()
        admin_b = self.make_admin()
        session = create_session(self.connection, admin_b.user_id)
        # Deja un solo administrador activo para la siguiente aserción.
        deactivate_user(self.connection, username=admin_a.username, actor_username=admin_b.username, reason="deja uno solo")
        with self.assertRaises(LastAdministratorError):
            deactivate_user(self.connection, username=admin_b.username, actor_username=admin_b.username, reason="autodesactivación")
        self.assertTrue(self.active(admin_b.user_id))
        self.assertIsNone(self.session_row(session.session_id)[0])  # la sesión NO quedó revocada por el intento fallido

    def test_last_admin_cannot_be_deactivated_by_another_admin(self):
        solo_admin = self.make_admin()
        other_admin = self.make_admin()
        deactivate_user(self.connection, username=other_admin.username, actor_username=solo_admin.username, reason="deja uno")
        with self.assertRaises(LastAdministratorError):
            deactivate_user(self.connection, username=solo_admin.username, actor_username=solo_admin.username, reason="autodesactivación")
        self.assertTrue(self.active(solo_admin.user_id))

    def test_concurrent_deactivation_of_two_distinct_admins_never_leaves_zero_active(self):
        """Dos administradores activos (y ningún otro); dos hilos intentan desactivarse ENTRE SÍ al mismo
        tiempo. Resultado aceptable: exactamente una desactivación aplicada (la otra rechazada por
        LastAdministratorError) o, si el orden de bloqueo se cruza, una de las dos transacciones puede
        recibir un deadlock de PostgreSQL (psycopg.Error) — ambos desenlaces son seguros. Lo que NUNCA
        puede ocurrir es que ambas desactivaciones se apliquen, dejando cero administradores activos."""
        admin_a = self.make_admin()
        admin_b = self.make_admin()
        workers, barrier, outcomes, errors = 2, threading.Barrier(2), [], []

        def attempt(target_username, actor_username):
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    try:
                        result = deactivate_user(connection, username=target_username, actor_username=actor_username, reason="concurrencia")
                        outcomes.append(("ok", result.changed))
                    except LastAdministratorError:
                        outcomes.append(("blocked", None))
                    except psycopg.Error as error:
                        outcomes.append(("db_error", type(error).__name__))
            except Exception as error:  # pragma: no cover - reportado abajo
                errors.append(repr(error))

        threads = [
            threading.Thread(target=attempt, args=(admin_b.username, admin_a.username)),
            threading.Thread(target=attempt, args=(admin_a.username, admin_b.username)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(outcomes), workers)
        active_count = self.scalar(
            """SELECT count(*) FROM vinto_master."user" u JOIN vinto_master.user_profile up ON up.user_id=u.id
               JOIN vinto_master.profile p ON p.id=up.profile_id WHERE u.active AND p.active AND p.code='DATA_BALTREK'""")
        self.assertGreaterEqual(active_count, 1)  # invariante: nunca cero administradores activos
        applied = sum(1 for status, changed in outcomes if status == "ok" and changed)
        self.assertLessEqual(applied, 1)  # a lo sumo una de las dos desactivaciones se aplicó realmente


if __name__ == "__main__":
    unittest.main()
