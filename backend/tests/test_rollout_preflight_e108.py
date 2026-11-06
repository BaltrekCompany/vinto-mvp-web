"""E1-08 legacy reconciliation diagnostic: ephemeral PG17 database only.

Every diagnostic query must run under SET TRANSACTION READ ONLY. No VPS access.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders import rollout_preflight, line_execution, close_order

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e108diag_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class LegacyRolloutPreflightTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)

    def inspect_read_only(self):
        with self.connection.transaction():
            self.connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            report = rollout_preflight.collect(self.connection)
        return report

    def test_refuses_any_read_write_transaction(self):
        with self.assertRaisesRegex(RuntimeError, "READ ONLY"):
            rollout_preflight.collect(self.connection)

    def test_empty_fixture_has_no_legacy_blockers(self):
        report = self.inspect_read_only()
        self.assertEqual(report["preflight"], "VINTO_E1_08_READ_ONLY")
        self.assertTrue(report["schema"]["migration_0013_recorded"])
        self.assertTrue(report["schema"]["migration_0013_checksum_matches_checkout"])
        self.assertTrue(report["schema"]["execution_table_installed"])
        self.assertTrue(report["schema"]["execution_unique_machine_index"])
        self.assertTrue(report["schema"]["execution_guard_trigger_enabled"])
        self.assertEqual(report["totals"]["assignments_active"], 0)
        self.assertEqual(report["active_by_sector_machine"], [])
        self.assertEqual(report["blockers"], [])
        self.assertTrue(report["technical_preflight_clear"])

    def test_wrong_or_missing_0013_checksum_blocks_flag_go(self):
        with patch.object(rollout_preflight, "_MIGRATION_PATH", Path("/not-installed/migration-0013.sql")):
            report = self.inspect_read_only()
        self.assertFalse(report["schema"]["migration_0013_checksum_matches_checkout"])
        self.assertIn("MIGRATION_0013_CHECKSUM_MISMATCH", report["blockers"])
        self.assertFalse(report["technical_preflight_clear"])

    def test_legacy_active_assignment_is_detected_without_backfilling(self):
        order = self.same_machine_order(2)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            assignment = self.activate(order, 0).assignment
        before = self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution")
        report = self.inspect_read_only()
        self.assertEqual(before, 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution"), 0)
        self.assertEqual(report["totals"]["assignments_active"], 1)
        self.assertEqual(report["schema"]["active_without_execution"], 1)
        self.assertEqual(report["schema"]["lines_in_progress_without_execution"], 2)
        self.assertIn("ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION", report["blockers"])
        self.assertIn("IN_PROGRESS_ORDERS_WITHOUT_EXECUTION", report["blockers"])
        self.assertFalse(report["technical_preflight_clear"])
        self.assertEqual(report["active_by_sector_machine"], [
            {"sector": "BOBINAS", "machine": "MP1",
             "active_assignments": 1, "distinct_orders": 1},
        ])
        result_json = json.dumps(report)
        self.assertNotIn(str(assignment.id), result_json)
        self.assertNotIn(str(order.id), result_json)
        self.assertNotIn(str(self.supervisor), result_json)

    def test_new_enabled_assignment_is_not_mistaken_for_a_legacy_one(self):
        with patch.object(settings, "work_order_line_execution_enabled", True):
            order = self.same_machine_order(1)
            self.activate(order, 0)
            report = self.inspect_read_only()
        self.assertEqual(report["schema"]["active_without_execution"], 0)
        self.assertEqual(report["schema"]["active_enabled"], 1)
        self.assertEqual(report["schema"]["active_in_production"], 0)
        self.assertEqual(report["schema"]["lines_in_progress_without_execution"], 0)
        self.assertEqual(report["blockers"], [])

    def test_finished_and_closed_order_does_not_need_auto_backfill(self):
        with patch.object(settings, "work_order_line_execution_enabled", True):
            order = self.same_machine_order(1)
            activation = self.activate(order, 0).assignment
            line_execution.start_line(
                self.connection, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", assignment_id=activation.id, sectors=("BOBINAS",))
            line_execution.finish_line(
                self.connection, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", sectors=("BOBINAS",))
            close_order.close_work_order(
                self.connection, actor_id=self.supervisor,
                work_order_id=order.id, sectors=("BOBINAS",))
            report = self.inspect_read_only()
        self.assertEqual(report["totals"]["orders_in_progress"], 0)
        self.assertEqual(report["totals"]["assignments_active"], 0)
        self.assertEqual(report["blockers"], [])

    def test_active_legacy_assignment_without_current_shift_still_blocks_rollout(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            self.activate(order, 0)
        with patch.object(base._assignments, "_now", return_value=base.NIGHT):
            report = self.inspect_read_only()
        self.assertIn("ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION", report["blockers"])
        # The diagnostic deliberately does not guess shift resolution or infer
        # that an expired assignment can be promoted into production.
        self.assertFalse(report["technical_preflight_clear"])


if __name__ == "__main__":
    unittest.main()
