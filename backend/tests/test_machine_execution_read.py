"""E1-06: machine-scoped production state for Operación, PostgreSQL 17 only."""
import unittest
from unittest.mock import patch

from app.assignments import execution_read
from app.work_orders.errors import MachineOutsideScopeError
from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders import line_execution

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e106_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class MachineExecutionReadTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        flag = patch.object(settings, "work_order_line_execution_enabled", True)
        flag.start()
        self.addCleanup(flag.stop)

    def read(self, machine="MP1", scope=("MP1",)):
        return execution_read.read_machine_execution(
            self.connection, machine_code=machine, sectors=("BOBINAS",),
            machine_codes=set(scope))

    def start(self, order, code, assignment):
        return line_execution.start_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code=code, assignment_id=assignment.id, sectors=("BOBINAS",))

    def finish(self, order, code):
        return line_execution.finish_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code=code, sectors=("BOBINAS",))

    def test_enabled_lines_are_not_marked_as_producing(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        result = self.read()
        self.assertIs(result["line_execution"], True)
        self.assertEqual(result["assignments"], [
            {"assignment_id": first.id, "status": "enabled"},
            {"assignment_id": second.id, "status": "enabled"},
        ])

    def test_only_started_line_is_producing_and_finished_line_disappears(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        self.start(order, "L1", first)
        snapshot = {x["assignment_id"]: x["status"] for x in self.read()["assignments"]}
        self.assertEqual(snapshot, {first.id: "in_production", second.id: "enabled"})
        self.finish(order, "L1")
        self.assertEqual(self.read()["assignments"], [
            {"assignment_id": second.id, "status": "enabled"}])
        self.start(order, "L2", second)
        self.assertEqual(self.read()["assignments"][0]["status"], "in_production")

    def test_old_active_assignment_requires_review(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            old = self.activate(order, 0).assignment
        self.assertEqual(self.read()["assignments"],
                         [{"assignment_id": old.id, "status": "requires_review"}])

    def test_flag_off_keeps_legacy_without_looking_up_execution(self):
        order = self.same_machine_order(1)
        self.activate(order, 0)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            self.assertEqual(self.read(), {"line_execution": False, "assignments": []})

    def test_scope_is_checked_by_authoritative_assignment_query(self):
        order = self.same_machine_order(1)
        self.activate(order, 0)
        with self.assertRaises(MachineOutsideScopeError):
            self.read(scope=("MP3",))
        with self.assertRaises(MachineOutsideScopeError):
            self.read(machine="MP3", scope=("MP1",))
        self.assertEqual(len(self.read()["assignments"]), 1)

    def test_active_assignment_from_previous_shift_is_not_silently_promoted(self):
        order = self.same_machine_order(1)
        a = self.activate(order, 0).assignment
        self.start(order, "L1", a)
        with patch.object(base._assignments, "_now", return_value=base.NIGHT):
            # Old assignment remains mapped to the logical execution but its
            # stale flag still comes from /active-lines and blocks UI capture.
            self.assertEqual(self.read()["assignments"][0]["status"], "in_production")
            active = base.service.get_active_lines(
                self.connection, machine_code="MP1", sectors=("BOBINAS",),
                machine_codes={"MP1"})
            self.assertIs(active.items[0].stale, True)

    def test_no_assignments_has_no_invented_product(self):
        self.assertEqual(self.read(), {"line_execution": True, "assignments": []})


if __name__ == "__main__":
    unittest.main()
