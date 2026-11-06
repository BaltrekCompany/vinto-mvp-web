"""E1-07: full work order closure on disposable PostgreSQL 17 only."""
import threading
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.work_orders import line_execution as flow
from app.work_orders import close_order
from app.work_orders.errors import WorkOrderNotFoundError

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e107_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class CloseWorkOrderTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        flag = patch.object(settings, "work_order_line_execution_enabled", True)
        flag.start()
        self.addCleanup(flag.stop)

    def close(self, order, connection=None, sectors=("BOBINAS",)):
        return close_order.close_work_order(
            connection or self.connection, actor_id=self.supervisor,
            work_order_id=order.id, sectors=sectors)

    def start(self, order, line, assignment, connection=None):
        return flow.start_line(
            connection or self.connection, actor_id=self.supervisor,
            work_order_id=order.id, line_code=line,
            assignment_id=assignment.id, sectors=("BOBINAS",))

    def finish(self, order, line, connection=None):
        return flow.finish_line(
            connection or self.connection, actor_id=self.supervisor,
            work_order_id=order.id, line_code=line, sectors=("BOBINAS",))

    def test_published_order_cannot_be_closed(self):
        order = self.same_machine_order(2)
        with self.assertRaises(close_order.WorkOrderCloseInvalidStateError):
            self.close(order)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "published")

    def test_enabled_and_not_started_lines_block_and_report_all_codes(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        self.activate(order, 1)
        with self.assertRaises(close_order.WorkOrderCloseBlockedError) as ctx:
            self.close(order)
        self.assertEqual(ctx.exception.pending_lines, ("L1", "L2"))

    def test_finishing_one_line_cannot_close_other_enabled_line(self):
        order = self.same_machine_order(2)
        first = self.activate(order, 0).assignment
        self.activate(order, 1)
        self.start(order, "L1", first)
        self.finish(order, "L1")
        with self.assertRaises(close_order.WorkOrderCloseBlockedError) as ctx:
            self.close(order)
        self.assertEqual(ctx.exception.pending_lines, ("L2",))

    def test_finished_lines_can_close_without_any_capture_or_reason(self):
        """Deficit 120 planned / zero recorded is not itself a close rejection."""
        order = self.same_machine_order(2)
        first, second = [self.activate(order, i).assignment for i in (0, 1)]
        self.start(order, "L1", first)
        self.finish(order, "L1")
        self.start(order, "L2", second)
        self.finish(order, "L2")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)
        closed = self.close(order)
        self.assertEqual(closed.status, "closed")
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "closed")
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_line_execution WHERE work_order_id=%s AND status='finished'",
            (order.id,)), 2)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 0)

    def test_double_close_is_idempotent_and_keeps_timestamp(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        self.start(order, "L1", assigned)
        self.finish(order, "L1")
        self.close(order)
        stamp = self.scalar("SELECT updated_at FROM vinto_txn.work_order WHERE id=%s", (order.id,))
        self.assertEqual(self.close(order).status, "closed")
        self.assertEqual(self.scalar(
            "SELECT updated_at FROM vinto_txn.work_order WHERE id=%s", (order.id,)), stamp)

    def test_closed_order_cannot_reactivate_or_restart_line(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        self.start(order, "L1", assigned)
        self.finish(order, "L1")
        self.close(order)
        with self.assertRaises(Exception):
            self.activate(order, 0)
        with self.assertRaises(flow.ExecutionStateConflictError):
            self.start(order, "L1", assigned)

    def test_sector_scope_checked_before_status_or_pending_codes(self):
        order = self.same_machine_order(1)
        with self.assertRaises(WorkOrderNotFoundError):
            self.close(order, sectors=("REBOBINADO",))

    def test_gate_off_does_not_allow_close(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            with self.assertRaises(flow.ExecutionDisabledError):
                self.close(order)

    def test_multi_machine_order_needs_all_lines_finished(self):
        order = self.mixed_order()
        assignments = [self.activate(order, i).assignment for i in range(3)]
        self.start(order, "L1", assignments[0])
        self.start(order, "L3", assignments[2])
        self.finish(order, "L1")
        self.finish(order, "L3")
        with self.assertRaises(close_order.WorkOrderCloseBlockedError) as ctx:
            self.close(order)
        self.assertEqual(ctx.exception.pending_lines, ("L2",))
        self.start(order, "L2", assignments[1])
        self.finish(order, "L2")
        self.assertEqual(self.close(order).status, "closed")

    def test_concurrent_finish_and_close_are_serialized_without_deadlock(self):
        order = self.same_machine_order(1)
        assignment = self.activate(order, 0).assignment
        self.start(order, "L1", assignment)
        barrier = threading.Barrier(2)
        results = [None, None]

        def do_finish():
            try:
                with connect(self.database) as c:
                    barrier.wait(timeout=15)
                    self.finish(order, "L1", connection=c)
                results[0] = "finished"
            except Exception as e:
                results[0] = "unexpected:" + str(e)

        def do_close():
            try:
                with connect(self.database) as c:
                    barrier.wait(timeout=15)
                    self.close(order, connection=c)
                results[1] = "closed"
            except close_order.WorkOrderCloseBlockedError:
                results[1] = "blocked"
            except Exception as e:
                results[1] = "unexpected:" + str(e)

        threads = [threading.Thread(target=do_finish), threading.Thread(target=do_close)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)
        self.assertEqual(results[0], "finished", results)
        self.assertIn(results[1], ("closed", "blocked"), results)
        if results[1] == "blocked":
            self.assertEqual(self.close(order).status, "closed")
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "closed")


if __name__ == "__main__":
    unittest.main()
