"""E1-10 tests: ephemeral PostgreSQL ONLY. No production access, no real OT."""
import os
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders import rollout_preflight, service as orders
from app.work_orders.errors import WorkOrderArchiveBlockedError
from app.work_orders.qa_retirement_cli import RetirementBlocked, _apply, _snapshot

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e110_retirement_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class QARetirementTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)

    def manifest(self, order, *, lines=2, active=1):
        return {
            "order_numbers": [order.number],
            "expected_orders": 1,
            "expected_baseline_lines": lines,
            "expected_active_assignments": active,
            "actor_id": self.jefatura,
            "reason": "Retiro autorizado de OT ficticia para QA E1-10",
        }

    def preflight(self):
        with self.connection.transaction():
            self.connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            return rollout_preflight.collect(self.connection)

    def commit_retirement(self, doc):
        with patch.object(settings, "work_order_line_execution_enabled", False):
            with patch.dict(os.environ, {
                "VINTO_QA_RETIREMENT_CONFIRMED": "yes",
                "VINTO_QA_BACKUP_VERIFIED": "yes",
                "VINTO_QA_OFFHOST_VERIFIED": "yes",
            }):
                return _apply(self.connection, doc)

    def test_retirement_preserves_history_and_clears_preflight(self):
        order = self.same_machine_order(2)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            assignment = self.activate(order, 0).assignment
        before = {
            table: self.scalar(f"SELECT count(*) FROM vinto_txn.{table}")
            for table in ("work_order", "work_order_version", "work_order_line",
                          "assignment", "capture")
        }
        report = self.preflight()
        self.assertIn("ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION", report["blockers"])
        self.assertIn("IN_PROGRESS_ORDERS_WITHOUT_EXECUTION", report["blockers"])

        doc = self.manifest(order)
        _, active_ids, snapshot = _snapshot(self.connection, doc, lock=False)
        self.assertEqual(len(active_ids), 1)
        self.assertEqual(snapshot["baseline_lines"], 2)

        result = self.commit_retirement(doc)
        self.assertEqual(result["active_assignments"], 1)
        row = self.connection.execute("""
            SELECT status, qa_retired, archived_at, archived_reason
            FROM vinto_txn.work_order WHERE id=%s
        """, (order.id,)).fetchone()
        self.assertEqual(row[0], "in_progress")
        self.assertTrue(row[1])
        self.assertIsNotNone(row[2])
        self.assertEqual(row[3], doc["reason"])
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",
            (assignment.id,),
        ), "finished")
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_line_execution "
            "WHERE work_order_id=%s", (order.id,)
        ), 0)
        self.assertEqual({
            table: self.scalar(f"SELECT count(*) FROM vinto_txn.{table}")
            for table in before
        }, before)

        self.assertFalse(any(o.id == order.id for o in orders.list_work_orders(
            self.connection, sectors=("BOBINAS",))))
        self.assertTrue(any(o.id == order.id for o in orders.list_work_orders(
            self.connection, sectors=("BOBINAS",), archived=True)))
        with self.assertRaises(WorkOrderArchiveBlockedError):
            orders.restore_work_order(
                self.connection, actor_id=self.jefatura,
                work_order_id=order.id, sectors=("BOBINAS",))

        report = self.preflight()
        self.assertTrue(report["technical_preflight_clear"])
        self.assertEqual(report["totals"]["qa_retired_orders"], 1)
        self.assertEqual(report["totals"]["qa_retired_active_assignments"], 0)
        self.assertEqual(report["totals"]["orders_in_progress"], 0)
        self.assertEqual(report["schema"]["lines_in_progress_without_execution"], 0)
        self.assertEqual(report["schema"]["active_without_execution"], 0)

    def test_manifest_drift_refuses_without_partial_updates(self):
        order = self.same_machine_order(2)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            assignment = self.activate(order, 0).assignment
        doc = self.manifest(order, lines=999)
        with self.assertRaises(RetirementBlocked):
            self.commit_retirement(doc)
        self.assertFalse(self.scalar(
            "SELECT qa_retired FROM vinto_txn.work_order WHERE id=%s",
            (order.id,)))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",
            (assignment.id,)), "active")

    def test_feature_flag_must_be_off_and_backup_attested(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            self.activate(order, 0)
        doc = self.manifest(order, lines=1)
        with patch.object(settings, "work_order_line_execution_enabled", True):
            with self.assertRaises(RetirementBlocked):
                _apply(self.connection, doc)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RetirementBlocked):
                    _apply(self.connection, doc)
        self.assertFalse(self.scalar(
            "SELECT qa_retired FROM vinto_txn.work_order WHERE id=%s",
            (order.id,)))

    def test_normal_archive_contract_still_rejects_in_progress(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            self.activate(order, 0)
        with self.assertRaises(WorkOrderArchiveBlockedError):
            orders.archive_work_order(
                self.connection, actor_id=self.jefatura,
                work_order_id=order.id,
                reason="Prueba que el archivo normal siga protegido",
                sectors=("BOBINAS",))


if __name__ == "__main__":
    unittest.main()
