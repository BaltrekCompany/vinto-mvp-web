"""E2-D1 concurrency scenarios on disposable PostgreSQL 17 databases only."""
import threading
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import connect
from app.work_orders import reprogramming
from app.work_orders.errors import WorkOrderD1BlockedError, WorkOrderReprogramConflictError
from app.work_orders.service import LineInput

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = base.build_reference_template("vinto_e2d1race_tpl")


def tearDownModule():
    template = base.STATE.pop("template", None)
    if template:
        base.drop_database(template)


class E2D1RaceTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        for name in ("work_order_line_execution_enabled",
                     "work_order_reprogram_unassigned_in_progress_enabled"):
            p = patch.object(settings, name, True)
            p.start()
            self.addCleanup(p.stop)

    def revise(self, connection, order, quantity=27):
        target = order.baseline.lines[1]
        return reprogramming.reprogram_unassigned_in_progress_line(
            connection, actor_id=self.jefatura, work_order_id=order.id,
            line_code="L2", expected_version=2,
            expected=LineInput(target.pv_reference, target.article_code,
                               target.quantity, target.due_date),
            replacement=LineInput(target.pv_reference, target.article_code,
                                  quantity, target.due_date),
            reason="Revision concurrente segura de linea sin asignar",
            sectors=("BOBINAS",))

    def run_pair(self, first, second):
        barrier = threading.Barrier(2)
        results = [None, None]
        threads = []

        def execute(index, target):
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    results[index] = ("ok", target(connection))
            except Exception as error:
                results[index] = ("error", error)

        for index, fn in enumerate((first, second)):
            thread = threading.Thread(target=execute, args=(index, fn), daemon=True)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=45)
        self.assertFalse(any(thread.is_alive() for thread in threads),
                         "Potential deadlock in reprogram/assignment lock ordering")
        self.assertTrue(all(result is not None for result in results))
        return results

    def test_reprogram_vs_activate_target_serialises_without_orphans(self):
        order = self.same_machine_order(2)
        before = self.activate(order, 0).assignment
        results = self.run_pair(
            lambda c: self.revise(c, order, quantity=27),
            lambda c: base.service.activate(
                c, actor_id=self.supervisor_b, work_order_id=order.id,
                baseline_line_id=order.baseline.lines[1].id))
        self.assertEqual(results[1][0], "ok", results)
        if results[0][0] == "error":
            self.assertIsInstance(results[0][1], WorkOrderD1BlockedError)
            expected_version, expected_quantity = 2, order.baseline.lines[1].quantity
        else:
            expected_version, expected_quantity = 3, 27
        assigned = results[1][1].assignment
        self.assertEqual(assigned.operational_version_number, expected_version)
        self.assertEqual(assigned.line.quantity, expected_quantity)
        self.assertEqual(self.active_codes(), ["L1", "L2"])
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s", (before.id,)), "active")
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s",
            (order.id,)), expected_version)

    def test_two_reprogram_requests_with_same_version_have_one_winner(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        results = self.run_pair(
            lambda c: self.revise(c, order, quantity=27),
            lambda c: self.revise(c, order, quantity=29))
        self.assertEqual(sorted(item[0] for item in results), ["error", "ok"])
        error = next(value for status, value in results if status == "error")
        self.assertIsInstance(error, WorkOrderReprogramConflictError)
        winner = next(value for status, value in results if status == "ok")
        self.assertEqual(winner.programming.version_number, 3)
        self.assertIn(winner.programming.lines[1].quantity, (27, 29))
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s",
            (order.id,)), 3)
        self.assertEqual(self.active_codes(), ["L1"])


if __name__ == "__main__":
    unittest.main()
