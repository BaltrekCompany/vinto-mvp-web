"""Migration 0003: vinto_txn.capture.revision semantics.

INSERT -> 1 (client value ignored); any UPDATE of a draft keeps the revision; any other UPDATE (a correction,
including reopening a submitted capture) adds exactly one. Part 1 reuses the rolled-back schema fixtures of the shared test database; part 2 uses
ephemeral *_test databases to exercise real COMMITs and the migration itself. Nothing touches vinto.
"""

import contextlib
import io
import unittest
from uuid import uuid4

import psycopg

from app.db_guard import connect_test_database
from app.ephemeral_db import connect, create_database, drop_database
from migrate import apply as apply_migrations
from migrate import applied_migrations, read_migrations, validate_history
try:  # reuse the rolled-back fixtures (user, machine, published form, schedule, device); works in discover and dotted mode
    from test_schema import SchemaTests
except ModuleNotFoundError:
    from tests.test_schema import SchemaTests

SUBMIT = "UPDATE vinto_txn.capture SET status='submitted',submitted_at=clock_timestamp() WHERE id=%s"
CORRECT = "UPDATE vinto_txn.capture SET correction_reason='typo in a value' WHERE id=%s"


class RevisionTests(unittest.TestCase):
    """Rolled-back fixtures on the shared test database."""

    def setUp(self):
        self.fixture = SchemaTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.connection = self.fixture.connection

    def capture(self, **overrides):
        return self.fixture.capture(**overrides)

    def revision(self, capture):
        return self.connection.execute("SELECT revision FROM vinto_txn.capture WHERE id=%s", (capture,)).fetchone()[0]

    def submitted(self):
        capture = self.capture()
        self.fixture.detail(capture)
        self.connection.execute(SUBMIT, (capture,))
        return capture

    def rejects(self, statement, params=(), message=None):
        self.connection.execute("SAVEPOINT expected")
        with self.assertRaises(psycopg.errors.CheckViolation) as raised:
            self.connection.execute(statement, params)
            self.connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.connection.execute("ROLLBACK TO SAVEPOINT expected")
        if message:
            self.assertIn(message, str(raised.exception))

    def test_insert_starts_at_revision_one(self):
        self.assertEqual(self.revision(self.capture()), 1)

    def test_a_client_supplied_revision_is_ignored_on_insert(self):
        for supplied in (99, 0, -5, 2):
            with self.subTest(supplied=supplied):
                self.assertEqual(self.revision(self.capture(revision=supplied)), 1)

    def test_draft_to_submitted_keeps_revision_one(self):
        capture = self.submitted()
        self.assertEqual(self.revision(capture), 1)

    def test_a_client_supplied_revision_is_ignored_on_submission(self):
        capture = self.capture()
        self.fixture.detail(capture)
        self.connection.execute("UPDATE vinto_txn.capture SET status='submitted',submitted_at=clock_timestamp(),revision=77 WHERE id=%s", (capture,))
        self.assertEqual(self.revision(capture), 1)

    def test_first_correction_is_revision_two_and_the_second_is_three(self):
        capture = self.submitted()
        self.connection.execute(CORRECT, (capture,))
        self.assertEqual(self.revision(capture), 2)
        self.connection.execute("UPDATE vinto_txn.capture SET correction_reason='second fix' WHERE id=%s", (capture,))
        self.assertEqual(self.revision(capture), 3)
        self.connection.execute("UPDATE vinto_txn.capture SET correction_reason='third fix',revision=1 WHERE id=%s", (capture,))
        self.assertEqual(self.revision(capture), 4)  # an attempt to write the revision back is ignored

    def test_a_correction_without_correction_reason_is_rejected(self):
        capture = self.submitted()
        self.rejects("UPDATE vinto_txn.capture SET captured_at=captured_at + interval '1 minute' WHERE id=%s", (capture,), "audited reason")
        self.assertEqual(self.revision(capture), 1)

    def test_a_correction_without_vinto_reason_is_rejected(self):
        capture = self.submitted()
        self.connection.execute("SELECT set_config('vinto.reason','',true)")
        self.rejects(CORRECT, (capture,), "audited reason")
        self.connection.execute("SELECT set_config('vinto.reason','technical rollback verification',true)")
        self.assertEqual(self.revision(capture), 1)

    def reopen(self, capture, reason="reopen to fix"):
        self.connection.execute("UPDATE vinto_txn.capture SET status='draft',submitted_at=NULL,correction_reason=%s WHERE id=%s", (reason, capture))

    def edit_draft(self, capture):
        self.connection.execute("UPDATE vinto_txn.capture SET captured_at=captured_at + interval '1 minute' WHERE id=%s", (capture,))

    def test_draft_to_draft_keeps_the_revision_even_after_many_edits(self):
        capture = self.capture()
        self.assertEqual(self.revision(capture), 1)
        for _ in range(4):
            self.edit_draft(capture)
            self.assertEqual(self.revision(capture), 1)
        self.connection.execute("UPDATE vinto_txn.capture SET captured_at=captured_at,revision=50 WHERE id=%s", (capture,))
        self.assertEqual(self.revision(capture), 1)  # a client-supplied revision is ignored on a draft too

    def test_draft_to_blocked_keeps_the_revision(self):
        capture = self.capture()
        self.connection.execute("UPDATE vinto_txn.capture SET status='blocked' WHERE id=%s", (capture,))
        self.assertEqual(self.revision(capture), 1)

    def test_reopening_counts_one_correction_and_the_following_draft_edits_and_resubmission_keep_it(self):
        capture = self.submitted()
        self.assertEqual(self.revision(capture), 1)
        self.reopen(capture)
        self.assertEqual(self.revision(capture), 2)
        for _ in range(3):
            self.edit_draft(capture)
            self.assertEqual(self.revision(capture), 2)
        self.connection.execute(SUBMIT, (capture,))
        self.assertEqual(self.revision(capture), 2)

    def test_a_second_correction_after_reopening_is_revision_three(self):
        capture = self.submitted()
        self.reopen(capture)
        self.connection.execute(SUBMIT, (capture,))
        self.assertEqual(self.revision(capture), 2)
        self.connection.execute("UPDATE vinto_txn.capture SET correction_reason='second fix' WHERE id=%s", (capture,))
        self.assertEqual(self.revision(capture), 3)
        self.reopen(capture, "reopen again")
        self.assertEqual(self.revision(capture), 4)
        self.edit_draft(capture)
        self.connection.execute(SUBMIT, (capture,))
        self.assertEqual(self.revision(capture), 4)

    def test_reopening_still_requires_the_audited_reasons(self):
        capture = self.submitted()
        self.rejects("UPDATE vinto_txn.capture SET status='draft',submitted_at=NULL WHERE id=%s", (capture,), "audited reason")
        self.connection.execute("SELECT set_config('vinto.reason','',true)")
        self.rejects("UPDATE vinto_txn.capture SET status='draft',submitted_at=NULL,correction_reason='x' WHERE id=%s", (capture,), "audited reason")
        self.connection.execute("SELECT set_config('vinto.reason','technical rollback verification',true)")
        self.assertEqual(self.revision(capture), 1)

    def test_the_machine_cannot_change(self):
        capture = self.capture()
        other = self.fixture.insert("vinto_master.machine", "sector_id,code,name", (self.fixture.sector, "TECH2", "Second machine"))
        self.rejects("UPDATE vinto_txn.capture SET machine_id=%s WHERE id=%s", (other, capture), "context is immutable")

    def test_the_assignment_cannot_change(self):
        capture = self.capture()
        self.rejects("UPDATE vinto_txn.capture SET assignment_id=%s WHERE id=%s", (uuid4(), capture), "context is immutable")

    def test_the_rest_of_the_context_is_still_immutable(self):
        capture = self.capture()
        for column, value in (("operating_date", "2026-09-29"), ("device_id", self.fixture.insert("vinto_master.device", "external_key,machine_id", ("TECH2", self.fixture.machine))),
                              ("shift_schedule_id", self.fixture.insert("vinto_config.shift_schedule", "shift_id,sector_id,starts_at,ends_at,timezone,valid_from",
                                                                        (self.fixture.shift, self.fixture.sector, "19:00", "23:00", "America/Lima", "2026-02-01")))):
            with self.subTest(column=column):
                self.rejects(f"UPDATE vinto_txn.capture SET {column}=%s WHERE id=%s", (value, capture), "context is immutable")

    def test_a_closed_capture_stays_immutable(self):
        capture = self.submitted()
        self.connection.execute("UPDATE vinto_txn.capture SET status='closed',closed_at=clock_timestamp(),correction_reason='close' WHERE id=%s", (capture,))
        self.rejects("UPDATE vinto_txn.capture SET correction_reason='after close' WHERE id=%s", (capture,), "Closed capture is immutable")

    def test_required_fields_are_still_validated_when_the_transaction_ends(self):
        capture = self.capture()  # no required capture_detail
        self.connection.execute(SUBMIT, (capture,))
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.connection.rollback()

    def test_details_cannot_be_edited_once_submitted(self):
        capture = self.capture()
        detail = self.fixture.detail(capture)
        self.connection.execute(SUBMIT, (capture,))
        self.rejects("UPDATE vinto_txn.capture_detail SET value_decimal=5 WHERE id=%s", (detail,), "draft state")
        self.rejects("DELETE FROM vinto_txn.capture_detail WHERE id=%s", (detail,), "draft state")

    def test_the_other_protections_of_validate_capture_are_unchanged(self):
        unpublished = self.fixture.insert("vinto_config.form_version", "form_id,version_number,name,area,workflow_id,definition_checksum",
                                          (self.fixture.form, 5, "Draft form", "production", self.fixture.workflow, "5" * 64))
        self.connection.execute("INSERT INTO vinto_config.form_version_machine (form_version_id,machine_id) VALUES (%s,%s)", (unpublished, self.fixture.machine))
        self.rejects("INSERT INTO vinto_txn.capture (form_version_id,machine_id,shift_schedule_id,device_id,operating_date,captured_at) VALUES (%s,%s,%s,%s,'2026-09-30',clock_timestamp())",
                     (unpublished, self.fixture.machine, self.fixture.schedule, self.fixture.device), "published form")
        self.rejects("INSERT INTO vinto_txn.capture (form_version_id,machine_id,shift_schedule_id,device_id,operating_date,captured_at) VALUES (%s,%s,%s,%s,'2025-01-01',clock_timestamp())",
                     (self.fixture.form_version, self.fixture.machine, self.fixture.schedule, self.fixture.device), "shift mismatch")


class CommittedFlowTests(unittest.TestCase):
    """Real COMMITs in ephemeral databases."""

    def setUp(self):
        self.database = f"vinto_rev_{uuid4().hex[:12]}_test"
        create_database(self.database)
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)

    def migrate(self, upto=None):
        migrations = read_migrations()
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(self.connection, migrations[:upto] if upto else migrations)

    def fixtures(self):
        c = self.connection
        one = lambda sql, params=(): c.execute(sql, params).fetchone()[0]
        self.user = one('INSERT INTO vinto_master."user" (display_name) VALUES (%s) RETURNING id', ("REVISION FIXTURE",))
        sector = one("INSERT INTO vinto_master.sector (code,name) VALUES ('TECH','Technical') RETURNING id")
        self.machine = one("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'TECH','Technical') RETURNING id", (sector,))
        self.device = one("INSERT INTO vinto_master.device (external_key,machine_id) VALUES ('TECH',%s) RETURNING id", (self.machine,))
        shift = one("INSERT INTO vinto_config.shift (code,name) VALUES ('TECH','Technical') RETURNING id")
        self.schedule = one("""INSERT INTO vinto_config.shift_schedule (shift_id,sector_id,starts_at,ends_at,timezone,valid_from)
                               VALUES (%s,%s,'07:00','19:00','America/La_Paz','2026-01-01') RETURNING id""", (shift, sector))
        workflow = one("INSERT INTO vinto_config.workflow_definition (code,name) VALUES ('TECH','Technical') RETURNING id")
        form = one("INSERT INTO vinto_config.form (legacy_key,code) VALUES ('TECH','TECH') RETURNING id")
        self.form_version = one("INSERT INTO vinto_config.form_version (form_id,version_number,name,area,workflow_id,definition_checksum) VALUES (%s,1,'T','production',%s,%s) RETURNING id",
                                (form, workflow, "1" * 64))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id,machine_id) VALUES (%s,%s)", (self.form_version, self.machine))
        self.field = one("""INSERT INTO vinto_config.field_definition (form_version_id,key,label,value_type,source,required,display_order)
                            VALUES (%s,'temperature','T','decimal','manual',true,1) RETURNING id""", (self.form_version,))
        c.execute("UPDATE vinto_config.form_version SET status='published',published_at=clock_timestamp() WHERE id=%s", (self.form_version,))

    def submit_in_one_transaction(self, with_required_detail=True):
        c = self.connection
        with c.transaction():
            c.execute("SELECT set_config('vinto.actor_id',%s,true)", (str(self.user),))
            c.execute("SELECT set_config('vinto.reason','revision test',true)")
            capture = c.execute("""INSERT INTO vinto_txn.capture (form_version_id,machine_id,shift_schedule_id,device_id,operating_date,captured_at)
                                   VALUES (%s,%s,%s,%s,'2026-10-06',clock_timestamp()) RETURNING id""",
                                (self.form_version, self.machine, self.schedule, self.device)).fetchone()[0]
            if with_required_detail:
                c.execute("""INSERT INTO vinto_txn.capture_detail (capture_id,form_version_id,field_definition_id,value_type,value_decimal)
                             VALUES (%s,%s,%s,'decimal',21.5)""", (capture, self.form_version, self.field))
            c.execute("UPDATE vinto_txn.capture SET status='submitted',submitted_at=clock_timestamp() WHERE id=%s", (capture,))
        return capture

    def revision(self, capture):
        return self.connection.execute("SELECT revision,status FROM vinto_txn.capture WHERE id=%s", (capture,)).fetchone()

    def test_the_real_flow_draft_details_submitted_commit_ends_in_revision_one(self):
        self.migrate()
        self.fixtures()
        capture = self.submit_in_one_transaction()
        self.assertEqual(self.revision(capture), (1, "submitted"))
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id=%s", (capture,)).fetchone()[0], 1)

    def test_commit_still_rejects_a_submission_without_required_values(self):
        self.migrate()
        self.fixtures()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.submit_in_one_transaction(with_required_detail=False)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_txn.capture").fetchone()[0], 0)  # nothing committed

    def test_a_committed_correction_after_the_submission_is_revision_two(self):
        self.migrate()
        self.fixtures()
        capture = self.submit_in_one_transaction()
        with self.connection.transaction():
            self.connection.execute("SELECT set_config('vinto.actor_id',%s,true)", (str(self.user),))
            self.connection.execute("SELECT set_config('vinto.reason','correction after review',true)")
            self.connection.execute("UPDATE vinto_txn.capture SET correction_reason='wrong temperature' WHERE id=%s", (capture,))
        self.assertEqual(self.revision(capture), (2, "submitted"))

    def test_0003_applies_over_a_database_that_already_has_0001_and_0002_and_leaves_history_alone(self):
        self.migrate(upto=2)
        self.assertEqual(len(applied_migrations(self.connection)), 2)
        self.fixtures()
        legacy = self.submit_in_one_transaction()
        self.assertEqual(self.revision(legacy), (2, "submitted"))  # 0001 semantics: the old behaviour
        before = self.connection.execute("SELECT prosrc FROM pg_proc WHERE proname='validate_capture'").fetchone()[0]
        self.assertNotIn("NEW.revision := OLD.revision;", before)
        self.migrate()
        self.assertEqual([row[0] for row in applied_migrations(self.connection)], [1, 2, 3, 4, 5])
        after = self.connection.execute("SELECT prosrc FROM pg_proc WHERE proname='validate_capture'").fetchone()[0]
        self.assertIn("NEW.revision := OLD.revision;", after)
        self.assertEqual(self.revision(legacy), (2, "submitted"))  # existing captures are not rewritten
        new = self.submit_in_one_transaction()
        self.assertEqual(self.revision(new), (1, "submitted"))
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname='validate_capture' AND tgrelid='vinto_txn.capture'::regclass").fetchone()[0], 1)  # the trigger was not recreated

    def test_0004_preserves_historical_bobbins_and_replaces_the_global_code_unique(self):
        self.migrate(upto=3)
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code, weight_kg) VALUES ('OLD-1', 12.5)")
        self.migrate()
        row = self.connection.execute(
            "SELECT code, weight_kg, machine_id, management_start_year, sequence_number, start_time, diameter_mm, grammage_g_m2, number_of_cuts FROM vinto_txn.bobbin").fetchall()
        self.assertEqual(row, [("OLD-1", 12.5, None, None, None, None, None, None, None)])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM pg_constraint WHERE conname='bobbin_code_key'").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='bobbin' AND action IN ('UPDATE','DELETE')").fetchone()[0], 0)

    def test_0001_and_0002_are_untouched(self):
        migrations = read_migrations()
        self.assertEqual([m.filename for m in migrations][:3], ["0001_initial_schema.sql", "0002_auth.sql", "0003_capture_revision_semantics.sql"])
        self.assertEqual(migrations[0].checksum, "500b68a0fe3af40d06fda81c12e8945c57b99c669ec84348fa5808e1684d3c0f")


class TestDatabaseHistoryTests(unittest.TestCase):
    def test_migrate_check_shows_0001_0002_0003_applied_in_the_test_database(self):
        connection = connect_test_database(connect_timeout=3, autocommit=True)
        self.addCleanup(connection.close)
        applied = applied_migrations(connection)
        validate_history(read_migrations(), applied)
        self.assertEqual([row[1] for row in applied][:3], ["0001_initial_schema.sql", "0002_auth.sql", "0003_capture_revision_semantics.sql"])
        self.assertEqual(len(applied), len(read_migrations()))


if __name__ == "__main__":
    unittest.main()
