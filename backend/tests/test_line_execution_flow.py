"""E1-03: logical line execution. PostgreSQL ephemeral *_test databases only."""
import threading
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.work_orders import line_execution as flow
from app.work_orders.line_execution import (
    ExecutionAssignmentError, ExecutionDisabledError, ExecutionMachineBusyError,
    ExecutionNotReadyError, ExecutionStateConflictError,
)

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base


def setUpModule():
    base.STATE['template'] = build_reference_template('vinto_e103_tpl')


def tearDownModule():
    if base.STATE.get('template'):
        drop_database(base.STATE['template'])
        base.STATE.pop('template', None)


class LineExecutionTests(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        enabled = patch.object(settings, 'work_order_line_execution_enabled', True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def start(self, order, line, assignment, connection=None, actor=None):
        return flow.start_line(
            connection or self.connection, actor_id=actor or self.supervisor,
            work_order_id=order.id, line_code=line,
            assignment_id=assignment.id, sectors=('BOBINAS',))

    def finish_line(self, order, line, connection=None):
        return flow.finish_line(
            connection or self.connection, actor_id=self.supervisor,
            work_order_id=order.id, line_code=line, sectors=('BOBINAS',))

    def test_activating_two_lines_enables_without_starting(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0), self.activate(order, 1)
        rows = self.connection.execute(
            """SELECT l.line_code,e.status FROM vinto_txn.work_order_line_execution e
               JOIN vinto_txn.work_order_line l ON l.id=e.baseline_line_id
               WHERE e.work_order_id=%s ORDER BY l.line_code""", (order.id,)).fetchall()
        self.assertEqual(rows, [('L1','enabled'), ('L2','enabled')])
        self.assertEqual(first.assignment.status, 'active')
        self.assertEqual(second.assignment.status, 'active')

    def test_only_one_producing_then_finish_then_start_next(self):
        order = self.same_machine_order(2)
        first, second = self.activate(order, 0), self.activate(order, 1)
        active = self.start(order,'L1',first.assignment)
        self.assertEqual(active.status,'in_production')
        self.assertEqual(self.start(order,'L1',first.assignment).started_at,active.started_at)
        with self.assertRaises(ExecutionMachineBusyError):
            self.start(order,'L2',second.assignment)
        finished = self.finish_line(order,'L1')
        self.assertEqual(finished.status,'finished')
        self.assertEqual(self.finish_line(order,'L1').finished_at,finished.finished_at)
        self.assertEqual(self.start(order,'L2',second.assignment).status,'in_production')
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_line_execution WHERE machine_id=(SELECT id FROM vinto_master.machine WHERE code='MP1') AND status='in_production'"),1)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s",(order.id,)),'in_progress')

    def test_finish_line_finishes_only_its_shift_assignment(self):
        order=self.same_machine_order(2)
        a,b=self.activate(order,0),self.activate(order,1)
        self.start(order,'L1',a.assignment)
        self.finish_line(order,'L1')
        states=self.connection.execute(
            """SELECT l.line_code,a.status FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               WHERE a.id IN (%s,%s) ORDER BY l.line_code""",
            (a.assignment.id,b.assignment.id)).fetchall()
        self.assertEqual(states,[('L1','finished'),('L2','active')])
        with self.assertRaises(ExecutionStateConflictError):
            self.activate(order,0)

    def test_legacy_finish_cannot_orphan_current_production(self):
        order=self.same_machine_order(1)
        a=self.activate(order,0).assignment
        self.start(order,'L1',a)
        with self.assertRaises(ExecutionStateConflictError):
            base.service.finish(self.connection,actor_id=self.supervisor,assignment_id=a.id)
        self.assertEqual(self.finish_line(order,'L1').status,'finished')

    def test_reject_wrong_assignment_and_wrong_line(self):
        order=self.same_machine_order(2)
        a,b=self.activate(order,0),self.activate(order,1)
        with self.assertRaises(ExecutionAssignmentError):
            self.start(order,'L2',a.assignment)
        base.service.finish(self.connection,actor_id=self.supervisor,assignment_id=a.assignment.id)
        with self.assertRaises(ExecutionAssignmentError):
            self.start(order,'L1',a.assignment)
        self.assertEqual(self.start(order,'L2',b.assignment).status,'in_production')

    def test_legacy_active_assignment_requires_explicit_review(self):
        order=self.same_machine_order(1)
        with patch.object(settings,'work_order_line_execution_enabled',False):
            old=self.activate(order,0).assignment
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution"),0)
        with self.assertRaises(ExecutionNotReadyError):
            self.activate(order,0)
        with self.assertRaises(ExecutionNotReadyError):
            self.start(order,'L1',old)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution"),0)

    def test_feature_off_preserves_original_activation(self):
        order=self.same_machine_order(1)
        with patch.object(settings,'work_order_line_execution_enabled',False):
            assignment=self.activate(order,0).assignment
            with self.assertRaises(ExecutionDisabledError):
                self.start(order,'L1',assignment)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution"),0)

    def test_two_supervisors_racing_one_machine(self):
        order=self.same_machine_order(2)
        first,second=self.activate(order,0),self.activate(order,1)
        barrier=threading.Barrier(2)
        results=[None,None]
        def runner(i,code,a):
            try:
                with connect(self.database) as c:
                    barrier.wait(timeout=15)
                    result=self.start(order,code,a,connection=c)
                    results[i]=('ok',result.status)
            except ExecutionMachineBusyError:
                results[i]=('blocked',None)
            except Exception as error:
                results[i]=('unexpected',str(error))
        t1=threading.Thread(target=runner,args=(0,'L1',first.assignment))
        t2=threading.Thread(target=runner,args=(1,'L2',second.assignment))
        t1.start();t2.start();t1.join(timeout=75);t2.join(timeout=75)
        self.assertEqual(sorted(x[0] for x in results),['blocked','ok'],results)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution WHERE status='in_production'"),1)

    def test_shift_change_cannot_activate_a_new_order_until_previous_line_is_finished(self):
        """A stale assignment is not proof that its logical execution has ended."""
        from app.assignments.errors import MachineBusyWithOtherWorkOrderError
        old_order=self.same_machine_order(1)
        old_assignment=self.activate(old_order,0).assignment
        self.start(old_order,'L1',old_assignment)
        new_order=self.same_machine_order(1)
        with patch.object(base._assignments, "_now", return_value=base.NIGHT):
            with self.assertRaises(MachineBusyWithOtherWorkOrderError):
                self.activate(new_order,0)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.assignment WHERE id=%s",
            (old_assignment.id,)), "active")
        self.finish_line(old_order,'L1')
        with patch.object(base._assignments, "_now", return_value=base.NIGHT):
            new_assignment=self.activate(new_order,0).assignment
        self.assertEqual(new_assignment.status,'active')

    def test_two_machines_can_produce_in_parallel(self):
        order=self.mixed_order()
        items=[self.activate(order,i).assignment for i in range(3)]
        self.assertEqual(self.start(order,'L1',items[0]).status,'in_production')
        self.assertEqual(self.start(order,'L3',items[2]).status,'in_production')
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution WHERE status='in_production'"),2)


if __name__=='__main__':
    unittest.main()
