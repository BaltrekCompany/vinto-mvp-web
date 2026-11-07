"""E1-10 tests: ephemeral PostgreSQL ONLY. No production access, no real OT."""
import os
import unittest

import psycopg
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


    def synthetic_batch_13_18_9(self):
        """Mirror the VPS shape: 13 in-progress OTs, 18 baseline lines, 9 active
        assignments spread over 8 OTs, and 5 OTs without active assignments.
        Uses only ephemeral PG17 fixture data, never production identifiers.
        """
        bobinas_sector = self.scalar(
            "SELECT id FROM vinto_master.sector WHERE code='BOBINAS'"
        )
        for n in range(1, 7):
            code = f"QA-E110-{n}"
            self.connection.execute(
                "INSERT INTO vinto_master.machine (sector_id, code, name) "
                "VALUES (%s, %s, %s)", (bobinas_sector, code, code)
            )
            self.connection.execute("""
                INSERT INTO vinto_master.article_machine (article_id, machine_id)
                SELECT a.id, m.id FROM vinto_master.article a
                CROSS JOIN vinto_master.machine m
                WHERE a.code=%s AND m.code=%s
            """, (base.MP1_CODES[0], code))

        # 10 single-line OT plus 2/4/2 lines = 18 baseline lines.
        line_counts = [1] * 10 + [2, 4, 2]
        active_machines = {
            3: "MP1", 4: "MP3", 5: "QA-E110-1",
            6: "QA-E110-2", 7: "QA-E110-3",
            8: "QA-E110-4", 9: "QA-E110-5",
            12: "QA-E110-6",
        }
        orders = []
        for index, count in enumerate(line_counts):
            machine = active_machines.get(index, "MP1")
            article = base.MP3_CODES[0] if machine == "MP3" else base.MP1_CODES[0]
            rows = [
                base.line(article, pv=f"PV-QA-{index}-{line_index}")
                for line_index in range(count)
            ]
            orders.append(self.order(rows, machine=machine))

        with patch.object(settings, "work_order_line_execution_enabled", False):
            # Historical QA finished shifts: 5 in-progress OTs, zero active.
            for index in (0, 1, 2, 10, 11):
                assignment = self.activate(orders[index], 0).assignment
                base.service.finish(
                    self.connection, actor_id=self.supervisor,
                    assignment_id=assignment.id, sectors=("BOBINAS",)
                )
            # Eight in-progress OTs own 9 active assignments (last has 2).
            for index in sorted(active_machines):
                self.activate(orders[index], 0)
                if index == 12:
                    self.activate(orders[index], 1)

        doc = {
            "order_numbers": sorted(o.number for o in orders),
            "expected_orders": 13,
            "expected_baseline_lines": 18,
            "expected_active_assignments": 9,
            "actor_id": self.jefatura,
            "reason": "Retiro QA de 13 OT ficticias verificadas, lote atomico E1-10",
        }
        return orders, doc

    def test_exact_13_18_9_batch_is_atomic_and_preserves_unrelated_order(self):
        orders, doc = self.synthetic_batch_13_18_9()
        outsider = self.same_machine_order(1)  # published, not part of manifest
        before = {
            table: self.scalar(f"SELECT count(*) FROM vinto_txn.{table}")
            for table in (
                "work_order", "work_order_version", "work_order_line",
                "assignment", "capture"
            )
        }
        initial = self.preflight()
        self.assertEqual(initial["schema"]["lines_in_progress_without_execution"], 18)
        self.assertEqual(initial["schema"]["active_without_execution"], 9)
        self.assertFalse(initial["technical_preflight_clear"])

        _, assignment_ids, snapshot = _snapshot(self.connection, doc, lock=False)
        self.assertEqual((snapshot["orders"], snapshot["baseline_lines"],
                          snapshot["active_assignments"]), (13, 18, 9))
        self.assertEqual(len(assignment_ids), 9)
        result = self.commit_retirement(doc)
        self.assertEqual(result["active_assignments"], 9)

        self.assertEqual(self.scalar("""
            SELECT count(*) FROM vinto_txn.work_order
            WHERE id=ANY(%s) AND status='in_progress'
              AND qa_retired AND archived_at IS NOT NULL
        """, ([o.id for o in orders],)), 13)
        self.assertEqual(self.scalar("""
            SELECT count(*) FROM vinto_txn.assignment
            WHERE id=ANY(%s) AND status='finished'
              AND finished_at IS NOT NULL
        """, (assignment_ids,)), 9)
        self.assertEqual(self.scalar("""
            SELECT count(*) FROM vinto_txn.assignment
            WHERE id=ANY(%s) AND status='active'
        """, (assignment_ids,)), 0)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order WHERE id=%s",
            (outsider.id,)
        ), "published")
        self.assertEqual(self.scalar(
            "SELECT archived_at IS NULL AND NOT qa_retired "
            "FROM vinto_txn.work_order WHERE id=%s", (outsider.id,)
        ), True)
        self.assertEqual(before, {
            table: self.scalar(f"SELECT count(*) FROM vinto_txn.{table}")
            for table in before
        })
        final = self.preflight()
        self.assertTrue(final["technical_preflight_clear"])
        self.assertEqual(final["totals"]["qa_retired_orders"], 13)
        self.assertEqual(final["totals"]["qa_retired_active_assignments"], 0)
        self.assertEqual(final["schema"]["lines_in_progress_without_execution"], 0)

    def test_late_database_failure_rolls_back_every_order_and_assignment(self):
        first = self.same_machine_order(1, machine="MP1")
        second = self.same_machine_order(1, machine="MP3")
        with patch.object(settings, "work_order_line_execution_enabled", False):
            a1 = self.activate(first, 0).assignment
            a2 = self.activate(second, 0).assignment
        doc = {
            "order_numbers": sorted((first.number, second.number)),
            "expected_orders": 2,
            "expected_baseline_lines": 2,
            "expected_active_assignments": 2,
            "actor_id": self.jefatura,
            "reason": "Prueba forzada de rollback transaccional de retiro E1-10",
        }
        # Deliberately fail AFTER the CLI finishes assignments, while it
        # attempts to archive. A complete rollback must restore both phases.
        self.connection.execute("""
            CREATE FUNCTION vinto_txn.e110_force_abort_test()
            RETURNS trigger LANGUAGE plpgsql AS $e110$
            BEGIN
                IF NEW.qa_retired THEN
                    RAISE EXCEPTION 'synthetic E1-10 rollback test'
                        USING ERRCODE='23514';
                END IF;
                RETURN NEW;
            END; $e110$;
        """)
        self.connection.execute("""
            CREATE TRIGGER z_e110_force_abort_test
            BEFORE UPDATE ON vinto_txn.work_order
            FOR EACH ROW EXECUTE FUNCTION vinto_txn.e110_force_abort_test()
        """)
        before_audit = self.scalar(
            "SELECT count(*) FROM vinto_audit.audit_event"
        )
        with self.assertRaises(psycopg.Error):
            self.commit_retirement(doc)
        self.assertEqual(self.scalar("""
            SELECT count(*) FROM vinto_txn.work_order
            WHERE id=ANY(%s) AND (qa_retired OR archived_at IS NOT NULL)
        """, ([first.id, second.id],)), 0)
        self.assertEqual(self.scalar("""
            SELECT count(*) FROM vinto_txn.assignment
            WHERE id=ANY(%s) AND status='active' AND finished_at IS NULL
        """, ([a1.id, a2.id],)), 2)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_audit.audit_event"
        ), before_audit)


if __name__ == "__main__":
    unittest.main()
