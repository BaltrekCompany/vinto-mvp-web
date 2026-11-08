"""E2-D2-B1.1: supervised reserve/cancel against disposable PG17 *_test only."""
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app.config import settings
from app.ephemeral_db import connect
from app.work_orders import handoff_service, line_execution
from app.work_orders.errors import (
    WorkOrderHandoffBlockedError, WorkOrderHandoffChangedError,
    WorkOrderHandoffDisabledError, WorkOrderHandoffPendingError, WorkOrderNotFoundError,
)

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = base.build_reference_template("vinto_e2d2b11_tpl")


def tearDownModule():
    template = base.STATE.pop("template", None)
    if template:
        base.drop_database(template)


class ReserveCancelTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        for name in ("work_order_line_execution_enabled",
                     "work_order_reprogram_handoff_enabled"):
            p = patch.object(settings, name, True)
            p.start()
            self.addCleanup(p.stop)

    def reserve(self, order, assignment, version=2, index=0):
        return handoff_service.reserve(
            self.connection, actor_id=self.supervisor,
            work_order_id=order.id, line_code=f"L{index+1}",
            assignment_id=assignment.id, expected_version=version,
            reason="Reserva supervisada de linea sin iniciar", sectors=("BOBINAS",))

    def cancel(self, handoff_id):
        return handoff_service.cancel(
            self.connection, actor_id=self.supervisor_b,
            handoff_id=handoff_id,
            reason="Cancelacion supervisada documentada", sectors=("BOBINAS",))

    def count(self, name):
        return self.scalar("SELECT count(*) FROM "+name)

    def test_reserve_then_cancel_unblocks_start_and_preserves_history(self):
        order = self.same_machine_order(2)
        assigned = self.activate(order, 0).assignment
        reserved = self.reserve(order, assigned)
        self.assertEqual(reserved["status"], "pending")
        self.assertEqual(reserved["prior_assignment_id"], assigned.id)
        self.assertEqual(reserved["expected_version"], 2)

        with self.assertRaises(WorkOrderHandoffPendingError):
            line_execution.start_line(
                self.connection, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", assignment_id=assigned.id, sectors=("BOBINAS",))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s",
            (order.baseline.lines[0].id,)), "enabled")
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s", (assigned.id,)), "active")
        self.assertEqual(self.count("vinto_txn.work_order_version"), 2)

        cancelled = self.cancel(reserved["handoff_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNotNone(cancelled["completed_at"])
        self.assertEqual(self.cancel(reserved["handoff_id"]), cancelled)
        result = line_execution.start_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code="L1", assignment_id=assigned.id, sectors=("BOBINAS",))
        self.assertEqual(result.status, "in_production")

    def test_flag_off_denies_reservation_without_writes(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        with patch.object(settings, "work_order_reprogram_handoff_enabled", False):
            with self.assertRaises(WorkOrderHandoffDisabledError):
                self.reserve(order, assigned)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)

    def test_stale_expected_version_denies_without_writes(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        with self.assertRaises(WorkOrderHandoffChangedError):
            self.reserve(order, assigned, version=15)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)

    def test_wrong_assignment_line_denies_without_writes(self):
        order = self.same_machine_order(2)
        first = self.activate(order, 0).assignment
        self.activate(order, 1)
        with self.assertRaises(WorkOrderHandoffBlockedError):
            self.reserve(order, first, index=1)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)

    def test_started_line_is_never_eligible(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        line_execution.start_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code="L1", assignment_id=assigned.id, sectors=("BOBINAS",))
        with self.assertRaises(WorkOrderHandoffBlockedError):
            self.reserve(order, assigned)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)

    def test_stale_shift_assignment_denied(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        self.patch_now(base.NIGHT)
        with self.assertRaises(WorkOrderHandoffBlockedError):
            self.reserve(order, assigned)

    def test_out_of_scope_is_404(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        with self.assertRaises(WorkOrderNotFoundError):
            handoff_service.reserve(
                self.connection, actor_id=self.supervisor,
                work_order_id=order.id, line_code="L1",
                assignment_id=assigned.id, expected_version=2,
                reason="Reserva fuera del alcance completo",
                sectors=("REBOBINADO",))
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)

    def test_duplicate_reservation_is_denied_with_original_preserved(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        original = self.reserve(order, assigned)
        with self.assertRaises(WorkOrderHandoffPendingError):
            self.reserve(order, assigned)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 1)
        self.assertEqual(self.cancel(original["handoff_id"])["status"], "cancelled")
        self.assertEqual(self.reserve(order, assigned)["status"], "pending")

    def test_db_rejects_forbidden_transition(self):
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        reserved = self.reserve(order, assigned)
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.transaction():
                self.connection.execute(
                    "SELECT set_config('vinto.actor_id',%s,true)", (str(self.supervisor),))
                self.connection.execute(
                    "SELECT set_config('vinto.request_id',%s,true)", (str(uuid4()),))
                self.connection.execute(
                    "SELECT set_config('vinto.reason',%s,true)", ("forged transition",))
                self.connection.execute(
                    "UPDATE vinto_txn.work_order_line_reprogram_handoff SET status='published' WHERE id=%s",
                    (reserved["handoff_id"],))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
            (reserved["handoff_id"],)), "pending")

    def test_cross_assignment_capture_evidence_denies(self):
        # Captures are only possible for started lines; any such historical
        # evidence permanently excludes a logical line from D2.
        order = self.same_machine_order(1)
        assigned = self.activate(order, 0).assignment
        line_execution.start_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code="L1", assignment_id=assigned.id, sectors=("BOBINAS",))
        with self.assertRaises(WorkOrderHandoffBlockedError):
            self.reserve(order, assigned)
        self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)


    def test_reserve_races_with_start_without_deadlock_or_partial_state(self):
        order = self.same_machine_order(1)
        a = self.activate(order, 0).assignment
        barrier = threading.Barrier(2)
        outcomes = [None, None]

        def run(i, action):
            try:
                with connect(self.database) as conn:
                    barrier.wait(timeout=10)
                    action(conn)
                    outcomes[i] = ("ok", None)
            except Exception as err:
                outcomes[i] = ("error", err)

        def reserve(conn):
            return handoff_service.reserve(
                conn, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", assignment_id=a.id, expected_version=2,
                reason="Reserva concurrente supervisada de linea",
                sectors=("BOBINAS",))

        def start(conn):
            return line_execution.start_line(
                conn, actor_id=self.supervisor, work_order_id=order.id,
                line_code="L1", assignment_id=a.id, sectors=("BOBINAS",))

        pair = [
            threading.Thread(target=run, args=(0, reserve), daemon=True),
            threading.Thread(target=run, args=(1, start), daemon=True),
        ]
        for thread in pair:
            thread.start()
        for thread in pair:
            thread.join(timeout=45)
        self.assertFalse(any(thread.is_alive() for thread in pair), "deadlock")
        self.assertEqual(sorted(result[0] for result in outcomes), ["error", "ok"])
        if outcomes[0][0] == "ok":
            self.assertIsInstance(outcomes[1][1], WorkOrderHandoffPendingError)
            self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 1)
            expected = "enabled"
        else:
            self.assertIsInstance(outcomes[0][1], WorkOrderHandoffBlockedError)
            self.assertEqual(self.count("vinto_txn.work_order_line_reprogram_handoff"), 0)
            expected = "in_production"
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s",
            (order.baseline.lines[0].id,)), expected)


if __name__ == "__main__":
    unittest.main()
