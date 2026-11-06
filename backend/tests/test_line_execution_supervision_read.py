"""E1-05 read-only Supervisor projection on disposable PostgreSQL 17 databases."""
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders import line_execution
from app.work_orders.errors import WorkOrderNotFoundError

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e105_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class SupervisorExecutionProjectionTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        flag = patch.object(settings, "work_order_line_execution_enabled", True)
        flag.start()
        self.addCleanup(flag.stop)

    def read(self, order, sectors=("BOBINAS",)):
        return line_execution.read_work_order_execution(
            self.connection, work_order_id=order.id, sectors=sectors)

    def test_published_lines_without_assignments_are_planned(self):
        order = self.same_machine_order(2)
        data = self.read(order)
        self.assertEqual(data["work_order_id"], order.id)
        self.assertEqual([item["status"] for item in data["lines"]], ["planned", "planned"])
        self.assertTrue(all(item["current_assignment_id"] is None for item in data["lines"]))

    def test_habilitation_does_not_mean_producing(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        lines = self.read(order)["lines"]
        self.assertEqual([line["status"] for line in lines], ["enabled", "enabled"])
        self.assertEqual([line["current_assignment_id"] for line in lines], [first.id, second.id])
        self.assertTrue(all(line["started_at"] is None for line in lines))

    def test_start_and_finish_have_server_authoritative_states(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        line_execution.start_line(self.connection, actor_id=self.supervisor, work_order_id=order.id,
                                  line_code="L1", assignment_id=first.id, sectors=("BOBINAS",))
        lines = self.read(order)["lines"]
        self.assertEqual([line["status"] for line in lines], ["in_production", "enabled"])
        self.assertEqual(lines[0]["started_by"], self.supervisor)
        line_execution.finish_line(self.connection, actor_id=self.supervisor, work_order_id=order.id,
                                   line_code="L1", sectors=("BOBINAS",))
        lines = self.read(order)["lines"]
        self.assertEqual([line["status"] for line in lines], ["finished", "enabled"])
        self.assertEqual(lines[0]["finished_by"], self.supervisor)
        self.assertIsNone(lines[0]["current_assignment_id"])
        self.assertEqual(lines[1]["current_assignment_id"], second.id)

    def test_active_legacy_assignment_is_marked_for_review_not_started(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            self.activate(order, 0)
        item = self.read(order)["lines"][0]
        self.assertEqual(item["status"], "requires_review")
        self.assertIsNone(item["started_at"])

    def test_expired_assignment_is_not_startable_but_status_is_retained(self):
        order = self.same_machine_order(1)
        assignment = self.activate(order, 0).assignment
        self.assertEqual(self.read(order)["lines"][0]["current_assignment_id"], assignment.id)
        with patch.object(base._assignments, "_now", return_value=base.NIGHT):
            line = self.read(order)["lines"][0]
        self.assertEqual(line["status"], "enabled")
        self.assertIsNone(line["current_assignment_id"])

    def test_full_order_sector_scope_required(self):
        order = self.same_machine_order(1)
        with self.assertRaises(WorkOrderNotFoundError):
            self.read(order, sectors=("REBOBINADO",))
        self.assertEqual(self.read(order)["lines"][0]["machine_code"], "MP1")

    def test_flag_off_denies_read_without_accessing_schema(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            with self.assertRaises(line_execution.ExecutionDisabledError):
                self.read(order)


if __name__ == "__main__":
    unittest.main()
