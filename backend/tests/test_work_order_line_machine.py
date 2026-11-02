"""MF13-03.B PR1: machine per work order line (migration 0010). TEST_DATABASE_URL only; every fixture is rolled back.

Two groups:
  * LineMachineSchemaTests: behaviour of the migrated schema (compatibility with the deployed backend, coherence).
  * LineMachineMigrationRehearsalTests: inside ONE transaction, go back to the 0009 shape with the rollback script,
    load representative legacy data, run the real 0010 file, compare, then roll everything back.
"""

import unittest
from pathlib import Path
from uuid import uuid4

import psycopg

from app.db_guard import connect_test_database

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "0010_work_order_line_machine.sql"
ROLLBACK = BACKEND / "rollbacks" / "0010_work_order_line_machine_rollback.sql"
LINE_COLUMNS = "work_order_version_id,line_code,pv_reference,article_version_id,unit_id,quantity,due_date"
ASSIGNMENT_COLUMNS = "work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by"


class Fixture:
    """Two sectors, two machines (M1 sector A, M2 sector B), articles A (only M1) and B (only M2)."""

    def __init__(self, connection):
        self.connection = connection
        self.user = uuid4()
        connection.execute('INSERT INTO vinto_master."user" (id,display_name) VALUES (%s,%s)', (self.user, "MF13-03B FIXTURE"))
        connection.execute("SELECT set_config('vinto.actor_id',%s,true)", (str(self.user),))
        connection.execute("SELECT set_config('vinto.reason','mf13-03b fixture',true)")
        self.sector_a = self.insert("vinto_master.sector", "code,name", ("MFA", "Fixture A"))
        self.sector_b = self.insert("vinto_master.sector", "code,name", ("MFB", "Fixture B"))
        self.m1 = self.insert("vinto_master.machine", "sector_id,code,name", (self.sector_a, "MF-M1", "Fixture M1"))
        self.m2 = self.insert("vinto_master.machine", "sector_id,code,name", (self.sector_b, "MF-M2", "Fixture M2"))
        self.unit = self.insert("vinto_master.unit", "code,label", ("MFU", "Fixture unit"))
        self.article_a = self.article("MF-A", self.m1)
        self.article_b = self.article("MF-B", self.m2)
        self.article_free = self.article("MF-FREE", None)
        shift = self.insert("vinto_config.shift", "code,name", ("MFS", "Fixture shift"))
        self.schedules = {}
        for key, sector in (("a", self.sector_a), ("b", self.sector_b)):
            self.schedules[key] = self.insert(
                "vinto_config.shift_schedule", "shift_id,sector_id,starts_at,ends_at,timezone,valid_from",
                (shift, sector, "07:00", "19:00", "America/Lima", "2026-01-01"))

    def insert(self, table, columns, values):
        placeholders = ",".join("%s" for _ in values)
        return self.connection.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) RETURNING id", values).fetchone()[0]

    def article(self, code, machine):
        article = self.insert("vinto_master.article", "code,is_product", (code, True))
        version = self.insert("vinto_master.article_version", "article_id,version_number,description,unit_id",
                              (article, 1, f"Fixture {code}", self.unit))
        if machine is not None:
            self.connection.execute("INSERT INTO vinto_master.article_machine (article_id,machine_id) VALUES (%s,%s)",
                                    (article, machine))
        return version

    def order(self, number, machine, kind="baseline", version_number=1):
        order = self.insert("vinto_txn.work_order", "number,machine_id", (number, machine))
        return order, self.version(order, kind, version_number)

    def version(self, order, kind, version_number):
        return self.insert("vinto_txn.work_order_version", "work_order_id,version_number,kind", (order, version_number, kind))

    def line(self, version, code, article, machine=None):
        columns, values = LINE_COLUMNS, (version, code, "PV", article, self.unit, 1, "2026-09-30")
        if machine is not None:
            columns, values = columns + ",machine_id", values + (machine,)
        return self.insert("vinto_txn.work_order_line", columns, values)

    def legacy_line(self, version, code, article):
        return self.line(version, code, article)

    def publish(self, version):
        self.connection.execute("UPDATE vinto_txn.work_order_version SET published_at=clock_timestamp() WHERE id=%s", (version,))

    def assignment(self, line, machine, schedule):
        return self.insert("vinto_txn.assignment", ASSIGNMENT_COLUMNS, (line, machine, schedule, "2026-09-30", self.user))


class ConnectionMixin:
    def open(self):
        connection = connect_test_database(connect_timeout=3, options="-c statement_timeout=20000 -c lock_timeout=5000")
        self.addCleanup(connection.close)
        self.addCleanup(connection.rollback)
        return connection

    def rejected(self, operation, sqlstate="23514"):
        with self.assertRaises(psycopg.Error) as caught:
            with self.connection.transaction():
                operation()
        self.assertEqual(caught.exception.sqlstate, sqlstate)


class LineMachineSchemaTests(ConnectionMixin, unittest.TestCase):
    def setUp(self):
        self.connection = self.open()
        self.f = Fixture(self.connection)

    def test_column_is_not_null_with_foreign_key_and_index(self):
        row = self.connection.execute(
            """SELECT is_nullable FROM information_schema.columns
               WHERE table_schema='vinto_txn' AND table_name='work_order_line' AND column_name='machine_id'""").fetchone()
        self.assertEqual(row, ("NO",))
        constraint = self.connection.execute(
            """SELECT confrelid::regclass::text, confdeltype FROM pg_constraint
               WHERE conname='work_order_line_machine_fk' AND conrelid='vinto_txn.work_order_line'::regclass""").fetchone()
        self.assertEqual(constraint, ("vinto_master.machine", "r"))
        self.assertIsNotNone(self.connection.execute("SELECT to_regclass('vinto_txn.work_order_line_machine_fk_idx')").fetchone()[0])

    def test_legacy_header_machine_is_kept_not_null(self):
        nullable = self.connection.execute(
            """SELECT is_nullable FROM information_schema.columns
               WHERE table_schema='vinto_txn' AND table_name='work_order' AND column_name='machine_id'""").fetchone()[0]
        self.assertEqual(nullable, "NO")

    def test_insert_without_machine_defaults_to_header_machine_like_the_deployed_backend(self):
        _, version = self.f.order("MF-OT-1", self.f.m1)
        line = self.f.legacy_line(version, "L1", self.f.article_a)
        self.assertEqual(self.connection.execute("SELECT machine_id FROM vinto_txn.work_order_line WHERE id=%s", (line,)).fetchone()[0], self.f.m1)

    def test_multi_machine_baseline_lines_are_allowed_when_the_article_is_enabled_for_each_machine(self):
        _, version = self.f.order("MF-OT-2", self.f.m1)
        self.f.line(version, "L1", self.f.article_a, self.f.m1)
        line = self.f.line(version, "L2", self.f.article_b, self.f.m2)
        self.assertEqual(self.connection.execute("SELECT machine_id FROM vinto_txn.work_order_line WHERE id=%s", (line,)).fetchone()[0], self.f.m2)

    def test_article_not_enabled_for_the_line_machine_is_rejected(self):
        _, version = self.f.order("MF-OT-3", self.f.m1)
        self.rejected(lambda: self.f.line(version, "L1", self.f.article_b, self.f.m1))
        self.rejected(lambda: self.f.line(version, "L2", self.f.article_free, self.f.m1))
        self.rejected(lambda: self.f.legacy_line(version, "L3", self.f.article_b))  # defaulted machine is checked too

    def test_unknown_machine_is_rejected(self):
        # article_machine has its own FK to machine, so an unknown machine can never satisfy the article check.
        _, version = self.f.order("MF-OT-4", self.f.m1)
        self.rejected(lambda: self.f.line(version, "L1", self.f.article_a, uuid4()))

    def test_operational_copy_without_machine_inherits_each_baseline_machine(self):
        """The deployed _ensure_operational copies lines with INSERT..SELECT that omits machine_id."""
        order, baseline = self.f.order("MF-OT-5", self.f.m1)
        self.f.line(baseline, "L1", self.f.article_a, self.f.m1)
        self.f.line(baseline, "L2", self.f.article_b, self.f.m2)
        self.f.publish(baseline)
        operational = self.f.version(order, "operational", 2)
        self.connection.execute(
            f"""INSERT INTO vinto_txn.work_order_line ({LINE_COLUMNS})
                SELECT %s, line_code, pv_reference, article_version_id, unit_id, quantity, due_date
                FROM vinto_txn.work_order_line WHERE work_order_version_id = %s""", (operational, baseline))
        rows = self.connection.execute(
            "SELECT line_code, machine_id FROM vinto_txn.work_order_line WHERE work_order_version_id=%s ORDER BY line_code",
            (operational,)).fetchall()
        self.assertEqual(rows, [("L1", self.f.m1), ("L2", self.f.m2)])

    def test_operational_line_must_match_its_baseline_machine(self):
        order, baseline = self.f.order("MF-OT-6", self.f.m1)
        self.f.line(baseline, "L1", self.f.article_a, self.f.m1)
        self.f.publish(baseline)
        operational = self.f.version(order, "operational", 2)
        self.rejected(lambda: self.f.line(operational, "L1", self.f.article_a, self.f.m2))

    def test_operational_copy_is_not_blocked_by_a_later_article_machine_change(self):
        order, baseline = self.f.order("MF-OT-7", self.f.m1)
        self.f.line(baseline, "L1", self.f.article_a, self.f.m1)
        self.f.publish(baseline)
        self.connection.execute("DELETE FROM vinto_master.article_machine WHERE machine_id=%s", (self.f.m1,))
        operational = self.f.version(order, "operational", 2)
        self.f.line(operational, "L1", self.f.article_a)  # must not raise

    def test_published_lines_remain_immutable_and_the_guard_is_enabled(self):
        _, version = self.f.order("MF-OT-8", self.f.m1)
        line = self.f.line(version, "L1", self.f.article_a, self.f.m1)
        self.f.publish(version)
        self.rejected(lambda: self.connection.execute(
            "UPDATE vinto_txn.work_order_line SET machine_id=%s WHERE id=%s", (self.f.m2, line)))
        self.rejected(lambda: self.f.line(version, "L2", self.f.article_a, self.f.m1))
        enabled = self.connection.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgrelid='vinto_txn.work_order_line'::regclass AND tgname='guard_order_line'").fetchone()[0]
        self.assertEqual(enabled, "O")

    def test_assignment_uses_the_machine_of_the_line_not_the_header(self):
        _, version = self.f.order("MF-OT-9", self.f.m1)
        l1 = self.f.line(version, "L1", self.f.article_a, self.f.m1)
        l2 = self.f.line(version, "L2", self.f.article_b, self.f.m2)
        self.rejected(lambda: self.f.assignment(l2, self.f.m1, self.f.schedules["a"]))  # header machine, wrong for the line
        self.rejected(lambda: self.f.assignment(l1, self.f.m2, self.f.schedules["b"]))
        self.f.assignment(l1, self.f.m1, self.f.schedules["a"])
        self.f.assignment(l2, self.f.m2, self.f.schedules["b"])

    def test_one_active_assignment_per_machine_is_untouched(self):
        _, version = self.f.order("MF-OT-10", self.f.m1)
        l1 = self.f.line(version, "L1", self.f.article_a, self.f.m1)
        l2 = self.f.line(version, "L2", self.f.article_a, self.f.m1)
        self.assertIsNotNone(self.connection.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname='vinto_txn' AND indexname='assignment_one_active_machine'").fetchone())
        self.f.assignment(l1, self.f.m1, self.f.schedules["a"])
        self.rejected(lambda: self.f.assignment(l2, self.f.m1, self.f.schedules["a"]), sqlstate="23505")

    def test_line_inserts_are_audited_with_the_actor(self):
        _, version = self.f.order("MF-OT-11", self.f.m1)
        line = self.f.line(version, "L1", self.f.article_a, self.f.m1)
        event = self.connection.execute(
            """SELECT actor_id, new_data->>'machine_id' FROM vinto_audit.audit_event
               WHERE entity_table='work_order_line' AND action='INSERT' AND entity_key->>'id'=%s""", (str(line),)).fetchone()
        self.assertEqual(event, (self.f.user, str(self.f.m1)))


class LineMachineMigrationRehearsalTests(ConnectionMixin, unittest.TestCase):
    """Start from the 0009 shape (rollback script), load legacy data, apply the real 0010 file, compare."""

    SNAPSHOT = """SELECT id, to_jsonb(line) - 'machine_id' - 'updated_at' FROM vinto_txn.work_order_line line ORDER BY id"""

    def setUp(self):
        self.connection = self.open()
        try:
            self.connection.execute(ROLLBACK.read_text(encoding="utf-8"))
        except psycopg.errors.InsufficientPrivilege:
            self.skipTest("the test role does not own the schema; rehearsal needs the migrator role")
        self.assertFalse(self.column_exists(), "rollback must restore the 0009 shape")
        self.f = Fixture(self.connection)
        self.build_legacy_data()

    def column_exists(self):
        return self.connection.execute(
            """SELECT 1 FROM information_schema.columns
               WHERE table_schema='vinto_txn' AND table_name='work_order_line' AND column_name='machine_id'""").fetchone() is not None

    def build_legacy_data(self):
        f = self.f
        # Published single-machine OT on M1 (baseline + operational) with an active assignment, and one on M2.
        self.order_1, baseline_1 = f.order("MF-LEG-1", f.m1)
        self.b1 = [f.legacy_line(baseline_1, "L1", f.article_a), f.legacy_line(baseline_1, "L2", f.article_a)]
        f.publish(baseline_1)
        operational_1 = f.version(self.order_1, "operational", 2)
        self.o1 = [f.legacy_line(operational_1, "L1", f.article_a), f.legacy_line(operational_1, "L2", f.article_a)]
        f.publish(operational_1)
        self.assignment = f.assignment(self.o1[0], f.m1, f.schedules["a"])
        _, baseline_2 = f.order("MF-LEG-2", f.m2)
        self.b2 = [f.legacy_line(baseline_2, "L1", f.article_b)]
        f.publish(baseline_2)
        # Draft OT, unpublished baseline.
        _, draft = f.order("MF-LEG-3", f.m1)
        self.draft_line = f.legacy_line(draft, "L1", f.article_a)
        # Legacy line whose article is NOT enabled for the machine: must migrate untouched (no retroactive failure).
        _, odd = f.order("MF-LEG-4", f.m1)
        self.odd_line = f.legacy_line(odd, "L1", f.article_free)
        f.publish(odd)
        self.all_lines = self.b1 + self.o1 + self.b2 + [self.draft_line, self.odd_line]

    def migrate(self):
        # The real migration runs without an application actor; keep updated_by comparable.
        self.connection.execute("SELECT set_config('vinto.actor_id','',true)")
        self.connection.execute(MIGRATION.read_text(encoding="utf-8"))

    def test_backfill_copies_header_machine_without_losing_or_altering_anything(self):
        c = self.connection
        before_rows = c.execute(self.SNAPSHOT).fetchall()
        before_assignment = c.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a WHERE id=%s", (self.assignment,)).fetchone()
        before_orders = c.execute("SELECT to_jsonb(w) FROM vinto_txn.work_order w ORDER BY id").fetchall()
        before_events = c.execute("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='work_order_line'").fetchone()[0]
        self.migrate()
        self.assertEqual(c.execute(self.SNAPSHOT).fetchall(), before_rows)
        self.assertEqual(c.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a WHERE id=%s", (self.assignment,)).fetchone(), before_assignment)
        self.assertEqual(c.execute("SELECT to_jsonb(w) FROM vinto_txn.work_order w ORDER BY id").fetchall(), before_orders)
        mismatched = c.execute(
            """SELECT count(*) FROM vinto_txn.work_order_line line
               JOIN vinto_txn.work_order_version version ON version.id = line.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id = version.work_order_id
               WHERE line.machine_id IS DISTINCT FROM wo.machine_id""").fetchone()[0]
        self.assertEqual(mismatched, 0)
        self.assertEqual(c.execute("SELECT count(*) FROM vinto_txn.work_order_line WHERE id = ANY(%s)", (self.all_lines,)).fetchone()[0], len(self.all_lines))
        # Every backfilled row has an audit event with the stated reason.
        events = c.execute(
            """SELECT count(*) FROM vinto_audit.audit_event
               WHERE entity_table='work_order_line' AND action='UPDATE' AND reason LIKE 'MF13-03B PR1 backfill%%'""").fetchone()[0]
        self.assertGreaterEqual(events, len(self.all_lines))
        self.assertGreater(c.execute("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='work_order_line'").fetchone()[0], before_events)

    def test_after_migration_the_legacy_data_still_obeys_the_business_rules(self):
        self.migrate()
        f = self.f
        enabled = self.connection.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgrelid='vinto_txn.work_order_line'::regclass AND tgname='guard_order_line'").fetchone()[0]
        self.assertEqual(enabled, "O")
        self.rejected(lambda: self.connection.execute("UPDATE vinto_txn.work_order_line SET quantity=5 WHERE id=%s", (self.b1[0],)))
        self.rejected(lambda: self.connection.execute("UPDATE vinto_txn.work_order_line SET machine_id=%s WHERE id=%s", (f.m2, self.b1[0])))
        self.rejected(lambda: self.connection.execute("DELETE FROM vinto_txn.work_order_line WHERE id=%s", (self.b1[0],)))
        # Existing active assignment is intact; finishing it and activating the other operational line works as before.
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s", (self.assignment,))
        f.assignment(self.o1[1], f.m1, f.schedules["a"])
        # Wrong-machine assignment for a migrated line is still rejected.
        self.rejected(lambda: f.assignment(self.b2[0], f.m1, f.schedules["a"]))
        # A new line in the draft version can be added through the pre-0010 insert shape.
        draft_version = self.connection.execute(
            "SELECT work_order_version_id FROM vinto_txn.work_order_line WHERE id=%s", (self.draft_line,)).fetchone()[0]
        added = f.legacy_line(draft_version, "L2", f.article_a)
        self.assertEqual(self.connection.execute("SELECT machine_id FROM vinto_txn.work_order_line WHERE id=%s", (added,)).fetchone()[0], f.m1)

    def test_failed_migration_restores_the_guard_and_leaves_no_trace(self):
        """Controlled, reversible transition: a failure after the guard was switched off must roll everything back."""
        broken = MIGRATION.read_text(encoding="utf-8").replace(
            "ALTER TABLE vinto_txn.work_order_line ENABLE TRIGGER guard_order_line;",
            "SELECT 1/0;\nALTER TABLE vinto_txn.work_order_line ENABLE TRIGGER guard_order_line;")
        self.assertIn("SELECT 1/0", broken)
        with self.assertRaises(psycopg.errors.DivisionByZero):
            with self.connection.transaction():
                self.connection.execute(broken)
        self.assertFalse(self.column_exists())
        enabled = self.connection.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgrelid='vinto_txn.work_order_line'::regclass AND tgname='guard_order_line'").fetchone()[0]
        self.assertEqual(enabled, "O")
        self.rejected(lambda: self.connection.execute("UPDATE vinto_txn.work_order_line SET quantity=5 WHERE id=%s", (self.b1[0],)))

    def test_rollback_after_migration_returns_to_the_0009_shape_with_data_intact(self):
        before = self.connection.execute(self.SNAPSHOT).fetchall()
        self.migrate()
        self.connection.execute(ROLLBACK.read_text(encoding="utf-8"))
        self.assertFalse(self.column_exists())
        self.assertEqual(self.connection.execute(self.SNAPSHOT).fetchall(), before)
        self.assertIsNone(self.connection.execute("SELECT to_regprocedure('vinto_txn.validate_order_line_machine()')").fetchone()[0])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_meta.schema_migration WHERE version=10").fetchone()[0], 0)

    def test_rollback_is_refused_once_a_multi_machine_line_exists(self):
        self.migrate()
        f = self.f
        order, version = f.order("MF-LEG-5", f.m1)
        f.line(version, "L1", f.article_b, f.m2)
        with self.assertRaises(psycopg.errors.RaiseException):
            with self.connection.transaction():
                self.connection.execute(ROLLBACK.read_text(encoding="utf-8"))
        self.assertTrue(self.column_exists())


if __name__ == "__main__":
    unittest.main()
