"""Barrera de importación a DEV (M1-B2-c2a): un catálogo CANDIDATO o un directorio no promovido nunca puede aplicarse a DEV.

Ninguna prueba abre una conexión a la base de desarrollo: `import_reference.open_connection` se reemplaza SIEMPRE (un centinela o una base efímera *_test).
"""

import contextlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import import_reference
from app.db_guard import UnsafeDatabaseError
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed import reference
from app.seed.bundle import BUNDLE_DIR, load_bundle

STATE = {}


class ConnectionAttempted(Exception):
    """Centinela: la barrera dejó pasar la operación y el CLI intentó abrir la conexión (que es una simulación, nunca DEV)."""


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devguard_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE.pop("template"))


def copy_bundle(case):
    directory = Path(tempfile.mkdtemp(prefix="seed-guard-bundle-"))
    case.addCleanup(shutil.rmtree, directory, ignore_errors=True)
    shutil.copytree(BUNDLE_DIR, directory, dirs_exist_ok=True)
    return directory


def mark_candidate(directory, warning=True):
    """Convierte la copia en un bundle de aspecto CANDIDATO, como los que genera el exportador (scope.candidate + advertencia)."""
    path = Path(directory) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["scope"]["candidate"] = True
    if warning:
        manifest["warnings"].append({"code": "SCOPE_PENDING_APPROVAL", "severity": "warning", "message": "Alcance CANDIDATO: no autorizado para DEV."})
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return directory


class DevGuardCase(unittest.TestCase):
    def run_cli(self, *arguments, opens="forbidden", official=None):
        """Ejecuta import_reference.main con la conexión simulada. opens='forbidden': tocar la conexión es un fallo de la prueba."""
        side_effect = AssertionError("la conexión a DEV no debe abrirse") if opens == "forbidden" else ConnectionAttempted()
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            opened = stack.enter_context(patch.object(import_reference, "open_connection", side_effect=side_effect))
            if official is not None:
                stack.enter_context(patch.object(import_reference, "BUNDLE_DIR", official))
            stack.enter_context(contextlib.redirect_stdout(out))
            try:
                code = import_reference.main(list(arguments))
            except ConnectionAttempted:
                code = "connection-attempted"
        return code, out.getvalue(), opened


class RejectedForDevTests(DevGuardCase):
    def test_a_candidate_bundle_is_rejected_for_dev_apply_before_any_connection(self):
        directory = mark_candidate(copy_bundle(self))
        code, output, opened = self.run_cli("--target", "dev", "--apply", "--bundle", str(directory))
        self.assertEqual(code, 1)
        opened.assert_not_called()
        self.assertIn("rechazada", output)
        self.assertNotIn(str(directory), output, "the message must not reveal absolute paths")
        self.assertNotRegex(output.lower(), r"password|postgresql://|secret|token")

    def test_an_unpromoted_external_directory_is_rejected_even_without_the_candidate_flag(self):
        directory = copy_bundle(self)  # byte-identical to the approved bundle, but not the official directory
        self.assertEqual(load_bundle(directory).source_checksum, load_bundle().source_checksum)
        code, output, opened = self.run_cli("--target", "dev", "--apply", "--bundle", str(directory))
        self.assertEqual(code, 1)
        opened.assert_not_called()
        self.assertIn("solo admite el bundle oficial", output)
        # a directory that merely LOOKS official is still not the official one
        lookalike = directory.parent / f"{directory.name}-x" / "seed_data"
        shutil.copytree(directory, lookalike)
        self.addCleanup(shutil.rmtree, lookalike.parent, ignore_errors=True)
        code, _, opened = self.run_cli("--target", "dev", "--apply", "--bundle", str(lookalike))
        self.assertEqual(code, 1)
        opened.assert_not_called()

    def test_a_candidate_manifest_that_ends_up_in_the_official_directory_is_still_rejected(self):
        accidental = mark_candidate(copy_bundle(self))  # pretend the official directory contains a candidate manifest
        for arguments in (("--target", "dev", "--apply"), ("--target", "dev", "--apply", "--bundle", str(accidental))):
            code, output, opened = self.run_cli(*arguments, official=accidental)
            self.assertEqual(code, 1, arguments)
            opened.assert_not_called()
            self.assertIn("CANDIDATO", output)
        # the flag alone is enough, without the warning
        code, _, opened = self.run_cli("--target", "dev", "--apply", official=mark_candidate(copy_bundle(self), warning=False))
        self.assertEqual(code, 1)
        opened.assert_not_called()

    def test_missing_or_broken_bundles_are_rejected_before_any_connection(self):
        for target in (str(Path(tempfile.gettempdir()) / "no-such-bundle-dir"), tempfile.gettempdir()):
            code, _, opened = self.run_cli("--target", "dev", "--apply", "--bundle", target)
            self.assertEqual(code, 1)
            opened.assert_not_called()

    def test_equivalent_paths_and_links_cannot_impersonate_the_official_bundle(self):
        outside = copy_bundle(self)
        link = outside.parent / f"{outside.name}-link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available here")
        self.addCleanup(lambda: link.unlink() if link.is_symlink() else None)
        for candidate_path in (link, link / ".", outside / ".." / outside.name, str(outside) + os.sep):
            code, _, opened = self.run_cli("--target", "dev", "--apply", "--bundle", str(candidate_path))
            self.assertEqual(code, 1, candidate_path)
            opened.assert_not_called()
        # a link that points to a candidate is rejected too, whatever its name
        mark_candidate(outside)
        code, _, opened = self.run_cli("--target", "dev", "--apply", "--bundle", str(link))
        self.assertEqual(code, 1)
        opened.assert_not_called()

    def test_there_is_no_bypass_option(self):
        help_text = io.StringIO()
        with contextlib.redirect_stdout(help_text), self.assertRaises(SystemExit):
            import_reference.main(["--help"])
        options = set(re.findall(r"(?m)^  (?:-h, )?(--[a-z]+)", help_text.getvalue()))  # the options argparse itself lists
        self.assertEqual(options, {"--target", "--apply", "--bundle", "--help"})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            import_reference.main(["--target", "dev", "--apply", "--force"])


class AllowedTests(DevGuardCase):
    def test_the_official_bundle_keeps_its_normal_behaviour_for_dev(self):
        for arguments in (("--target", "dev", "--apply"), ("--target", "dev", "--apply", "--bundle", str(BUNDLE_DIR)), ("--target", "dev")):
            code, output, opened = self.run_cli(*arguments, opens="sentinel")
            self.assertEqual(code, "connection-attempted", arguments)  # the guard let it through; the connection is the sentinel, never DEV
            opened.assert_called_once_with("dev")
            self.assertIn("Bundle válido", output)

    def test_equivalent_spellings_of_the_official_path_are_the_official_bundle(self):
        equivalents = (BUNDLE_DIR / ".." / BUNDLE_DIR.name, Path(str(BUNDLE_DIR) + os.sep), BUNDLE_DIR / ".")
        for path in equivalents:
            code, _, opened = self.run_cli("--target", "dev", "--apply", "--bundle", str(path), opens="sentinel")
            self.assertEqual(code, "connection-attempted", path)
            opened.assert_called_once_with("dev")

    def test_a_link_to_the_official_directory_is_the_official_bundle(self):
        link = Path(tempfile.mkdtemp(prefix="seed-guard-link-")) / "alias"
        self.addCleanup(shutil.rmtree, link.parent, ignore_errors=True)
        try:
            os.symlink(BUNDLE_DIR, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available here")
        code, _, _ = self.run_cli("--target", "dev", "--apply", "--bundle", str(link), opens="sentinel")
        self.assertEqual(code, "connection-attempted")

    def test_a_future_promoted_bundle_in_the_official_directory_can_be_imported(self):
        # Promotion = a reviewed change of backend/seed_data to a bundle WITHOUT the candidate flag: it passes both barriers and reaches the connection.
        promoted = copy_bundle(self)
        manifest_path = promoted / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["scope"].pop("candidate", None)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        for arguments in (("--target", "dev", "--apply"), ("--target", "dev", "--apply", "--bundle", str(promoted))):
            code, output, opened = self.run_cli(*arguments, opens="sentinel", official=promoted)
            self.assertEqual(code, "connection-attempted", arguments)
            opened.assert_called_once_with("dev")
            self.assertIn("Bundle válido", output)

    def test_a_dev_dry_run_is_not_blocked_because_it_writes_nothing(self):
        candidate = mark_candidate(copy_bundle(self))
        code, _, opened = self.run_cli("--target", "dev", "--bundle", str(candidate), opens="sentinel")
        self.assertEqual(code, "connection-attempted")
        opened.assert_called_once_with("dev")


class EphemeralDatabaseTests(DevGuardCase):
    """Candidates remain fully usable against *_test databases: dry-run, apply and a second idempotent apply."""

    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_devguard")
        self.addCleanup(drop_database, self.database)

    def cli(self, *arguments):
        out = io.StringIO()
        with patch.object(import_reference, "open_connection", side_effect=lambda target: connect(self.database)), contextlib.redirect_stdout(out):
            return import_reference.main(list(arguments)), out.getvalue()

    def test_a_candidate_bundle_can_be_dry_run_applied_and_applied_again_on_a_test_database(self):
        candidate = mark_candidate(copy_bundle(self))
        code, output = self.cli("--target", "test", "--bundle", str(candidate))
        self.assertEqual(code, 0, output)
        code, output = self.cli("--target", "test", "--apply", "--bundle", str(candidate))
        self.assertEqual(code, 0, output)
        with connect(self.database) as connection:
            count = lambda: connection.execute("SELECT count(*) FROM vinto_master.article").fetchone()[0]
            first = count()
        code, output = self.cli("--target", "test", "--apply", "--bundle", str(candidate))
        self.assertEqual(code, 0, output)
        self.assertIn("NO-OP", output)
        with connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM vinto_master.article").fetchone()[0], first)

    def test_the_official_bundle_still_imports_normally_on_a_test_database(self):
        code, output = self.cli("--target", "test", "--apply")
        self.assertEqual(code, 0, output)
        self.assertRegex(output, r"NO-OP|completada")


class ApplyLevelDefenceTests(unittest.TestCase):
    """reference.apply refuses a candidate on any database that is not a *_test one, whoever calls it."""

    class FakeConnection:
        def __init__(self, database):
            self.database, self.statements = database, []

        def execute(self, sql, params=()):
            self.statements.append(sql)
            if "current_database" in sql:
                database = self.database
                return type("Cursor", (), {"fetchone": lambda self_: (database,)})()
            raise AssertionError("nothing else may run before the refusal")

        def transaction(self):
            raise AssertionError("no transaction may start")

    def candidate_bundle(self):
        directory = Path(tempfile.mkdtemp(prefix="seed-guard-apply-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        shutil.copytree(BUNDLE_DIR, directory, dirs_exist_ok=True)
        return load_bundle(mark_candidate(directory))

    def test_a_candidate_is_refused_on_a_non_test_database_without_running_anything_else(self):
        for name in ("vinto", "vinto_dev", "production", "test_vinto", "_test"):
            connection = self.FakeConnection(name)
            with self.assertRaises(UnsafeDatabaseError, msg=name):
                reference.apply(connection, self.candidate_bundle())
            self.assertEqual(connection.statements, ["SELECT current_database()"], name)

    def test_the_approved_bundle_is_not_subject_to_this_defence(self):
        connection = self.FakeConnection("vinto")
        with self.assertRaises(AssertionError):  # it goes on to open the transaction (the fake refuses), proving it was not refused as a candidate
            reference.apply(connection, load_bundle())


if __name__ == "__main__":
    unittest.main()
