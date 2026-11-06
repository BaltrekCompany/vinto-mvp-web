"""E1-09 archive: disposable PostgreSQL 17 *_test only, never production.

Archive preserves original OT status and all descendants. The guard rejects
legacy in_progress and any order with an assignment. Test DB is copied from
a fully migrated fixture; no operator credentials are used.
"""
import secrets
import unittest
from datetime import date
from uuid import uuid4

import psycopg

from app.auth.service import create_user
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.work_orders import service
from app.work_orders.errors import (WorkOrderArchiveBlockedError, WorkOrderNotArchivedError,
                                    WorkOrderNotFoundError)
from app.work_orders.service import LineInput

BUNDLE = load_bundle()
ARTICLE = sorted(x["article_code"] for x in BUNDLE.article_machines if x["machine_code"] == "MP1")[0]
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_e109archive_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_e109archive")
        self.addCleanup(drop_database, self.database)
        self.conn = connect(self.database)
        self.addCleanup(self.conn.close)
        self.actor = create_user(
            self.conn, username="archive." + uuid4().hex[:12],
            display_name="Archive Fixture", profile_code="JEFATURA",
            password="pw-" + secrets.token_urlsafe(18), sectors=("BOBINAS",),
        ).user_id

    def make(self):
        return service.create_work_order(
            self.conn, actor_id=self.actor, machine_code="MP1",
            lines=[LineInput("PV-ARCHIVE-TEST", ARTICLE, 100, date(2026, 10, 30))],
            sectors=("BOBINAS",),
        )

    def scalar(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]

    def archive(self, order, reason="Escenario ficticio para archivo"):
        return service.archive_work_order(
            self.conn, actor_id=self.actor, work_order_id=order.id,
            reason=reason, sectors=("BOBINAS",),
        )

    def test_draft_archive_is_audited_hidden_and_restorable(self):
        order = self.make()
        before = {table: self.scalar(f"SELECT count(*) FROM vinto_txn.{table}")
                  for table in ("work_order", "work_order_version", "work_order_line", "assignment", "capture")}
        view = self.archive(order)
        self.assertEqual(view.status, "draft")
        metadata = self.conn.execute(
            "SELECT archived_at, archived_by, archived_reason FROM vinto_txn.work_order WHERE id=%s",
            (order.id,),
        ).fetchone()
        self.assertIsNotNone(metadata[0])
        self.assertEqual(metadata[1], self.actor)
        self.assertEqual(metadata[2], "Escenario ficticio para archivo")
        self.assertFalse(any(x.id == order.id for x in service.list_work_orders(
            self.conn, sectors=("BOBINAS",))))
        history = service.list_work_orders(self.conn, sectors=("BOBINAS",), archived=True)
        self.assertEqual([x.id for x in history], [order.id])
        with self.assertRaises(WorkOrderNotFoundError):
            service.get_work_order(self.conn, order.id, sectors=("BOBINAS",))
        self.assertEqual(service.get_work_order(
            self.conn, order.id, sectors=("BOBINAS",), include_archived=True).id, order.id)
        self.assertGreaterEqual(self.scalar(
            """SELECT count(*) FROM vinto_audit.audit_event
               WHERE entity_table='work_order' AND action='UPDATE'
                 AND entity_key->>'id'=%s AND reason='work order archive'""",
            (str(order.id),)), 1)

        restored = service.restore_work_order(
            self.conn, actor_id=self.actor, work_order_id=order.id,
            sectors=("BOBINAS",))
        self.assertEqual(restored.status, "draft")
        self.assertIsNone(self.scalar(
            "SELECT archived_at FROM vinto_txn.work_order WHERE id=%s", (order.id,)))
        self.assertTrue(any(x.id == order.id for x in service.list_work_orders(
            self.conn, sectors=("BOBINAS",))))
        self.assertEqual(service.list_work_orders(self.conn, sectors=("BOBINAS",), archived=True), [])
        self.assertGreaterEqual(self.scalar(
            """SELECT count(*) FROM vinto_audit.audit_event
               WHERE entity_table='work_order' AND action='UPDATE'
                 AND entity_key->>'id'=%s AND reason='work order restore archive'""",
            (str(order.id),)), 1)
        after = {table: self.scalar(f"SELECT count(*) FROM vinto_txn.{table}") for table in before}
        self.assertEqual(before, after)

    def test_published_archive_preserves_published_state(self):
        order = self.make()
        service.publish_work_order(self.conn, actor_id=self.actor, work_order_id=order.id,
                                   sectors=("BOBINAS",))
        archived = self.archive(order)
        self.assertEqual(archived.status, "published")
        restored = service.restore_work_order(
            self.conn, actor_id=self.actor, work_order_id=order.id, sectors=("BOBINAS",))
        self.assertEqual(restored.status, "published")

    def test_assignment_archive_trigger_only_intercepts_insert(self):
        """The finish path uses machine -> assignment locks and must not
        attempt a parent OT lock. Assignment identity UPDATE is immutable in
        migration 0011, so an UPDATE cannot move a row into an archived OT.
        """
        row = self.conn.execute(
            """SELECT t.tgtype::int FROM pg_trigger t
               WHERE t.tgrelid = 'vinto_txn.assignment'::regclass
                 AND t.tgname = 'a_guard_archive_assignment'""").fetchone()
        self.assertIsNotNone(row)
        trigger_type = row[0]
        self.assertNotEqual(trigger_type & 4, 0, "assignment INSERT must be guarded")
        self.assertEqual(trigger_type & 16, 0, "assignment UPDATE must not lock OT (deadlock)")
        self.assertNotEqual(trigger_type & 2, 0, "guard must run before insert")

    def test_in_progress_order_is_not_archivable_even_without_assignments(self):
        order = self.make()
        service.publish_work_order(self.conn, actor_id=self.actor,
                                   work_order_id=order.id, sectors=("BOBINAS",))
        self.conn.execute("UPDATE vinto_txn.work_order SET status='in_progress' WHERE id=%s",
                          (order.id,))
        with self.assertRaises(WorkOrderArchiveBlockedError):
            self.archive(order)
        self.assertIsNone(self.scalar(
            "SELECT archived_at FROM vinto_txn.work_order WHERE id=%s", (order.id,)))

    def test_scope_reason_and_restore_gates(self):
        order = self.make()
        for reason in ("", "sin razón", "a" * 301):
            with self.subTest(reason=reason[:12]), self.assertRaises(WorkOrderArchiveBlockedError):
                self.archive(order, reason=reason)
        with self.assertRaises(WorkOrderNotFoundError):
            service.archive_work_order(
                self.conn, actor_id=self.actor, work_order_id=order.id,
                reason="Caso ficticio fuera de alcance", sectors=("REBOBINADO",))
        with self.assertRaises(WorkOrderNotArchivedError):
            service.restore_work_order(
                self.conn, actor_id=self.actor, work_order_id=order.id, sectors=("BOBINAS",))
        self.archive(order)
        with self.assertRaises(WorkOrderNotFoundError):
            self.archive(order)  # already archived not in operational scope

    def test_direct_sql_cannot_archive_without_actor_or_edit_archived_rows(self):
        order = self.make()
        with self.assertRaises(psycopg.Error):
            self.conn.execute(
                """UPDATE vinto_txn.work_order
                   SET archived_at=clock_timestamp(), archived_by=%s,
                       archived_reason='Registro ficticio sin actor de sesión'
                   WHERE id=%s""", (self.actor, order.id))
        self.archive(order)
        with self.assertRaises(psycopg.Error):
            self.conn.execute(
                "UPDATE vinto_txn.work_order SET status='closed' WHERE id=%s", (order.id,))
        with self.assertRaises(psycopg.Error):
            self.conn.execute(
                """INSERT INTO vinto_txn.work_order_version(work_order_id,version_number,kind)
                   VALUES(%s,2,'operational')""", (order.id,))
        with self.assertRaises(psycopg.Error):
            self.conn.execute(
                """INSERT INTO vinto_txn.work_order_line
                     (work_order_version_id,line_code,pv_reference,article_version_id,
                      unit_id,quantity,due_date,machine_id)
                   SELECT work_order_version_id,'L999',pv_reference,article_version_id,
                          unit_id,quantity,due_date,machine_id
                   FROM vinto_txn.work_order_line WHERE id=%s""",
                (order.baseline.lines[0].id,))
        with self.assertRaises(psycopg.Error):
            self.conn.execute(
                """INSERT INTO vinto_txn.assignment
                     (work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by)
                   SELECT id,machine_id,%s,'2026-10-30',%s
                   FROM vinto_txn.work_order_line WHERE id=%s""",
                (uuid4(), self.actor, order.baseline.lines[0].id))
        with self.assertRaises(psycopg.Error):
            self.conn.execute(
                """UPDATE vinto_txn.work_order
                   SET archived_at=NULL,archived_by=NULL,archived_reason=NULL
                   WHERE id=%s""", (order.id,))
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "draft")


if __name__ == "__main__":
    unittest.main()
