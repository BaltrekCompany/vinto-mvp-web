"""E1-04: F3/F6 new captures require an explicitly started logical line.

All tests use disposable PostgreSQL *_test databases; no production access.
"""
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import capture_service
from app.bobbins import service as bobbins
from app.capture_errors import AssignmentNotActiveError, LineNotInProductionError
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.work_orders import line_execution

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


F6_VALUES = {
    "cantidad_fardos": 10, "punto_merma": "recorte_maquina",
    "tipo_producto": "hoja_doble", "peso_kg": "125.50",
}
F3_VALUES = {
    "hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5",
    "peso_kg": "845.25", "numero_de_cortes": "3",
}


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e104_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class CaptureExecutionCase(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        enable = patch.object(settings, "work_order_line_execution_enabled", True)
        enable.start()
        self.addCleanup(enable.stop)
        capture_time = patch.object(capture_service, "_now", return_value=base.DAY)
        capture_time.start()
        self.addCleanup(capture_time.stop)

    def start(self, order, line, assignment):
        return line_execution.start_line(
            self.connection, actor_id=self.supervisor, work_order_id=order.id,
            line_code=line, assignment_id=assignment.id, sectors=("BOBINAS",))

    def finish(self, order, line, connection=None):
        return line_execution.finish_line(
            connection or self.connection, actor_id=self.supervisor,
            work_order_id=order.id, line_code=line, sectors=("BOBINAS",))

    def f6(self, assignment, capture_id=None, connection=None):
        return capture_service.submit_production_capture(
            connection or self.connection, actor_id=self.jefatura,
            capture_id=capture_id or uuid4(), form_code="VINTO-P1-06",
            assignment_id=assignment.id, device_key=str(self.device),
            values=F6_VALUES, sectors=("BOBINAS",))

    def f3(self, assignment, capture_id=None, connection=None):
        return bobbins.submit_bobbin_production(
            connection or self.connection, actor_id=self.jefatura,
            capture_id=capture_id or uuid4(), assignment_id=assignment.id,
            device_key=str(self.device), values=F3_VALUES, sectors=("BOBINAS",))

    @property
    def device(self):
        if not hasattr(self, "_device"):
            self._device = uuid4()
        return self._device

    def count(self, table):
        return self.scalar("SELECT count(*) FROM " + table)

    def test_f6_only_accepts_started_line(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        with self.assertRaises(LineNotInProductionError):
            self.f6(first)
        self.assertEqual(self.count("vinto_txn.capture"), 0)
        self.start(order, "L1", first)
        saved = self.f6(first)
        self.assertTrue(saved.created)
        with self.assertRaises(LineNotInProductionError):
            self.f6(second)
        self.assertEqual(self.count("vinto_txn.capture"), 1)
        self.finish(order, "L1")
        with self.assertRaises(AssignmentNotActiveError):
            self.f6(first)
        self.assertEqual(self.count("vinto_txn.capture"), 1)

    def test_f3_blocks_unstarted_line_without_bobbin_counter_side_effect(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        with self.assertRaises(LineNotInProductionError):
            self.f3(first)
        self.assertEqual(self.count("vinto_txn.bobbin"), 0)
        self.assertEqual(self.count("vinto_txn.bobbin_sequence"), 0)
        self.start(order, "L1", first)
        saved = self.f3(first)
        self.assertTrue(saved.created)
        with self.assertRaises(LineNotInProductionError):
            self.f3(second)
        self.assertEqual(self.count("vinto_txn.bobbin"), 1)
        self.assertEqual(self.count("vinto_txn.bobbin_sequence"), 1)

    def test_historical_f3_f6_retry_is_idempotent_after_line_finishes(self):
        order = self.same_machine_order(1)
        assignment = self.activate(order, 0).assignment
        self.start(order, "L1", assignment)
        capture_f3, capture_f6 = uuid4(), uuid4()
        f3 = self.f3(assignment, capture_id=capture_f3)
        f6 = self.f6(assignment, capture_id=capture_f6)
        self.finish(order, "L1")
        assert self.f3(assignment, capture_id=capture_f3).already_submitted
        assert self.f6(assignment, capture_id=capture_f6).already_submitted
        self.assertEqual(self.count("vinto_txn.capture"), 2)
        self.assertEqual(self.count("vinto_txn.bobbin"), 1)
        self.assertEqual(f3.capture.id, capture_f3)
        self.assertEqual(f6.capture.id, capture_f6)

    def test_legacy_active_assignment_without_execution_is_rejected(self):
        order = self.same_machine_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            assignment = self.activate(order, 0).assignment
        self.assertEqual(self.count("vinto_txn.work_order_line_execution"), 0)
        with self.assertRaises(LineNotInProductionError):
            self.f6(assignment)
        with self.assertRaises(LineNotInProductionError):
            self.f3(assignment)
        self.assertEqual(self.count("vinto_txn.capture"), 0)

    def test_old_behaviour_is_intact_when_flag_off(self):
        order = self.same_machine_order(1)
        assignment = self.activate(order, 0).assignment
        with patch.object(settings, "work_order_line_execution_enabled", False):
            self.assertTrue(self.f6(assignment).created)
            self.assertTrue(self.f3(assignment).created)
        self.assertEqual(self.count("vinto_txn.capture"), 2)

    def test_capture_and_finish_race_cannot_write_after_finish(self):
        order = self.same_machine_order(1)
        assignment = self.activate(order, 0).assignment
        self.start(order, "L1", assignment)
        barrier = threading.Barrier(2)
        results = [None, None]

        def capture():
            try:
                with connect(self.database) as c:
                    barrier.wait(timeout=15)
                    self.f6(assignment, connection=c)
                results[0] = "captured"
            except AssignmentNotActiveError:
                results[0] = "blocked"
            except Exception as error:
                results[0] = f"unexpected: {error}"

        def finish():
            try:
                with connect(self.database) as c:
                    barrier.wait(timeout=15)
                    self.finish(order, "L1", connection=c)
                results[1] = "finished"
            except Exception as error:
                results[1] = f"unexpected: {error}"

        threads = [threading.Thread(target=capture), threading.Thread(target=finish)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)
        self.assertIn(results[0], ("captured", "blocked"), results)
        self.assertEqual(results[1], "finished", results)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE work_order_id=%s",
            (order.id,)), "finished")
        self.assertLessEqual(self.count("vinto_txn.capture"), 1)


if __name__ == "__main__":
    unittest.main()
