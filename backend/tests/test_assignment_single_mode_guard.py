"""MF13-03.B migration 0012: database guard for one active assignment per machine while multi-line mode is not declared.

Reuses the PR3 fixtures (ephemeral *_test databases from a migrated template). Nothing touches vinto, vinto_piloto or any server.
Concurrency is synchronised with a barrier and database locks, never with sleeps.
"""

import pathlib
import threading
import unittest
from unittest.mock import patch

import psycopg

from app.assignments.errors import MachineBusyWithOtherWorkOrderError, MultipleActiveAssignmentsError
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, drop_database

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base

service, MP1_CODES, MP3_ONLY = base.service, base.MP1_CODES, base.MP3_ONLY
ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "0012_assignment_single_mode_guard.sql"
ROLLBACK = ROOT / "rollbacks" / "0012_assignment_single_mode_guard_rollback.sql"
ROLLBACK_0013 = ROOT / "rollbacks" / "0013_work_order_line_execution_rollback.sql"
PREFLIGHT = ROOT / "preflights" / "0012_assignment_single_mode_preflight.sql"


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_sm_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])


class GuardCase(base.SameOrderCase):
    def insert_sql(self, order, index, mode=None, connection=None):
        """Direct INSERT of an active assignment for operational line `index` of `order`, copying shift/date from an existing row of the machine."""
        c = connection or self.connection
        c.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.supervisor),))
        c.execute("SELECT set_config('vinto.request_id', 'sm-fixture', true)")
        c.execute("SELECT set_config('vinto.reason', 'sm fixture', true)")
        if mode is not None:
            c.execute("SELECT set_config('vinto.assignment_multi_line', %s, true)", (mode,))
        return c.execute(
            """INSERT INTO vinto_txn.assignment (work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by)
               SELECT l.id, l.machine_id, ref.shift_schedule_id, ref.operating_date, %s
                 FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id,
                      (SELECT shift_schedule_id, operating_date FROM vinto_txn.assignment ORDER BY created_at LIMIT 1) ref
                WHERE v.work_order_id = %s AND v.kind = 'operational' AND l.line_code = %s RETURNING id""",
            (self.supervisor, order.id, f"L{index + 1}")).fetchone()[0]

    def sql_error(self, operation):
        with self.assertRaises(psycopg.Error) as caught:
            with self.connection.transaction():
                operation()
        return caught.exception

    def run_threads(self, targets):
        outcomes, barrier = [None] * len(targets), threading.Barrier(len(targets))

        def runner(index, target):
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    outcomes[index] = ("ok", target(connection))
            except Exception as error:
                outcomes[index] = ("error", error)

        threads = [threading.Thread(target=runner, args=(i, t)) for i, t in enumerate(targets)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)
        return outcomes

    def act(self, order, index):
        return lambda c: service.activate(c, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[index].id)


class GateOffTests(GuardCase):
    """Gate OFF: historical behaviour preserved, and the database now backs it."""

    def test_individual_activation_still_replaces_the_previous_assignment(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        second = self.activate(order, 1)
        self.assertEqual(len(second.finished_assignment_ids), 1)
        self.assertEqual(self.states(), [("L1", "finished"), ("L2", "active")])

    def test_the_service_declares_off_mode_and_a_direct_second_insert_is_rejected(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        error = self.sql_error(lambda: self.insert_sql(order, 1))  # no declaration at all -> fail-safe single mode
        self.assertEqual(error.sqlstate, "23P01")
        self.assertIn("multi-line mode is not declared", str(error))
        self.assertEqual(self.sql_error(lambda: self.insert_sql(order, 1, "off")).sqlstate, "23P01")
        self.assertEqual(self.active_codes(), ["L1"])

    def test_only_the_exact_value_on_relaxes_the_guard(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        for value in ("ON", "true", "1", "yes", " on", ""):
            self.assertEqual(self.sql_error(lambda value=value: self.insert_sql(order, 1, value)).sqlstate, "23P01", value)
        self.assertEqual(self.active_codes(), ["L1"])

    def test_a_first_active_assignment_on_a_free_machine_needs_no_declaration(self):
        order = self.same_machine_order(1)
        self.activate(order, 0)
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=self.scalar("SELECT id FROM vinto_txn.assignment"))
        with self.connection.transaction():
            self.insert_sql(order, 0)  # the machine has no active row; the line is free again
        self.assertEqual(self.states(), [("L1", "finished"), ("L1", "active")])

    def test_two_concurrent_activations_end_with_exactly_one_active_assignment(self):
        order = self.same_machine_order(2)
        outcomes = self.run_threads([self.act(order, 0), self.act(order, 1)])
        self.assertEqual([o[0] for o in outcomes], ["ok", "ok"])
        self.assertEqual(len(self.active_codes()), 1)
        self.assertEqual(sorted(s for _, s in self.states()), ["active", "finished"])

    def test_direct_concurrent_inserts_bypassing_the_service_lock_cannot_both_win(self):
        order = self.same_machine_order(3)
        self.activate(order, 0)
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=self.scalar("SELECT id FROM vinto_txn.assignment"))

        def insert(index):
            def run(connection):
                with connection.transaction():
                    return self.insert_sql(order, index, connection=connection)
            return run
        outcomes = self.run_threads([insert(1), insert(2)])
        self.assertEqual(sorted(o[0] for o in outcomes), ["error", "ok"])
        self.assertEqual(next(o[1] for o in outcomes if o[0] == "error").sqlstate, "23P01")
        self.assertEqual(len(self.active_codes()), 1)

    def test_activation_and_finish_racing_never_leave_two_active(self):
        order = self.same_machine_order(2)
        first = self.activate(order, 0).assignment
        outcomes = self.run_threads([self.act(order, 1), lambda c: service.finish(c, actor_id=self.supervisor, assignment_id=first.id)])
        self.assertEqual([o[0] for o in outcomes], ["ok", "ok"])
        self.assertEqual(self.active_codes(), ["L2"])
        self.assertEqual(self.states(), [("L1", "finished"), ("L2", "active")])

    def test_retries_are_idempotent(self):
        order = self.same_machine_order(1)
        first = self.activate(order, 0)
        again = self.activate(order, 0)
        self.assertEqual((again.created, again.already_active, again.assignment.id), (False, True, first.assignment.id))
        self.assertEqual(self.states(), [("L1", "active")])

    def test_legacy_machine_with_several_active_rows_is_still_handled_by_the_application(self):
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(2)
            self.activate(order, 0)
            self.activate(order, 1)
        self.assertEqual(self.active_codes(), ["L1", "L2"])
        with self.assertRaises(MultipleActiveAssignmentsError):  # gate OFF afterwards: nothing is guessed, nothing is written
            self.activate(self.same_machine_order(1), 0)
        self.assertEqual(self.active_codes(), ["L1", "L2"])
        ids = [row[0] for row in self.connection.execute("SELECT id FROM vinto_txn.assignment ORDER BY created_at").fetchall()]
        for assignment_id in ids:  # finishing existing active rows is never blocked
            service.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment_id)
        self.assertEqual(self.active_codes(), [])


class GateOnTests(GuardCase):
    def setUp(self):
        super().setUp()
        self.gate(True)

    def test_individual_activation_of_several_lines_of_one_order(self):
        order = self.same_machine_order(3)
        for index in range(3):
            self.activate(order, index)
        self.assertEqual(self.active_codes(), ["L1", "L2", "L3"])

    def test_bulk_activation_is_not_blocked(self):
        order = self.mixed_order()
        plan = service.preview_activate_all(self.connection, work_order_id=order.id)
        result = service.activate_all(self.connection, actor_id=self.supervisor, work_order_id=order.id, plan_hash=plan.plan.plan_hash)
        self.assertEqual(result.outcome, "applied")
        self.assertEqual((self.active_codes("MP1"), self.active_codes("MP3")), (["L1", "L2"], ["L3"]))
        again = service.activate_all(self.connection, actor_id=self.supervisor, work_order_id=order.id, plan_hash=plan.plan.plan_hash)
        self.assertEqual(again.outcome, "already_in_effect")

    def test_another_work_order_is_still_rejected_and_nothing_is_finished(self):
        one, two = self.same_machine_order(2), self.same_machine_order(1)
        self.activate(one, 0)
        with self.assertRaises(MachineBusyWithOtherWorkOrderError):
            self.activate(two, 0)
        self.assertEqual(self.states(), [("L1", "active")])

    def test_a_declared_on_direct_insert_is_still_bound_by_the_0011_rules(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        with self.connection.transaction():
            self.insert_sql(order, 1, "on")
        self.assertEqual(self.active_codes(), ["L1", "L2"])
        self.assertEqual(self.sql_error(lambda: self.insert_sql(order, 1, "on")).sqlstate, "23505")  # the line is already active

    def test_concurrent_activations_with_the_gate_on_all_end_active(self):
        order = self.same_machine_order(3)
        outcomes = self.run_threads([self.act(order, i) for i in range(3)])
        self.assertEqual([o[0] for o in outcomes], ["ok"] * 3)
        self.assertEqual(self.active_codes(), ["L1", "L2", "L3"])


class MigrationRehearsalTests(GuardCase):
    """Apply the real 0012 file, its rollback and the preflight over synthetic data."""

    def snapshot(self):
        return (self.connection.execute("SELECT to_jsonb(a) - 'updated_at' FROM vinto_txn.assignment a ORDER BY id").fetchall(),
                self.connection.execute("SELECT to_jsonb(c) - 'updated_at' FROM vinto_txn.capture c ORDER BY id").fetchall(),
                self.connection.execute("SELECT to_jsonb(e) FROM vinto_audit.audit_event e WHERE entity_table = 'assignment' ORDER BY id").fetchall())

    def trigger_count(self):
        return self.scalar("SELECT count(*) FROM pg_trigger WHERE tgname = 'validate_assignment_single_mode' AND NOT tgisinternal")

    def test_the_template_has_0012_registered_and_the_trigger_enabled(self):
        self.assertEqual(self.scalar("SELECT filename FROM vinto_meta.schema_migration WHERE version = 12"), "0012_assignment_single_mode_guard.sql")
        self.assertEqual(self.scalar("SELECT tgenabled FROM pg_trigger WHERE tgname = 'validate_assignment_single_mode'"), "O")

    def test_rollback_then_reapply_over_compatible_data_preserves_history(self):
        one = self.same_machine_order(2)
        self.activate(one, 0)
        self.activate(one, 1)  # replaced: L1 finished (history), L2 active
        self.activate(self.same_machine_order(1, machine="MP3"), 0)
        before = self.snapshot()
        checksum = self.scalar("SELECT checksum FROM vinto_meta.schema_migration WHERE version = 12")
        with self.connection.transaction():
            self.connection.execute(ROLLBACK.read_text(encoding="utf-8"))
            self.assertEqual((self.trigger_count(), self.scalar("SELECT count(*) FROM vinto_meta.schema_migration WHERE version = 12")), (0, 0))
            self.assertEqual(self.snapshot(), before)
            self.connection.execute(MIGRATION.read_text(encoding="utf-8"))
            self.assertEqual((self.trigger_count(), self.snapshot()), (1, before))
            self.connection.execute("INSERT INTO vinto_meta.schema_migration (version, filename, checksum) VALUES (12, '0012_assignment_single_mode_guard.sql', %s)", (checksum,))
        self.assertEqual(self.snapshot(), before)

    def test_migration_over_incompatible_existing_data_changes_nothing_and_never_blocks_finishing(self):
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(3)
            for index in range(3):
                self.activate(order, index)
        self.assertEqual(self.active_codes(), ["L1", "L2", "L3"])
        before = self.snapshot()
        with self.connection.transaction():
            self.connection.execute(ROLLBACK.read_text(encoding="utf-8"))
            self.connection.execute(MIGRATION.read_text(encoding="utf-8"))  # applies cleanly over a machine holding 3 active rows
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.trigger_count(), 1)
        ids = [row[0] for row in self.connection.execute("SELECT id FROM vinto_txn.assignment ORDER BY created_at").fetchall()]
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=ids[2])  # L3 is free again, L1 and L2 stay active
        self.assertEqual(self.sql_error(lambda: self.insert_sql(order, 2)).sqlstate, "23P01")  # the guard is live on a machine that already holds 2 active rows
        for assignment_id in ids:
            service.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment_id)
        self.assertEqual([s for _, s in self.states()], ["finished"] * 3)

    def test_rollback_has_no_data_precondition_and_is_never_refused(self):
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(2)
            self.activate(order, 0)
            self.activate(order, 1)
        before = self.snapshot()
        with self.connection.transaction():
            self.connection.execute(ROLLBACK.read_text(encoding="utf-8"))
        self.assertEqual((self.trigger_count(), self.snapshot()), (0, before))
        self.assertEqual(self.active_codes(), ["L1", "L2"])

    def test_preflight_is_read_only_and_reports_machines_with_several_active_rows(self):
        self.assertEqual(self.connection.execute(PREFLIGHT.read_text(encoding="utf-8")).fetchall(), [])
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(2)
            self.activate(order, 0)
            self.activate(order, 1)
        before = self.snapshot()
        rows = self.connection.execute(PREFLIGHT.read_text(encoding="utf-8")).fetchall()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [("MP1", 2, 1)])
        self.assertEqual(rows[0][3], self.scalar("SELECT number FROM vinto_txn.work_order WHERE id=%s", (order.id,)))  # a person can see WHICH work order
        active_ids = [str(r[0]) for r in self.connection.execute("SELECT id FROM vinto_txn.assignment WHERE status='active'").fetchall()]
        self.assertTrue(all(i in rows[0][4] for i in active_ids))  # and which assignments to finish explicitly
        self.assertEqual(self.snapshot(), before)

    def test_files_follow_the_repository_conventions(self):
        text = MIGRATION.read_text(encoding="utf-8")
        for forbidden in ("BEGIN;", "COMMIT;", "CONCURRENTLY", "DELETE", "UPDATE vinto_txn", "DROP TABLE", "TRUNCATE"):
            self.assertNotIn(forbidden, text)


class TransactionScopeTests(GuardCase):
    """The declaration is transaction-local: it can never leak into a later transaction of the same (reused) connection."""

    def setting(self):
        return self.scalar("SELECT coalesce(current_setting('vinto.assignment_multi_line', true), '')")

    def finish_all(self):
        for assignment_id in [r[0] for r in self.connection.execute("SELECT id FROM vinto_txn.assignment WHERE status='active'").fetchall()]:
            service.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment_id)

    def test_the_declaration_disappears_after_commit(self):
        with self.connection.transaction():
            self.connection.execute("SELECT set_config('vinto.assignment_multi_line', 'on', true)")
            self.assertEqual(self.setting(), "on")
        self.assertEqual(self.setting(), "")

    def test_the_declaration_disappears_after_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.connection.transaction():
                self.connection.execute("SELECT set_config('vinto.assignment_multi_line', 'on', true)")
                raise RuntimeError("boom")
        self.assertEqual(self.setting(), "")

    def test_an_earlier_on_does_not_enable_later_inserts_on_a_reused_connection(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        with self.connection.transaction():
            self.insert_sql(order, 1, "on")  # allowed, and declared 'on' for THIS transaction only
        self.assertEqual(self.setting(), "")
        self.finish_all()
        with self.connection.transaction():
            self.insert_sql(order, 0)  # free machine
        self.assertEqual(self.sql_error(lambda: self.insert_sql(order, 1)).sqlstate, "23P01")  # no declaration now: single mode again

    def test_the_service_declaration_is_local_and_the_next_activation_redeclares_its_own_mode(self):
        order = self.same_machine_order(3)
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            self.activate(order, 0)
            self.activate(order, 1)
            self.assertEqual(self.setting(), "")  # the service transaction ended: nothing leaked
        self.assertEqual(self.active_codes(), ["L1", "L2"])
        self.finish_all()
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            self.activate(order, 0)
        self.activate(order, 1)  # same connection, gate OFF now: replaces instead of adding
        self.assertEqual(self.active_codes(), ["L2"])
        self.assertEqual(self.setting(), "")

    def test_a_rolled_back_activation_leaves_no_declaration_behind(self):
        one, two = self.same_machine_order(1), self.same_machine_order(1)
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            self.activate(one, 0)
            with self.assertRaises(MachineBusyWithOtherWorkOrderError):
                self.activate(two, 0)
            self.assertEqual(self.setting(), "")
        self.assertEqual(self.active_codes(), ["L1"])

    def test_application_connections_run_at_read_committed(self):
        self.assertEqual(self.scalar("SHOW default_transaction_isolation"), "read committed")
        self.assertEqual(self.scalar("SELECT current_setting('transaction_isolation')"), "read committed")

    def test_app_code_has_one_insert_and_declares_the_mode_before_it(self):
        text = (ROOT / "app" / "assignments" / "service.py").read_text(encoding="utf-8")
        self.assertLess(text.index("set_config('vinto.assignment_multi_line'"), text.index("INSERT INTO vinto_txn.assignment"))
        self.assertEqual(text.count("INSERT INTO vinto_txn.assignment"), 1)
        for path in (ROOT / "app").rglob("*.py"):
            if not (path.name == "service.py" and path.parent.name == "assignments"):
                self.assertNotIn("INSERT INTO vinto_txn.assignment", path.read_text(encoding="utf-8"), str(path))


class LockOrderTests(GuardCase):
    """No new deadlocks: the trigger takes the SAME advisory lock the service already holds (re-entrant), after the order lock."""

    def hammer(self, rounds):
        order = self.same_machine_order(3)
        self.activate(order, 0)
        failures = []
        for _ in range(rounds):
            actives = [r[0] for r in self.connection.execute("SELECT id FROM vinto_txn.assignment WHERE status='active'").fetchall()]
            targets = [self.act(order, i) for i in range(3)] + [
                (lambda c, a=a: service.finish(c, actor_id=self.supervisor, assignment_id=a)) for a in actives]
            failures += [o[1] for o in self.run_threads(targets) if o[0] == "error"]
        return failures

    def test_activation_and_finish_in_a_loop_never_deadlock_with_the_gate_off(self):
        failures = self.hammer(6)
        self.assertEqual([getattr(f, "sqlstate", None) or repr(f) for f in failures], [])
        self.assertLessEqual(len(self.active_codes()), 1)

    def test_activation_and_finish_in_a_loop_never_deadlock_with_the_gate_on(self):
        self.gate(True)
        failures = self.hammer(6)
        self.assertEqual([getattr(f, "sqlstate", None) or repr(f) for f in failures], [])
        self.assertEqual(self.scalar("SELECT count(*) - count(DISTINCT work_order_line_id) FROM vinto_txn.assignment WHERE status='active'"), 0)


class DeploymentTests(GuardCase):
    """Installation under concurrent sessions, old backend, and migration history through the real runner."""

    def rolled_back_database(self):
        with self.connection.transaction():
            self.connection.execute(ROLLBACK.read_text(encoding="utf-8"))

    def trigger_enabled(self):
        return self.connection.execute("SELECT tgenabled FROM pg_trigger WHERE tgname = 'validate_assignment_single_mode'").fetchone()

    def test_the_runner_registers_0012_with_the_exact_checksum_after_a_rollback(self):
        import migrate
        # Remove 0013 from the ephemeral database first (history must stay
        # contiguous); the production rollback refuses this if execution rows exist.
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution"), 0)
        self.connection.execute(ROLLBACK_0013.read_text(encoding="utf-8"))
        self.rolled_back_database()
        self.assertEqual(self.scalar("SELECT max(version) FROM vinto_meta.schema_migration"), 11)
        migrations = migrate.read_migrations()
        migrate.apply(self.connection, migrations)
        migration_0012 = next(item for item in migrations if item.version == 12)
        self.assertEqual(self.connection.execute("SELECT version, filename, checksum FROM vinto_meta.schema_migration WHERE version = 12").fetchone(),
                         (12, MIGRATION.name, migration_0012.checksum))
        self.assertEqual(self.scalar("SELECT max(version) FROM vinto_meta.schema_migration"), len(migrations))
        self.assertEqual(self.trigger_enabled(), ("O",))
        migrate.validate_history(migrate.read_migrations(), migrate.applied_migrations(self.connection))  # what `--check` verifies

    def test_installing_waits_for_an_in_flight_write_and_then_succeeds(self):
        self.rolled_back_database()
        holder, installed = connect(self.database), []
        self.addCleanup(holder.close)
        holder.execute("BEGIN")
        holder.execute("LOCK TABLE vinto_txn.assignment IN ROW EXCLUSIVE MODE")  # what an in-flight INSERT holds

        def install():
            try:
                with connect(self.database) as other:
                    other.execute("SET lock_timeout = '1500ms'")
                    with other.transaction():
                        other.execute(MIGRATION.read_text(encoding="utf-8"))
                    installed.append("ok")
            except psycopg.Error as error:
                installed.append(error.sqlstate)
        thread = threading.Thread(target=install)
        thread.start()
        thread.join(timeout=30)
        self.assertEqual(installed, ["55P03"])  # waits for the writer, then gives up cleanly; the transaction rolled back
        self.assertEqual(self.scalar("SELECT count(*) FROM pg_trigger WHERE tgname = 'validate_assignment_single_mode'"), 0)
        holder.execute("COMMIT")
        installed.clear()
        thread = threading.Thread(target=install)
        thread.start()
        thread.join(timeout=30)
        self.assertEqual(installed, ["ok"])
        self.assertEqual(self.trigger_enabled(), ("O",))

    def test_an_old_backend_that_never_declares_the_mode_cannot_add_a_second_line_after_0012(self):
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(2)
            self.activate(order, 0)
        self.assertEqual(self.sql_error(lambda: self.insert_sql(order, 1)).sqlstate, "23P01")  # exactly what an undeclared (old) writer does
        self.assertEqual(self.active_codes(), ["L1"])

    def test_the_preflight_flags_the_incompatible_state_without_changing_it(self):
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(3)
            for index in range(3):
                self.activate(order, index)
        before = self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a ORDER BY id").fetchall()
        rows = self.connection.execute(PREFLIGHT.read_text(encoding="utf-8")).fetchall()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [("MP1", 3, 1)])
        self.assertEqual(self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a ORDER BY id").fetchall(), before)


if __name__ == "__main__":
    unittest.main()
