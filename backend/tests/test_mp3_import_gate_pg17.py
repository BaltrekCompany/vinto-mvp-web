"""RG01 importer: run the exact 25->26 form dry-run and apply against PG17 *_test."""
import dataclasses
import unittest
from uuid import uuid4

from app.ephemeral_db import create_database, drop_database, connect
from app.seed import reference
from app.seed.bundle import load_bundle
from mp3_rg01_import_gate import ImportGateError, check_bundle, validate_plan, inspect, EXPECTED, FORM_CODE
from migrate import apply as apply_migrations, read_migrations

BUNDLE = load_bundle()


class ImportGateStaticTests(unittest.TestCase):
    def test_exact_rg01_form_is_whitelisted_and_does_not_change_other_forms(self):
        check_bundle(BUNDLE)
        rg = next(f for f in BUNDLE.forms if f["code"] == FORM_CODE)
        self.assertEqual(rg["machines"], ["MP3"])
        self.assertEqual(len(rg["fields"]), 133)
        self.assertEqual(len([f for f in rg["fields"] if f["required"]]), 7)
        old = [f for f in BUNDLE.forms if f["code"] != FORM_CODE]
        self.assertEqual(len(old), 25)
        self.assertEqual(sum(len(f["fields"]) + sum(len(g["fields"]) for g in f["groups"]) for f in old), 437)  # CV-P113 v3 reemplaza 20 campos anteriores por 9

    def test_gate_refuses_unexpected_mutations_and_conflicts(self):
        class Report:
            def __init__(self, changes, conflicts=()):
                self.counts = {k: {"create": v, "present": 0} for k, v in changes.items()}
                self.conflicts = conflicts
        self.assertEqual(validate_plan(Report(EXPECTED)), "new")
        self.assertEqual(validate_plan(Report({})), "already_imported")
        for changes in ({"form": 2, **{k: v for k, v in EXPECTED.items() if k != "form"}}, {"field": 134}, {"machine": 1}):
            with self.assertRaises(ImportGateError):
                validate_plan(Report(changes))
        with self.assertRaises(ImportGateError):
            validate_plan(Report({}, ("unexpected drift",)))


class ImportGatePG17Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_rg01_import_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        apply_migrations(cls.connection, read_migrations())

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def test_01_import_only_rg01_from_exact_old_25_form_snapshot(self):
        # Simulate 25 forms currently in production; no business writes.
        old = dataclasses.replace(BUNDLE, forms=tuple(f for f in BUNDLE.forms if f["code"] != FORM_CODE), source_checksum="5" * 64)
        r0 = reference.apply(self.connection, old)
        self.assertEqual(r0.mode, "applied")
        before = self.connection.execute("SELECT count(*) FROM vinto_config.form").fetchone()[0]
        self.assertEqual(before, 25)
        plan = inspect(self.connection, BUNDLE)
        self.assertEqual((plan["state"], plan["pending_creates"]), ("new", 136))
        # Dry-run cannot write.
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_config.form").fetchone()[0], before)

        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual(result.mode, "applied")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_config.form").fetchone()[0], 26)
        pair = self.connection.execute(
            """SELECT m.code, v.version_number, count(fd.id)
               FROM vinto_config.form f JOIN vinto_config.form_version v ON v.form_id=f.id
               JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id=v.id
               JOIN vinto_master.machine m ON m.id=fvm.machine_id
               JOIN vinto_config.field_definition fd ON fd.form_version_id=v.id
               WHERE f.code=%s GROUP BY m.code,v.version_number""", (FORM_CODE,)).fetchall()
        self.assertEqual(pair, [("MP3", 1, 133)])
        self.assertEqual((inspect(self.connection, BUNDLE)["state"], reference.apply(self.connection,BUNDLE).mode), ("already_imported", "noop"))

    def test_02_a_second_dry_run_does_not_insert_anything(self):
        forms_before = self.connection.execute("SELECT count(*) FROM vinto_config.form").fetchone()[0]
        self.assertEqual(inspect(self.connection, BUNDLE)["state"], "already_imported")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_config.form").fetchone()[0], forms_before)


if __name__ == "__main__":
    unittest.main()
