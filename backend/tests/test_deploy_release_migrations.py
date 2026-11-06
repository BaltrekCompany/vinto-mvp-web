"""MF-13-03.B PR-C (OBS-2): `deploy.sh check-release / migrate-release` and the schema guard of `activate`, exercised for REAL.

What runs for real: the deploy phases themselves (bash), the release's OWN `migrate.py` and migration files, and an ephemeral PostgreSQL `*_test` database (created and dropped here; nothing touches vinto,
vinto_piloto or any server). What is substituted: `sudo` is a shim that drops `-u <user>` (the container user does everything), so the REAL privilege separation is NOT exercised here; that is covered by
deploy/mvp/scripts/tests/test_activate_hardening.sh with two real users. `systemctl` is a shim that only records its calls: the migration phases must never call it.

Skipped when bash/flock or the deploy scripts are not available (set VINTO_DEPLOY_SCRIPTS to deploy/mvp/scripts, e.g. a read-only mount in the backend container).
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import migrate
from app.ephemeral_db import connect, create_database, database_url, drop_database

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = Path(os.environ.get("VINTO_DEPLOY_SCRIPTS") or BACKEND.parent / "deploy" / "mvp" / "scripts")
OLD_SHA, NEW_SHA, ODD_SHA = "0" * 39 + "a", "0" * 39 + "b", "0" * 39 + "c"
HAVE_TOOLS = SCRIPTS.joinpath("deploy.sh").is_file() and shutil.which("bash") and shutil.which("flock")
REAL = migrate.read_migrations()
NEW_COUNT = len(REAL)  # includes the E1-02 0013 schema migration
PROBE_NAME = f"{NEW_COUNT + 1:04d}_prc_probe.sql"  # next available migration for the disposable fault injection


def _write(path: Path, text: str, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if mode:
        path.chmod(mode)


@unittest.skipUnless(HAVE_TOOLS, "bash/flock or the deploy scripts are not available")
class ReleaseMigrationCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="prc-"))
        # deploy scripts with LF endings (a Windows checkout mounted into Linux has CRLF) and a private SCRIPT_DIR (the lock file lives there)
        cls.scripts = cls.tmp / "scripts"
        cls.scripts.mkdir()
        for name in ("deploy.sh", "lib_common.sh", "rollback.sh"):
            (cls.scripts / name).write_bytes((SCRIPTS / name).read_bytes().replace(b"\r\n", b"\n"))
        cls.bin = cls.tmp / "bin"
        _write(cls.bin / "sudo", '#!/bin/sh\nif [ "$1" = "-u" ]; then shift 2; fi\nexec "$@"\n', 0o755)
        cls.systemctl_log = cls.tmp / "systemctl.log"
        _write(cls.bin / "systemctl", f'#!/bin/sh\necho "$@" >> {cls.systemctl_log}\nexit 0\n', 0o755)
        cls.code = cls.tmp / "code"  # one shared copy of the backend package; each release links to it
        shutil.copytree(BACKEND / "app", cls.code / "app", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(BACKEND / "migrate.py", cls.code / "migrate.py")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.database = f"vinto_prc_{uuid4().hex[:12]}_test"
        create_database(self.database)
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.app_dir = Path(tempfile.mkdtemp(prefix="app-", dir=self.tmp))
        self.systemctl_log.unlink(missing_ok=True)
        self.make_release(OLD_SHA, REAL[:9])  # the deployed release: knows up to 0009
        (self.app_dir / "current").symlink_to(self.app_dir / "releases" / OLD_SHA)

    # ---- fixtures -------------------------------------------------------------------------------------------------------------------------------------------------

    def make_release(self, sha, migrations, extra=None, prepared=True):
        """releases/<sha>/ with the release's own migrate.py, migrations folder (the given real files + optional extra {name: sql}), venv python, uvicorn, frontend build and backend/.env."""
        backend = self.app_dir / "releases" / sha / "backend"
        backend.mkdir(parents=True)
        os.symlink(self.code / "app", backend / "app")
        shutil.copy(self.code / "migrate.py", backend / "migrate.py")
        (backend / "migrations").mkdir()
        for item in migrations:
            (backend / "migrations" / item.filename).write_bytes(item.sql.encode("utf-8"))
        for name, sql in (extra or {}).items():
            _write(backend / "migrations" / name, sql)
        _write(backend / ".env", "")
        if prepared:
            (backend / ".venv" / "bin").mkdir(parents=True)
            os.symlink(sys.executable, backend / ".venv" / "bin" / "python")
            _write(backend / ".venv" / "bin" / "uvicorn", "#!/bin/sh\nexit 0\n", 0o755)
            _write(backend.parent / "dist" / "standalone" / "server.js", "")
        return backend

    def migrate_database_to(self, count):
        migrate.apply(self.connection, REAL[:count])

    def versions(self):
        return [r[0] for r in self.connection.execute("SELECT version FROM vinto_meta.schema_migration ORDER BY version").fetchall()] if self.has_history() else []

    def has_history(self):
        return self.connection.execute("SELECT to_regclass('vinto_meta.schema_migration')").fetchone()[0] is not None

    def run_phase(self, phase, sha=None, confirm=True, authorized=None, snippet=None):
        env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "MVP_APP_DIR": str(self.app_dir), "MVP_SERVICE_USER": "prc-svc-nonexistent", "PYTHONDONTWRITEBYTECODE": "1",
               "DATABASE_URL": database_url(self.database), "MIGRATOR_DATABASE_URL": database_url(self.database), "HOME": str(self.tmp)}
        if confirm:
            env["CONFIRM"] = "yes"
        if authorized:
            env["AUTHORIZED_COMMIT"] = authorized
        command = ["bash", str(self.scripts / "deploy.sh"), phase] + ([sha] if sha else [])
        if snippet:
            command = ["bash", "-c", snippet]
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=180)

    def current_target(self):
        return os.readlink(self.app_dir / "current")

    def systemctl_calls(self):
        return self.systemctl_log.read_text() if self.systemctl_log.exists() else ""

    def assert_untouched(self, versions_before, expected_current=None):
        self.assertEqual(self.versions(), versions_before)
        self.assertEqual(self.current_target(), expected_current or str(self.app_dir / "releases" / OLD_SHA), "'current' must never change")
        self.assertEqual(self.systemctl_calls(), "", "no service was restarted")


class CheckAndMigrateTests(ReleaseMigrationCase):
    # ---- 1. up to date ---------------------------------------------------------------------------------------------------------------------------------------------

    def test_an_up_to_date_database_is_reported_and_nothing_is_applied(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(NEW_COUNT)
        before = self.connection.execute("SELECT version, applied_at FROM vinto_meta.schema_migration ORDER BY version").fetchall()
        check = self.run_phase("check-release", NEW_SHA, confirm=False)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("ya incluye todas las migraciones", check.stdout)
        done = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Nada que aplicar", done.stdout)
        self.assertEqual(self.connection.execute("SELECT version, applied_at FROM vinto_meta.schema_migration ORDER BY version").fetchall(), before)
        self.assert_untouched(list(range(1, NEW_COUNT + 1)))

    # ---- 2. pending migrations -------------------------------------------------------------------------------------------------------------------------------------

    def test_pending_migrations_are_listed_read_only_with_exit_code_2(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(9)
        check = self.run_phase("check-release", NEW_SHA, confirm=False)  # no CONFIRM needed: it is read only
        self.assertEqual(check.returncode, 2, check.stdout + check.stderr)
        for name in ("0010_work_order_line_machine.sql: pendiente", "0011_assignment_same_work_order_lines.sql: pendiente", "0012_assignment_single_mode_guard.sql: pendiente"):
            self.assertIn(name, check.stdout)
        self.assertIn("migrate-release", check.stdout)
        self.assert_untouched(list(range(1, 10)))

    def test_migrate_release_demands_confirmation_and_the_exact_authorised_commit(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(9)
        no_confirm = self.run_phase("migrate-release", NEW_SHA, confirm=False, authorized=NEW_SHA)
        no_authorisation = self.run_phase("migrate-release", NEW_SHA)
        wrong_authorisation = self.run_phase("migrate-release", NEW_SHA, authorized=OLD_SHA)
        short = self.run_phase("migrate-release", "abc123", authorized="abc123")
        for result in (no_confirm, no_authorisation, wrong_authorisation, short):
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("CONFIRM=yes", no_confirm.stderr)
        self.assertIn("AUTHORIZED_COMMIT", no_authorisation.stderr)
        self.assert_untouched(list(range(1, 10)))

    # ---- 8. successful migration WITHOUT activating the release ---------------------------------------------------------------------------------------------------

    def test_a_successful_migration_leaves_current_untouched_and_restarts_nothing(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(9)
        done = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("no se reinició ningún servicio ni se activó nada", done.stdout)
        self.assertEqual(self.versions(), list(range(1, NEW_COUNT + 1)))
        self.assertEqual(self.current_target(), str(self.app_dir / "releases" / OLD_SHA))
        self.assertEqual(self.systemctl_calls(), "")
        self.assertEqual(self.connection.execute("SELECT tgenabled FROM pg_trigger WHERE tgname='validate_assignment_single_mode'").fetchone()[0], "O")

    # ---- 6. repeated execution ---------------------------------------------------------------------------------------------------------------------------------------

    def test_running_it_twice_is_idempotent(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(9)
        first = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        stamp = self.connection.execute("SELECT max(applied_at) FROM vinto_meta.schema_migration").fetchone()[0]
        second = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stdout + second.stdout + second.stderr)
        self.assertIn("Nada que aplicar", second.stdout)
        self.assertEqual(self.connection.execute("SELECT max(applied_at) FROM vinto_meta.schema_migration").fetchone()[0], stamp)

    # ---- 3. wrong checksum --------------------------------------------------------------------------------------------------------------------------------------------

    def test_a_modified_migration_is_detected_and_nothing_is_applied(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(9)
        self.connection.execute("UPDATE vinto_meta.schema_migration SET checksum = %s WHERE version = 5", ("f" * 64,))
        check = self.run_phase("check-release", NEW_SHA, confirm=False)
        done = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        for result in (check, done):
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("modificada", result.stdout + result.stderr)
        self.assertIn("Detenido: no se aplicó nada", done.stderr)
        self.assert_untouched(list(range(1, 10)))

    def test_a_release_whose_migration_file_was_edited_after_being_applied_is_refused(self):
        self.migrate_database_to(9)
        edited = self.make_release(NEW_SHA, REAL)
        target = edited / "migrations" / REAL[2].filename
        target.write_text(target.read_text(encoding="utf-8") + "\n-- edited after being applied\n", encoding="utf-8")
        done = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assert_untouched(list(range(1, 10)))

    # ---- 4. error in the middle of a migration + 9. recovery ---------------------------------------------------------------------------------------------------------------

    def test_a_failing_migration_rolls_back_only_itself_and_the_command_is_repeatable_after_the_fix(self):
        bad = "CREATE TABLE vinto_txn.prc_probe (id integer);\nSELECT 1/0;\n"
        self.make_release(NEW_SHA, REAL, extra={PROBE_NAME: bad})
        self.migrate_database_to(9)
        failed = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertIn("la migración en curso se revirtió entera", failed.stderr)
        self.assertEqual(self.versions(), list(range(1, NEW_COUNT + 1)), "all real migrations stay applied; failed probe is not registered")
        self.assertNotIn(NEW_COUNT + 1, self.versions())
        self.assertIsNone(self.connection.execute("SELECT to_regclass('vinto_txn.prc_probe')").fetchone()[0], "the failed migration left no partial DDL")
        self.assertEqual(self.current_target(), str(self.app_dir / "releases" / OLD_SHA))
        self.assertEqual(self.systemctl_calls(), "")
        # recovery: the cause is fixed in the release folder (same file name, valid SQL) and the SAME command applies only what is missing
        (self.app_dir / "releases" / NEW_SHA / "backend" / "migrations" / PROBE_NAME).write_text("CREATE TABLE vinto_txn.prc_probe (id integer);\n", encoding="utf-8")
        fixed = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual(fixed.returncode, 0, fixed.stdout + fixed.stderr)
        self.assertEqual(self.versions(), list(range(1, NEW_COUNT + 2)))
        self.assertIsNotNone(self.connection.execute("SELECT to_regclass('vinto_txn.prc_probe')").fetchone()[0])

    # ---- the release must be prepared; the database is not touched otherwise --------------------------------------------------------------------------------------------

    def test_an_unprepared_release_is_refused_before_touching_the_database(self):
        self.make_release(NEW_SHA, REAL, prepared=False)  # no venv, no frontend build
        self.migrate_database_to(9)
        done = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("No se tocó la base", done.stderr)
        self.assert_untouched(list(range(1, 10)))
        missing = self.run_phase("migrate-release", ODD_SHA, authorized=ODD_SHA)  # a release that does not exist at all
        self.assertEqual(missing.returncode, 1)
        self.assert_untouched(list(range(1, 10)))

    def test_it_uses_the_releases_own_migration_files_not_those_of_current(self):
        self.make_release(NEW_SHA, REAL[:11])  # this release only knows up to 0011
        self.migrate_database_to(9)
        done = self.run_phase("migrate-release", NEW_SHA, authorized=NEW_SHA)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.versions(), list(range(1, 12)), "0012 is NOT applied: this release does not contain it")

    # ---- 7. the activation guard -----------------------------------------------------------------------------------------------------------------------------------------

    GUARD = 'set -uo pipefail; export SCRIPT_DIR="{scripts}"; source "{scripts}/lib_common.sh"; assert_schema_migrated {argument}'

    def guard(self, argument=""):
        return self.run_phase(None, snippet=self.GUARD.format(scripts=self.scripts, argument=argument))

    def test_the_activation_guard_refuses_a_new_release_on_an_old_schema(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(9)
        refused = self.guard(f'"{self.app_dir}/releases/{NEW_SHA}"')
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("no está completamente migrado", refused.stderr)
        self.assertIn("check-release", refused.stderr)

    def test_the_old_guard_on_current_would_have_let_it_through_which_is_the_bug_being_fixed(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(9)
        on_current = self.guard()  # no argument = 'current' = the OLD release: the behaviour of `activate` before PR-C
        self.assertEqual(on_current.returncode, 0, on_current.stdout + on_current.stderr)

    def test_the_activation_guard_accepts_the_new_release_once_it_is_migrated(self):
        self.make_release(NEW_SHA, REAL)
        self.migrate_database_to(NEW_COUNT)
        self.assertEqual(self.guard(f'"{self.app_dir}/releases/{NEW_SHA}"').returncode, 0)

    def test_activate_passes_the_target_release_to_the_guard(self):
        text = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
        body = text[text.index("phase_activate() {"):text.index("phase_postgres_up() {")]
        self.assertIn('assert_schema_migrated "$release_dir"', body.replace("\r\n", "\n"))
        self.assertLess(body.index("assert_schema_migrated"), body.index('ln -sfn "$release_dir"'), "the guard runs BEFORE 'current' is switched")

    # ---- 10. application rollback without reverting the schema ----------------------------------------------------------------------------------------------------------------------

    def test_an_older_release_is_not_activatable_on_a_newer_schema_but_the_rollback_path_never_asks_the_schema(self):
        self.migrate_database_to(NEW_COUNT)
        older = self.run_phase("check-release", OLD_SHA, confirm=False)  # the deployed (older) release against the 0012 schema
        self.assertEqual(older.returncode, 1, older.stdout + older.stderr)
        self.assertIn("rollback.sh version", older.stderr)
        rollback = (SCRIPTS / "rollback.sh").read_text(encoding="utf-8")
        version_body = rollback[rollback.index("rollback_version() {"):rollback.index("rollback_postgres() {")]
        for forbidden in ("migrate.py", "assert_schema_migrated", "migrate-release"):
            self.assertNotIn(forbidden, version_body, "reverting the application must not touch or require the schema")
        self.assertEqual(self.versions(), list(range(1, NEW_COUNT + 1)), "the schema was not reverted")


class PreflightOrderTests(ReleaseMigrationCase):
    """The preflight BEFORE migrating must work on the existing schema (without 0010-0012); the verification AFTER migrating needs them. Both are read only."""

    def run_sql_file(self, name):
        import psycopg
        text = (BACKEND / "preflights" / name).read_text(encoding="utf-8")
        results = []
        with self.connection.transaction():
            self.connection.execute("SET TRANSACTION READ ONLY")  # any write would fail: the file is provably read only
            for statement in text.split(";\n"):
                if all(line.startswith("--") or not line.strip() for line in statement.splitlines()):
                    continue
                results.append(self.connection.execute(statement).fetchall())
        return results

    def test_the_preflight_before_migrating_runs_on_a_schema_without_0010_to_0012(self):
        self.migrate_database_to(9)
        self.assertIsNone(self.connection.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='vinto_txn' AND table_name='work_order_line' AND column_name='machine_id'").fetchone(),
                          "the fixture really is a pre-0010 schema")
        results = self.run_sql_file("mf13_03b_preflight_before_migrate.sql")
        self.assertEqual(results[0][0], (9, 9, True), "history 9/9 and the legacy unique index still present")
        self.assertEqual(results[2], [], "no 0011 precondition is violated")

    def test_it_also_runs_after_the_migrations_and_the_legacy_index_is_gone(self):
        self.migrate_database_to(NEW_COUNT)
        results = self.run_sql_file("mf13_03b_preflight_before_migrate.sql")
        self.assertEqual(results[0][0], (NEW_COUNT, NEW_COUNT, False))

    def test_the_verification_after_migrating_cannot_run_before_and_says_so_by_failing(self):
        import psycopg
        self.migrate_database_to(9)
        with self.assertRaises(psycopg.errors.UndefinedColumn):
            self.run_sql_file("mf13_03b_verify_after_migrate.sql")

    def test_the_verification_after_migrating_passes_on_a_migrated_database(self):
        self.migrate_database_to(NEW_COUNT)
        results = self.run_sql_file("mf13_03b_verify_after_migrate.sql")
        self.assertEqual(results[0][0][:2], (NEW_COUNT, NEW_COUNT))
        self.assertEqual(results[0][0][2], "O")
        self.assertEqual(results[3], [], "no impossible state")


if __name__ == "__main__":
    unittest.main()
