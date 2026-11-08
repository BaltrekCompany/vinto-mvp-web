"""B2-OPS: preflight identity/privilege isolation. No live DB or VPS."""
import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg
from pydantic import SecretStr

from app.config import settings
from app.work_orders import handoff_rollout_cli as cli


class OpsIdentityTests(unittest.TestCase):
    def _invoke(self, *, mode, migrator, app_url):
        db = MagicMock()
        db.__enter__.return_value = db
        db.transaction.return_value.__enter__.return_value = None
        out, err = io.StringIO(), io.StringIO()
        with (patch.object(settings, "pg_privilege_mode", mode),
              patch.object(settings, "migrator_database_url",
                           SecretStr(migrator) if migrator else None),
              patch.object(settings, "database_url",
                           SecretStr(app_url) if app_url else None),
              patch.object(cli.psycopg, "connect", return_value=db) as connect,
              patch.object(cli, "collect", return_value={
                  "technical_preflight_clear": True,
                  "open_handoff_count": 0,
                  "blockers": []}),
              contextlib.redirect_stdout(out),
              contextlib.redirect_stderr(err)):
            rc = cli.main(["rollback"])
        return rc, connect, out.getvalue(), err.getvalue()

    def test_hardened_uses_migrator_identity_and_readonly_transaction(self):
        migrator="postgresql://migrator:very-secret@127.0.0.1:5432/vinto"
        app="postgresql://app:another-secret@127.0.0.1:5432/vinto"
        rc, connect, out, err = self._invoke(
            mode="hardened", migrator=migrator, app_url=app)
        self.assertEqual(rc, 0)
        self.assertEqual(connect.call_args.args[0], migrator)
        opts=connect.call_args.kwargs["options"]
        self.assertIn("default_transaction_read_only=on",opts)
        self.assertIn("statement_timeout=15000",opts)
        self.assertIn('"technical_preflight_clear": true',out)
        self.assertNotIn("very-secret",out+err)
        self.assertNotIn("another-secret",out+err)

    def test_hardened_without_migrator_is_failclosed(self):
        rc, connect, out, err = self._invoke(
            mode="hardened", migrator=None,
            app_url="postgresql://app:app-secret@127.0.0.1:5432/vinto")
        self.assertEqual(rc, 3)
        connect.assert_not_called()
        self.assertIn("D2_PREFLIGHT_QUERY_UNAVAILABLE",err)
        self.assertNotIn("app-secret",out+err)

    def test_legacy_uses_configured_migrator_before_app(self):
        rc, connect, _, _ = self._invoke(
            mode="legacy", migrator="postgresql://migrator/db",
            app_url="postgresql://app/db")
        self.assertEqual(rc, 0)
        self.assertEqual(connect.call_args.args[0],"postgresql://migrator/db")

    def test_legacy_app_fallback_permission_denied_is_no_go(self):
        with (patch.object(settings,"pg_privilege_mode","legacy"),
              patch.object(settings,"migrator_database_url",None),
              patch.object(settings,"database_url",
                           SecretStr("postgresql://app:private@host/vinto")),
              patch.object(cli.psycopg,"connect",
                           side_effect=psycopg.errors.InsufficientPrivilege(
                               "permission denied for schema vinto_meta")) as connect):
            err=io.StringIO()
            with contextlib.redirect_stderr(err):
                rc=cli.main(["rollback"])
            self.assertEqual(rc,3)
            self.assertEqual(connect.call_args.args[0],
                             "postgresql://app:private@host/vinto")
            self.assertEqual(err.getvalue().strip(),"D2_PREFLIGHT_QUERY_UNAVAILABLE")
            self.assertNotIn("private",err.getvalue())

    def test_no_vinto_app_grant_to_migration_meta(self):
        root=Path(__file__).resolve().parents[2]
        roles=(root/"backend/roles/02_schema_grants.sql").read_text()
        self.assertIn("NUNCA vinto_meta",roles)
        self.assertNotIn("GRANT USAGE ON SCHEMA vinto_meta TO vinto_app;", "\n".join(
            line for line in roles.splitlines()
            if line.strip() and not line.strip().startswith("--")))


if __name__=="__main__":
    unittest.main()
