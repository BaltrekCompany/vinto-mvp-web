"""E2-D2-B0: isolated PostgreSQL 17 reservation barriers, never production DB.

B0 has NO writer/API; rows are synthetic fixture inserts by the CI DB owner.
The E2-D2 flag is OFF by default; enabling it in tests exercises all guards.
"""
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import capture_service
from app.assignments import service as assignments
from app.bobbins import service as bobbins
from app.config import settings
from app.work_orders import line_execution
from app.work_orders.errors import WorkOrderHandoffPendingError

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = base.build_reference_template("vinto_e2d2b0_tpl")


def tearDownModule():
    template = base.STATE.pop("template", None)
    if template:
        base.drop_database(template)


class HandoffB0Tests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        p = patch.object(settings, "work_order_line_execution_enabled", True)
        p.start()
        self.addCleanup(p.stop)

    def guard(self, value=True):
        p = patch.object(settings, "work_order_reprogram_handoff_enabled", value)
        p.start()
        self.addCleanup(p.stop)

    def reserve(self, order, assignment, line_index=0, status="pending"):
        baseline = order.baseline.lines[line_index]
        machine_id = self.scalar("SELECT machine_id FROM vinto_txn.assignment WHERE id=%s",
                                 (assignment.id,))
        self.connection.execute(
            "SELECT set_config('vinto.actor_id',%s,false)", (str(self.supervisor),))
        self.connection.execute(
            "SELECT set_config('vinto.request_id',%s,false)", (f"e2d2b0-fixture:{uuid4()}",))
        self.connection.execute(
            "SELECT set_config('vinto.reason',%s,false)", ("synthetic reservation in isolated DB",))
        return self.connection.execute(
            """INSERT INTO vinto_txn.work_order_line_reprogram_handoff
               (work_order_id,baseline_line_id,machine_id,prior_assignment_id,
                expected_version_number,status,requested_by,reason)
               VALUES (%s,%s,%s,%s,2,%s,%s,%s) RETURNING id""",
            (order.id, baseline.id, machine_id, assignment.id, status,
             self.supervisor, "Synthetic pre-start handoff fixture")
        ).fetchone()[0]

    def count(self, table):
        return self.scalar("SELECT count(*) FROM " + table)

    def test_schema_empty_and_off_by_default(self):
        self.assertFalse(settings.work_order_reprogram_handoff_enabled)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)

    def test_pending_blocks_start_without_e1_change(self):
        self.guard()
        order = self.same_machine_order(1)
        assignment = self.activate(order, 0).assignment
        self.reserve(order, assignment)
        with self.assertRaises(WorkOrderHandoffPendingError):
            line_execution.start_line(
                self.connection, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", assignment_id=assignment.id, sectors=("BOBINAS",))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s",
            (order.baseline.lines[0].id,)), "enabled")
        self.assertEqual(self.count("vinto_txn.capture"), 0)

    def test_pending_blocks_finish_and_same_line_activation(self):
        self.guard()
        order = self.same_machine_order(1)
        a = self.activate(order, 0).assignment
        self.reserve(order, a)
        with self.assertRaises(WorkOrderHandoffPendingError):
            assignments.finish(
                self.connection, actor_id=self.supervisor,
                assignment_id=a.id, sectors=("BOBINAS",))
        with self.assertRaises(WorkOrderHandoffPendingError):
            self.activate(order, 0)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s", (a.id,)), "active")

    def test_other_line_shift_change_cannot_implicitly_finish_reserved(self):
        self.guard()
        order = self.same_machine_order(2)
        first = self.activate(order, 0).assignment
        self.reserve(order, first)
        self.patch_now(base.NIGHT)
        with self.assertRaises(WorkOrderHandoffPendingError):
            self.activate(order, 1)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",
            (first.id,)), "active")
        self.assertEqual(self.count("vinto_txn.assignment"), 1)

    def test_pending_blocks_both_f3_and_f6_capture_paths(self):
        self.guard()
        with patch.object(capture_service, "_now", return_value=base.DAY):
            order = self.same_machine_order(1)
            a = self.activate(order, 0).assignment
            line_execution.start_line(
                self.connection, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", assignment_id=a.id, sectors=("BOBINAS",))
            # B1.1 now forbids any impossible pending reservation for a line
            # already producing. Inject the guard exception at the service
            # seam to verify both F3 and F6 call it before any data writes.
            with patch("app.work_orders.handoff_guard.require_assignment_unreserved",
                       side_effect=WorkOrderHandoffPendingError()):
                with self.assertRaises(WorkOrderHandoffPendingError):
                    capture_service.submit_production_capture(
                        self.connection, actor_id=self.jefatura, capture_id=uuid4(),
                        form_code="VINTO-P1-06", assignment_id=a.id,
                        device_key=str(uuid4()), sectors=("BOBINAS",),
                        values={"cantidad_fardos": 10, "punto_merma": "recorte_maquina",
                                "tipo_producto": "hoja_doble", "peso_kg": "125.50"})
                with self.assertRaises(WorkOrderHandoffPendingError):
                    bobbins.submit_bobbin_production(
                        self.connection, actor_id=self.jefatura, capture_id=uuid4(),
                        assignment_id=a.id, device_key=str(uuid4()),
                        sectors=("BOBINAS",),
                        values={"hora_inicio": "07:15", "hora_fin": "08:40",
                                "diametro": "1200.5", "peso_kg": "845.25",
                                "numero_de_cortes": "3"})
        self.assertEqual(self.count("vinto_txn.capture"), 0)
        self.assertEqual(self.count("vinto_txn.bobbin"), 0)
        self.assertEqual(self.count("vinto_txn.bobbin_sequence"), 0)

    def test_flag_off_retains_existing_start_semantics(self):
        self.guard(False)
        order = self.same_machine_order(1)
        a = self.activate(order, 0).assignment
        self.reserve(order, a)
        result = line_execution.start_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code="L1", assignment_id=a.id, sectors=("BOBINAS",))
        self.assertEqual(result.status, "in_production")

    def test_unique_open_reservation_per_baseline(self):
        self.guard()
        order = self.same_machine_order(1)
        a = self.activate(order, 0).assignment
        self.reserve(order, a)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.connection.transaction():
                self.reserve(order, a)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 1)

    def test_cancelled_reservation_no_longer_blocks(self):
        self.guard()
        order = self.same_machine_order(1)
        a = self.activate(order, 0).assignment
        row_id = self.reserve(order, a)
        self.connection.execute(
            "UPDATE vinto_txn.work_order_line_reprogram_handoff SET status='cancelled',completed_at=clock_timestamp() WHERE id=%s",
            (row_id,))
        result = line_execution.start_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code="L1", assignment_id=a.id, sectors=("BOBINAS",))
        self.assertEqual(result.status, "in_production")

    def test_no_writer_permission_is_planned_until_b1(self):
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)
        # Tests run on latest schema. B1.1 deliberately grants INSERT and
        # narrow column UPDATE, still never DELETE. Check B1's least privilege.
        exists = self.scalar("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app')")
        if exists:
            self.assertTrue(self.scalar(
                "SELECT has_table_privilege('vinto_app','vinto_txn.work_order_line_reprogram_handoff','SELECT')"))
            self.assertTrue(self.scalar(
                "SELECT has_table_privilege('vinto_app','vinto_txn.work_order_line_reprogram_handoff','INSERT')"))
            self.assertTrue(self.scalar(
                "SELECT has_column_privilege('vinto_app','vinto_txn.work_order_line_reprogram_handoff','status','UPDATE')"))
            self.assertFalse(self.scalar(
                "SELECT has_column_privilege('vinto_app','vinto_txn.work_order_line_reprogram_handoff','reason','UPDATE')"))
            self.assertFalse(self.scalar(
                "SELECT has_table_privilege('vinto_app','vinto_txn.work_order_line_reprogram_handoff','DELETE')"))


if __name__ == "__main__":
    unittest.main()
