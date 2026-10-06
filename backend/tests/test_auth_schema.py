"""Migration 0002 (vinto_auth) on the isolated test database. Every fixture is rolled back.

Secrets used here (hashes, tokens) are generated per test run and never persisted.
"""

import hashlib
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from app.db_guard import connect_test_database
from migrate import applied_migrations, read_migrations, validate_history

# 0001 is immutable: its checksum must never change once applied anywhere.
MIGRATION_0001_SHA256 = "500b68a0fe3af40d06fda81c12e8945c57b99c669ec84348fa5808e1684d3c0f"
AUTH_TABLES = {"credential", "session", "auth_event"}


def new_password_hash():
    return "$argon2id$ephemeral$" + secrets.token_hex(24)


def new_token_hash():
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


class AuthSchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = connect_test_database(
            connect_timeout=3, options="-c statement_timeout=10000 -c lock_timeout=3000")
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)

    def make_user(self, name="AUTH TECHNICAL ROLLBACK FIXTURE"):
        return self.connection.execute(
            'INSERT INTO vinto_master."user" (display_name) VALUES (%s) RETURNING id', (name,)).fetchone()[0]

    def make_credential(self, user_id, username="technical.user", password_hash=None):
        password_hash = password_hash or new_password_hash()
        self.connection.execute(
            "INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm) VALUES (%s,%s,%s,'argon2id')",
            (user_id, username, password_hash))
        return password_hash

    def make_session(self, user_id, token_hash=None, **extra):
        token_hash = token_hash or new_token_hash()
        now = datetime.now(timezone.utc)
        created_at = extra.pop("created_at", now)
        expires_at = extra.pop("expires_at", created_at + timedelta(hours=8))
        return self.connection.execute(
            "INSERT INTO vinto_auth.session (user_id,token_hash,created_at,expires_at) VALUES (%s,%s,%s,%s) RETURNING id",
            (user_id, token_hash, created_at, expires_at)).fetchone()[0], token_hash

    def expect(self, error, sql, params=()):
        """Run a statement that must fail without aborting the surrounding transaction."""
        self.connection.execute("SAVEPOINT expected_failure")
        with self.assertRaises(error):
            self.connection.execute(sql, params)
        self.connection.execute("ROLLBACK TO SAVEPOINT expected_failure")


class MigrationHistoryTests(AuthSchemaTestCase):
    def test_0002_is_applied_on_the_test_database(self):
        rows = self.connection.execute(
            "SELECT version,filename,checksum FROM vinto_meta.schema_migration ORDER BY version").fetchall()
        migrations = read_migrations()
        self.assertEqual([r[0] for r in rows], list(range(1, len(migrations) + 1)))
        self.assertEqual(rows[1][1], "0002_auth.sql")
        self.assertEqual(rows[1][2], migrations[1].checksum)

    def test_check_is_green(self):
        migrations = read_migrations()
        applied = applied_migrations(self.connection)
        validate_history(migrations, applied)
        self.assertEqual(len(applied), len(migrations))

    def test_0001_keeps_its_exact_checksum(self):
        first = read_migrations()[0]
        self.assertEqual(first.filename, "0001_initial_schema.sql")
        self.assertEqual(first.checksum, MIGRATION_0001_SHA256)
        stored = self.connection.execute(
            "SELECT checksum FROM vinto_meta.schema_migration WHERE version=1").fetchone()[0]
        self.assertEqual(stored, MIGRATION_0001_SHA256)

    def test_auth_schema_has_exactly_the_expected_tables_with_primary_keys(self):
        tables = {r[0] for r in self.connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='vinto_auth' AND table_type='BASE TABLE'").fetchall()}
        self.assertEqual(tables, AUTH_TABLES)
        without_pk = self.connection.execute("""
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='vinto_auth' AND c.relkind='r'
              AND NOT EXISTS (SELECT 1 FROM pg_constraint p WHERE p.conrelid=c.oid AND p.contype='p')""").fetchall()
        self.assertEqual(without_pk, [])


class CredentialTests(AuthSchemaTestCase):
    def test_username_is_case_insensitive_unique(self):
        first, second = self.make_user(), self.make_user()
        self.make_credential(first, "Alexis")
        self.expect(UniqueViolation,
                    "INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm) VALUES (%s,'alexis',%s,'argon2id')",
                    (second, new_password_hash()))

    def test_username_must_be_clean_and_bounded(self):
        user = self.make_user()
        for bad in ("", " padded ", "x" * 65):
            self.expect(CheckViolation,
                        "INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm) VALUES (%s,%s,%s,'argon2id')",
                        (user, bad, new_password_hash()))

    def test_credential_requires_an_existing_user(self):
        self.expect(ForeignKeyViolation,
                    "INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm) VALUES (%s,'ghost',%s,'argon2id')",
                    (uuid4(), new_password_hash()))

    def test_one_credential_per_user(self):
        user = self.make_user()
        self.make_credential(user, "first.name")
        self.expect(UniqueViolation,
                    "INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm) VALUES (%s,'second.name',%s,'argon2id')",
                    (user, new_password_hash()))

    def test_negative_failed_attempts_are_rejected(self):
        user = self.make_user()
        self.make_credential(user)
        self.expect(CheckViolation, "UPDATE vinto_auth.credential SET failed_attempts=-1 WHERE user_id=%s", (user,))
        self.connection.execute("UPDATE vinto_auth.credential SET failed_attempts=3 WHERE user_id=%s", (user,))

    def test_empty_hash_and_unknown_algorithm_are_rejected(self):
        user = self.make_user()
        self.expect(CheckViolation,
                    "INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm) VALUES (%s,'a.b','','argon2id')", (user,))
        self.expect(CheckViolation,
                    "INSERT INTO vinto_auth.credential (user_id,username,password_hash,hash_algorithm) VALUES (%s,'a.b',%s,'md5')",
                    (user, new_password_hash()))

    def test_credential_owner_cannot_change(self):
        first, second = self.make_user(), self.make_user()
        self.make_credential(first)
        self.expect(CheckViolation, "UPDATE vinto_auth.credential SET user_id=%s WHERE user_id=%s", (second, first))

    def test_touch_row_sets_timestamps_and_actor(self):
        actor, user = self.make_user("ACTOR"), self.make_user()
        self.connection.execute("SELECT set_config('vinto.actor_id',%s,true)", (str(actor),))
        self.make_credential(user)
        row = self.connection.execute(
            "SELECT created_by,updated_by,created_at<=updated_at FROM vinto_auth.credential WHERE user_id=%s", (user,)).fetchone()
        self.assertEqual(row, (actor, actor, True))


class SessionTests(AuthSchemaTestCase):
    def test_session_requires_an_existing_user(self):
        self.expect(ForeignKeyViolation,
                    "INSERT INTO vinto_auth.session (user_id,token_hash,expires_at) VALUES (%s,%s,clock_timestamp()+interval '1 hour')",
                    (uuid4(), new_token_hash()))

    def test_token_hash_is_unique(self):
        user = self.make_user()
        _, token_hash = self.make_session(user)
        self.expect(UniqueViolation,
                    "INSERT INTO vinto_auth.session (user_id,token_hash,expires_at) VALUES (%s,%s,clock_timestamp()+interval '1 hour')",
                    (user, token_hash))

    def test_token_hash_must_be_sha256_hex(self):
        user = self.make_user()
        for bad in ("short", "G" * 64, "A" * 64, "a" * 63):
            self.expect(CheckViolation,
                        "INSERT INTO vinto_auth.session (user_id,token_hash,expires_at) VALUES (%s,%s,clock_timestamp()+interval '1 hour')",
                        (user, bad))

    def test_expiry_must_be_after_creation(self):
        user = self.make_user()
        created = datetime.now(timezone.utc)
        for expires in (created, created - timedelta(minutes=1)):
            self.expect(CheckViolation,
                        "INSERT INTO vinto_auth.session (user_id,token_hash,created_at,expires_at) VALUES (%s,%s,%s,%s)",
                        (user, new_token_hash(), created, expires))

    def test_identity_is_immutable_and_revocation_is_final(self):
        first, second = self.make_user(), self.make_user()
        session_id, _ = self.make_session(first)
        self.expect(CheckViolation, "UPDATE vinto_auth.session SET user_id=%s WHERE id=%s", (second, session_id))
        self.expect(CheckViolation, "UPDATE vinto_auth.session SET token_hash=%s WHERE id=%s", (new_token_hash(), session_id))
        self.connection.execute("UPDATE vinto_auth.session SET last_seen_at=clock_timestamp() WHERE id=%s", (session_id,))
        self.connection.execute("UPDATE vinto_auth.session SET revoked_at=clock_timestamp() WHERE id=%s", (session_id,))
        self.expect(CheckViolation, "UPDATE vinto_auth.session SET revoked_at=NULL WHERE id=%s", (session_id,))


class AuthEventTests(AuthSchemaTestCase):
    def test_only_the_allowed_events_are_accepted(self):
        user = self.make_user()
        for event in ("login_ok", "login_fail", "logout", "lockout", "password_change"):
            self.connection.execute("INSERT INTO vinto_auth.auth_event (user_id,event,request_id) VALUES (%s,%s,'req-1')", (user, event))
        self.connection.execute("INSERT INTO vinto_auth.auth_event (event) VALUES ('login_fail')")  # unknown username: no user
        self.expect(CheckViolation, "INSERT INTO vinto_auth.auth_event (user_id,event) VALUES (%s,'password_reset')", (user,))

    def test_auth_event_has_no_secret_columns(self):
        columns = {r[0] for r in self.connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='vinto_auth' AND table_name='auth_event'").fetchall()}
        self.assertEqual(columns, {"id", "user_id", "event", "occurred_at", "request_id"})

    def test_auth_event_is_append_only(self):
        user = self.make_user()
        self.connection.execute("INSERT INTO vinto_auth.auth_event (user_id,event) VALUES (%s,'login_ok')", (user,))
        self.expect(CheckViolation, "UPDATE vinto_auth.auth_event SET event='logout'")
        self.expect(CheckViolation, "DELETE FROM vinto_auth.auth_event")
        self.expect(CheckViolation, "TRUNCATE vinto_auth.auth_event")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_auth.auth_event").fetchone()[0], 1)


class SecretsStayOutOfAuditTests(AuthSchemaTestCase):
    def audit_text(self):
        return " ".join(f"{old} {new}" for old, new in self.connection.execute(
            "SELECT old_data::text,new_data::text FROM vinto_audit.audit_event").fetchall())

    def test_no_record_change_trigger_exists_in_vinto_auth(self):
        audited = self.connection.execute("""
            SELECT c.relname,t.tgname FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace
            WHERE n.nspname='vinto_auth' AND NOT t.tgisinternal AND pn.nspname='vinto_audit' AND p.proname='record_change'
        """).fetchall()
        self.assertEqual(audited, [])

    def test_password_hash_never_reaches_audit_event(self):
        user = self.make_user()
        first_hash = self.make_credential(user)
        second_hash = new_password_hash()
        self.connection.execute(
            "UPDATE vinto_auth.credential SET password_hash=%s,failed_attempts=1,password_changed_at=clock_timestamp() WHERE user_id=%s",
            (second_hash, user))
        # Control: the audit mechanism is active for audited tables in this same transaction.
        self.assertGreater(self.connection.execute(
            "SELECT count(*) FROM vinto_audit.audit_event WHERE entity_schema='vinto_master' AND entity_table='user'").fetchone()[0], 0)
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_audit.audit_event WHERE entity_schema='vinto_auth'").fetchone()[0], 0)
        text = self.audit_text()
        self.assertNotIn(first_hash, text)
        self.assertNotIn(second_hash, text)

    def test_token_hash_never_reaches_audit_event(self):
        user = self.make_user()
        session_id, token_hash = self.make_session(user)
        self.connection.execute("UPDATE vinto_auth.session SET last_seen_at=clock_timestamp(),revoked_at=clock_timestamp() WHERE id=%s", (session_id,))
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_audit.audit_event WHERE entity_schema='vinto_auth'").fetchone()[0], 0)
        self.assertNotIn(token_hash, self.audit_text())


if __name__ == "__main__":
    unittest.main()
