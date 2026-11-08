"""E2-D0: read-only PG17 census on disposable *_test databases only."""
import json
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders import e2d_readiness, line_execution

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e2d0diag_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class E2DReadinessTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)

    def read_only(self):
        with self.connection.transaction():
            self.connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return e2d_readiness.collect(self.connection)

    def bucket(self, report, status, code):
        return sum(r["baseline_lines"] for r in report["groups"]
                   if r["order_status"] == status and r["risk_bucket"] == code)

    def test_refuses_any_writable_or_wrong_isolation_transaction(self):
        with self.assertRaisesRegex(RuntimeError, "READ ONLY"):
            e2d_readiness.collect(self.connection)
        with self.connection.transaction():
            self.connection.execute("SET TRANSACTION READ ONLY")
            with self.assertRaisesRegex(RuntimeError, "READ ONLY"):
                e2d_readiness.collect(self.connection)

    def test_empty_is_counts_only_and_not_a_permission_to_reprogram(self):
        report = self.read_only()
        self.assertEqual(report["groups"], [])
        self.assertEqual(report["totals"]["baseline_lines_inspected"], 0)
        self.assertEqual(report["preflight"], "VINTO_E2D0_READ_ONLY")
        self.assertIs(report["operational_go"], False)
        self.assertIs(report["production_write_authorized"], False)

    def test_published_without_assignment_is_not_marked_in_production(self):
        order = self.same_machine_order(2)
        report = self.read_only()
        self.assertEqual(self.bucket(report, "published", "UNASSIGNED_NO_EXECUTION_EVIDENCE"), 2)
        self.assertEqual(report["totals"]["unassigned_lines_of_in_progress_ots"], 0)
        text = json.dumps(report)
        self.assertNotIn(str(order.id), text)
        self.assertNotIn(str(self.jefatura), text)
        for item in order.baseline.lines:
            self.assertNotIn(str(item.id), text)

    def test_running_other_line_does_not_make_untouched_line_produced(self):
        with patch.object(settings, "work_order_line_execution_enabled", True):
            order = self.same_machine_order(2)
            assigned = self.activate(order, 0).assignment
            report = self.read_only()
            self.assertEqual(self.bucket(report, "in_progress", "ASSIGNED_OR_ENABLED_NOT_STARTED"), 1)
            self.assertEqual(self.bucket(report, "in_progress", "UNASSIGNED_NO_EXECUTION_EVIDENCE"), 1)
            self.assertEqual(report["totals"]["unassigned_lines_of_in_progress_ots"], 1)
            self.assertEqual(report["totals"]["currently_in_production"], 0)
            line_execution.start_line(
                self.connection, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", assignment_id=assigned.id, sectors=("BOBINAS",))
            started = self.read_only()
            self.assertEqual(self.bucket(started, "in_progress", "PRODUCTION_OR_CAPTURE_HISTORY"), 1)
            self.assertEqual(started["totals"]["currently_in_production"], 1)
            self.assertEqual(started["totals"]["unassigned_lines_of_in_progress_ots"], 1)
            self.assertIs(started["operational_go"], False)

    def test_legacy_assignment_without_e1_is_not_silently_safe(self):
        with patch.object(settings, "work_order_line_execution_enabled", False):
            order = self.same_machine_order(1)
            assignment = self.activate(order, 0).assignment
        report = self.read_only()
        self.assertEqual(self.bucket(report, "in_progress", "LEGACY_ACTIVE_UNRECONCILED"), 1)
        self.assertEqual(report["totals"]["legacy_unreconciled"], 1)
        self.assertNotIn(str(assignment.id), json.dumps(report))


if __name__ == "__main__":
    unittest.main()
