"""Session service: opaque tokens stored only as SHA-256, fixed expiry, revocation and the atomic login.

Runs in ephemeral *_test databases (copied from a migrated template with the reference profiles).
Passwords and tokens are generated per run and never persisted in the repository.
"""

import base64
import hashlib
import re
import secrets
import time
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from app.auth import sessions
from app.auth.errors import InvalidCredentialsError, InvalidSessionError
from app.auth.service import create_user
from app.auth.sessions import (NewSession, create_session, generate_token, hash_token, login_with_session, resolve_session,
                               revoke_session)
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database

STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_sess_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class SessionCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_sess")
        cls.connection = connect(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def make_user(self, profile="OPERACION"):
        password = "pw-" + secrets.token_urlsafe(18)
        created = create_user(self.connection, username=f"sess.{uuid4().hex[:12]}", display_name="Session Fixture",
                              profile_code=profile, password=password)
        return created, password

    def session_row(self, session_id):
        return self.connection.execute(
            "SELECT token_hash,created_at,expires_at,last_seen_at,revoked_at FROM vinto_auth.session WHERE id=%s", (session_id,)).fetchone()

    def insert_known_session(self, user_id, *, created_ago="2 hours", expires_in="-1 hour", revoked=False):
        """Session with a token we know, to place it in the past (the live trigger forbids editing created_at)."""
        raw = generate_token()
        self.connection.execute(
            f"""INSERT INTO vinto_auth.session (user_id,token_hash,created_at,expires_at,last_seen_at,revoked_at)
                VALUES (%s,%s,clock_timestamp()-interval '{created_ago}',clock_timestamp()+interval '{expires_in}',
                        clock_timestamp()-interval '{created_ago}',{'clock_timestamp()-interval ' + repr(created_ago) if revoked else 'NULL'})""",
            (user_id, hash_token(raw)))
        return raw

    def logout_events(self, user_id):
        return self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id=%s AND event='logout'", (user_id,))


class TokenTests(SessionCase):
    def test_token_has_at_least_256_bits_of_entropy(self):
        token = generate_token()
        padded = token + "=" * (-len(token) % 4)
        self.assertGreaterEqual(len(base64.urlsafe_b64decode(padded)), 32)
        self.assertEqual(len({generate_token() for _ in range(2000)}), 2000)

    def test_raw_token_is_never_stored(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.session WHERE token_hash=%s", (new.raw_token,)), 0)
        table = str(self.connection.execute("SELECT * FROM vinto_auth.session").fetchall())
        self.assertNotIn(new.raw_token, table)

    def test_token_hash_is_lowercase_sha256_hex(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        stored = self.session_row(new.session_id)[0]
        self.assertEqual(stored, hashlib.sha256(new.raw_token.encode("utf-8")).hexdigest())
        self.assertRegex(stored, r"^[a-f0-9]{64}$")
        self.assertEqual(hash_token(new.raw_token), stored)

    def test_two_sessions_have_different_tokens_and_both_stay_valid(self):
        created, _ = self.make_user()
        first, second = create_session(self.connection, created.user_id), create_session(self.connection, created.user_id)
        self.assertNotEqual(first.raw_token, second.raw_token)
        self.assertNotEqual(self.session_row(first.session_id)[0], self.session_row(second.session_id)[0])
        self.assertEqual(resolve_session(self.connection, first.raw_token).user_id, created.user_id)
        self.assertEqual(resolve_session(self.connection, second.raw_token).user_id, created.user_id)

    def test_repr_never_shows_the_raw_token(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        self.assertNotIn(new.raw_token, repr(new))
        self.assertNotIn(new.raw_token, str(new))
        self.assertIsInstance(new, NewSession)

    def test_ttl_comes_from_configuration_and_is_fixed(self):
        created, _ = self.make_user()
        default = create_session(self.connection, created.user_id)
        self.assertEqual(default.max_age_seconds, 12 * 3600)
        remaining = self.scalar("SELECT expires_at - clock_timestamp() FROM vinto_auth.session WHERE id=%s", (default.session_id,))
        self.assertTrue(timedelta(hours=11, minutes=59) < remaining <= timedelta(hours=12), remaining)
        with patch.object(settings, "auth_session_hours", 1):
            short = create_session(self.connection, created.user_id)
        self.assertEqual(short.max_age_seconds, 3600)
        self.assertEqual(self.session_row(short.session_id)[4], None)  # revoked_at NULL


class ResolveTests(SessionCase):
    def test_valid_session_resolves_the_user_with_profiles_and_permissions(self):
        created, _ = self.make_user("CALIDAD")
        new = create_session(self.connection, created.user_id)
        principal = resolve_session(self.connection, new.raw_token)
        self.assertEqual((principal.user_id, principal.username, principal.profile_codes), (created.user_id, created.username, ("CALIDAD",)))
        self.assertTrue(principal.can("quality.release"))
        self.assertFalse(principal.can("production.capture"))

    def test_expired_session_does_not_resolve(self):
        created, _ = self.make_user()
        with self.assertRaises(InvalidSessionError):
            resolve_session(self.connection, self.insert_known_session(created.user_id))

    def test_revoked_session_does_not_resolve(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        self.assertTrue(revoke_session(self.connection, new.raw_token))
        with self.assertRaises(InvalidSessionError):
            resolve_session(self.connection, new.raw_token)

    def test_inactive_user_does_not_resolve(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (created.user_id,))
        with self.assertRaises(InvalidSessionError):
            resolve_session(self.connection, new.raw_token)

    def test_inactive_profiles_grant_no_permissions(self):
        database = copy_database(STATE["template"], "vinto_sess_p")
        self.addCleanup(drop_database, database)
        with connect(database) as connection:
            password = "pw-" + secrets.token_urlsafe(18)
            created = create_user(connection, username="inactive.profile", display_name="X", profile_code="OPERACION", password=password)
            new = create_session(connection, created.user_id)
            connection.execute("UPDATE vinto_master.profile SET active=false WHERE code='OPERACION'")
            principal = resolve_session(connection, new.raw_token)
        self.assertEqual((principal.profile_codes, principal.permissions), ((), frozenset()))

    def test_unknown_malformed_and_random_tokens_are_all_the_same_error(self):
        for token in (generate_token(), "", None, 12345, "x" * 500, " ", "../etc/passwd", hash_token("anything")):
            with self.subTest(repr(token)[:30]), self.assertRaises(InvalidSessionError) as raised:
                resolve_session(self.connection, token)
            self.assertEqual(str(raised.exception), "Sesión no válida")

    def test_last_seen_advances_but_expiry_is_fixed(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        _, created_at, expires_before, seen_before, _ = self.session_row(new.session_id)
        time.sleep(0.05)
        resolve_session(self.connection, new.raw_token)
        time.sleep(0.05)
        resolve_session(self.connection, new.raw_token)
        _, created_after, expires_after, seen_after, revoked = self.session_row(new.session_id)
        self.assertGreater(seen_after, seen_before)
        self.assertEqual(expires_after, expires_before)  # fixed expiration: never extended
        self.assertEqual(created_after, created_at)
        self.assertIsNone(revoked)


class RevokeTests(SessionCase):
    def test_revoke_is_idempotent_and_keeps_the_hash(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        stored_hash = self.session_row(new.session_id)[0]
        self.assertTrue(revoke_session(self.connection, new.raw_token, request_id="req-logout"))
        first_revoked_at = self.session_row(new.session_id)[4]
        self.assertIsNotNone(first_revoked_at)
        self.assertFalse(revoke_session(self.connection, new.raw_token))
        self.assertFalse(revoke_session(self.connection, new.raw_token))
        row = self.session_row(new.session_id)
        self.assertEqual((row[0], row[4]), (stored_hash, first_revoked_at))  # revoked once, hash untouched

    def test_logout_event_is_recorded_once_with_the_request_id(self):
        created, _ = self.make_user()
        new = create_session(self.connection, created.user_id)
        revoke_session(self.connection, new.raw_token, request_id="req-1")
        revoke_session(self.connection, new.raw_token, request_id="req-2")
        rows = self.connection.execute("SELECT event,request_id FROM vinto_auth.auth_event WHERE user_id=%s", (created.user_id,)).fetchall()
        self.assertEqual(rows, [("logout", "req-1")])

    def test_unknown_expired_or_malformed_tokens_revoke_nothing_and_log_nothing(self):
        created, _ = self.make_user()
        expired = self.insert_known_session(created.user_id)
        for token in (generate_token(), expired, "", None, "x" * 500):
            self.assertFalse(revoke_session(self.connection, token))
        self.assertEqual(self.logout_events(created.user_id), 0)

    def test_revoking_one_session_leaves_the_others(self):
        created, _ = self.make_user()
        first, second = create_session(self.connection, created.user_id), create_session(self.connection, created.user_id)
        revoke_session(self.connection, first.raw_token)
        with self.assertRaises(InvalidSessionError):
            resolve_session(self.connection, first.raw_token)
        self.assertEqual(resolve_session(self.connection, second.raw_token).user_id, created.user_id)


class LoginAtomicityTests(SessionCase):
    def test_success_creates_login_ok_and_a_session_together(self):
        created, password = self.make_user()
        principal, new = login_with_session(self.connection, created.username, password, request_id="req-login")
        self.assertEqual(principal.user_id, created.user_id)
        self.assertEqual(resolve_session(self.connection, new.raw_token).user_id, created.user_id)
        self.assertEqual(self.connection.execute("SELECT event,request_id FROM vinto_auth.auth_event WHERE user_id=%s", (created.user_id,)).fetchall(),
                         [("login_ok", "req-login")])

    def test_login_does_not_revoke_earlier_sessions(self):
        created, password = self.make_user()
        first = create_session(self.connection, created.user_id)
        login_with_session(self.connection, created.username, password)
        self.assertEqual(resolve_session(self.connection, first.raw_token).user_id, created.user_id)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.session WHERE user_id=%s AND revoked_at IS NULL", (created.user_id,)), 2)

    def test_failed_credentials_commit_the_event_and_create_no_session(self):
        created, _ = self.make_user()
        with self.assertRaises(InvalidCredentialsError):
            login_with_session(self.connection, created.username, "wrong-" + secrets.token_urlsafe(8))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id=%s AND event='login_fail'", (created.user_id,)), 1)
        self.assertEqual(self.scalar("SELECT failed_attempts FROM vinto_auth.credential WHERE user_id=%s", (created.user_id,)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.session WHERE user_id=%s", (created.user_id,)), 0)

    def test_session_creation_failure_rolls_back_the_whole_login(self):
        created, password = self.make_user()
        with self.assertRaises(InvalidCredentialsError):  # leave a non-zero counter to prove it is restored
            login_with_session(self.connection, created.username, "wrong-" + secrets.token_urlsafe(8))
        with patch.object(sessions, "create_session", side_effect=RuntimeError("session could not be created")):
            with self.assertRaises(RuntimeError):
                login_with_session(self.connection, created.username, password)
        self.assertEqual(self.scalar("SELECT failed_attempts FROM vinto_auth.credential WHERE user_id=%s", (created.user_id,)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id=%s AND event='login_ok'", (created.user_id,)), 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.session WHERE user_id=%s", (created.user_id,)), 0)


class NoSecretsTests(SessionCase):
    def test_token_and_hash_never_reach_logs_audit_or_events(self):
        created, password = self.make_user()
        with self.assertNoLogs(level="DEBUG"):
            principal, new = login_with_session(self.connection, created.username, password, request_id="req-x")
            resolve_session(self.connection, new.raw_token)
            revoke_session(self.connection, new.raw_token, request_id="req-y")
        stored_hash = hash_token(new.raw_token)
        audit = " ".join(f"{o} {n}" for o, n in self.connection.execute("SELECT old_data::text,new_data::text FROM vinto_audit.audit_event").fetchall())
        events = str(self.connection.execute("SELECT * FROM vinto_auth.auth_event").fetchall())
        for secret in (new.raw_token, stored_hash, password):
            self.assertNotIn(secret, audit)
            self.assertNotIn(secret, events)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_schema='vinto_auth'"), 0)
        self.assertRegex(stored_hash, r"^[a-f0-9]{64}$")
        self.assertIsNone(re.search(re.escape(new.raw_token), repr(principal)))


if __name__ == "__main__":
    unittest.main()
