"""E2-D2-B2-B recovery and rollback gate against disposable PostgreSQL17."""
from unittest.mock import patch
from uuid import uuid4

from app.assignments import revision_notices
from app.config import settings
from app.work_orders import handoff_service, handoff_publication
from app.work_orders.handoff_rollout_preflight import collect
from app.work_orders.errors import WorkOrderNotFoundError
try:
    import test_e2d2b12_publish_reassign as previous
except ModuleNotFoundError:
    from tests import test_e2d2b12_publish_reassign as previous


def setUpModule():
    previous.base.STATE["template"] = previous.base.build_reference_template(
        "vinto_e2d2b2b_tpl")


def tearDownModule():
    template = previous.base.STATE.pop("template", None)
    if template:
        previous.base.drop_database(template)


class RecoveryTests(previous.PublishReassignTests):
    """Include the previous publish/reassign invariants as regressions."""

    def status(self, h):
        return handoff_service.read_handoff(
            self.connection,handoff_id=h["handoff_id"],sectors=("BOBINAS",))

    def snapshot(self):
        with self.connection.transaction():
            self.connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return collect(self.connection)

    def test_flag_off_can_cancel_pending_and_unblock_safely(self):
        order,prior,h,old,new=self.case()
        self.assertEqual(self.status(h)["status"],"pending")
        self.assertEqual(self.status(h)["recovery_action"],"cancel_pending_or_publish")
        with patch.object(settings,"work_order_reprogram_handoff_enabled",False):
            cancelled=handoff_service.cancel(
                self.connection,actor_id=self.supervisor_b,
                handoff_id=h["handoff_id"],
                reason="Cancelacion segura con D2 desactivado",
                sectors=("BOBINAS",))
        self.assertEqual(cancelled["status"],"cancelled")
        self.assertEqual(self.status(h)["status"],"cancelled")
        self.assertTrue(self.snapshot()["safe_to_disable_or_rollback"])
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",(prior.id,)),"active")

    def test_published_can_reassign_under_flag_off_then_operator_ack(self):
        order,prior,h,old,new=self.case()
        pub=self.publish(h,old,new)
        self.assertEqual(self.status(h)["status"],"published")
        self.assertEqual(self.status(h)["recovery_action"],"retry_supervisor_reassign")
        with patch.object(settings,"work_order_reprogram_handoff_enabled",False):
            reassigned=handoff_publication.reassign(
                self.connection,actor_id=self.supervisor,
                handoff_id=h["handoff_id"],sectors=("BOBINAS",))
            self.assertEqual(reassigned["status"],"reassigned")
            self.assertEqual(self.status(h)["recovery_action"],
                             "operator_acknowledge_exact_revision")
            actor=self.make_user("OPERACION")
            receipt=revision_notices.acknowledge_revision(
                self.connection,actor_id=actor,
                assignment_id=reassigned["replacement_assignment_id"],
                expected_version=3,sectors=("BOBINAS",),
                machine_codes=("MP1",),request_id=str(uuid4()))
        self.assertEqual(receipt["version_number"],3)
        self.assertEqual(self.status(h)["status"],"acknowledged")
        self.assertEqual(self.status(h)["published_version"],3)
        self.assertTrue(self.snapshot()["safe_to_disable_or_rollback"])

    def test_gate_blocks_rollback_for_pending_published_reassigned(self):
        order,prior,h,old,new=self.case()
        pending=self.snapshot()
        self.assertFalse(pending["safe_to_disable_or_rollback"])
        self.assertIn("D2_OPEN_HANDOFFS_PRESENT",pending["blockers"])
        self.assertEqual(pending["handoffs_by_state"]["pending"],1)
        self.publish(h,old,new)
        published=self.snapshot()
        self.assertFalse(published["safe_to_disable_or_rollback"])
        self.assertEqual(published["handoffs_by_state"]["published"],1)
        swap=self.reassign(h)
        reassigned=self.snapshot()
        self.assertFalse(reassigned["safe_to_disable_or_rollback"])
        self.assertEqual(reassigned["handoffs_by_state"]["reassigned"],1)
        # The CLI collector is aggregated: no OTP/assignment/user/hand-off
        # identifying fields are part of its output.
        output=str(reassigned)
        self.assertNotIn(str(h["handoff_id"]),output)
        self.assertNotIn(str(order.id),output)
        self.assertNotIn(str(prior.id),output)
        self.assertNotIn(str(swap["replacement_assignment_id"]),output)

    def test_handoff_status_rejects_out_of_scope_without_leak(self):
        order,prior,h,old,new=self.case()
        with self.assertRaises(WorkOrderNotFoundError):
            handoff_service.read_handoff(
                self.connection,handoff_id=h["handoff_id"],
                sectors=("REBOBINADO",))
        with self.assertRaises(WorkOrderNotFoundError):
            handoff_service.read_handoff(
                self.connection,handoff_id=uuid4(),sectors=("BOBINAS",))

    def test_empty_table_and_strong_sql_barrier_required_for_gate(self):
        state=self.snapshot()
        self.assertTrue(state["technical_preflight_clear"])
        self.assertTrue(state["d2_e1_sql_guard_enabled"])
        self.assertTrue(state["d2_handoff_table_installed"])
        self.assertEqual(state["open_handoff_count"],0)
        self.assertTrue(all(state["d2_migrations_verified"].values()))
