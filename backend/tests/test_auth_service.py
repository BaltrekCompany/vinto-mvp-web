"""Auth domain: passwords, username policy, permission matrix, user creation, authenticate and lockout.

Database tests run in ephemeral *_test databases copied from a migrated template that already contains the
reference profiles, so they do not depend on what vinto_test holds. Passwords used here are generated per run.
"""

import contextlib
import io
import os
import secrets
import threading
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import create_user as create_user_cli
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.auth import passwords, permissions, service
from app.auth.errors import (AccountLockedError, InvalidCredentialsError, InvalidDisplayNameError, InvalidPasswordPolicyError,
                             InvalidUsernameError, ProfileNotFoundError, UserAlreadyExistsError)
from app.auth.service import authenticate, create_user, normalize_username
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
    STATE["template"] = f"vinto_auth_tpl_{uuid4().hex[:10]}_test"
    create_database(STATE["template"])
    with connect(STATE["template"]) as connection:
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(connection, read_migrations())
        reference.apply(connection, load_bundle())  # provides the five reference profiles


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def new_password():
    return "pw-" + secrets.token_urlsafe(18)  # >= 12 characters, different on every run


class DatabaseCase(unittest.TestCase):
    @classmethod
    def make_database(cls):
        name = f"vinto_auth_{uuid4().hex[:12]}_test"
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

    def count(self, table, where="true", connection=None):
        return self.scalar(f"SELECT count(*) FROM {table} WHERE {where}", connection=connection)

    def make_user(self, profile="OPERACION", username=None, password=None, connection=None):
        password = password or new_password()
        username = username or f"tech.{uuid4().hex[:12]}"
        created = create_user(connection or self.connection, username=username, display_name="Technical Fixture",
                              profile_code=profile, password=password)
        return created, password

    def credential(self, user_id):
        return self.connection.execute("SELECT failed_attempts,locked_until,password_hash FROM vinto_auth.credential WHERE user_id=%s", (user_id,)).fetchone()

    def events(self, user_id):
        return [r[0] for r in self.connection.execute("SELECT event FROM vinto_auth.auth_event WHERE user_id=%s ORDER BY id", (user_id,)).fetchall()]


# ---------------------------------------------------------------------------------------------------
# pure
# ---------------------------------------------------------------------------------------------------

class PasswordTests(unittest.TestCase):
    def test_hash_is_argon2id_and_verifiable(self):
        password = new_password()
        encoded = passwords.hash_password(password)
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertTrue(passwords.verify_password(encoded, password))

    def test_same_password_produces_different_hashes(self):
        password = new_password()
        self.assertNotEqual(passwords.hash_password(password), passwords.hash_password(password))

    def test_wrong_password_and_garbage_hash_fail_quietly(self):
        encoded = passwords.hash_password(new_password())
        self.assertFalse(passwords.verify_password(encoded, new_password()))
        self.assertFalse(passwords.verify_password("not-a-hash", "whatever-password"))
        self.assertFalse(passwords.verify_password("", ""))

    def test_hash_never_contains_the_plain_password(self):
        password = new_password()
        self.assertNotIn(password, passwords.hash_password(password))

    def test_length_is_the_only_rule(self):
        for short in ("", "a" * 11):
            with self.assertRaises(InvalidPasswordPolicyError):
                passwords.validate_password_policy(short)
        for long in ("a" * 257, "é" * 300):
            with self.assertRaises(InvalidPasswordPolicyError):
                passwords.validate_password_policy(long)
        with self.assertRaises(InvalidPasswordPolicyError):
            passwords.validate_password_policy(None)
        for acceptable in ("a" * 12, "a" * 256, "aaaaaaaaaaaa", "123456789012", "solo minusculas largas"):
            passwords.validate_password_policy(acceptable)  # no uppercase / digit / symbol requirement

    def test_dummy_hash_is_a_valid_argon2id_hash_nobody_knows(self):
        dummy = passwords.dummy_hash()
        self.assertTrue(dummy.startswith("$argon2id$"))
        self.assertIs(dummy, passwords.dummy_hash())
        self.assertFalse(passwords.verify_password(dummy, new_password()))
        self.assertFalse(passwords.needs_rehash(dummy))


class UsernameTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_username("Alexis.Casas"), "alexis.casas")
        self.assertEqual(normalize_username("  dev.jefatura \n"), "dev.jefatura")
        for valid in ("dev.jefatura", "alexis.casas", "op_mp1_01", "a", "x" * 64, "a-b.c_d"):
            self.assertEqual(normalize_username(valid), valid)

    def test_invalid_usernames_are_rejected(self):
        for invalid in ("", "   ", "with space", "a b", "ñandu", "a@b.com", "dev/jefatura", "x" * 65, "İstanbul", "a\tb", None, 42):
            with self.subTest(repr(invalid)), self.assertRaises(InvalidUsernameError):
                normalize_username(invalid)


class PermissionMatrixTests(unittest.TestCase):
    EXPECTED = {
        "JEFATURA": {"work_order.read", "work_order.manage", "assignment.read", "catalog.read"},
        "SUPERVISION": {"work_order.read", "assignment.read", "assignment.manage", "catalog.read"},
        "OPERACION": {"work_order.read", "assignment.read", "production.capture", "catalog.read"},
        "CALIDAD": {"work_order.read", "assignment.read", "quality.capture", "quality.release", "catalog.read"},
        "DATA_BALTREK": {"work_order.read", "assignment.read", "catalog.read", "catalog.manage", "user.manage"},
    }

    def test_matrix_is_exact_per_profile(self):
        self.assertEqual({k: set(v) for k, v in permissions.PROFILE_PERMISSIONS.items()}, self.EXPECTED)
        for profile, expected in self.EXPECTED.items():
            self.assertEqual(permissions.permissions_for_profiles([profile]), frozenset(expected), profile)

    def test_canonical_permissions(self):
        self.assertEqual(set(permissions.ALL_PERMISSIONS), {
            "work_order.read", "work_order.manage", "assignment.read", "assignment.manage", "production.capture",
            "quality.capture", "quality.release", "catalog.read", "catalog.manage", "user.manage"})

    def test_data_baltrek_cannot_operate_the_plant(self):
        for permission in ("work_order.manage", "assignment.manage", "production.capture", "quality.capture", "quality.release"):
            self.assertFalse(permissions.has_permission(["DATA_BALTREK"], permission), permission)
        self.assertTrue(permissions.has_permission(["DATA_BALTREK"], "user.manage"))
        self.assertTrue(permissions.has_permission(["DATA_BALTREK"], "catalog.manage"))

    def test_multiple_profiles_union_their_permissions(self):
        union = permissions.permissions_for_profiles(["SUPERVISION", "CALIDAD"])
        self.assertEqual(union, frozenset(self.EXPECTED["SUPERVISION"] | self.EXPECTED["CALIDAD"]))
        self.assertTrue(permissions.has_permission(["OPERACION", "JEFATURA"], "work_order.manage"))
        self.assertTrue(permissions.has_permission(["OPERACION", "JEFATURA"], "production.capture"))

    def test_unknown_or_empty_profiles_grant_nothing(self):
        self.assertEqual(permissions.permissions_for_profiles(["NO_EXISTE", "jefatura", ""]), frozenset())
        self.assertEqual(permissions.permissions_for_profiles([]), frozenset())
        self.assertFalse(permissions.has_permission(["NO_EXISTE"], "work_order.read"))

    def test_unknown_permission_names_are_a_programming_error(self):
        with self.assertRaises(ValueError):
            permissions.has_permission(["JEFATURA"], "work_order.delete")

    def test_matrix_does_not_touch_the_database(self):
        import inspect
        source = inspect.getsource(permissions)
        self.assertNotIn("psycopg", source)
        self.assertNotIn("connection", source)


# ---------------------------------------------------------------------------------------------------
# user creation
# ---------------------------------------------------------------------------------------------------

class CreateUserTests(DatabaseCase):
    def test_creates_user_profile_and_credential(self):
        password = new_password()
        created = create_user(self.connection, username="  Dev.Jefatura ", display_name=" Jefatura DEV ",
                              profile_code="JEFATURA", password=password)
        self.assertEqual((created.username, created.display_name, created.profile_code), ("dev.jefatura", "Jefatura DEV", "JEFATURA"))
        self.assertEqual(self.connection.execute('SELECT display_name,active,external_subject,created_by FROM vinto_master."user" WHERE id=%s',
                                                 (created.user_id,)).fetchone(), ("Jefatura DEV", True, None, None))
        self.assertEqual(self.connection.execute(
            """SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id=up.profile_id
               WHERE up.user_id=%s""", (created.user_id,)).fetchall(), [("JEFATURA",)])
        self.assertEqual(self.connection.execute(
            "SELECT username,hash_algorithm,failed_attempts,locked_until,must_change FROM vinto_auth.credential WHERE user_id=%s",
            (created.user_id,)).fetchone(), ("dev.jefatura", "argon2id", 0, None, False))

    def test_credential_holds_an_argon2id_hash_that_verifies(self):
        created, password = self.make_user()
        stored = self.credential(created.user_id)[2]
        self.assertTrue(stored.startswith("$argon2id$"))
        self.assertNotIn(password, stored)
        self.assertTrue(passwords.verify_password(stored, password))

    def test_unknown_profile_rolls_everything_back_and_creates_no_profile(self):
        before = {t: self.count(t) for t in ('vinto_master."user"', "vinto_master.user_profile", "vinto_auth.credential", "vinto_master.profile")}
        for code in ("NO_EXISTE", "jefatura", ""):
            with self.subTest(code), self.assertRaises(ProfileNotFoundError):
                create_user(self.connection, username=f"x.{uuid4().hex[:8]}", display_name="X", profile_code=code, password=new_password())
        self.assertEqual({t: self.count(t) for t in before}, before)
        self.assertEqual(self.count("vinto_master.profile", "code='NO_EXISTE'"), 0)

    def test_inactive_profile_cannot_be_assigned(self):
        profile = f"TECH_INACTIVE_{uuid4().hex[:6]}".upper()
        self.connection.execute("INSERT INTO vinto_master.profile (code,name,active) VALUES (%s,'Inactive technical profile',false)", (profile,))
        before = self.count('vinto_master."user"')
        with self.assertRaises(ProfileNotFoundError):
            create_user(self.connection, username="inactive.profile", display_name="X", profile_code=profile, password=new_password())
        self.assertEqual(self.count('vinto_master."user"'), before)

    def test_username_is_unique_ignoring_case_and_failure_is_atomic(self):
        self.make_user(username="Alexis.Dup")
        before = {t: self.count(t) for t in ('vinto_master."user"', "vinto_master.user_profile", "vinto_auth.credential")}
        with self.assertRaises(UserAlreadyExistsError):
            create_user(self.connection, username="alexis.dup", display_name="Otro", profile_code="CALIDAD", password=new_password())
        self.assertEqual({t: self.count(t) for t in before}, before)

    def test_invalid_input_creates_nothing(self):
        before = self.count('vinto_master."user"')
        with self.assertRaises(InvalidUsernameError):
            create_user(self.connection, username="bad name", display_name="X", profile_code="OPERACION", password=new_password())
        with self.assertRaises(InvalidPasswordPolicyError):
            create_user(self.connection, username="short.pw", display_name="X", profile_code="OPERACION", password="short")
        with self.assertRaises(InvalidDisplayNameError):
            create_user(self.connection, username="no.name", display_name="  ", profile_code="OPERACION", password=new_password())
        self.assertEqual(self.count('vinto_master."user"'), before)

    def test_password_and_hash_never_reach_audit_event(self):
        password = new_password()
        created, _ = self.make_user(password=password)
        encoded = self.credential(created.user_id)[2]
        self.assertEqual(self.count("vinto_audit.audit_event", "entity_schema='vinto_auth'"), 0)
        self.assertGreater(self.count("vinto_audit.audit_event", "entity_table='user'"), 0)  # control: auditing is active
        dump = " ".join(f"{o} {n}" for o, n in self.connection.execute("SELECT old_data::text,new_data::text FROM vinto_audit.audit_event").fetchall())
        self.assertNotIn(password, dump)
        self.assertNotIn(encoded, dump)
        self.assertNotIn("argon2", dump)

    def test_operation_is_identified_in_the_audit_trail_without_an_actor(self):
        created, _ = self.make_user()
        row = self.connection.execute(
            "SELECT reason,request_id,actor_id FROM vinto_audit.audit_event WHERE entity_table='user' AND entity_key->>'id'=%s",
            (str(created.user_id),)).fetchone()
        self.assertEqual(row[0], "user creation by create_user")
        self.assertTrue(row[1].startswith("create_user:"))
        self.assertIsNone(row[2])


class CreateUserCliTests(DatabaseCase):
    def run_cli(self, arguments, password=None, second=None, env=None):
        answers = iter([password, password if second is None else second])
        output = io.StringIO()
        with patch.object(create_user_cli, "open_connection", side_effect=lambda target: connect(self.database)), \
                patch.object(create_user_cli.getpass, "getpass", side_effect=lambda prompt="": next(answers)), \
                patch.dict(os.environ, env or {}), contextlib.redirect_stdout(output):
            code = create_user_cli.main(arguments)
        return code, output.getvalue()

    def test_creates_a_user_with_a_prompted_password_and_never_prints_it(self):
        password = new_password()
        code, output = self.run_cli(["--target", "test", "--username", "Cli.User", "--display-name", "Cli User", "--profile", "CALIDAD"], password)
        self.assertEqual(code, 0)
        self.assertIn("username=cli.user", output)
        self.assertNotIn(password, output)
        self.assertNotIn("argon2", output)
        stored = self.scalar("SELECT password_hash FROM vinto_auth.credential WHERE username='cli.user'")
        self.assertNotIn(stored, output)
        self.assertEqual(authenticate(self.connection, "cli.user", password).profile_codes, ("CALIDAD",))

    def test_password_confirmation_must_match(self):
        before = self.count('vinto_master."user"')
        code, output = self.run_cli(["--target", "test", "--username", "cli.mismatch", "--display-name", "X", "--profile", "CALIDAD"],
                                    new_password(), second=new_password())
        self.assertEqual(code, 1)
        self.assertIn("no coinciden", output)
        self.assertEqual(self.count('vinto_master."user"'), before)

    def test_unknown_profile_and_weak_password_are_reported_without_creating_anything(self):
        before = self.count('vinto_master."user"')
        code, output = self.run_cli(["--target", "test", "--username", "cli.noprofile", "--display-name", "X", "--profile", "NOPE"], new_password())
        self.assertEqual(code, 1)
        self.assertIn("no existe o está inactivo", output)
        code, output = self.run_cli(["--target", "test", "--username", "cli.weak", "--display-name", "X", "--profile", "CALIDAD"], "short")
        self.assertEqual(code, 1)
        self.assertNotIn("short", output.replace("Usuario no creado", ""))
        self.assertEqual(self.count('vinto_master."user"'), before)

    def test_password_can_come_from_an_explicitly_named_environment_variable(self):
        password = new_password()
        code, output = self.run_cli(["--target", "test", "--username", "cli.env", "--display-name", "X", "--profile", "OPERACION",
                                     "--password-env", "VINTO_TEST_PASSWORD"], env={"VINTO_TEST_PASSWORD": password})
        self.assertEqual(code, 0)
        self.assertNotIn(password, output)
        self.assertTrue(authenticate(self.connection, "cli.env", password).can("production.capture"))

    def test_target_is_mandatory_and_there_is_no_password_argument(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            create_user_cli.main(["--username", "x", "--display-name", "X", "--profile", "CALIDAD"])
        self.assertEqual(raised.exception.code, 2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            create_user_cli.main(["--target", "test", "--username", "x", "--display-name", "X", "--profile", "CALIDAD", "--password", "abc"])


# ---------------------------------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------------------------------

class AuthenticateTests(DatabaseCase):
    def test_correct_login_returns_the_principal_and_records_login_ok(self):
        created, password = self.make_user("SUPERVISION")
        principal = authenticate(self.connection, created.username, password, request_id="req-1")
        self.assertEqual((principal.user_id, principal.username, principal.profile_codes), (created.user_id, created.username, ("SUPERVISION",)))
        self.assertEqual(principal.permissions, permissions.permissions_for_profiles(["SUPERVISION"]))
        self.assertTrue(principal.can("assignment.manage"))
        self.assertFalse(principal.can("production.capture"))
        self.assertFalse(principal.must_change)
        self.assertEqual(self.events(created.user_id), ["login_ok"])
        self.assertEqual(self.scalar("SELECT request_id FROM vinto_auth.auth_event WHERE user_id=%s", (created.user_id,)), "req-1")

    def test_username_is_normalized_on_login(self):
        created, password = self.make_user(username="mixed.case")
        self.assertEqual(authenticate(self.connection, "  MIXED.Case ", password).user_id, created.user_id)

    def test_wrong_password_fails_and_counts(self):
        created, password = self.make_user()
        with self.assertRaises(InvalidCredentialsError):
            authenticate(self.connection, created.username, new_password())
        self.assertEqual(self.credential(created.user_id)[:2], (1, None))
        self.assertEqual(self.events(created.user_id), ["login_fail"])

    def test_unknown_user_gets_the_same_error_and_an_event_without_user_or_username(self):
        created, _ = self.make_user()
        with self.assertRaises(InvalidCredentialsError) as unknown:
            authenticate(self.connection, "does.not.exist", new_password())
        with self.assertRaises(InvalidCredentialsError) as wrong:
            authenticate(self.connection, created.username, new_password())
        self.assertIs(type(unknown.exception), type(wrong.exception))
        self.assertEqual(str(unknown.exception), str(wrong.exception))
        self.assertEqual(self.count("vinto_auth.auth_event", "user_id IS NULL AND event='login_fail'") >= 1, True)
        columns = {r[0] for r in self.connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='vinto_auth' AND table_name='auth_event'").fetchall()}
        self.assertNotIn("username_attempted", columns)

    def test_unknown_user_still_pays_an_argon2_verification(self):
        created, _ = self.make_user()
        with patch.object(service, "verify_password", wraps=passwords.verify_password) as spy:
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, "ghost.user", new_password())
            self.assertEqual(spy.call_count, 1)
            self.assertEqual(spy.call_args.args[0], passwords.dummy_hash())
            spy.reset_mock()
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, new_password())
            self.assertEqual(spy.call_count, 1)

    def test_malformed_input_is_just_invalid_credentials(self):
        for username, password in (("bad name!", new_password()), ("", "x"), (None, None), ("ok.name", "x" * 5000), ("ok.name", 12345)):
            with self.subTest(repr(username)), self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, username, password)

    def test_inactive_user_cannot_authenticate_even_with_the_right_password(self):
        created, password = self.make_user()
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (created.user_id,))
        with self.assertRaises(InvalidCredentialsError):
            authenticate(self.connection, created.username, password)
        self.assertEqual(self.credential(created.user_id)[:2], (0, None))  # inactivity is not a lockout trigger
        self.assertEqual(self.events(created.user_id), ["login_fail"])

    def test_inactive_profile_grants_no_permissions(self):
        database = self.make_database()
        self.addCleanup(drop_database, database)
        with connect(database) as connection:
            created, password = self.make_user("OPERACION", connection=connection)
            connection.execute("UPDATE vinto_master.profile SET active=false WHERE code='OPERACION'")
            principal = authenticate(connection, created.username, password)
        self.assertEqual((principal.profile_codes, principal.permissions), ((), frozenset()))
        self.assertFalse(principal.can("production.capture"))

    def test_only_active_profiles_count_in_a_multi_profile_user(self):
        database = self.make_database()
        self.addCleanup(drop_database, database)
        with connect(database) as connection:
            created, password = self.make_user("OPERACION", connection=connection)
            connection.execute("INSERT INTO vinto_master.user_profile (user_id,profile_id) SELECT %s,id FROM vinto_master.profile WHERE code='CALIDAD'", (created.user_id,))
            connection.execute("UPDATE vinto_master.profile SET active=false WHERE code='OPERACION'")
            principal = authenticate(connection, created.username, password)
        self.assertEqual(principal.profile_codes, ("CALIDAD",))
        self.assertTrue(principal.can("quality.release"))
        self.assertFalse(principal.can("production.capture"))

    def test_success_resets_the_failure_counter(self):
        created, password = self.make_user()
        for _ in range(3):
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, new_password())
        self.assertEqual(self.credential(created.user_id)[0], 3)
        authenticate(self.connection, created.username, password)
        self.assertEqual(self.credential(created.user_id)[:2], (0, None))

    def test_every_failure_increments_the_counter(self):
        created, _ = self.make_user()
        for expected in range(1, 5):
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, new_password())
            self.assertEqual(self.credential(created.user_id)[0], expected)
        self.assertEqual(self.events(created.user_id), ["login_fail"] * 4)

    def test_fifth_failure_locks_the_account_for_fifteen_minutes(self):
        created, password = self.make_user()
        for _ in range(5):
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, new_password())
        attempts, locked_until, _ = self.credential(created.user_id)
        self.assertEqual(attempts, 5)
        remaining = self.scalar("SELECT locked_until - clock_timestamp() FROM vinto_auth.credential WHERE user_id=%s", (created.user_id,))
        self.assertTrue(timedelta(minutes=14, seconds=50) < remaining <= timedelta(minutes=15), remaining)
        self.assertEqual(self.events(created.user_id), ["login_fail"] * 4 + ["login_fail", "lockout"])
        self.assertEqual(self.count("vinto_auth.auth_event", f"user_id='{created.user_id}' AND event='lockout'"), 1)

    def test_correct_password_does_not_authenticate_during_the_lockout(self):
        created, password = self.make_user()
        for _ in range(5):
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, new_password())
        locked_until = self.credential(created.user_id)[1]
        with self.assertRaises(AccountLockedError) as raised:
            authenticate(self.connection, created.username, password)
        self.assertEqual(raised.exception.locked_until, locked_until)
        self.assertEqual(self.credential(created.user_id)[:2], (5, locked_until))  # the lock is not extended or reset
        self.assertNotIn("login_ok", self.events(created.user_id))

    def test_user_can_authenticate_after_the_lockout_expires(self):
        created, password = self.make_user()
        for _ in range(5):
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, new_password())
        self.connection.execute("UPDATE vinto_auth.credential SET locked_until=clock_timestamp()-interval '1 minute' WHERE user_id=%s", (created.user_id,))
        principal = authenticate(self.connection, created.username, password)
        self.assertEqual(principal.user_id, created.user_id)
        self.assertEqual(self.credential(created.user_id)[:2], (0, None))
        self.assertEqual(self.events(created.user_id)[-1], "login_ok")

    def test_an_expired_lockout_restarts_the_count_instead_of_relocking_at_once(self):
        created, password = self.make_user()
        for _ in range(5):
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, new_password())
        self.connection.execute("UPDATE vinto_auth.credential SET locked_until=clock_timestamp()-interval '1 second' WHERE user_id=%s", (created.user_id,))
        with self.assertRaises(InvalidCredentialsError):
            authenticate(self.connection, created.username, new_password())
        self.assertEqual(self.credential(created.user_id)[:2], (1, None))
        authenticate(self.connection, created.username, password)

    def test_lockout_thresholds_come_from_configuration(self):
        created, _ = self.make_user()
        with patch.object(settings, "auth_max_failed_attempts", 2), patch.object(settings, "auth_lockout_minutes", 1):
            for _ in range(2):
                with self.assertRaises(InvalidCredentialsError):
                    authenticate(self.connection, created.username, new_password())
            remaining = self.scalar("SELECT locked_until - clock_timestamp() FROM vinto_auth.credential WHERE user_id=%s", (created.user_id,))
        self.assertTrue(timedelta(seconds=50) < remaining <= timedelta(minutes=1), remaining)
        self.assertEqual(self.events(created.user_id), ["login_fail", "login_fail", "lockout"])

    def test_event_sequence_is_exact(self):
        created, password = self.make_user()
        with self.assertRaises(InvalidCredentialsError):
            authenticate(self.connection, created.username, new_password())
        authenticate(self.connection, created.username, password)
        with self.assertRaises(InvalidCredentialsError):
            authenticate(self.connection, created.username, new_password())
        self.assertEqual(self.events(created.user_id), ["login_fail", "login_ok", "login_fail"])

    def test_counter_and_event_are_atomic(self):
        created, _ = self.make_user()
        with patch.object(service, "_event", side_effect=RuntimeError("event could not be written")):
            with self.assertRaises(RuntimeError):
                authenticate(self.connection, created.username, new_password())
        self.assertEqual(self.credential(created.user_id)[:2], (0, None))  # no counter without its event
        self.assertEqual(self.events(created.user_id), [])

    def test_no_secret_reaches_events_audit_or_logs(self):
        created, password = self.make_user()
        wrong, token_like = new_password(), secrets.token_hex(32)
        with self.assertNoLogs(level="DEBUG"):
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, created.username, wrong)
            with self.assertRaises(InvalidCredentialsError):
                authenticate(self.connection, token_like, token_like)
            authenticate(self.connection, created.username, password)
        stored = self.credential(created.user_id)[2]
        events = str(self.connection.execute("SELECT * FROM vinto_auth.auth_event").fetchall())
        audit = " ".join(f"{o} {n}" for o, n in self.connection.execute("SELECT old_data::text,new_data::text FROM vinto_audit.audit_event").fetchall())
        for secret in (password, wrong, token_like, stored):
            self.assertNotIn(secret, events)
            self.assertNotIn(secret, audit)


class ConcurrencyTests(DatabaseCase):
    def test_concurrent_failures_do_not_lose_increments(self):
        created, _ = self.make_user()
        workers, barrier, errors = 4, threading.Barrier(4), []

        def attempt():
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    try:
                        authenticate(connection, created.username, new_password())
                    except InvalidCredentialsError:
                        pass
            except Exception as error:  # pragma: no cover - reported below
                errors.append(repr(error))

        threads = [threading.Thread(target=attempt) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(self.credential(created.user_id)[0], workers)  # below the lockout threshold: every attempt counted
        self.assertEqual(self.events(created.user_id), ["login_fail"] * workers)


if __name__ == "__main__":
    unittest.main()
