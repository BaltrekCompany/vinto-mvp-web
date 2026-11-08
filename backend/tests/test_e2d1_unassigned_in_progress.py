"""E2-D1 isolated PG17 tests (disposable *_test only)."""
import unittest
from unittest.mock import patch
from app.config import settings
from app.work_orders import reprogramming, line_execution
from app.work_orders.errors import WorkOrderD1DisabledError, WorkOrderD1BlockedError, WorkOrderReprogramConflictError
from app.work_orders.service import LineInput

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = base.build_reference_template("vinto_e2d1_tpl")


def tearDownModule():
    template = base.STATE.pop("template", None)
    if template:
        base.drop_database(template)


class E2D1Tests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        p = patch.object(settings, "work_order_line_execution_enabled", True)
        p.start()
        self.addCleanup(p.stop)

    def enable_d1(self):
        p = patch.object(settings, "work_order_reprogram_unassigned_in_progress_enabled", True)
        p.start()
        self.addCleanup(p.stop)

    def revise(self, order, index=1, version=2):
        view = base.work_orders.get_work_order(self.connection, order.id, sectors=("BOBINAS",), multi_machine_visible=True)
        line = (view.programming or view.baseline).lines[index]
        old = LineInput(line.pv_reference, line.article_code, line.quantity, line.due_date)
        new = LineInput(line.pv_reference, line.article_code, line.quantity + 7, line.due_date)
        return reprogramming.reprogram_unassigned_in_progress_line(
            self.connection, actor_id=self.jefatura, work_order_id=order.id,
            line_code=line.line_code, expected_version=version, expected=old,
            replacement=new, reason="Reprogramacion controlada de linea no iniciada",
            sectors=("BOBINAS",))

    def versions(self, order):
        return self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (order.id,))

    def test_off_fails_without_writes(self):
        order = self.same_machine_order(2)
        self.activate(order, 0)
        with self.assertRaises(WorkOrderD1DisabledError):
            self.revise(order)
        self.assertEqual(self.versions(order), 2)

    def test_running_l1_untouched_l2_revised_and_l1_idempotent(self):
        self.enable_d1()
        order = self.same_machine_order(2)
        l1 = self.activate(order, 0).assignment
        line_execution.start_line(self.connection, actor_id=self.supervisor, work_order_id=order.id,
                                  line_code="L1", assignment_id=l1.id, sectors=("BOBINAS",))
        row = self.connection.execute(
            "SELECT work_order_line_id,status FROM vinto_txn.assignment WHERE id=%s", (l1.id,)).fetchone()
        revised = self.revise(order)
        self.assertEqual(revised.programming.version_number, 3)
        self.assertEqual(revised.programming.lines[1].quantity, order.baseline.lines[1].quantity + 7)
        self.assertEqual(
            self.connection.execute("SELECT work_order_line_id,status FROM vinto_txn.assignment WHERE id=%s",
                                    (l1.id,)).fetchone(), row)
        again = self.activate(order, 0)
        self.assertTrue(again.already_active)
        self.assertFalse(again.created)
        self.assertEqual(again.assignment.id, l1.id)
        l2 = self.activate(order, 1)
        self.assertEqual(l2.assignment.operational_version_number, 3)
        self.assertEqual(l2.assignment.line.quantity, order.baseline.lines[1].quantity + 7)
        self.assertEqual(self.active_codes(), ["L1", "L2"])

    def test_assigned_unstarted_target_is_blocked(self):
        self.enable_d1()
        order = self.same_machine_order(2)
        self.activate(order, 0)
        self.activate(order, 1)
        with self.assertRaises(WorkOrderD1BlockedError):
            self.revise(order)
        self.assertEqual(self.versions(order), 2)

    def test_stale_revision_rejected_without_writes(self):
        self.enable_d1()
        order = self.same_machine_order(2)
        self.activate(order, 0)
        with self.assertRaises(WorkOrderReprogramConflictError):
            self.revise(order, version=999)
        self.assertEqual(self.versions(order), 2)

    def test_legacy_active_assignment_without_e1_is_not_reprogrammable(self):
        self.enable_d1()
        order = self.same_machine_order(2)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            self.activate(order, 0)
        with self.assertRaises(WorkOrderD1BlockedError):
            self.revise(order)
        self.assertEqual(self.versions(order), 2)

    def test_historical_legacy_assignment_on_another_line_blocks_d1(self):
        self.enable_d1()
        order = self.same_machine_order(3)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            old = self.activate(order, 2).assignment
            base.service.finish(
                self.connection, actor_id=self.supervisor,
                assignment_id=old.id, sectors=("BOBINAS",))
        self.activate(order, 0)
        with self.assertRaises(WorkOrderD1BlockedError):
            self.revise(order, index=1)
        self.assertEqual(self.versions(order), 2)

    def test_no_other_active_assignment_is_blocked(self):
        self.enable_d1()
        order = self.same_machine_order(2)
        a = self.activate(order, 0).assignment
        base.service.finish(self.connection, actor_id=self.supervisor, assignment_id=a.id, sectors=("BOBINAS",))
        with self.assertRaises(WorkOrderD1BlockedError):
            self.revise(order)
        self.assertEqual(self.versions(order), 2)


if __name__ == "__main__":
    unittest.main()
