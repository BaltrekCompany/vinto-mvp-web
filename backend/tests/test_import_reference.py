"""Reference importer. Every database test runs in ephemeral *_test databases created from a
migrated template, so results never depend on what an earlier manual run left in vinto_test and
nothing is left behind. All connections go through connect_test_database() (current_database()).
"""

import contextlib
import dataclasses
import hashlib
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import import_reference
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.config import settings
from app.db_guard import connect_test_database, is_test_database_name
from app.seed import reference
from app.seed.bundle import BUNDLE_DIR, BundleError, canonical_json, compute_source_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

BUNDLE = load_bundle()
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
    suffix = uuid4().hex[:10]
    STATE["empty"], STATE["imported"] = f"vinto_tpl_empty_{suffix}_test", f"vinto_tpl_imported_{suffix}_test"
    create_database(STATE["empty"])
    with connect(STATE["empty"]) as connection, contextlib.redirect_stdout(io.StringIO()):
        apply_migrations(connection, read_migrations())
    create_database(STATE["imported"], template=STATE["empty"])
    with connect(STATE["imported"]) as connection:
        reference.apply(connection, BUNDLE)


def tearDownModule():
    for name in (STATE.get("imported"), STATE.get("empty")):
        if name:
            drop_database(name)


class DatabaseCase(unittest.TestCase):
    def new_database(self, template="empty"):
        name = f"vinto_imp_{uuid4().hex[:12]}_test"
        create_database(name, template=STATE[template])
        self.addCleanup(drop_database, name)
        return name

    def open(self, name):
        connection = connect(name)
        self.addCleanup(connection.close)
        return connection

    @staticmethod
    def count(connection, table, where="true"):
        return connection.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]

    def tables_snapshot(self, connection):
        tables = ["vinto_master.unit", "vinto_master.material_class", "vinto_master.sector", "vinto_master.machine",
                  "vinto_master.profile", "vinto_master.article", "vinto_master.article_version", "vinto_master.article_machine",
                  "vinto_config.shift", "vinto_config.shift_schedule", "vinto_config.workflow_definition", "vinto_config.form",
                  "vinto_config.form_version", "vinto_config.form_version_machine", "vinto_config.field_definition",
                  "vinto_config.field_option", "vinto_audit.import_batch", "vinto_audit.import_record", "vinto_audit.audit_event"]
        return {t: self.count(connection, t) for t in tables}


def modified_bundle_dir(testcase):
    directory = Path(tempfile.mkdtemp(prefix="seed-bundle-"))
    testcase.addCleanup(shutil.rmtree, directory, ignore_errors=True)
    shutil.copytree(BUNDLE_DIR, directory, dirs_exist_ok=True)
    return directory


class BundleValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = modified_bundle_dir(self)

    def test_valid_bundle_is_accepted(self):
        bundle = load_bundle(self.directory)
        self.assertEqual((len(bundle.articles), len(bundle.units), len(bundle.profiles)), (93, 2, 5))

    def test_source_checksum_is_the_sha256_of_the_canonical_manifest(self):
        manifest = json.loads((BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
        expected = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
        self.assertEqual(BUNDLE.source_checksum, expected)
        self.assertRegex(BUNDLE.source_checksum, r"^[a-f0-9]{64}$")
        self.assertEqual(compute_source_checksum(manifest), expected)

    def test_altered_file_is_rejected_before_any_write(self):
        path = self.directory / "articles.json"
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "SHA-256 no coincide"):
            load_bundle(self.directory)
        with patch.object(import_reference, "open_connection", side_effect=AssertionError("no debe conectarse")) as opened, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = import_reference.main(["--target", "test", "--apply", "--bundle", str(self.directory)])
        self.assertEqual(code, 1)
        opened.assert_not_called()
        self.assertIn("Bundle rechazado", output.getvalue())

    def test_unknown_manifest_schema_version_is_rejected(self):
        path = self.directory / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 99
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "schema_version"):
            load_bundle(self.directory)

    def test_wrong_form_definition_checksum_is_rejected(self):
        form_path = self.directory / "forms" / "VINTO-P1-06.json"
        form = json.loads(form_path.read_text(encoding="utf-8"))
        form["definition_checksum"] = "0" * 64
        text = json.dumps(form, indent=2, ensure_ascii=False) + "\n"
        form_path.write_text(text, encoding="utf-8")
        manifest_path = self.directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:  # keep file hash/size consistent so the checksum rule is what fails
            if entry["path"] == "forms/VINTO-P1-06.json":
                entry["sha256"], entry["bytes"] = hashlib.sha256(text.encode()).hexdigest(), len(text.encode())
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "definition_checksum"):
            load_bundle(self.directory)

    def test_missing_extra_and_miscounted_files_are_rejected(self):
        (self.directory / "extra.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "no declarado"):
            load_bundle(self.directory)
        (self.directory / "extra.json").unlink()
        (self.directory / "profiles.json").unlink()
        with self.assertRaisesRegex(BundleError, "Falta el archivo declarado"):
            load_bundle(self.directory)

    def test_unsafe_manifest_paths_are_rejected(self):
        path = self.directory / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][0]["path"] = "../outside.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(BundleError, "Ruta no permitida"):
            load_bundle(self.directory)

    def test_target_is_mandatory(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            import_reference.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_advisory_lock_key_is_deterministic_and_bigint(self):
        key = reference.advisory_lock_key(reference.SOURCE)
        self.assertEqual(key, reference.advisory_lock_key(reference.SOURCE))
        self.assertNotEqual(key, reference.advisory_lock_key("another-source"))
        self.assertTrue(-(2 ** 63) <= key < 2 ** 63)

    def test_advisory_lock_key_does_not_depend_on_the_checksum(self):
        import inspect
        self.assertEqual(list(inspect.signature(reference.advisory_lock_key).parameters), ["source"])


class SpyConnection:
    """Records every statement so a dry-run can be proven free of writes."""

    def __init__(self, connection):
        self.connection, self.statements = connection, []

    def execute(self, query, *args, **kwargs):
        self.statements.append(str(query))
        return self.connection.execute(query, *args, **kwargs)

    def transaction(self, *args, **kwargs):
        return self.connection.transaction(*args, **kwargs)


class DryRunTests(DatabaseCase):
    def test_dry_run_writes_zero_rows(self):
        connection = self.open(self.new_database())
        before = self.tables_snapshot(connection)
        spy = SpyConnection(connection)
        result = reference.dry_run(spy, BUNDLE)
        self.assertEqual(result.mode, "dry-run")
        self.assertEqual(result.conflicts, [])
        self.assertEqual(result.counts["article"], {"create": 93, "present": 0})
        self.assertEqual(self.tables_snapshot(connection), before)
        self.assertEqual(before["vinto_audit.import_batch"], 0)
        self.assertIn("SET TRANSACTION READ ONLY", spy.statements)
        writes = [s for s in spy.statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "DROP", "ALTER"))]
        self.assertEqual(writes, [])

    def test_dry_run_detects_an_existing_conflict(self):
        connection = self.open(self.new_database())
        connection.execute("INSERT INTO vinto_master.unit (code,label) VALUES ('KG','Kilogramo')")
        before = self.tables_snapshot(connection)
        result = reference.dry_run(connection, BUNDLE)
        self.assertEqual([c.key for c in result.conflicts], ["unit:KG"])
        self.assertIn("label", result.conflicts[0].detail)
        self.assertEqual(self.tables_snapshot(connection), before)

    def test_dry_run_on_a_consistent_imported_database_is_consistent_with_zero_writes(self):
        connection = self.open(self.new_database("imported"))
        before = self.tables_snapshot(connection)
        spy = SpyConnection(connection)
        result = reference.dry_run(spy, BUNDLE)
        self.assertEqual((result.mode, result.state), ("dry-run", "consistent"))
        self.assertIsNotNone(result.batch_id)  # the completed batch is reported, but the database is still compared
        self.assertEqual((result.conflicts, result.pending_creates), ([], 0))
        self.assertEqual(sum(n["present"] for n in result.counts.values()), 312)
        self.assertEqual(self.tables_snapshot(connection), before)
        self.assertEqual([s for s in spy.statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))], [])

    def test_dry_run_on_an_empty_database_is_pending_not_consistent(self):
        connection = self.open(self.new_database())
        result = reference.dry_run(connection, BUNDLE)
        self.assertEqual((result.state, result.pending_creates), ("pending", 312))


class ImportedStateTests(DatabaseCase):
    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_imp_{uuid4().hex[:12]}_test"
        create_database(cls.database, template=STATE["imported"])
        cls.connection = connect(cls.database)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def rows(self, query, params=()):
        return self.connection.execute(query, params).fetchall()

    def test_masters_have_the_expected_counts_and_values(self):
        c = self.connection
        self.assertEqual(self.rows("SELECT code FROM vinto_master.unit ORDER BY code"), [("KG",), ("UN",)])
        self.assertEqual(self.count(c, "vinto_master.material_class"), 4)
        self.assertEqual(self.rows("SELECT code,name FROM vinto_master.sector"), [("BOBINAS", "Bobinas")])
        self.assertEqual(self.rows("SELECT m.code,s.code FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id=m.sector_id ORDER BY 1"),
                         [("MP1", "BOBINAS"), ("MP3", "BOBINAS")])
        self.assertEqual(self.count(c, "vinto_master.article"), 93)
        self.assertEqual(self.count(c, "vinto_master.article_version", "version_number=1"), 93)
        self.assertEqual(self.count(c, "vinto_master.article_machine"), 93)
        self.assertEqual({r[0] for r in self.rows("SELECT code FROM vinto_master.profile")},
                         {"JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"})
        self.assertEqual(self.rows("SELECT code FROM vinto_config.workflow_definition"), [("production-standard",)])
        self.assertEqual(self.rows("SELECT code FROM vinto_config.shift ORDER BY code"), [("DIA",), ("NOCHE",)])

    def test_shift_schedules(self):
        rows = self.rows("""SELECT sh.code,sc.starts_at::text,sc.ends_at::text,sc.timezone,sc.valid_from::text,sc.valid_to,s.code
                            FROM vinto_config.shift_schedule sc JOIN vinto_config.shift sh ON sh.id=sc.shift_id
                            JOIN vinto_master.sector s ON s.id=sc.sector_id ORDER BY sh.code""")
        self.assertEqual(rows, [("DIA", "07:00:00", "19:00:00", "America/La_Paz", "2026-01-01", None, "BOBINAS"),
                                ("NOCHE", "19:00:00", "07:00:00", "America/La_Paz", "2026-01-01", None, "BOBINAS")])

    def test_articles_without_material_class_and_dual_articles(self):
        for code in ("M3-3013", "M3-3418"):
            row = self.rows("""SELECT a.is_product,a.is_material,v.material_class_id FROM vinto_master.article a
                               JOIN vinto_master.article_version v ON v.article_id=a.id WHERE a.code=%s""", (code,))
            self.assertEqual(row, [(True, False, None)], code)
        self.assertEqual(self.count(self.connection, "vinto_master.article", "is_product AND is_material"), 91)
        self.assertEqual(self.count(self.connection, "vinto_master.article", "is_product"), 93)
        self.assertEqual(self.count(self.connection, "vinto_master.article_version", "material_class_id IS NULL"), 2)
        self.assertEqual(self.count(self.connection, "vinto_master.article_version", "nominal_weight_kg IS NOT NULL"), 0)

    def test_article_versions_and_form_point_to_the_completed_batch(self):
        batches = self.rows("SELECT id,source,source_checksum,status,completed_at IS NOT NULL FROM vinto_audit.import_batch")
        self.assertEqual(len(batches), 1)
        batch_id, source, checksum, status, completed = batches[0]
        self.assertEqual((source, checksum, status, completed), (reference.SOURCE, BUNDLE.source_checksum, "completed", True))
        self.assertEqual(self.count(self.connection, "vinto_master.article_version", f"source_batch_id='{batch_id}'"), 93)
        self.assertEqual(self.count(self.connection, "vinto_config.form_version", f"source_batch_id='{batch_id}'"), 1)

    def test_import_records_cover_every_entity_with_unique_keys(self):
        total = self.count(self.connection, "vinto_audit.import_record")
        self.assertEqual(total, 312)
        self.assertEqual(self.count(self.connection, "vinto_audit.import_record", "status='accepted' AND issues='[]'::jsonb"), 312)
        self.assertEqual(self.rows("SELECT summary->>'records' FROM vinto_audit.import_batch"), [("312",)])
        keys = {r[0] for r in self.rows("SELECT source_key FROM vinto_audit.import_record")}
        self.assertIn("unit:KG", keys)
        self.assertIn("form_version:VINTO-P1-06:1", keys)
        self.assertIn("option:VINTO-P1-06:1:punto_merma:bobina_rechazada", keys)
        self.assertEqual(self.count(self.connection, "vinto_audit.import_record", "target_table='unit' AND target_id IS NOT NULL"), 2)

    def test_form_six_is_published_with_the_bundle_checksum(self):
        form = BUNDLE.forms[0]
        self.assertEqual(self.rows("SELECT code,legacy_key,legacy_number FROM vinto_config.form"),
                         [("VINTO-P1-06", "form_6_registro_de_control_de_fardos", 6)])
        self.assertEqual(self.rows("SELECT version_number,status,published_at IS NOT NULL,definition_checksum,area,name FROM vinto_config.form_version"),
                         [(1, "published", True, form["definition_checksum"], "production", form["name"])])
        self.assertEqual(self.rows("SELECT m.code FROM vinto_config.form_version_machine fvm JOIN vinto_master.machine m ON m.id=fvm.machine_id ORDER BY 1"),
                         [("MP1",), ("MP3",)])

    def test_form_six_fields_types_required_and_units(self):
        rows = self.rows("""SELECT f.key,f.value_type,f.source,f.required,u.code,f.field_group_id IS NULL,f.display_order
                            FROM vinto_config.field_definition f LEFT JOIN vinto_master.unit u ON u.id=f.unit_id ORDER BY f.display_order""")
        self.assertEqual(rows, [
            ("cantidad_fardos", "integer", "manual", True, None, True, 1),
            ("punto_merma", "text", "manual", True, None, True, 2),
            ("tipo_producto", "text", "manual", True, None, True, 3),
            ("peso_kg", "decimal", "manual", True, "KG", True, 4),
            ("observaciones", "textarea", "manual", False, None, True, 5)])
        self.assertEqual(self.count(self.connection, "vinto_config.field_group"), 0)

    def test_form_six_options(self):
        rows = self.rows("""SELECT f.key,o.option_key FROM vinto_config.field_option o
                            JOIN vinto_config.field_definition f ON f.id=o.field_definition_id ORDER BY f.display_order,o.display_order""")
        self.assertEqual(rows, [("punto_merma", "bobina_rechazada"), ("punto_merma", "recorte_maquina"),
                                ("tipo_producto", "servilleta"), ("tipo_producto", "hoja_doble"), ("tipo_producto", "hoja_simple")])

    def test_nothing_outside_the_scope_was_created(self):
        for table in ("vinto_master.user", "vinto_master.user_profile", "vinto_auth.credential", "vinto_auth.session", "vinto_auth.auth_event",
                      "vinto_master.device", "vinto_txn.work_order", "vinto_txn.work_order_version", "vinto_txn.work_order_line",
                      "vinto_txn.assignment", "vinto_txn.capture", "vinto_txn.capture_detail", "vinto_config.recipe_version",
                      "vinto_txn.bobbin", "vinto_txn.quality_release"):
            self.assertEqual(self.count(self.connection, table), 0, table)

    def test_import_never_set_an_actor(self):
        self.assertEqual(self.count(self.connection, "vinto_master.unit", "created_by IS NOT NULL"), 0)
        reasons = {r[0] for r in self.rows("SELECT DISTINCT reason FROM vinto_audit.audit_event")}
        self.assertEqual(reasons, {reference.REASON})
        self.assertEqual(self.count(self.connection, "vinto_audit.audit_event", "actor_id IS NOT NULL"), 0)


class ApplyTests(DatabaseCase):
    def test_first_import_then_noop_with_a_single_completed_batch(self):
        connection = self.open(self.new_database())
        first = reference.apply(connection, BUNDLE)
        self.assertEqual(first.mode, "applied")
        self.assertEqual(sum(n["create"] for n in first.counts.values()), 312)
        after_first = self.tables_snapshot(connection)
        second = reference.apply(connection, BUNDLE)
        self.assertEqual((second.mode, second.batch_id), ("noop", first.batch_id))
        self.assertEqual(self.tables_snapshot(connection), after_first)
        self.assertEqual(self.count(connection, "vinto_audit.import_batch", "status='completed'"), 1)

    def test_cli_dry_run_then_apply_then_noop(self):
        name = self.new_database()
        with patch.object(import_reference, "open_connection", side_effect=lambda target: connect(name)):
            outputs = []
            for arguments in (["--target", "test"], ["--target", "test", "--apply"], ["--target", "test", "--apply"]):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(import_reference.main(arguments), 0)
                outputs.append(output.getvalue())
        self.assertIn("0 filas escritas", outputs[0])
        self.assertIn("Importación completada", outputs[1])
        self.assertIn("NO-OP", outputs[2])

    def test_changed_checksum_creates_a_new_batch_and_leaves_existing_rows_untouched(self):
        connection = self.open(self.new_database("imported"))
        before = connection.execute("SELECT id,published_at FROM vinto_config.form_version").fetchall()
        other = dataclasses.replace(BUNDLE, source_checksum="b" * 64)
        result = reference.apply(connection, other)
        self.assertEqual(result.mode, "applied")
        self.assertTrue(all(n["create"] == 0 for n in result.counts.values()))
        self.assertEqual(self.count(connection, "vinto_audit.import_batch", "status='completed'"), 2)
        self.assertEqual(connection.execute("SELECT id,published_at FROM vinto_config.form_version").fetchall(), before)
        self.assertEqual(self.count(connection, "vinto_config.field_definition"), 5)
        self.assertEqual(self.count(connection, "vinto_audit.import_record", "issues='[\"already_present\"]'::jsonb"), 312)

    def test_identical_existing_article_is_not_modified(self):
        connection = self.open(self.new_database())
        article = next(a for a in BUNDLE.articles if a["version"]["material_class"])
        version = article["version"]
        connection.execute("INSERT INTO vinto_master.unit (code,label) VALUES (%s,%s)", (version["unit"], version["unit"]))
        klass = next(c for c in BUNDLE.material_classes if c["code"] == version["material_class"])
        connection.execute("INSERT INTO vinto_master.material_class (code,name) VALUES (%s,%s)", (klass["code"], klass["name"]))
        article_id = connection.execute("INSERT INTO vinto_master.article (code,is_product,is_material) VALUES (%s,%s,%s) RETURNING id",
                                        (article["code"], article["is_product"], article["is_material"])).fetchone()[0]
        connection.execute("""INSERT INTO vinto_master.article_version (article_id,version_number,description,unit_id,material_class_id)
                              SELECT %s,1,%s,(SELECT id FROM vinto_master.unit WHERE code=%s),(SELECT id FROM vinto_master.material_class WHERE code=%s)""",
                           (article_id, version["description"], version["unit"], klass["code"]))
        snapshot = connection.execute("SELECT id,source_batch_id,effective_at FROM vinto_master.article_version WHERE article_id=%s", (article_id,)).fetchall()
        result = reference.apply(connection, BUNDLE)
        self.assertEqual(result.mode, "applied")
        self.assertEqual(connection.execute("SELECT id,source_batch_id,effective_at FROM vinto_master.article_version WHERE article_id=%s", (article_id,)).fetchall(), snapshot)
        self.assertEqual(snapshot[0][1], None)
        self.assertEqual(result.counts["article"], {"create": 92, "present": 1})
        issues = connection.execute("SELECT issues FROM vinto_audit.import_record WHERE source_key=%s",
                                    (f"article_version:{article['code']}:1",)).fetchone()[0]
        self.assertEqual(issues, ["already_present"])
        self.assertEqual(self.count(connection, "vinto_master.article_version"), 93)

    def test_article_version_one_with_different_content_is_a_conflict_without_writes(self):
        connection = self.open(self.new_database())
        article = BUNDLE.articles[0]
        connection.execute("INSERT INTO vinto_master.unit (code,label) VALUES (%s,%s)", (article["version"]["unit"], article["version"]["unit"]))
        article_id = connection.execute("INSERT INTO vinto_master.article (code,is_product,is_material) VALUES (%s,%s,%s) RETURNING id",
                                        (article["code"], article["is_product"], article["is_material"])).fetchone()[0]
        connection.execute("""INSERT INTO vinto_master.article_version (article_id,version_number,description,unit_id)
                              SELECT %s,1,'DESCRIPCION DISTINTA',id FROM vinto_master.unit WHERE code=%s""", (article_id, article["version"]["unit"]))
        before = self.tables_snapshot(connection)
        with self.assertRaises(reference.ReferenceConflictError) as raised:
            reference.apply(connection, BUNDLE)
        self.assertIn(f"article_version:{article['code']}:1", [c.key for c in raised.exception.conflicts])
        self.assertEqual(self.tables_snapshot(connection), before)

    def test_same_form_version_with_different_checksum_is_a_conflict(self):
        connection = self.open(self.new_database("imported"))
        before = self.tables_snapshot(connection)
        changed = dict(BUNDLE.forms[0], definition_checksum="0" * 64)
        other = dataclasses.replace(BUNDLE, forms=(changed,), source_checksum="c" * 64)
        with self.assertRaisesRegex(reference.ReferenceConflictError, "form_version:VINTO-P1-06:1"):
            reference.apply(connection, other)
        self.assertEqual(self.tables_snapshot(connection), before)

    def test_late_conflict_rolls_everything_back(self):
        connection = self.open(self.new_database())
        connection.execute("INSERT INTO vinto_config.workflow_definition (code,name) VALUES ('production-standard','production-standard')")
        form_id = connection.execute("INSERT INTO vinto_config.form (legacy_key,code,legacy_number) VALUES (%s,%s,6) RETURNING id",
                                     (BUNDLE.forms[0]["legacy_key"], BUNDLE.forms[0]["code"])).fetchone()[0]
        connection.execute("""INSERT INTO vinto_config.form_version (form_id,version_number,name,area,workflow_id,definition_checksum)
                              SELECT %s,1,%s,'production',id,%s FROM vinto_config.workflow_definition""",
                           (form_id, BUNDLE.forms[0]["name"], "f" * 64))
        before = self.tables_snapshot(connection)
        with self.assertRaises(reference.ReferenceConflictError):
            reference.apply(connection, BUNDLE)  # units, articles, shifts... were inserted before the form was compared
        self.assertEqual(self.tables_snapshot(connection), before)
        self.assertEqual(self.count(connection, "vinto_audit.import_batch"), 0)
        self.assertEqual(self.count(connection, "vinto_audit.import_batch", "status='completed'"), 0)
        self.assertEqual(self.count(connection, "vinto_master.unit"), 0)
        self.assertEqual(self.count(connection, "vinto_config.form_version", "status='draft'"), 1)  # only the pre-existing one
        self.assertEqual(self.count(connection, "vinto_config.field_definition"), 0)

    def test_no_orphan_draft_form_version_after_a_failed_import(self):
        connection = self.open(self.new_database())
        connection.execute("INSERT INTO vinto_master.unit (code,label) VALUES ('KG','Kilogramo')")  # conflict raised after the form was created
        with self.assertRaises(reference.ReferenceConflictError):
            reference.apply(connection, BUNDLE)
        self.assertEqual(self.count(connection, "vinto_config.form_version"), 0)
        self.assertEqual(self.count(connection, "vinto_config.form"), 0)
        self.assertEqual(self.count(connection, "vinto_audit.import_batch"), 0)


class ConcurrencyTests(DatabaseCase):
    def test_two_equal_imports_leave_a_single_completed_batch(self):
        for _ in range(2):
            name = self.new_database()
            barrier, results, errors = threading.Barrier(2), [], []

            def worker():
                try:
                    with connect(name) as connection:
                        barrier.wait(timeout=10)
                        results.append(reference.apply(connection, BUNDLE).mode)
                except Exception as error:  # pragma: no cover - reported by the assertion below
                    errors.append(repr(error))

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=120)
            self.assertEqual(errors, [])
            self.assertEqual(sorted(results), ["applied", "noop"])
            with connect(name) as connection:
                self.assertEqual(self.count(connection, "vinto_audit.import_batch"), 1)
                self.assertEqual(self.count(connection, "vinto_audit.import_batch", "status='completed'"), 1)
                self.assertEqual(self.count(connection, "vinto_master.article"), 93)
                self.assertEqual(self.count(connection, "vinto_audit.import_record"), 312)
            drop_database(name)


class ConsistentStateTests(DatabaseCase):
    def test_apply_on_a_consistent_imported_database_is_a_noop_with_zero_writes(self):
        connection = self.open(self.new_database("imported"))
        before = self.tables_snapshot(connection)
        spy = SpyConnection(connection)
        result = reference.apply(spy, BUNDLE)
        self.assertEqual(result.mode, "noop")
        self.assertEqual(sum(n["present"] for n in result.counts.values()), 312)
        self.assertEqual(self.tables_snapshot(connection), before)
        self.assertEqual(self.count(connection, "vinto_audit.import_batch"), 1)
        self.assertEqual([s for s in spy.statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))], [])


class DriftTests(DatabaseCase):
    """A completed batch must not hide manual changes made to PostgreSQL afterwards."""

    ARTICLE = BUNDLE.articles[0]["code"]
    MACHINE = next(r["machine_code"] for r in BUNDLE.article_machines if r["article_code"] == BUNDLE.articles[0]["code"])
    CASES = {
        "unit label": ("UPDATE vinto_master.unit SET label='Kilogramo' WHERE code='KG'", (), "unit:KG"),
        "machine name": ("UPDATE vinto_master.machine SET name='MP-1' WHERE code='MP1'", (), "machine:MP1"),
        "article is_material": ("UPDATE vinto_master.article SET is_material = NOT is_material WHERE code=%s", (ARTICLE,), f"article:{ARTICLE}"),
        "article_version description": ("UPDATE vinto_master.article_version SET description='CAMBIADA' WHERE article_id=(SELECT id FROM vinto_master.article WHERE code=%s)",
                                        (ARTICLE,), f"article_version:{ARTICLE}:1"),
        "missing article_machine": ("""DELETE FROM vinto_master.article_machine WHERE article_id=(SELECT id FROM vinto_master.article WHERE code=%s)
                                       AND machine_id=(SELECT id FROM vinto_master.machine WHERE code=%s)""", (ARTICLE, MACHINE),
                                    f"article_machine:{ARTICLE}:{MACHINE}"),
        "shift_schedule": ("UPDATE vinto_config.shift_schedule SET ends_at='18:00' WHERE shift_id=(SELECT id FROM vinto_config.shift WHERE code='DIA')",
                           (), "shift_schedule:BOBINAS:DIA:2026-01-01"),
        "workflow name": ("UPDATE vinto_config.workflow_definition SET name='Otro nombre'", (), "workflow:production-standard"),
        "field_definition": ("UPDATE vinto_config.field_definition SET required=false WHERE key='peso_kg'", (), "field:VINTO-P1-06:1:peso_kg"),
        "missing field_option": ("DELETE FROM vinto_config.field_option WHERE option_key='hoja_simple'", (), "option:VINTO-P1-06:1:tipo_producto"),
    }

    @staticmethod
    def tamper(connection, statement, params):
        # Published/immutable rows are guarded by triggers; a superuser disabling them is exactly how drift happens.
        connection.execute("SET session_replication_role = replica")
        try:
            connection.execute(statement, params)
        finally:
            connection.execute("SET session_replication_role = DEFAULT")

    def test_dry_run_and_apply_detect_every_kind_of_drift_without_repairing_or_creating_batches(self):
        for name, (statement, params, expected_key) in self.CASES.items():
            with self.subTest(name):
                connection = self.open(self.new_database("imported"))
                self.tamper(connection, statement, params)
                before = self.tables_snapshot(connection)

                dry = reference.dry_run(connection, BUNDLE)
                self.assertEqual(dry.state, "conflict")
                self.assertIn(expected_key, [c.key for c in dry.conflicts])

                with self.assertRaises(reference.ReferenceConflictError) as raised:
                    reference.apply(connection, BUNDLE)  # same checksum as the completed batch
                self.assertIn(expected_key, [c.key for c in raised.exception.conflicts])

                self.assertEqual(self.tables_snapshot(connection), before)  # nothing written, nothing repaired
                self.assertEqual(self.count(connection, "vinto_audit.import_batch"), 1)
                self.assertEqual(self.count(connection, "vinto_audit.import_batch", "status='completed'"), 1)
                self.assertEqual(reference.dry_run(connection, BUNDLE).state, "conflict")  # drift is still there

    def test_cli_reports_drift_in_dry_run_and_apply(self):
        name = self.new_database("imported")
        with connect(name) as connection:
            self.tamper(connection, *self.CASES["unit label"][:2])
        with patch.object(import_reference, "open_connection", side_effect=lambda target: connect(name)):
            with contextlib.redirect_stdout(io.StringIO()) as dry_output:
                self.assertEqual(import_reference.main(["--target", "test"]), 1)
            with contextlib.redirect_stdout(io.StringIO()) as apply_output:
                self.assertEqual(import_reference.main(["--target", "test", "--apply"]), 1)
        self.assertIn("CONFLICT / DRIFT", dry_output.getvalue())
        self.assertIn("unit:KG", dry_output.getvalue())
        self.assertIn("no se escribió nada ni se reparó", apply_output.getvalue())

    def test_cli_reports_consistent_state_and_noop(self):
        name = self.new_database("imported")
        with patch.object(import_reference, "open_connection", side_effect=lambda target: connect(name)):
            with contextlib.redirect_stdout(io.StringIO()) as dry_output:
                self.assertEqual(import_reference.main(["--target", "test"]), 0)
            with contextlib.redirect_stdout(io.StringIO()) as apply_output:
                self.assertEqual(import_reference.main(["--target", "test", "--apply"]), 0)
        self.assertIn("CONSISTENT / NO CHANGES", dry_output.getvalue())
        self.assertIn("NO-OP", apply_output.getvalue())


class SourceLockTests(DatabaseCase):
    def test_different_checksums_of_the_same_source_never_mutate_concurrently(self):
        changed_units = tuple(dict(u, label="Kilogramo") if u["code"] == "KG" else u for u in BUNDLE.units)
        bundle_b = dataclasses.replace(BUNDLE, units=changed_units, source_checksum="b" * 64)
        original_run = reference._Run.run
        for _ in range(2):
            name = self.new_database()
            barrier, guard = threading.Barrier(2), threading.Lock()
            intervals, outcomes, errors = [], [], []

            def slow_run(run):
                started = time.monotonic()
                time.sleep(0.4)  # widen the window in which an unprotected second import would overlap
                try:
                    return original_run(run)
                finally:
                    with guard:
                        intervals.append((started, time.monotonic()))

            def worker(bundle):
                try:
                    with connect(name) as connection:
                        barrier.wait(timeout=10)
                        outcomes.append(reference.apply(connection, bundle).mode)
                except reference.ReferenceConflictError:
                    outcomes.append("conflict")
                except Exception as error:  # UniqueViolation or partial states would show up here
                    errors.append(repr(error))

            with patch.object(reference._Run, "run", slow_run):
                threads = [threading.Thread(target=worker, args=(b,)) for b in (BUNDLE, bundle_b)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=120)
            self.assertEqual(errors, [])
            self.assertEqual(sorted(outcomes), ["applied", "conflict"])  # contents differ: the loser sees the winner's masters
            self.assertEqual(len(intervals), 2)
            first, second = sorted(intervals)
            self.assertLessEqual(first[1], second[0], "the two imports evaluated/mutated masters at the same time")
            with connect(name) as connection:
                self.assertEqual(self.count(connection, "vinto_audit.import_batch"), 1)
                self.assertEqual(self.count(connection, "vinto_audit.import_batch", "status='completed'"), 1)
                self.assertEqual(self.count(connection, "vinto_audit.import_record"), 312)
                self.assertEqual(self.count(connection, "vinto_master.article"), 93)
                self.assertEqual(self.count(connection, "vinto_config.form_version", "status='published'"), 1)
                self.assertEqual(self.count(connection, "vinto_config.form_version", "status='draft'"), 0)
                label = connection.execute("SELECT label FROM vinto_master.unit WHERE code='KG'").fetchone()[0]
                self.assertIn(label, ("KG", "Kilogramo"))
            drop_database(name)


if __name__ == "__main__":
    unittest.main()
