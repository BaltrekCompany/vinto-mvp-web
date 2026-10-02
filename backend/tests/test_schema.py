"""Integration checks against migrated PostgreSQL. Every fixture is rolled back."""

import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg

from app.config import settings
from migrate import LOCK_KEY, Migration, MigrationError, apply, read_migrations, validate_history


class MigrationFilesTests(unittest.TestCase):
    def test_checksum_ignores_windows_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "0001_example.sql"
            path.write_bytes(b"SELECT 1;\r\n")
            checksum = read_migrations(Path(directory))[0].checksum
            path.write_bytes(b"SELECT 1;\n")
            self.assertEqual(checksum, read_migrations(Path(directory))[0].checksum)

    def test_applied_checksum_change_is_rejected(self):
        migrations = read_migrations()
        with self.assertRaises(MigrationError):
            validate_history(migrations, [(1, migrations[0].filename, "0" * 64)])

    def test_missing_or_duplicate_versions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "0002_example.sql").write_text("SELECT 1;", encoding="utf-8")
            with self.assertRaises(MigrationError):
                read_migrations(Path(directory))


class SchemaTests(unittest.TestCase):
    def setUp(self):
        if settings.database_url is None:
            self.fail("DATABASE_URL must be configured for integration checks")
        self.connection = psycopg.connect(
            settings.database_url.get_secret_value(), connect_timeout=3,
            options="-c statement_timeout=10000 -c lock_timeout=3000",
        )
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        self.user = uuid4()
        self.connection.execute(
            'INSERT INTO vinto_master."user" (id,display_name) VALUES (%s,%s)',
            (self.user, "TECHNICAL ROLLBACK FIXTURE"),
        )
        self.connection.execute("SELECT set_config('vinto.actor_id',%s,true)", (str(self.user),))
        self.connection.execute("SELECT set_config('vinto.reason','technical rollback verification',true)")
        self.sector = self.insert("vinto_master.sector", "code,name", ("TECH", "Technical fixture"))
        self.machine = self.insert("vinto_master.machine", "sector_id,code,name", (self.sector, "TECH", "Technical fixture"))
        self.device = self.insert("vinto_master.device", "external_key,machine_id", ("TECH", self.machine))
        self.unit = self.insert("vinto_master.unit", "code,label", ("TECH", "Technical fixture"))
        self.shift = self.insert("vinto_config.shift", "code,name", ("TECH", "Technical fixture"))
        self.schedule = self.insert(
            "vinto_config.shift_schedule", "shift_id,sector_id,starts_at,ends_at,timezone,valid_from",
            (self.shift,self.sector,"07:00","19:00","America/Lima","2026-01-01"),
        )
        self.workflow = self.insert("vinto_config.workflow_definition", "code,name", ("TECH", "Technical fixture"))
        self.form = self.insert("vinto_config.form", "legacy_key,code", ("TECH", "TECH"))
        self.form_version, self.group, self.field, self.group_field = self.make_form_version(1)

    def insert(self, table, columns, values):
        # Table/column names are hardcoded fixtures, never user input.
        placeholders = ",".join("%s" for _ in values)
        return self.connection.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING id", values
        ).fetchone()[0]

    def make_form_version(self, version):
        form_version = self.insert(
            "vinto_config.form_version", "form_id,version_number,name,area,workflow_id,definition_checksum",
            (self.form,version,"Technical fixture","production",self.workflow,"1" * 64),
        )
        self.connection.execute(
            "INSERT INTO vinto_config.form_version_machine (form_version_id,machine_id) VALUES (%s,%s)",
            (form_version,self.machine),
        )
        group = self.insert(
            "vinto_config.field_group", "form_version_id,code,label,display_order,repeatable,max_rows",
            (form_version,"rows","Technical fixture",1,True,3),
        )
        field = self.insert(
            "vinto_config.field_definition", "form_version_id,key,label,value_type,source,required,display_order",
            (form_version,"temperature","Technical fixture","decimal","manual",True,1),
        )
        group_field = self.insert(
            "vinto_config.field_definition", "form_version_id,field_group_id,key,label,value_type,source,required,display_order",
            (form_version,group,"weight","Technical fixture","decimal","manual",True,1),
        )
        self.connection.execute(
            "UPDATE vinto_config.form_version SET status='published',published_at=clock_timestamp() WHERE id=%s",
            (form_version,),
        )
        return form_version,group,field,group_field

    def capture(self, **overrides):
        values = dict(form_version_id=self.form_version,machine_id=self.machine,
                      shift_schedule_id=self.schedule,device_id=self.device,operating_date="2026-09-30",
                      captured_at="2026-09-30T12:00:00Z")
        values.update(overrides)
        return self.insert("vinto_txn.capture", ",".join(values), tuple(values.values()))

    def detail(self, capture, **overrides):
        values = dict(capture_id=capture,form_version_id=self.form_version,
                      field_definition_id=self.field,value_type="decimal",value_decimal=0)
        values.update(overrides)
        return self.insert("vinto_txn.capture_detail", ",".join(values), tuple(values.values()))

    def reject(self, operation):
        with self.assertRaises(psycopg.Error):
            with self.connection.transaction():
                operation()
                self.connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_all_tables_have_primary_keys_and_valid_constraints(self):
        expected = set(re.findall(r'CREATE TABLE (vinto_\w+)\."(\w+)"', read_migrations()[0].sql))
        actual = set(self.connection.execute("""
            SELECT table_schema,table_name FROM information_schema.tables
            WHERE table_schema IN ('vinto_master','vinto_config','vinto_txn','vinto_audit')
              AND table_type='BASE TABLE'
        """).fetchall())
        self.assertEqual(expected,actual)
        self.assertEqual(len(actual),39)
        missing = self.connection.execute("""
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('vinto_master','vinto_config','vinto_txn','vinto_audit') AND c.relkind='r'
              AND NOT EXISTS (SELECT 1 FROM pg_constraint p WHERE p.conrelid=c.oid AND p.contype='p')
        """).fetchall()
        self.assertEqual(missing,[])
        invalid = self.connection.execute("""
            SELECT conname FROM pg_constraint p JOIN pg_namespace n ON n.oid=p.connamespace
            WHERE n.nspname IN ('vinto_master','vinto_config','vinto_txn','vinto_audit') AND NOT convalidated
        """).fetchall()
        self.assertEqual(invalid,[])

    def test_foreign_keys_reject_unknown_machine(self):
        self.reject(lambda: self.insert("vinto_master.device","external_key,machine_id",("BAD",uuid4())))

    def test_machine_must_be_allowed_for_form(self):
        other_machine = self.insert("vinto_master.machine","sector_id,code,name",(self.sector,"OTHER","Technical fixture"))
        self.reject(lambda: self.capture(machine_id=other_machine))

    def test_field_cannot_come_from_another_form_version(self):
        other_version, _, other_field, _ = self.make_form_version(2)
        capture = self.capture()
        self.reject(lambda: self.detail(capture,field_definition_id=other_field))

    def test_detail_is_unique_and_type_checked(self):
        capture = self.capture()
        self.detail(capture)
        self.reject(lambda: self.detail(capture))
        self.reject(lambda: self.detail(capture,value_type="text",value_text="bad",value_decimal=None))

    def test_group_must_match_field_and_capture(self):
        capture = self.capture()
        other_capture = self.capture()
        row = self.insert("vinto_txn.capture_group_row","capture_id,form_version_id,field_group_id,row_number",(other_capture,self.form_version,self.group,1))
        self.reject(lambda: self.detail(capture,field_definition_id=self.group_field,field_group_id=self.group,group_row_id=row))
        self.reject(lambda: self.detail(capture,field_definition_id=self.group_field))

    def test_incomplete_draft_allowed_submission_rejected(self):
        capture = self.capture()
        self.connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.reject(lambda: self.connection.execute(
            "UPDATE vinto_txn.capture SET status='submitted',submitted_at=clock_timestamp() WHERE id=%s",(capture,)))

    def test_submission_audit_and_revision(self):
        capture = self.capture()
        self.detail(capture)
        self.connection.execute("UPDATE vinto_txn.capture SET status='submitted',submitted_at=clock_timestamp() WHERE id=%s",(capture,))
        self.connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        row = self.connection.execute("SELECT revision,created_by,updated_by FROM vinto_txn.capture WHERE id=%s",(capture,)).fetchone()
        self.assertEqual(row,(2,self.user,self.user))
        event = self.connection.execute("SELECT actor_id,old_data->>'status',new_data->>'status' FROM vinto_audit.audit_event WHERE entity_table='capture' AND action='UPDATE' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(event,(self.user,"draft","submitted"))
        self.reject(lambda: self.connection.execute("UPDATE vinto_txn.capture_detail SET value_decimal=1 WHERE capture_id=%s",(capture,)))

    def test_published_form_and_article_versions_are_immutable(self):
        self.reject(lambda: self.connection.execute("UPDATE vinto_config.field_definition SET label='changed' WHERE id=%s",(self.field,)))
        self.reject(lambda: self.connection.execute("UPDATE vinto_config.form_version SET name='changed' WHERE id=%s",(self.form_version,)))
        article = self.insert("vinto_master.article","code,is_product",("TECH",True))
        version = self.insert("vinto_master.article_version","article_id,version_number,description,unit_id",(article,1,"Technical fixture",self.unit))
        self.reject(lambda: self.connection.execute("UPDATE vinto_master.article_version SET description='changed' WHERE id=%s",(version,)))

    def test_audit_events_cannot_be_changed_or_deleted(self):
        self.reject(lambda: self.connection.execute("UPDATE vinto_audit.audit_event SET reason='changed'"))
        self.reject(lambda: self.connection.execute("DELETE FROM vinto_audit.audit_event"))

    def test_one_active_assignment_per_machine(self):
        article = self.insert("vinto_master.article","code,is_product",("TECH",True))
        version = self.insert("vinto_master.article_version","article_id,version_number,description,unit_id",(article,1,"Technical fixture",self.unit))
        order = self.insert("vinto_txn.work_order","number,machine_id",("TECH",self.machine))
        revision = self.insert("vinto_txn.work_order_version","work_order_id,version_number,kind",(order,1,"baseline"))
        line = self.insert("vinto_txn.work_order_line","work_order_version_id,line_code,pv_reference,article_version_id,unit_id,quantity,due_date",(revision,"L1","TECH",version,self.unit,1,"2026-09-30"))
        columns = "work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by"
        values = (line,self.machine,self.schedule,"2026-09-30",self.user)
        self.insert("vinto_txn.assignment",columns,values)
        self.reject(lambda: self.insert("vinto_txn.assignment",columns,values))

    def test_transaction_failure_rolls_back_rows_and_audit(self):
        before = self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0]
        with self.assertRaises(RuntimeError):
            with self.connection.transaction():
                self.insert("vinto_master.profile","code,name",("ROLLBACK","Technical fixture"))
                raise RuntimeError("technical rollback")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_master.profile WHERE code='ROLLBACK'").fetchone()[0],0)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0],before)


class MigrationDatabaseTests(unittest.TestCase):
    def connect(self):
        connection = psycopg.connect(
            settings.database_url.get_secret_value(),connect_timeout=3,autocommit=True,
            options="-c statement_timeout=10000 -c lock_timeout=3000",
        )
        self.addCleanup(connection.close)
        return connection

    def test_repeat_apply_does_not_change_history(self):
        connection = self.connect()
        before = connection.execute("SELECT * FROM vinto_meta.schema_migration ORDER BY version").fetchall()
        apply(connection,read_migrations())
        self.assertEqual(connection.execute("SELECT * FROM vinto_meta.schema_migration ORDER BY version").fetchall(),before)

    def test_failed_migration_rolls_back_ddl_and_history(self):
        connection = self.connect()
        current = read_migrations()
        source = "CREATE TABLE vinto_meta.technical_rollback_probe (id integer PRIMARY KEY); SELECT 1/0;"
        probe = Migration(len(current)+1,"0002_technical_rollback_probe.sql",hashlib.sha256(source.encode()).hexdigest(),source)
        with self.assertRaises(psycopg.errors.DivisionByZero):
            apply(connection,[*current,probe])
        self.assertIsNone(connection.execute("SELECT to_regclass('vinto_meta.technical_rollback_probe')").fetchone()[0])
        self.assertEqual(connection.execute("SELECT count(*) FROM vinto_meta.schema_migration").fetchone()[0],len(current))

    def test_concurrent_runner_is_rejected(self):
        owner = self.connect()
        contender = self.connect()
        owner.execute("SELECT pg_advisory_lock(%s)",(LOCK_KEY,))
        try:
            with self.assertRaises(MigrationError):
                apply(contender,read_migrations())
        finally:
            owner.execute("SELECT pg_advisory_unlock(%s)",(LOCK_KEY,))


if __name__ == "__main__":
    unittest.main()
