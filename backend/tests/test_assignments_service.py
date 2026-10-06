"""Operational copy and assignments (domain): baseline stays intact, one active assignment per machine, shifts from the backend.

Runs in ephemeral *_test databases copied from a migrated template with the reference bundle (sector BOBINAS,
machines MP1/MP3, DIA/NOCHE schedules). Nothing touches vinto.
"""

import secrets
import threading
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app.assignments import service
from app.assignments.errors import (AssignmentNotFoundError, BaselineLineNotFoundError, WorkOrderNotActivatableError)
from app.auth.service import create_user
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.shifts import SHIFT_AMBIGUOUS, SHIFT_NOT_CONFIGURED, ShiftResolutionError, resolve_shift
from app.work_orders import service as work_orders
from app.work_orders.errors import WorkOrderNotFoundError
from app.work_orders.service import LineInput

BUNDLE = load_bundle()
STATE = {}
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
MP3_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP3")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 America/La_Paz -> DIA, 2026-10-06
NIGHT = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)  # 21:00 America/La_Paz -> NOCHE, 2026-10-06


def setUpModule():
    STATE["template"] = build_reference_template("vinto_as_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class AssignmentCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_as")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.jefatura = self.make_user("JEFATURA")
        self.supervisor = self.make_user("SUPERVISION")

    def make_user(self, profile):
        return create_user(self.connection, username=f"as.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile,
                           password="pw-" + secrets.token_urlsafe(18)).user_id

    def make_order(self, lines=3, machine="MP1", publish=True, connection=None):
        codes = MP1_CODES if machine == "MP1" else MP3_CODES
        connection = connection or self.connection
        view = work_orders.create_work_order(connection, actor_id=self.jefatura, machine_code=machine, lines=[
            LineInput(f"PV-{i + 1}", codes[i], 10 * (i + 1), date(2026, 11, i + 1)) for i in range(lines)])
        if publish:
            view = work_orders.publish_work_order(connection, actor_id=self.jefatura, work_order_id=view.id)
        return view

    def activate(self, order, index=0, actor=None, connection=None, **kwargs):
        return service.activate(connection or self.connection, actor_id=actor or self.supervisor, work_order_id=order.id,
                                baseline_line_id=order.baseline.lines[index].id, **kwargs)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def versions(self, order):
        return self.connection.execute("SELECT version_number,kind,published_at IS NOT NULL FROM vinto_txn.work_order_version WHERE work_order_id=%s ORDER BY version_number",
                                       (order.id,)).fetchall()

    def snapshot_baseline(self, order):
        version = self.connection.execute("SELECT * FROM vinto_txn.work_order_version WHERE id=%s", (order.baseline.id,)).fetchall()
        lines = self.connection.execute("SELECT * FROM vinto_txn.work_order_line WHERE work_order_version_id=%s ORDER BY line_code", (order.baseline.id,)).fetchall()
        wo = self.connection.execute("SELECT number,machine_id FROM vinto_txn.work_order WHERE id=%s", (order.id,)).fetchall()
        return version, lines, wo

    def operational_lines(self, order):
        return self.connection.execute(
            """SELECT l.id,l.line_code,l.pv_reference,l.article_version_id,l.unit_id,l.quantity,l.due_date FROM vinto_txn.work_order_line l
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id WHERE v.work_order_id=%s AND v.kind='operational'
               ORDER BY l.line_code""", (order.id,)).fetchall()

    def assignment_states(self, machine="MP1"):
        return self.connection.execute(
            """SELECT a.status FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id=a.machine_id WHERE m.code=%s ORDER BY a.created_at""", (machine,)).fetchall()


class OperationalVersionTests(AssignmentCase):
    def test_baseline_stays_identical_after_activations(self):
        order = self.make_order()
        before = self.snapshot_baseline(order)
        self.activate(order, 0)
        self.activate(order, 1)
        self.assertEqual(self.snapshot_baseline(order), before)
        self.assertEqual(before[0][0][3], "baseline")

    def test_first_activation_creates_a_published_v2_operational(self):
        order = self.make_order()
        self.assertEqual(self.versions(order), [(1, "baseline", True)])
        self.activate(order, 0)
        self.assertEqual(self.versions(order), [(1, "baseline", True), (2, "operational", True)])

    def test_the_operational_version_copies_every_line_even_if_one_is_activated(self):
        order = self.make_order(lines=3)
        self.activate(order, 0)
        copies = self.operational_lines(order)
        self.assertEqual([c[1] for c in copies], ["L1", "L2", "L3"])

    def test_copied_lines_get_new_ids_and_keep_every_planned_value(self):
        order = self.make_order(lines=3)
        self.activate(order, 1)
        baseline = self.connection.execute(
            "SELECT id,line_code,pv_reference,article_version_id,unit_id,quantity,due_date FROM vinto_txn.work_order_line WHERE work_order_version_id=%s ORDER BY line_code",
            (order.baseline.id,)).fetchall()
        copies = self.operational_lines(order)
        self.assertTrue({b[0] for b in baseline}.isdisjoint({c[0] for c in copies}))  # new ids
        self.assertEqual([b[1:] for b in baseline], [c[1:] for c in copies])  # code, PV, article_version, unit, quantity, due date

    def test_the_operational_version_is_published_after_its_lines_were_copied(self):
        order = self.make_order(lines=2)
        self.activate(order, 0)
        events = self.connection.execute(
            """SELECT id,entity_table,action FROM vinto_audit.audit_event WHERE entity_table IN ('work_order_line','work_order_version')
               AND new_data->>'work_order_version_id' IS NOT NULL OR (entity_table='work_order_version' AND action='UPDATE')
               ORDER BY id""").fetchall()
        copy_ids = [e[0] for e in events if e[1] == "work_order_line" and e[2] == "INSERT"]
        publish_ids = [e[0] for e in events if e[1] == "work_order_version" and e[2] == "UPDATE"]
        op_copies = self.connection.execute(
            """SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='work_order_line' AND action='INSERT'
               AND new_data->>'work_order_version_id'=(SELECT id::text FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational')""", (order.id,)).fetchone()[0]
        self.assertEqual(op_copies, 2)
        last_copy = self.connection.execute(
            """SELECT max(id) FROM vinto_audit.audit_event WHERE entity_table='work_order_line' AND action='INSERT'
               AND new_data->>'work_order_version_id'=(SELECT id::text FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational')""", (order.id,)).fetchone()[0]
        publish = self.connection.execute(
            """SELECT min(id) FROM vinto_audit.audit_event WHERE entity_table='work_order_version' AND action='UPDATE'
               AND entity_key->>'id'=(SELECT id::text FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational')""", (order.id,)).fetchone()[0]
        self.assertGreater(publish, last_copy)
        self.assertTrue(copy_ids and publish_ids)

    def test_the_published_operational_version_is_immutable(self):
        order = self.make_order(lines=2)
        self.activate(order, 0)
        line_id = self.operational_lines(order)[0][0]
        version_id = self.scalar("SELECT id FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order.id,))
        for statement, params in (("UPDATE vinto_txn.work_order_line SET quantity=1 WHERE id=%s", (line_id,)), ("DELETE FROM vinto_txn.work_order_line WHERE id=%s", (line_id,)),
                                  ("UPDATE vinto_txn.work_order_version SET published_at=NULL WHERE id=%s", (version_id,))):
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.connection.execute(statement, params)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute("""INSERT INTO vinto_txn.work_order_line (work_order_version_id,line_code,pv_reference,article_version_id,unit_id,quantity,due_date)
                                       SELECT work_order_version_id,'L99',pv_reference,article_version_id,unit_id,quantity,due_date FROM vinto_txn.work_order_line WHERE id=%s""", (line_id,))

    def test_later_activations_reuse_the_same_operational_version(self):
        order = self.make_order(lines=3)
        self.activate(order, 0)
        self.activate(order, 1)
        self.activate(order, 2)
        with patch.object(service, "_now", return_value=NIGHT):
            self.activate(order, 2)
        self.assertEqual(self.versions(order), [(1, "baseline", True), (2, "operational", True)])
        self.assertEqual(len(self.operational_lines(order)), 3)

    def test_operational_versions_and_lines_record_the_supervisor(self):
        order = self.make_order()
        self.activate(order, 0)
        version = self.connection.execute("SELECT created_by,updated_by FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order.id,)).fetchone()
        self.assertEqual(version, (self.supervisor, self.supervisor))
        lines = self.connection.execute(
            """SELECT DISTINCT l.created_by FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE v.work_order_id=%s AND v.kind='operational'""", (order.id,)).fetchall()
        self.assertEqual(lines, [(self.supervisor,)])
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.work_order WHERE id=%s", (order.id,)), self.jefatura)  # the order itself is untouched


class ActivationTests(AssignmentCase):
    def test_activate_creates_an_assignment_on_the_operational_line(self):
        order = self.make_order()
        result = self.activate(order, 0)
        self.assertTrue(result.created)
        self.assertFalse(result.already_active)
        self.assertIsNone(result.finished_assignment_id)
        row = self.connection.execute(
            """SELECT a.status,v.kind,v.version_number,l.line_code,a.work_order_line_id FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE a.id=%s""", (result.assignment.id,)).fetchone()
        self.assertEqual(row[:4], ("active", "operational", 2, "L1"))
        self.assertNotIn(row[4], [l.id for l in order.baseline.lines])  # never a baseline line
        self.assertEqual((result.assignment.operational_version_number, result.assignment.line.line_code), (2, "L1"))

    def test_the_machine_comes_from_the_work_order(self):
        for machine in ("MP1", "MP3"):
            order = self.make_order(lines=1, machine=machine)
            result = self.activate(order, 0)
            self.assertEqual(result.assignment.machine_code, machine)
            self.assertEqual(self.scalar("SELECT m.code FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id=a.machine_id WHERE a.id=%s", (result.assignment.id,)), machine)

    def test_shift_and_operating_date_come_from_resolve_shift_at_the_database_clock(self):
        order = self.make_order(lines=1)
        result = self.activate(order, 0)
        expected = resolve_shift(self.connection, self.scalar("SELECT clock_timestamp()"), sector_code="BOBINAS")
        self.assertIn(result.assignment.shift_code, ("DIA", "NOCHE"))
        row = self.connection.execute("SELECT shift_schedule_id,operating_date FROM vinto_txn.assignment WHERE id=%s", (result.assignment.id,)).fetchone()
        self.assertIn(row[1], (expected.operating_date, date.fromordinal(expected.operating_date.toordinal() - 1), date.fromordinal(expected.operating_date.toordinal() + 1)))

    def test_shift_and_date_are_exactly_what_resolve_shift_returns_for_the_clock(self):
        order = self.make_order(lines=1)
        with patch.object(service, "_now", return_value=DAY):
            result = self.activate(order, 0)
        expected = resolve_shift(self.connection, DAY, sector_code="BOBINAS")
        self.assertEqual((result.assignment.shift_code, result.assignment.shift_name, result.assignment.operating_date), ("DIA", "Día", date(2026, 10, 6)))
        self.assertEqual(self.scalar("SELECT shift_schedule_id FROM vinto_txn.assignment WHERE id=%s", (result.assignment.id,)), expected.shift_schedule_id)
        self.assertEqual(self.scalar("SELECT operating_date FROM vinto_txn.assignment WHERE id=%s", (result.assignment.id,)), expected.operating_date)

    def test_assigned_by_is_the_supervisor_and_audit_rows_carry_the_actor(self):
        order = self.make_order(lines=1)
        result = self.activate(order, 0)
        self.assertEqual((result.assignment.assigned_by_id, result.assignment.assigned_by_name), (self.supervisor, "Supervision Fixture"))
        self.assertEqual(self.connection.execute("SELECT assigned_by,created_by,updated_by FROM vinto_txn.assignment WHERE id=%s", (result.assignment.id,)).fetchone(),
                         (self.supervisor, self.supervisor, self.supervisor))

    def test_the_work_order_moves_from_published_to_in_progress_and_stays_there(self):
        order = self.make_order()
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "published")
        self.activate(order, 0)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "in_progress")
        self.activate(order, 1)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "in_progress")

    def test_same_activation_in_the_same_context_is_idempotent_and_writes_nothing(self):
        order = self.make_order()
        with patch.object(service, "_now", return_value=DAY):
            first = self.activate(order, 0)
            audit_before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
            second = self.activate(order, 0)
        self.assertTrue(first.created)
        self.assertEqual((second.created, second.already_active, second.assignment.id), (False, True, first.assignment.id))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audit_before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 1)

    def test_a_different_line_finishes_the_previous_assignment_in_the_same_machine(self):
        order = self.make_order()
        first = self.activate(order, 0)
        second = self.activate(order, 1)
        self.assertEqual(second.finished_assignment_id, first.assignment.id)
        self.assertEqual(service.get_assignment(self.connection, first.assignment.id).status, "finished")
        self.assertEqual(service.get_assignment(self.connection, second.assignment.id).status, "active")
        self.assertEqual(self.assignment_states(), [("finished",), ("active",)])
        self.assertEqual(self.scalar("SELECT updated_by FROM vinto_txn.assignment WHERE id=%s", (first.assignment.id,)), self.supervisor)

    def test_a_line_of_another_order_on_the_same_machine_also_replaces_the_active_assignment(self):
        one, two = self.make_order(lines=1), self.make_order(lines=1)
        first = self.activate(one, 0)
        second = self.activate(two, 0)
        self.assertEqual(second.finished_assignment_id, first.assignment.id)
        self.assertEqual(self.assignment_states(), [("finished",), ("active",)])

    def test_assignments_on_different_machines_do_not_interfere(self):
        mp1, mp3 = self.make_order(lines=1, machine="MP1"), self.make_order(lines=1, machine="MP3")
        self.activate(mp1, 0)
        self.activate(mp3, 0)
        self.assertEqual(self.assignment_states("MP1"), [("active",)])
        self.assertEqual(self.assignment_states("MP3"), [("active",)])

    def test_a_shift_change_finishes_the_previous_assignment_and_creates_a_new_one(self):
        order = self.make_order(lines=1)
        with patch.object(service, "_now", return_value=DAY):
            day = self.activate(order, 0)
        with patch.object(service, "_now", return_value=NIGHT):
            night = self.activate(order, 0)
            again = self.activate(order, 0)
        self.assertEqual((day.assignment.shift_code, night.assignment.shift_code), ("DIA", "NOCHE"))
        self.assertEqual((night.assignment.operating_date, day.assignment.operating_date), (date(2026, 10, 6), date(2026, 10, 6)))
        self.assertTrue(night.created)
        self.assertEqual(night.finished_assignment_id, day.assignment.id)
        self.assertEqual((again.already_active, again.assignment.id), (True, night.assignment.id))
        self.assertEqual(self.assignment_states(), [("finished",), ("active",)])
        old = self.connection.execute("SELECT shift_schedule_id,operating_date,status FROM vinto_txn.assignment WHERE id=%s", (day.assignment.id,)).fetchone()
        self.assertEqual(old[2], "finished")  # the earlier row keeps its own shift and date
        self.assertNotEqual(old[0], self.scalar("SELECT shift_schedule_id FROM vinto_txn.assignment WHERE id=%s", (night.assignment.id,)))

    def test_a_finished_assignment_is_never_reactivated(self):
        order = self.make_order(lines=2)
        with patch.object(service, "_now", return_value=DAY):
            first = self.activate(order, 0)
            self.activate(order, 1)
            third = self.activate(order, 0)  # same line, same shift, but the earlier row is finished: a NEW row
        self.assertNotEqual(third.assignment.id, first.assignment.id)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (first.assignment.id,)), "finished")
        self.assertEqual(self.assignment_states(), [("finished",), ("finished",), ("active",)])

    def test_history_of_finished_assignments_is_kept(self):
        order = self.make_order(lines=3)
        for index in (0, 1, 2, 0):
            self.activate(order, index)
        states = [s[0] for s in self.assignment_states()]
        self.assertEqual(states, ["finished", "finished", "finished", "active"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE finished_at IS NOT NULL"), 3)

    def test_finished_at_is_set_with_the_database_clock(self):
        order = self.make_order(lines=2)
        first = self.activate(order, 0)
        second = self.activate(order, 1)
        finished_at, created_at = self.connection.execute("SELECT finished_at,created_at FROM vinto_txn.assignment WHERE id=%s", (first.assignment.id,)).fetchone()
        self.assertGreaterEqual(finished_at, created_at)
        self.assertLessEqual(finished_at, self.scalar("SELECT clock_timestamp()"))
        self.assertIsNone(second.assignment.finished_at)

    def test_audit_reasons_for_each_step(self):
        order = self.make_order(lines=2)
        self.activate(order, 0, request_id="req-a")
        self.activate(order, 1, request_id="req-b")
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=self.scalar("SELECT id FROM vinto_txn.assignment WHERE status='active'"), request_id="req-c")
        reasons = {r[0] for r in self.connection.execute("SELECT DISTINCT reason FROM vinto_audit.audit_event WHERE entity_table IN ('assignment','work_order_version') AND reason IS NOT NULL").fetchall()}
        self.assertTrue({"create operational work order version", "activate assignment", "finish previous assignment", "finish assignment"} <= reasons)
        actors = {r[0] for r in self.connection.execute("SELECT DISTINCT actor_id FROM vinto_audit.audit_event WHERE entity_table='assignment'").fetchall()}
        self.assertEqual(actors, {self.supervisor})
        dump = " ".join(f"{o} {n}" for o, n in self.connection.execute("SELECT old_data::text,new_data::text FROM vinto_audit.audit_event WHERE entity_schema='vinto_txn'").fetchall()).lower()
        for forbidden in ("password", "token", "argon2", "cookie"):
            self.assertNotIn(forbidden, dump)

    def test_the_machine_lock_has_no_effect_on_other_reads(self):
        order = self.make_order(lines=1)
        self.activate(order, 0)
        self.assertEqual(len(service.list_assignments(self.connection)), 1)


class ValidationTests(AssignmentCase):
    def test_a_draft_order_cannot_be_activated(self):
        order = self.make_order(publish=False)
        with self.assertRaises(WorkOrderNotActivatableError):
            self.activate(order, 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (order.id,)), 1)

    def test_a_closed_order_cannot_be_activated(self):
        order = self.make_order()
        self.connection.execute("UPDATE vinto_txn.work_order SET status='closed' WHERE id=%s", (order.id,))
        with self.assertRaises(WorkOrderNotActivatableError):
            self.activate(order, 0)
        self.assertEqual(self.versions(order), [(1, "baseline", True)])

    def test_a_baseline_line_of_another_order_is_rejected(self):
        one, two = self.make_order(), self.make_order()
        with self.assertRaises(BaselineLineNotFoundError):
            service.activate(self.connection, actor_id=self.supervisor, work_order_id=one.id, baseline_line_id=two.baseline.lines[0].id)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 0)
        self.assertEqual(self.versions(one), [(1, "baseline", True)])

    def test_an_operational_line_id_is_not_accepted_as_a_baseline_line(self):
        order = self.make_order()
        self.activate(order, 0)
        operational_line_id = self.operational_lines(order)[0][0]
        with self.assertRaises(BaselineLineNotFoundError):
            service.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=operational_line_id)

    def test_unknown_and_malformed_ids(self):
        order = self.make_order()
        for work_order_id in (uuid4(), "not-a-uuid", None):
            with self.subTest(work_order_id=str(work_order_id)), self.assertRaises(WorkOrderNotFoundError):
                service.activate(self.connection, actor_id=self.supervisor, work_order_id=work_order_id, baseline_line_id=order.baseline.lines[0].id)
        for line_id in (uuid4(), "nope"):
            with self.subTest(line_id=str(line_id)), self.assertRaises(BaselineLineNotFoundError):
                service.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=line_id)

    def test_an_inactive_machine_blocks_activation(self):
        order = self.make_order(lines=1)
        self.connection.execute("UPDATE vinto_master.machine SET active=false WHERE code='MP1'")
        with self.assertRaises(WorkOrderNotActivatableError):
            self.activate(order, 0)

    def test_missing_shift_configuration_is_rejected_without_writing_anything(self):
        order = self.make_order(lines=2)
        self.connection.execute("UPDATE vinto_config.shift SET active=false")
        with self.assertRaises(ShiftResolutionError) as raised:
            self.activate(order, 0)
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)
        self.assertEqual(self.versions(order), [(1, "baseline", True)])  # not even the operational copy
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 0)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "published")

    def test_ambiguous_shift_configuration_is_rejected(self):
        order = self.make_order(lines=1)
        self.connection.execute("""INSERT INTO vinto_config.shift (code,name) VALUES ('OVERLAP','Solapado')""")
        self.connection.execute("""INSERT INTO vinto_config.shift_schedule (shift_id,sector_id,starts_at,ends_at,timezone,valid_from)
                                   SELECT sh.id,s.id,'00:00','23:59','America/La_Paz','2026-01-01' FROM vinto_config.shift sh, vinto_master.sector s
                                   WHERE sh.code='OVERLAP' AND s.code='BOBINAS'""")
        with self.assertRaises(ShiftResolutionError) as raised:
            self.activate(order, 0)
        self.assertEqual(raised.exception.code, SHIFT_AMBIGUOUS)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 0)

    def test_the_machine_must_still_be_in_bobinas(self):
        order = self.make_order(lines=1)
        sector_id = self.scalar("INSERT INTO vinto_master.sector (code,name) VALUES ('OTRO','Otro') RETURNING id")
        self.connection.execute("UPDATE vinto_master.machine SET sector_id=%s WHERE code='MP1'", (sector_id,))
        with self.assertRaises(WorkOrderNotFoundError):
            self.activate(order, 0)


class FinishAndQueryTests(AssignmentCase):
    def test_manual_finish_and_idempotent_repeat(self):
        order = self.make_order(lines=1)
        active = self.activate(order, 0).assignment
        finished = service.finish(self.connection, actor_id=self.supervisor, assignment_id=active.id)
        self.assertEqual(finished.status, "finished")
        self.assertIsNotNone(finished.finished_at)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "in_progress")  # no order closing
        audit_before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        again = service.finish(self.connection, actor_id=self.supervisor, assignment_id=active.id)
        self.assertEqual(again.finished_at, finished.finished_at)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audit_before)

    def test_finish_unknown_or_malformed_assignment(self):
        for value in (uuid4(), "nope", None):
            with self.subTest(str(value)), self.assertRaises(AssignmentNotFoundError):
                service.finish(self.connection, actor_id=self.supervisor, assignment_id=value)

    def test_after_finishing_a_new_activation_creates_a_new_assignment(self):
        order = self.make_order(lines=1)
        first = self.activate(order, 0).assignment
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=first.id)
        second = self.activate(order, 0)
        self.assertTrue(second.created)
        self.assertIsNone(second.finished_assignment_id)
        self.assertNotEqual(second.assignment.id, first.id)

    def test_list_filters_and_order(self):
        one, two = self.make_order(lines=2), self.make_order(lines=1, machine="MP3")
        a = self.activate(one, 0).assignment
        b = self.activate(one, 1).assignment
        c = self.activate(two, 0).assignment
        everything = service.list_assignments(self.connection)
        self.assertEqual([v.id for v in everything], [c.id, b.id, a.id])
        self.assertEqual([v.id for v in service.list_assignments(self.connection, machine_code="MP1")], [b.id, a.id])
        self.assertEqual([v.id for v in service.list_assignments(self.connection, status="active")], [c.id, b.id])
        self.assertEqual([v.id for v in service.list_assignments(self.connection, status="finished")], [a.id])
        self.assertEqual([v.id for v in service.list_assignments(self.connection, work_order_id=two.id)], [c.id])
        self.assertEqual([v.id for v in service.list_assignments(self.connection, operating_date=a.operating_date, machine_code="MP3")], [c.id])
        self.assertEqual(service.list_assignments(self.connection, operating_date=date(2000, 1, 1)), [])
        self.assertEqual(len(service.list_assignments(self.connection, limit=1)), 1)

    def test_active_assignment_for_a_machine_with_stale_detection(self):
        order = self.make_order(lines=1)
        self.assertIsNone(service.get_active(self.connection, machine_code="MP1").assignment)
        with patch.object(service, "_now", return_value=DAY):
            made = self.activate(order, 0).assignment
            fresh = service.get_active(self.connection, machine_code="MP1")
        self.assertEqual((fresh.assignment.id, fresh.stale, fresh.current_shift_code, fresh.current_operating_date), (made.id, False, "DIA", date(2026, 10, 6)))
        with patch.object(service, "_now", return_value=NIGHT):
            stale = service.get_active(self.connection, machine_code="MP1")
        self.assertEqual((stale.assignment.id, stale.stale, stale.current_shift_code), (made.id, True, "NOCHE"))
        self.assertIsNone(service.get_active(self.connection, machine_code="MP3").assignment)

    def test_active_with_unresolvable_shift_does_not_fail(self):
        order = self.make_order(lines=1)
        self.activate(order, 0)
        self.connection.execute("UPDATE vinto_config.shift SET active=false")
        result = service.get_active(self.connection, machine_code="MP1")
        self.assertIsNotNone(result.assignment)
        self.assertIsNone(result.stale)
        self.assertIsNone(result.current_shift_code)


class ConcurrencyTests(AssignmentCase):
    def run_threads(self, targets):
        errors, barrier, results = [], threading.Barrier(len(targets)), [None] * len(targets)

        def runner(index, target):
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    results[index] = target(connection)
            except Exception as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=runner, args=(i, t)) for i, t in enumerate(targets)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)
        self.assertEqual(errors, [])
        return results

    def act(self, order, index):
        return lambda c: service.activate(c, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[index].id)

    def test_simultaneous_first_activations_create_a_single_operational_version_and_assignment(self):
        order = self.make_order(lines=2)
        results = self.run_threads([self.act(order, 0)] * 4)
        self.assertEqual(self.versions(order), [(1, "baseline", True), (2, "operational", True)])
        self.assertEqual(sorted((r.created, r.already_active) for r in results), [(False, True)] * 3 + [(True, False)])
        self.assertEqual(self.assignment_states(), [("active",)])
        self.assertEqual(len({r.assignment.id for r in results}), 1)

    def test_two_different_lines_in_the_same_machine_never_leave_two_active(self):
        order = self.make_order(lines=3)
        self.run_threads([self.act(order, 0), self.act(order, 1), self.act(order, 2)])
        states = [s[0] for s in self.assignment_states()]
        self.assertEqual(sorted(states), ["active", "finished", "finished"])
        self.assertEqual(self.versions(order), [(1, "baseline", True), (2, "operational", True)])

    def test_two_orders_competing_for_the_same_machine_leave_one_active(self):
        one, two = self.make_order(lines=1), self.make_order(lines=1)
        self.run_threads([self.act(one, 0), self.act(two, 0)])
        self.assertEqual(sorted(s[0] for s in self.assignment_states()), ["active", "finished"])

    def test_the_same_line_activated_concurrently_is_idempotent(self):
        order = self.make_order(lines=1)
        results = self.run_threads([self.act(order, 0)] * 5)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 1)
        self.assertEqual(sum(1 for r in results if r.created), 1)
        self.assertEqual(sum(1 for r in results if r.already_active), 4)

    def test_activate_against_finish_leaves_a_coherent_state(self):
        order = self.make_order(lines=2)
        first = self.activate(order, 0).assignment
        self.run_threads([self.act(order, 1), lambda c: service.finish(c, actor_id=self.supervisor, assignment_id=first.id)])
        states = self.connection.execute(
            "SELECT a.status,l.line_code,a.finished_at IS NOT NULL FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id ORDER BY a.created_at").fetchall()
        self.assertEqual(states, [("finished", "L1", True), ("active", "L2", False)])  # either order ends here, never a half-updated row

    def test_concurrent_finishes_are_idempotent(self):
        order = self.make_order(lines=1)
        active = self.activate(order, 0).assignment
        results = self.run_threads([lambda c: service.finish(c, actor_id=self.supervisor, assignment_id=active.id)] * 4)
        self.assertEqual({r.finished_at for r in results}, {results[0].finished_at})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='assignment' AND action='UPDATE' AND entity_key->>'id'=%s", (str(active.id),)), 1)


if __name__ == "__main__":
    unittest.main()
