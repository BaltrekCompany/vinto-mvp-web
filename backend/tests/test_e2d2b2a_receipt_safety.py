"""E2-D2-B2-A: operator's exact E2-C1 receipt completes D2, PG17 only.

Release/flag remains OFF. This test uses disposable DB clones; never VPS.
"""
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app.assignments import revision_notices
from app.assignments.errors import RevisionNoticeConflictError, AssignmentNotFoundError
from app.config import settings
from app.work_orders import line_execution
from app.work_orders.errors import WorkOrderHandoffPendingError

try:
    import test_e2d2b12_publish_reassign as previous
except ModuleNotFoundError:
    from tests import test_e2d2b12_publish_reassign as previous


def setUpModule():
    previous.base.STATE["template"] = previous.base.build_reference_template(
        "vinto_e2d2b2a_tpl")


def tearDownModule():
    template=previous.base.STATE.pop("template",None)
    if template:
        previous.base.drop_database(template)


class ReceiptAndFlagSafetyTests(previous.PublishReassignTests):
    """Inherits the B1.2 scenario regressions on the expanded schema."""

    def flow(self):
        order,prior,h,expected,new=self.case()
        pub=self.publish(h,expected,new)
        swap=self.reassign(h)
        self.assertEqual(pub["version_number"],swap["version_number"])
        return order,prior,h,pub,swap

    def operator_receipt(self,assignment,version,actor):
        return revision_notices.acknowledge_revision(
            self.connection,actor_id=actor,
            assignment_id=assignment,expected_version=version,
            sectors=("BOBINAS",),machine_codes=("MP1",),
            request_id=str(uuid4()))

    def test_operator_receipt_closes_handoff_then_supervisor_can_start(self):
        order,prior,h,pub,swap=self.flow()
        new_assignment=swap["replacement_assignment_id"]
        actor=self.make_user("OPERACION")
        notices=revision_notices.list_revision_notices(
            self.connection,user_id=actor,sectors=("BOBINAS",),
            machine_codes=("MP1",))
        matching=[n for n in notices if n["assignment_id"]==new_assignment]
        self.assertEqual(len(matching),1)
        self.assertIsNone(matching[0]["acknowledged_at"])

        with self.assertRaises(WorkOrderHandoffPendingError):
            line_execution.start_line(
                self.connection,actor_id=self.supervisor,work_order_id=order.id,
                line_code="L1",assignment_id=new_assignment,sectors=("BOBINAS",))

        receipt=self.operator_receipt(new_assignment,3,actor)
        self.assertEqual(receipt["assignment_id"],new_assignment)
        self.assertEqual(receipt["version_number"],3)
        state=self.connection.execute(
            """SELECT status,completed_at FROM
               vinto_txn.work_order_line_reprogram_handoff WHERE id=%s""",
            (h["handoff_id"],)).fetchone()
        self.assertEqual(state[0],"acknowledged")
        self.assertIsNotNone(state[1])
        first_receipt=receipt["acknowledged_at"]
        repeat=self.operator_receipt(new_assignment,3,actor)
        self.assertEqual(repeat["acknowledged_at"],first_receipt)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_revision_receipt WHERE assignment_id=%s AND user_id=%s",
            (new_assignment,actor)),1)
        result=line_execution.start_line(
            self.connection,actor_id=self.supervisor,work_order_id=order.id,
            line_code="L1",assignment_id=new_assignment,sectors=("BOBINAS",))
        self.assertEqual(result.status,"in_production")
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",(prior.id,)),"finished")

    def test_wrong_version_and_scope_cannot_ack_or_complete(self):
        order,prior,h,pub,swap=self.flow()
        new=swap["replacement_assignment_id"]
        actor=self.make_user("OPERACION")
        with self.assertRaises(RevisionNoticeConflictError):
            self.operator_receipt(new,2,actor)
        with self.assertRaises(AssignmentNotFoundError):
            revision_notices.acknowledge_revision(
                self.connection,actor_id=actor,
                assignment_id=new,expected_version=3,
                sectors=("REBOBINADO",),machine_codes=("MP1",),
                request_id=str(uuid4()))
        with self.assertRaises(AssignmentNotFoundError):
            revision_notices.acknowledge_revision(
                self.connection,actor_id=actor,
                assignment_id=new,expected_version=3,
                sectors=("BOBINAS",),machine_codes=("MP3",),
                request_id=str(uuid4()))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
            (h["handoff_id"],)),"reassigned")
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_revision_receipt WHERE assignment_id=%s",
            (new,)),0)

    def test_database_refuses_forged_completion_without_operator_receipt(self):
        order,prior,h,pub,swap=self.flow()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.transaction():
                self.connection.execute(
                    "SELECT set_config('vinto.actor_id',%s,true)",
                    (str(self.supervisor),))
                self.connection.execute(
                    "SELECT set_config('vinto.request_id',%s,true)",(str(uuid4()),))
                self.connection.execute(
                    "SELECT set_config('vinto.reason',%s,true)",("forged acknowledgement",))
                self.connection.execute(
                    """UPDATE vinto_txn.work_order_line_reprogram_handoff
                       SET status='acknowledged',completed_at=clock_timestamp()
                       WHERE id=%s""",(h["handoff_id"],))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
            (h["handoff_id"],)),"reassigned")

    def test_flag_off_does_not_release_pending_or_reassigned(self):
        order,prior,h,pub,swap=self.flow()
        with patch.object(settings,"work_order_reprogram_handoff_enabled",False):
            with self.assertRaises(WorkOrderHandoffPendingError):
                line_execution.start_line(
                    self.connection,actor_id=self.supervisor,work_order_id=order.id,
                    line_code="L1",assignment_id=swap["replacement_assignment_id"],
                    sectors=("BOBINAS",))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s",
            (order.baseline.lines[0].id,)),"enabled")
        # Database trigger protects even a backend rollback with old code.
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.transaction():
                self.connection.execute(
                    "SELECT set_config('vinto.actor_id',%s,true)",(str(self.supervisor),))
                self.connection.execute(
                    "SELECT set_config('vinto.request_id',%s,true)",(str(uuid4()),))
                self.connection.execute(
                    "SELECT set_config('vinto.reason',%s,true)",("unsafe forced start",))
                self.connection.execute(
                    """UPDATE vinto_txn.work_order_line_execution
                       SET status='in_production',started_at=clock_timestamp(),
                           started_by=%s WHERE baseline_line_id=%s""",
                    (self.supervisor,order.baseline.lines[0].id))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
            (h["handoff_id"],)),"reassigned")

    def test_acknowledgement_allowed_even_if_flag_turned_off(self):
        order,prior,h,pub,swap=self.flow()
        actor=self.make_user("OPERACION")
        with patch.object(settings,"work_order_reprogram_handoff_enabled",False):
            result=self.operator_receipt(swap["replacement_assignment_id"],3,actor)
        self.assertEqual(result["version_number"],3)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s",
            (h["handoff_id"],)),"acknowledged")
