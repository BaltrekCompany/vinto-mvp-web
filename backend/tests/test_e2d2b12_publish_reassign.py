"""E2-D2-B1.2: isolated PG17 publication + atomic explicit reassignment.

No production database. The final reassigned state must remain blocked by B0:
operator acknowledgement is deferred to D2-B2.
"""
import unittest
from unittest.mock import patch

from app.config import settings
from app.work_orders import handoff_service, handoff_publication, line_execution
from app.work_orders import reprogramming, service
from app.work_orders.errors import (
    WorkOrderHandoffPendingError, WorkOrderHandoffChangedError,
    WorkOrderHandoffBlockedError,
)
try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE["template"] = base.build_reference_template("vinto_d2b12_tpl")


def tearDownModule():
    template = base.STATE.pop("template", None)
    if template:
        base.drop_database(template)


class PublishReassignTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        for name in ("work_order_line_execution_enabled",
                     "work_order_reprogram_handoff_enabled"):
            p=patch.object(settings,name,True)
            p.start()
            self.addCleanup(p.stop)

    def case(self, lines=1):
        order=self.same_machine_order(lines)
        a=self.activate(order,0).assignment
        h=handoff_service.reserve(
            self.connection,actor_id=self.supervisor,
            work_order_id=order.id,line_code="L1",
            assignment_id=a.id,expected_version=2,
            reason="Reserva previa para reprogramacion supervisada",
            sectors=("BOBINAS",))
        source=self.connection.execute(
            """SELECT l.pv_reference,art.code,l.quantity,l.due_date
               FROM vinto_txn.work_order_version v
               JOIN vinto_txn.work_order_line l ON l.work_order_version_id=v.id
               JOIN vinto_master.article_version av ON av.id=l.article_version_id
               JOIN vinto_master.article art ON art.id=av.article_id
               WHERE v.work_order_id=%s AND v.version_number=2
                 AND l.line_code='L1'""",(order.id,)).fetchone()
        self.assertIsNotNone(source)
        expected=service.LineInput(*source)
        replacement=service.LineInput(source[0]+"-REV",source[1],
                                     source[2]+10,source[3])
        return order,a,h,expected,replacement

    def publish(self,h,expected,replacement):
        return handoff_publication.publish(
            self.connection,actor_id=self.jefatura,
            handoff_id=h["handoff_id"],expected=expected,
            replacement=replacement,
            reason="Jefatura cambia programacion autorizada",
            sectors=("BOBINAS",))

    def reassign(self,h):
        return handoff_publication.reassign(
            self.connection,actor_id=self.supervisor,
            handoff_id=h["handoff_id"],sectors=("BOBINAS",))

    def test_publish_then_explicit_reassign_and_b2_gate(self):
        order,prior,h,expected,new=self.case()
        old_line=self.scalar(
            "SELECT work_order_line_id FROM vinto_txn.assignment WHERE id=%s",(prior.id,))
        result=self.publish(h,expected,new)
        self.assertEqual(result["status"],"published")
        self.assertEqual(result["version_number"],3)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",(prior.id,)),"active")
        self.assertEqual(self.scalar(
            "SELECT work_order_line_id FROM vinto_txn.assignment WHERE id=%s",(prior.id,)),old_line)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s",
            (order.id,)),3)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s",
            (order.baseline.lines[0].id,)),"enabled")
        with self.assertRaises(WorkOrderHandoffPendingError):
            line_execution.start_line(
                self.connection,actor_id=self.supervisor,work_order_id=order.id,
                line_code="L1",assignment_id=prior.id,sectors=("BOBINAS",))

        assignment=self.reassign(h)
        self.assertEqual(assignment["status"],"reassigned")
        new_id=assignment["replacement_assignment_id"]
        self.assertNotEqual(new_id,prior.id)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",(prior.id,)),"finished")
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",(new_id,)),"active")
        self.assertEqual(self.scalar(
            """SELECT v.version_number FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE a.id=%s""",(new_id,)),3)
        self.assertEqual(self.scalar(
            "SELECT work_order_line_id FROM vinto_txn.assignment WHERE id=%s",(prior.id,)),old_line)
        with self.assertRaises(WorkOrderHandoffPendingError):
            line_execution.start_line(
                self.connection,actor_id=self.supervisor,work_order_id=order.id,
                line_code="L1",assignment_id=new_id,sectors=("BOBINAS",))
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
                                     (h["handoff_id"],)),"reassigned")
        with self.assertRaises(WorkOrderHandoffChangedError):
            self.reassign(h)

    def test_stale_expected_fields_rejects_without_writing(self):
        order,prior,h,expected,new=self.case()
        wrong=service.LineInput(expected.pv_reference,expected.article_code,
                                expected.quantity+100,expected.due_date)
        with self.assertRaises(WorkOrderHandoffChangedError):
            self.publish(h,wrong,new)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s",
            (order.id,)),2)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
            (h["handoff_id"],)),"pending")

    def test_reassign_before_publish_rejected(self):
        order,prior,h,expected,new=self.case()
        with self.assertRaises(WorkOrderHandoffChangedError):
            self.reassign(h)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",(prior.id,)),"active")

    def test_other_open_handoff_same_OT_denied(self):
        order,prior,h,expected,new=self.case(lines=2)
        # L2 has its own eligible active assignment; only the OT-wide
        # open-revision invariant prevents a second simultaneous reserve.
        second=self.activate(order,1).assignment
        with self.assertRaises(WorkOrderHandoffPendingError):
            handoff_service.reserve(
                self.connection,actor_id=self.supervisor,work_order_id=order.id,
                line_code="L2",assignment_id=second.id,expected_version=2,
                reason="Otra reserva sobre la misma orden",
                sectors=("BOBINAS",))
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_line_reprogram_handoff"),1)

    def test_previous_published_handoff_cannot_cancel(self):
        order,prior,h,expected,new=self.case()
        self.publish(h,expected,new)
        with self.assertRaises(WorkOrderHandoffBlockedError):
            handoff_service.cancel(
                self.connection,actor_id=self.supervisor,
                handoff_id=h["handoff_id"],
                reason="Cancelar reprogramacion ya publicada",
                sectors=("BOBINAS",))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
            (h["handoff_id"],)),"published")


if __name__=="__main__":
    unittest.main()
