"""MF13-03.B PR3: several active assignments of the SAME work order on a machine (migration 0011 + assignment service).

Runs in ephemeral *_test databases copied from a migrated template with the reference bundle (sectors BOBINAS/REBOBINADO, machines
MP1/MP3, shifts DIA/NOCHE for BOBINAS). Each test adds a synthetic machine RB1 (REBOBINADO) and an inactive-able machine MPX.
Nothing touches vinto, vinto_piloto or any server.
"""

import secrets
import threading
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app.assignments import service as _assignments
from app.assignments.errors import (AssignmentNotFoundError, BaselineLineNotFoundError, MachineBusyWithOtherWorkOrderError,
                                    MultipleActiveAssignmentsError, WorkOrderNotActivatableError)
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.shifts import ShiftResolutionError
from app.work_orders import service as _work_orders
from app.work_orders.errors import MultiMachineDisabledError, WorkOrderNotFoundError
from app.work_orders.service import LineInput

try:
    from scope_helpers import internal
except ModuleNotFoundError:
    from tests.scope_helpers import internal

service = internal(_assignments)
work_orders = internal(_work_orders)

BUNDLE = load_bundle()
STATE = {}
DUE = date(2026, 10, 30)
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 America/La_Paz -> DIA, 2026-10-06
NIGHT = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)  # 21:00 America/La_Paz -> NOCHE, 2026-10-06


def codes_of(machine):
    return sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == machine)


MP1_CODES, MP3_CODES = codes_of("MP1"), codes_of("MP3")
MP3_ONLY = [c for c in MP3_CODES if c not in MP1_CODES]
MP1_ONLY = [c for c in MP1_CODES if c not in MP3_CODES]
RB1_ARTICLE = MP1_ONLY[1]


def setUpModule():
    STATE["template"] = build_reference_template("vinto_sw_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def line(code, machine=None, pv="PV-1"):
    return LineInput(pv, code, 10, DUE, machine)


class SameOrderCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_sw")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.jefatura = self.make_user("JEFATURA")
        self.supervisor = self.make_user("SUPERVISION")
        self.supervisor_b = self.make_user("SUPERVISION")
        c = self.connection
        c.execute("SELECT set_config('vinto.reason','mf13-03b pr3 fixture',false)")
        rebobinado = c.execute("SELECT id FROM vinto_master.sector WHERE code='REBOBINADO'").fetchone()[0]
        bobinas = c.execute("SELECT id FROM vinto_master.sector WHERE code='BOBINAS'").fetchone()[0]
        c.execute("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'RB1','RB1')", (rebobinado,))
        c.execute("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'MPX','MPX')", (bobinas,))
        c.execute("""INSERT INTO vinto_master.article_machine (article_id,machine_id)
                     SELECT a.id,m.id FROM vinto_master.article a, vinto_master.machine m WHERE a.code=%s AND m.code IN ('RB1','MPX')""", (RB1_ARTICLE,))
        self.patch_now(DAY)

    def patch_now(self, value):
        patcher = patch.object(_assignments, "_now", return_value=value)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._now_patch = patcher
        return patcher

    def gate(self, value=True):
        patcher = patch.object(settings, "work_orders_multi_machine_enabled", value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher

    def make_user(self, profile):
        return create_user(self.connection, username=f"sw.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile,
                           password="pw-" + secrets.token_urlsafe(18)).user_id

    def order(self, lines, machine="MP1", publish=True):
        view = work_orders.create_work_order(self.connection, actor_id=self.jefatura, machine_code=machine, lines=lines)
        if publish:
            view = work_orders.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=view.id)
        return view

    def same_machine_order(self, count=2, machine="MP1"):
        codes = MP1_CODES if machine == "MP1" else MP3_CODES
        return self.order([line(codes[i], pv=f"PV-{i + 1}") for i in range(count)], machine=machine)

    def mixed_order(self):
        """L1, L2 in MP1 and L3 in MP3 (needs the gate on while it is created)."""
        return self.order([line(MP1_CODES[0], "MP1", "PV-1"), line(MP1_CODES[1], "MP1", "PV-2"), line(MP3_ONLY[0], "MP3", "PV-3")])

    def activate(self, order, index=0, actor=None, connection=None, **kwargs):
        return service.activate(connection or self.connection, actor_id=actor or self.supervisor, work_order_id=order.id,
                                baseline_line_id=order.baseline.lines[index].id, **kwargs)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def states(self, machine="MP1"):
        return self.connection.execute(
            """SELECT l.line_code, a.status FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id=a.machine_id
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id WHERE m.code=%s ORDER BY a.created_at, a.id""", (machine,)).fetchall()

    def active_codes(self, machine="MP1"):
        return sorted(code for code, status in self.states(machine) if status == "active")

    def audit_events(self):
        return self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='assignment'")

    def rejected(self, operation, sqlstate):
        with self.assertRaises(psycopg.Error) as caught:
            with self.connection.transaction():
                operation()
        self.assertEqual(caught.exception.sqlstate, sqlstate)


class SameOrderActivationTests(SameOrderCase):
    """Areas 1-5, 18: the new semantics with the gate on."""

    def setUp(self):
        super().setUp()
        self.gate(True)

    def test_two_lines_of_one_order_are_active_together_and_the_second_does_not_finish_the_first(self):
        order = self.same_machine_order()
        first = self.activate(order, 0)
        second = self.activate(order, 1)
        self.assertEqual((first.created, second.created), (True, True))
        self.assertIsNone(second.finished_assignment_id)
        self.assertEqual(second.finished_assignment_ids, ())
        self.assertEqual(self.active_codes(), ["L1", "L2"])
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "in_progress")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order.id,)), 1)

    def test_a_mixed_order_activates_each_line_on_its_own_machine(self):
        order = self.mixed_order()
        results = [self.activate(order, i) for i in range(3)]
        self.assertEqual([r.assignment.machine_code for r in results], ["MP1", "MP1", "MP3"])
        self.assertEqual((self.active_codes("MP1"), self.active_codes("MP3")), (["L1", "L2"], ["L3"]))

    def test_another_order_cannot_enter_a_machine_with_active_lines_and_nothing_is_finished(self):
        one = self.same_machine_order(2)
        two = self.same_machine_order(1)
        self.activate(one, 0)
        self.activate(one, 1)
        with self.assertRaises(MachineBusyWithOtherWorkOrderError) as caught:
            self.activate(two, 0)
        self.assertEqual((caught.exception.http_status, caught.exception.code), (409, "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER"))
        self.assertEqual(self.states(), [("L1", "active"), ("L2", "active")])

    def test_a_rejected_activation_rolls_back_the_operational_version_and_the_order_status(self):
        one, two = self.same_machine_order(1), self.same_machine_order(1)
        self.activate(one, 0)
        before = self.audit_events()
        with self.assertRaises(MachineBusyWithOtherWorkOrderError):
            self.activate(two, 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (two.id,)), 1)  # baseline only
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (two.id,)), "published")
        self.assertEqual(self.audit_events(), before)

    def test_reactivating_the_same_line_in_the_same_context_is_idempotent_and_writes_nothing(self):
        order = self.same_machine_order()
        first = self.activate(order, 0)
        self.activate(order, 1)
        events, updated = self.audit_events(), self.scalar("SELECT max(updated_at) FROM vinto_txn.assignment")
        again = self.activate(order, 0, actor=self.supervisor_b)
        self.assertEqual((again.created, again.already_active, again.assignment.id), (False, True, first.assignment.id))
        self.assertEqual((self.audit_events(), self.scalar("SELECT max(updated_at) FROM vinto_txn.assignment")), (events, updated))
        self.assertEqual(self.active_codes(), ["L1", "L2"])

    def test_a_traditional_single_machine_order_also_gets_the_new_semantics_with_the_gate_on(self):
        order = self.same_machine_order(3, machine="MP3")
        for index in range(3):
            self.activate(order, index)
        self.assertEqual(self.active_codes("MP3"), ["L1", "L2", "L3"])


class ShiftAndHistoryTests(SameOrderCase):
    """Areas 11-14: expired assignments, history and capture references."""

    def setUp(self):
        super().setUp()
        self.gate(True)

    def test_a_new_shift_finishes_the_expired_lines_of_the_machine_and_keeps_their_context(self):
        order = self.same_machine_order()
        a1, a2 = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        before = {r[0]: r for r in self.connection.execute(
            "SELECT id, work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by FROM vinto_txn.assignment").fetchall()}
        self.patch_now(NIGHT)
        night = self.activate(order, 0)
        self.assertEqual(set(night.finished_assignment_ids), {a1.id, a2.id})
        self.assertIsNone(night.finished_assignment_id)  # two were finished: the legacy single-id field is never an arbitrary pick
        self.assertEqual(self.states(), [("L1", "finished"), ("L2", "finished"), ("L1", "active")])
        for assignment_id, row in before.items():  # the historical context of the old rows is untouched
            now = self.connection.execute("SELECT id, work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by FROM vinto_txn.assignment WHERE id=%s", (assignment_id,)).fetchone()
            self.assertEqual(now, row)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='finished' AND finished_at IS NULL"), 0)

    def test_expired_lines_of_another_order_do_not_block_a_new_order_in_the_next_shift(self):
        one, two = self.same_machine_order(1), self.same_machine_order(1)
        old = self.activate(one, 0).assignment
        self.patch_now(NIGHT)
        result = self.activate(two, 0)
        self.assertEqual((result.created, result.finished_assignment_id), (True, old.id))
        self.assertEqual(self.states(), [("L1", "finished"), ("L1", "active")])

    def test_a_new_operating_date_expires_the_previous_day(self):
        order = self.same_machine_order()
        old = self.activate(order, 0).assignment
        self.patch_now(datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc))  # DIA of the next operating date
        new = self.activate(order, 0)
        self.assertEqual((new.created, new.finished_assignment_id), (True, old.id))

    def test_the_machine_without_a_resolvable_shift_writes_nothing(self):
        order = self.same_machine_order()
        before = self.audit_events()
        self.patch_now(datetime(1990, 1, 1, tzinfo=timezone.utc))
        with self.assertRaises(ShiftResolutionError):
            self.activate(order, 0)
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.assignment"), self.audit_events()), (0, before))

    def test_a_finished_line_is_reactivated_with_a_new_row_and_the_old_one_is_history(self):
        order = self.same_machine_order(1)
        first = self.activate(order, 0).assignment
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=first.id)
        finished_at = self.scalar("SELECT finished_at FROM vinto_txn.assignment WHERE id=%s", (first.id,))
        again = self.activate(order, 0)
        self.assertTrue(again.created)
        self.assertNotEqual(again.assignment.id, first.id)
        self.assertEqual(self.scalar("SELECT finished_at FROM vinto_txn.assignment WHERE id=%s", (first.id,)), finished_at)
        self.assertEqual(self.states(), [("L1", "finished"), ("L1", "active")])

    def test_finishing_one_line_leaves_the_others_active(self):
        order = self.same_machine_order()
        first = self.activate(order, 0).assignment
        self.activate(order, 1)
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=first.id)
        self.assertEqual(self.states(), [("L1", "finished"), ("L2", "active")])

    def test_the_capture_foreign_key_still_points_at_the_assignment_identity(self):
        row = self.connection.execute(
            """SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c WHERE c.conrelid='vinto_txn.capture'::regclass AND c.contype='f'
               AND c.confrelid='vinto_txn.assignment'::regclass""").fetchall()
        self.assertEqual(len(row), 1)
        self.assertIn("(assignment_id, machine_id, shift_schedule_id, operating_date)", row[0][0])
        self.assertIn("REFERENCES vinto_txn.assignment(id, machine_id, shift_schedule_id, operating_date)", row[0][0])


class ValidationTests(SameOrderCase):
    """Areas 9-10: scope, inactive machine, wrong line."""

    def setUp(self):
        super().setUp()
        self.gate(True)

    def test_a_supervisor_without_the_sector_sees_the_order_as_missing(self):
        order = self.same_machine_order()
        with self.assertRaises(WorkOrderNotFoundError):
            service.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id, sectors=("REBOBINADO",))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 0)

    def test_a_line_of_an_unauthorized_machine_is_indistinguishable_from_a_missing_line(self):
        order = self.order([line(MP1_CODES[0], "MP1", "PV-1"), line(RB1_ARTICLE, "RB1", "PV-2")])
        with self.assertRaises(BaselineLineNotFoundError):  # BOBINAS-only supervisor: RB1 belongs to REBOBINADO
            service.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[1].id, sectors=("BOBINAS",))
        self.assertTrue(service.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id, sectors=("BOBINAS",)).created)

    def test_an_inactive_line_machine_cannot_be_activated(self):
        order = self.order([line(MP1_CODES[0], "MP1", "PV-1"), line(RB1_ARTICLE, "MPX", "PV-2")])
        self.connection.execute("UPDATE vinto_master.machine SET active=false WHERE code='MPX'")
        with self.assertRaises(WorkOrderNotActivatableError):
            self.activate(order, 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 0)

    def test_a_line_from_another_order_is_not_found(self):
        one, two = self.same_machine_order(1), self.same_machine_order(1)
        with self.assertRaises(BaselineLineNotFoundError):
            service.activate(self.connection, actor_id=self.supervisor, work_order_id=one.id, baseline_line_id=two.baseline.lines[0].id)

    def test_the_machine_of_a_published_line_cannot_change(self):
        order = self.same_machine_order(1)
        self.rejected(lambda: self.connection.execute("UPDATE vinto_txn.work_order_line SET machine_id=(SELECT id FROM vinto_master.machine WHERE code='MP3') WHERE id=%s", (order.baseline.lines[0].id,)), "23514")


class DirectSqlTests(SameOrderCase):
    """Area 15: the database refuses inconsistent rows even when written without the service."""

    def setUp(self):
        super().setUp()
        self.gate(True)
        self.one, self.two = self.same_machine_order(2), self.same_machine_order(1)
        self.a1 = self.activate(self.one, 0).assignment
        self.active = self.connection.execute(
            "SELECT work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by FROM vinto_txn.assignment WHERE id=%s", (self.a1.id,)).fetchone()

    def operational_line(self, order, code):
        return self.scalar(
            """SELECT l.id FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE v.work_order_id=%s AND v.kind='operational' AND l.line_code=%s""", (order.id, code))

    def insert(self, line_id):
        return self.connection.execute(
            "INSERT INTO vinto_txn.assignment (work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (line_id, self.active[1], self.active[2], self.active[3], self.active[4])).fetchone()[0]

    def test_a_second_active_row_for_the_same_line_is_rejected(self):
        self.rejected(lambda: self.insert(self.active[0]), "23505")

    def test_an_active_row_of_another_order_on_the_machine_is_rejected(self):
        # Build the other order's operational line on MP1 while MP1 is free (finish L1 first), then try to reactivate L1 of the first order.
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=self.a1.id)
        done = self.activate(self.two, 0).assignment  # OT2 L1 active on MP1
        self.assertEqual(self.active_codes(), ["L1"])
        self.rejected(lambda: self.insert(self.operational_line(self.one, "L2")), "23P01")
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (done.id,)), "active")

    def test_a_finished_assignment_cannot_be_reactivated(self):
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=self.a1.id)
        self.rejected(lambda: self.connection.execute("UPDATE vinto_txn.assignment SET status='active', finished_at=NULL WHERE id=%s", (self.a1.id,)), "23514")

    def test_identity_columns_are_immutable(self):
        other_line = self.operational_line(self.one, "L2")
        self.rejected(lambda: self.connection.execute("UPDATE vinto_txn.assignment SET work_order_line_id=%s WHERE id=%s", (other_line, self.a1.id)), "23514")
        self.rejected(lambda: self.connection.execute(
            "UPDATE vinto_txn.assignment SET machine_id=(SELECT id FROM vinto_master.machine WHERE code='MP3') WHERE id=%s", (self.a1.id,)), "23514")
        self.rejected(lambda: self.connection.execute("UPDATE vinto_txn.assignment SET operating_date=operating_date+1 WHERE id=%s", (self.a1.id,)), "23514")

    def test_the_line_machine_must_match_the_assignment_machine(self):
        mp3 = self.scalar("SELECT id FROM vinto_master.machine WHERE code='MP3'")
        self.rejected(lambda: self.connection.execute(
            "INSERT INTO vinto_txn.assignment (work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by) VALUES (%s,%s,%s,%s,%s)",
            (self.operational_line(self.one, "L2"), mp3, self.active[2], self.active[3], self.active[4])), "23514")

    def test_the_old_index_is_gone_and_the_new_protections_exist(self):
        indexes = {r[0] for r in self.connection.execute("SELECT indexname FROM pg_indexes WHERE schemaname='vinto_txn' AND tablename='assignment'").fetchall()}
        self.assertNotIn("assignment_one_active_machine", indexes)
        self.assertIn("assignment_one_active_line", indexes)
        self.assertEqual(self.scalar("SELECT tgenabled FROM pg_trigger WHERE tgname='validate_assignment_exclusivity'"), "O")

    def test_audit_and_touch_triggers_stay_active_on_assignment(self):
        names = {r[0] for r in self.connection.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='vinto_txn.assignment'::regclass AND NOT tgisinternal AND tgenabled='O'").fetchall()}
        self.assertTrue({"z_touch", "audit_changes", "validate_assignment", "validate_assignment_exclusivity"} <= names)

    def test_a_rolled_back_direct_insert_leaves_nothing(self):
        before = (self.scalar("SELECT count(*) FROM vinto_txn.assignment"), self.audit_events())
        self.rejected(lambda: self.insert(self.active[0]), "23505")
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.assignment"), self.audit_events()), before)


class GateOffTests(SameOrderCase):
    """Areas 16-17: historical semantics, and what happens when the gate is switched off after several lines were active."""

    def test_with_the_gate_off_a_new_line_replaces_the_previous_one(self):
        order = self.same_machine_order()
        first = self.activate(order, 0)
        second = self.activate(order, 1)
        self.assertEqual((second.created, second.finished_assignment_id, second.finished_assignment_ids), (True, first.assignment.id, (first.assignment.id,)))
        self.assertEqual(self.states(), [("L1", "finished"), ("L2", "active")])

    def test_with_the_gate_off_another_order_replaces_the_previous_one_as_before(self):
        one, two = self.same_machine_order(1), self.same_machine_order(1)
        self.activate(one, 0)
        self.activate(two, 0)
        self.assertEqual(self.states(), [("L1", "finished"), ("L1", "active")])

    def test_with_the_gate_off_a_line_on_another_machine_than_the_header_is_rejected(self):
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.mixed_order()
        with self.assertRaises(MultiMachineDisabledError):
            self.activate(order, 2)  # L3 lives on MP3, the header is MP1
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 0)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "published")

    def test_switching_the_gate_off_with_several_active_lines_neither_hides_nor_finishes_anything(self):
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(3)
            for index in range(3):
                self.activate(order, index)
        before = self.states()
        events = self.audit_events()
        again = self.activate(order, 0, actor=self.supervisor_b)  # a line that is already active stays idempotent: nothing to replace, nothing written
        self.assertEqual((again.created, again.already_active), (False, True))
        intruder = self.same_machine_order(1)
        with self.assertRaises(MultipleActiveAssignmentsError) as caught:  # anything that would replace one of several must be resolved explicitly
            self.activate(intruder, 0)
        self.assertEqual((caught.exception.http_status, caught.exception.code), (409, "MULTIPLE_ACTIVE_ASSIGNMENTS"))
        self.assertEqual((self.states(), self.audit_events()), (before, events))
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (intruder.id,)), "published")
        with self.assertRaises(MultipleActiveAssignmentsError):  # legacy single-assignment query refuses to pick one
            service.get_active(self.connection, machine_code="MP1", sectors=("BOBINAS",))
        listing = service.get_active_lines(self.connection, machine_code="MP1", sectors=("BOBINAS",))
        self.assertEqual([i.assignment.line.line_code for i in listing.items], ["L1", "L2", "L3"])
        rows = service.list_assignments(self.connection, machine_code="MP1", status="active", sectors=("BOBINAS",))
        self.assertEqual(len(rows), 3)
        # Explicit, audited resolution: finish two, the remaining one is the single legacy assignment again.
        for item in listing.items[:2]:
            service.finish(self.connection, actor_id=self.supervisor, assignment_id=item.assignment.id)
        self.assertEqual(service.get_active(self.connection, machine_code="MP1", sectors=("BOBINAS",)).assignment.line.line_code, "L3")
        replaced = self.activate(order, 0)  # historical replacement works again
        self.assertEqual((replaced.created, len(replaced.finished_assignment_ids)), (True, 1))

    def test_the_active_queries_with_zero_or_one_assignment_keep_the_historical_shape(self):
        empty = service.get_active(self.connection, machine_code="MP1", sectors=("BOBINAS",))
        self.assertIsNone(empty.assignment)
        order = self.same_machine_order(1)
        activated = self.activate(order, 0).assignment
        one = service.get_active(self.connection, machine_code="MP1", sectors=("BOBINAS",))
        self.assertEqual((one.assignment.id, one.stale), (activated.id, False))
        lines = service.get_active_lines(self.connection, machine_code="MP1", sectors=("BOBINAS",))
        self.assertEqual([(i.assignment.id, i.stale) for i in lines.items], [(activated.id, False)])


class ConcurrencyTests(SameOrderCase):
    """Areas 6-7: serialisation per machine, including direct SQL against the trigger lock."""

    def setUp(self):
        super().setUp()
        self.gate(True)

    def run_threads(self, targets):
        outcomes, barrier = [None] * len(targets), threading.Barrier(len(targets))

        def runner(index, target):
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    outcomes[index] = ("ok", target(connection))
            except Exception as error:
                outcomes[index] = ("error", error)

        threads = [threading.Thread(target=runner, args=(i, t)) for i, t in enumerate(targets)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=90)
        return outcomes

    def act(self, order, index, actor=None):
        return lambda c: service.activate(c, actor_id=actor or self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[index].id)

    def test_two_supervisors_repeating_the_same_activation_create_one_row(self):
        order = self.same_machine_order(1)
        outcomes = self.run_threads([self.act(order, 0, self.supervisor), self.act(order, 0, self.supervisor_b)] * 2)
        self.assertEqual([o[0] for o in outcomes], ["ok"] * 4)
        self.assertEqual(sorted(o[1].created for o in outcomes), [False, False, False, True])
        self.assertEqual(self.states(), [("L1", "active")])

    def test_concurrent_lines_of_one_order_all_end_active(self):
        order = self.same_machine_order(3)
        outcomes = self.run_threads([self.act(order, i) for i in range(3)])
        self.assertEqual([o[0] for o in outcomes], ["ok"] * 3)
        self.assertEqual(self.active_codes(), ["L1", "L2", "L3"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order.id,)), 1)

    def test_two_orders_competing_for_one_machine_leave_exactly_one_winner_and_finish_nothing(self):
        one, two = self.same_machine_order(1), self.same_machine_order(1)
        outcomes = self.run_threads([self.act(one, 0), self.act(two, 0)])
        kinds = sorted(o[0] for o in outcomes)
        self.assertEqual(kinds, ["error", "ok"])
        self.assertIsInstance(next(o[1] for o in outcomes if o[0] == "error"), MachineBusyWithOtherWorkOrderError)
        self.assertEqual(sorted(status for _, status in self.states()), ["active"])

    def test_the_trigger_alone_serialises_direct_sql_writers(self):
        """Two transactions insert active rows of different orders WITHOUT the service: the machine lock inside the trigger makes the second see the first."""
        one, two = self.same_machine_order(1), self.same_machine_order(1)
        for order in (one, two):  # create the operational versions through a finished cycle so the lines exist
            done = self.activate(order, 0).assignment
            service.finish(self.connection, actor_id=self.supervisor, assignment_id=done.id)
        lines = self.connection.execute(
            """SELECT l.id, l.machine_id FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE v.kind='operational' AND v.work_order_id = ANY(%s) ORDER BY v.work_order_id""", ([one.id, two.id],)).fetchall()
        schedule, day = self.connection.execute("SELECT shift_schedule_id, operating_date FROM vinto_txn.assignment LIMIT 1").fetchone()

        def raw_insert(line_id, machine_id):
            def run(c):
                c.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(self.supervisor),))
                c.execute("SELECT set_config('vinto.reason', 'direct sql', false)")
                with c.transaction():
                    c.execute("INSERT INTO vinto_txn.assignment (work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by) VALUES (%s,%s,%s,%s,%s)",
                              (line_id, machine_id, schedule, day, self.supervisor))
                    c.execute("SELECT pg_sleep(0.3)")  # hold the lock past the other transaction's attempt
            return run

        outcomes = self.run_threads([raw_insert(*lines[0]), raw_insert(*lines[1])])
        self.assertEqual(sorted(o[0] for o in outcomes), ["error", "ok"])
        error = next(o[1] for o in outcomes if o[0] == "error")
        self.assertEqual(getattr(error, "sqlstate", None), "23P01")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 1)

    def test_the_trigger_waits_on_the_very_lock_the_service_takes(self):
        """If the SQL key differed from app.assignments.service._machine_lock the trigger would not serialise with activate/finish."""
        order = self.same_machine_order(1)
        done = self.activate(order, 0).assignment
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=done.id)
        machine_id, line_id, schedule, day = self.connection.execute(
            """SELECT a.machine_id, a.work_order_line_id, a.shift_schedule_id, a.operating_date FROM vinto_txn.assignment a WHERE a.id=%s""", (done.id,)).fetchone()
        holder = connect(self.database)
        self.addCleanup(holder.close)
        with holder.transaction():
            service._machine_lock(holder, machine_id)  # the service's lock, held by another session
            self.connection.execute("SET lock_timeout = '300ms'")
            self.addCleanup(self.connection.execute, "RESET lock_timeout")
            self.rejected(lambda: self.connection.execute(
                "INSERT INTO vinto_txn.assignment (work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by) VALUES (%s,%s,%s,%s,%s)",
                (line_id, machine_id, schedule, day, self.supervisor)), "55P03")  # lock_not_available: the trigger tried to take the same key

    def test_activation_and_finish_in_opposite_order_do_not_deadlock(self):
        order = self.same_machine_order(2)
        first = self.activate(order, 0).assignment
        outcomes = self.run_threads([self.act(order, 1), lambda c: service.finish(c, actor_id=self.supervisor, assignment_id=first.id),
                                     lambda c: service.finish(c, actor_id=self.supervisor_b, assignment_id=first.id)])
        self.assertEqual([o[0] for o in outcomes], ["ok"] * 3)
        self.assertEqual(self.states(), [("L1", "finished"), ("L2", "active")])


class PrivilegeTests(SameOrderCase):
    """Area 20: the exclusivity function is a trigger (not callable) and the application role has what it needs to run it."""

    def test_the_function_is_not_callable_as_a_regular_function(self):
        with self.assertRaises(psycopg.Error):
            with self.connection.transaction():
                self.connection.execute("SELECT vinto_txn.validate_assignment_exclusivity()")

    def test_the_trigger_function_runs_as_the_invoker_without_security_definer(self):
        self.assertFalse(self.scalar("SELECT prosecdef FROM pg_proc WHERE proname='validate_assignment_exclusivity'"))

    def test_the_application_role_can_read_what_the_trigger_reads_and_write_assignments(self):
        if not self.scalar("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app')"):
            self.skipTest("role vinto_app does not exist in this cluster (created only by roles/00_create_roles.sql)")
        for table, privilege in (("assignment", "SELECT"), ("assignment", "INSERT"), ("assignment", "UPDATE"), ("work_order_line", "SELECT"), ("work_order_version", "SELECT")):
            self.assertTrue(self.scalar("SELECT has_table_privilege('vinto_app', %s, %s)", (f"vinto_txn.{table}", privilege)), (table, privilege))

    def test_the_grants_file_gives_the_application_role_the_privileges_the_trigger_needs(self):
        import pathlib
        text = pathlib.Path(__file__).resolve().parents[1].joinpath("roles", "03_table_grants.sql").read_text(encoding="utf-8")
        self.assertIn("vinto_txn.assignment", text)
        self.assertIn("vinto_txn.work_order_line", text)
        self.assertIn("vinto_txn.work_order_version", text)


class MigrationRehearsalTests(SameOrderCase):
    """Area 9 of the plan: apply the real 0011 file over representative legacy data, compare, and exercise the rollback script."""

    ROLLBACK = None

    def paths(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        return (root / "migrations" / "0011_assignment_same_work_order_lines.sql", root / "rollbacks" / "0011_assignment_same_work_order_lines_rollback.sql")

    def snapshot(self):
        return (self.connection.execute("SELECT to_jsonb(a) - 'updated_at' FROM vinto_txn.assignment a ORDER BY id").fetchall(),
                self.connection.execute("SELECT to_jsonb(c) - 'updated_at' FROM vinto_txn.capture c ORDER BY id").fetchall())

    def test_rollback_then_reapply_preserves_every_assignment_and_capture_row(self):
        migration, rollback = self.paths()
        one, two = self.same_machine_order(1), self.same_machine_order(1, machine="MP3")
        done = self.activate(one, 0).assignment
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=done.id)
        self.activate(one, 0)
        self.activate(two, 0)
        before = self.snapshot()
        schema_row = self.scalar("SELECT checksum FROM vinto_meta.schema_migration WHERE version = 11")
        with self.connection.transaction():
            self.connection.execute(rollback.read_text(encoding="utf-8"))
            self.assertEqual(self.scalar("SELECT count(*) FROM pg_indexes WHERE indexname='assignment_one_active_machine'"), 1)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_meta.schema_migration WHERE version = 11"), 0)
            self.assertEqual(self.snapshot(), before)
            self.connection.execute(migration.read_text(encoding="utf-8"))  # same data accepted again by the new rules
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.scalar("SELECT count(*) FROM pg_indexes WHERE indexname='assignment_one_active_machine'"), 0)
            self.connection.execute("INSERT INTO vinto_meta.schema_migration (version, filename, checksum) VALUES (11, '0011_assignment_same_work_order_lines.sql', %s)", (schema_row,))
        self.assertEqual(self.snapshot(), before)

    def test_rollback_is_refused_while_a_machine_has_several_active_assignments(self):
        _, rollback = self.paths()
        with patch.object(settings, "work_orders_multi_machine_enabled", True):
            order = self.same_machine_order(2)
            self.activate(order, 0)
            self.activate(order, 1)
        before = self.snapshot()
        with self.assertRaises(psycopg.Error) as caught:
            with self.connection.transaction():
                self.connection.execute(rollback.read_text(encoding="utf-8"))
        self.assertIn("Rollback refused", str(caught.exception))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.active_codes(), ["L1", "L2"])
        self.assertEqual(self.scalar("SELECT count(*) FROM pg_indexes WHERE indexname='assignment_one_active_machine'"), 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_meta.schema_migration WHERE version = 11"), 1)


class CaptureCompatibilityTests(SameOrderCase):
    """Area 19: F3 captures go through `assignment_id`, so every active line of the machine can be captured and keeps its own reference."""

    def setUp(self):
        super().setUp()
        self.gate(True)
        self._now_patch.stop()  # captures resolve the shift with the real clock; assignments must use it too

    def test_each_active_line_accepts_its_own_f3_capture(self):
        from app.bobbins import service as bobbins_service
        bobbins = internal(bobbins_service)
        articles = {a["code"]: a["version"] for a in BUNDLE.articles}
        with_grammage = [c for c in MP1_CODES if articles[c]["grammage_g_m2"] is not None][:2]
        order = self.order([line(with_grammage[0], pv="PV-1"), line(with_grammage[1], pv="PV-2")])
        a1, a2 = self.activate(order, 0).assignment, self.activate(order, 1).assignment
        operator = self.make_user("OPERACION")
        values = {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25", "numero_de_cortes": "3", "observaciones": "ok"}
        for assignment in (a1, a2, a1):  # a1 again AFTER a2 was activated: it must still be capturable
            bobbins.submit_bobbin_production(self.connection, actor_id=operator, capture_id=uuid4(), assignment_id=assignment.id, device_key=str(uuid4()), values=values)
        refs = self.connection.execute("SELECT assignment_id, count(*) FROM vinto_txn.capture GROUP BY assignment_id").fetchall()
        self.assertEqual(sorted((str(a), n) for a, n in refs), sorted([(str(a1.id), 2), (str(a2.id), 1)]))
        self.assertEqual(self.active_codes(), ["L1", "L2"])


class FinishCompatibilityTests(SameOrderCase):
    def test_finish_of_an_unknown_assignment_is_not_found(self):
        with self.assertRaises(AssignmentNotFoundError):
            service.finish(self.connection, actor_id=self.supervisor, assignment_id=uuid4())


if __name__ == "__main__":
    unittest.main()
