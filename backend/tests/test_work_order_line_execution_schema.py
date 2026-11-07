"""E1-02 PostgreSQL migration 0013: proposed database tests; ephemeral *_test only.

Uses existing SameOrderCase fixtures and build_reference_template. Not yet run.
"""

import threading
import unittest
from datetime import datetime, timezone

import psycopg

from app.ephemeral_db import build_reference_template, connect, drop_database
try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base

TEMPLATE = {}


def setUpModule():
    TEMPLATE['database'] = build_reference_template('vinto_e102_tpl')
    base.STATE['template'] = TEMPLATE['database']


def tearDownModule():
    if TEMPLATE.get('database'):
        drop_database(TEMPLATE['database'])
    base.STATE.pop('template', None)


class ExecutionSchemaTests(base.SameOrderCase):
    def insert(self, order, i, machine=None):
        baseline_id = order.baseline.lines[i].id
        return self.connection.execute('''
            INSERT INTO vinto_txn.work_order_line_execution (baseline_line_id,work_order_id,machine_id)
            SELECT l.id, v.work_order_id, COALESCE(%s::uuid, l.machine_id)
            FROM vinto_txn.work_order_line l
            JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
            WHERE l.id=%s AND v.kind='baseline' AND v.version_number=1 RETURNING status
        ''', (machine, baseline_id)).fetchone()[0]

    def change(self, line, status, connection=None, start_time=None):
        c = connection or self.connection
        if status == 'enabled':
            c.execute('UPDATE vinto_txn.work_order_line_execution SET status=%s WHERE baseline_line_id=%s', (status,line.id))
        elif status == 'in_production':
            c.execute('''UPDATE vinto_txn.work_order_line_execution
                SET status=%s,started_at=COALESCE(%s::timestamptz,clock_timestamp()),started_by=%s
                WHERE baseline_line_id=%s''', (status,start_time,self.supervisor,line.id))
        elif status == 'finished':
            c.execute('''UPDATE vinto_txn.work_order_line_execution
                SET status=%s,finished_at=clock_timestamp(),finished_by=%s WHERE baseline_line_id=%s''',
                (status,self.supervisor,line.id))

    def rejected(self, fn, expected):
        with self.assertRaises(psycopg.Error) as caught:
            with self.connection.transaction():
                fn()
        self.assertEqual(caught.exception.sqlstate, expected)

    def test_no_automatic_backfill(self):
        order = self.same_machine_order(2)
        self.assertEqual(self.scalar('SELECT count(*) FROM vinto_txn.work_order_line_execution'), 0)
        self.assertEqual(self.insert(order, 0), 'planned')

    def test_several_enabled_only_one_producing(self):
        order = self.same_machine_order(2)
        first, second = order.baseline.lines[:2]
        for i,line in enumerate((first,second)):
            self.insert(order,i)
            self.change(line,'enabled')
        self.change(first,'in_production')
        self.rejected(lambda: self.change(second,'in_production'), '23505')
        self.change(first,'finished')
        self.change(second,'in_production')
        self.change(second,'finished')
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line_execution WHERE status='finished'"),2)

    def test_invalid_transitions_and_immutable_history(self):
        order=self.same_machine_order(1)
        line=order.baseline.lines[0]
        self.insert(order,0)
        self.rejected(lambda:self.change(line,'in_production'),'23514')
        self.rejected(lambda:self.change(line,'finished'),'23514')
        self.change(line,'enabled')
        self.change(line,'in_production')
        self.change(line,'finished')
        self.rejected(lambda:self.change(line,'enabled'),'23514')
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='work_order_line_execution'"),0)

    def test_identity_matches_baseline_and_cannot_change(self):
        order=self.same_machine_order(1)
        machine=self.scalar("SELECT id FROM vinto_master.machine WHERE code='MP3'")
        self.rejected(lambda:self.insert(order,0,machine),'23514')
        self.insert(order,0)
        self.rejected(lambda:self.connection.execute(
            'UPDATE vinto_txn.work_order_line_execution SET machine_id=%s WHERE baseline_line_id=%s',
            (machine,order.baseline.lines[0].id)),'23514')

    def test_started_at_cannot_change_on_finish(self):
        order=self.same_machine_order(1)
        line=order.baseline.lines[0]
        self.insert(order,0)
        self.change(line,'enabled')
        self.change(line,'in_production')
        self.rejected(lambda:self.connection.execute('''
            UPDATE vinto_txn.work_order_line_execution
            SET status='finished',started_at=%s,finished_at=clock_timestamp(),finished_by=%s
            WHERE baseline_line_id=%s''',
            (datetime(2020,1,1,tzinfo=timezone.utc),self.supervisor,line.id)),'23514')

    def test_concurrent_updates_to_same_machine(self):
        order=self.same_machine_order(2)
        lines=order.baseline.lines[:2]
        for i,line in enumerate(lines):
            self.insert(order,i)
            self.change(line,'enabled')
        barrier=threading.Barrier(2)
        outcome=[None,None]
        def runner(i,line):
            try:
                with connect(self.database) as c:
                    barrier.wait(timeout=10)
                    with c.transaction():
                        self.change(line,'in_production',connection=c)
                outcome[i]=('ok',None)
            except psycopg.Error as err:
                outcome[i]=('error',err.sqlstate)
            except Exception as err:
                outcome[i]=('unexpected',str(err))
        threads=[threading.Thread(target=runner,args=(i,line)) for i,line in enumerate(lines)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=60)
        self.assertEqual(sorted(x[0] for x in outcome),['error','ok'],outcome)
        self.assertEqual(next(x[1] for x in outcome if x[0]=='error'),'23505')


    def test_rollback_empty_history_then_reapply(self):
        """Exercise historical 0013 rollback at the 0013 schema boundary.

        Modern checkouts also contain 0014/0015. Removing 0013 from a fully
        migrated database would leave holes in migration history and break
        dependent schema. Never run a legacy rollback against later migrations.
        """
        from pathlib import Path
        from uuid import uuid4
        from migrate import apply, applied_migrations, read_migrations
        from app.ephemeral_db import create_database, connect, drop_database

        root = Path(__file__).resolve().parents[1]
        sql = (root / 'rollbacks' / '0013_work_order_line_execution_rollback.sql').read_text(encoding='utf-8')
        historical = read_migrations()[:13]
        self.assertEqual([m.version for m in historical], list(range(1, 14)))

        name = f"vinto_e102_rollback_{uuid4().hex[:12]}_test"
        create_database(name)
        try:
            with connect(name) as c:
                apply(c, historical)
                self.assertEqual(c.execute(
                    'SELECT count(*) FROM vinto_txn.work_order_line_execution'
                ).fetchone()[0], 0)
                self.assertEqual(c.execute(
                    'SELECT max(version) FROM vinto_meta.schema_migration'
                ).fetchone()[0], 13)

                c.execute(sql, prepare=False)
                self.assertIsNone(c.execute(
                    "SELECT to_regclass('vinto_txn.work_order_line_execution')"
                ).fetchone()[0])
                self.assertEqual(c.execute(
                    'SELECT max(version) FROM vinto_meta.schema_migration'
                ).fetchone()[0], 12)

                apply(c, historical)
                self.assertEqual(c.execute(
                    'SELECT max(version) FROM vinto_meta.schema_migration'
                ).fetchone()[0], 13)
                self.assertIsNotNone(c.execute(
                    "SELECT to_regclass('vinto_txn.work_order_line_execution')"
                ).fetchone()[0])
                self.assertEqual(len(applied_migrations(c)), 13)
        finally:
            drop_database(name)

    def test_rollback_refuses_real_history_without_deleting_anything(self):
        """A planned line is already history; no rollback is permitted."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        sql = (root / 'rollbacks' / '0013_work_order_line_execution_rollback.sql').read_text(encoding='utf-8')
        order = self.same_machine_order(1)
        self.insert(order, 0)
        try:
            with self.assertRaises(psycopg.Error) as caught:
                self.connection.execute(sql, prepare=False)
            self.assertEqual(caught.exception.sqlstate, 'P0001')
        finally:
            # The rollback script started BEGIN, which must be cancelled on failure.
            self.connection.execute('ROLLBACK')
        self.assertEqual(self.scalar('SELECT count(*) FROM vinto_txn.work_order_line_execution'), 1)
        from migrate import read_migrations
        self.assertEqual(
            self.scalar('SELECT max(version) FROM vinto_meta.schema_migration'),
            len(read_migrations()),
        )

    def test_app_role_can_read_write_but_not_delete_or_truncate(self):
        """Only applies when an isolated test cluster explicitly provisions vinto_app."""
        exists = self.scalar("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app')")
        if not exists:
            self.skipTest('vinto_app not provisioned in this test cluster')
        table = 'vinto_txn.work_order_line_execution'
        expected = [('SELECT', True), ('INSERT', True), ('UPDATE', True),
                    ('DELETE', False), ('TRUNCATE', False)]
        for privilege, allowed in expected:
            actual = self.scalar("SELECT has_table_privilege('vinto_app', %s, %s)", (table, privilege))
            self.assertEqual(actual, allowed, privilege)


if __name__=='__main__':
    unittest.main()
