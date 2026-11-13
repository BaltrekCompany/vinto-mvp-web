"""MF13-03.B PR4: bulk activation of all lines of one work order (preview + confirm) in the assignment service.

Reuses the PR3 fixtures (ephemeral *_test databases from a migrated template; synthetic machine RB1 in REBOBINADO without shifts, MPX).
Nothing touches vinto, vinto_piloto or any server. Concurrency is synchronised with a barrier and database locks, never with sleeps.
"""

import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app.assignments import service as _assignments
from app.assignments.errors import ActivationBlockedError, ActivationPlanChangedError, WorkOrderNotActivatableError
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.work_orders.errors import MultiMachineDisabledError, WorkOrderNotFoundError

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base

service, line, MP1_CODES, MP3_ONLY, RB1_ARTICLE = base.service, base.line, base.MP1_CODES, base.MP3_ONLY, base.RB1_ARTICLE
DAY, NIGHT = base.DAY, base.NIGHT


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_aa_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])


class BulkCase(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        self.order3 = self.mixed_order()  # L1, L2 on MP1 and L3 on MP3

    def preview(self, order=None, **kwargs):
        return service.preview_activate_all(self.connection, work_order_id=(order or self.order3).id, **kwargs)

    def confirm(self, plan_hash, order=None, connection=None, actor=None, **kwargs):
        return service.activate_all(connection or self.connection, actor_id=actor or self.supervisor, work_order_id=(order or self.order3).id,
                                    plan_hash=plan_hash, **kwargs)

    def snapshot(self):
        c = self.connection
        return {name: c.execute(query).fetchall() for name, query in (
            ("assignments", "SELECT to_jsonb(a) FROM vinto_txn.assignment a ORDER BY id"),
            ("versions", "SELECT to_jsonb(v) FROM vinto_txn.work_order_version v ORDER BY id"),
            ("lines", "SELECT to_jsonb(l) FROM vinto_txn.work_order_line l ORDER BY id"),
            ("orders", "SELECT to_jsonb(w) FROM vinto_txn.work_order w ORDER BY id"),
            ("audit", "SELECT count(*) FROM vinto_audit.audit_event"))}

    def active(self):
        return self.connection.execute(
            """SELECT l.line_code, m.code FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_master.machine m ON m.id=a.machine_id WHERE a.status='active' ORDER BY l.line_code""").fetchall()

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


class ReprogrammedPreviewTests(BulkCase):
    """A preview approved before reprogramming must never confirm newer content."""

    def test_revision_changes_preview_and_stale_plan_is_rejected(self):
        from app.work_orders import reprogramming
        from app.work_orders.service import LineInput
        initial = self.preview().plan
        self.assertTrue(initial.can_confirm)
        first = self.order3.baseline.lines[0]
        new_quantity = first.quantity + 30
        reprogramming.reprogram_published_line(
            self.connection, actor_id=self.jefatura, work_order_id=self.order3.id,
            line_code=first.line_code, expected_version=1,
            expected=LineInput(first.pv_reference, first.article_code, first.quantity, first.due_date),
            replacement=LineInput("PV-CORREGIDO", first.article_code, new_quantity, first.due_date),
            reason="Incremento de programación antes de habilitar la línea",
            sectors=("BOBINAS",))
        new_plan = self.preview().plan
        self.assertNotEqual(initial.plan_hash, new_plan.plan_hash)
        self.assertEqual(new_plan.lines[0].pv_reference, "PV-CORREGIDO")
        self.assertEqual(new_plan.lines[0].article_code, first.article_code)
        with self.assertRaises(ActivationPlanChangedError):
            self.confirm(initial.plan_hash)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 0)
        activated = self.confirm(new_plan.plan_hash)
        self.assertEqual(activated.outcome, "applied")
        self.assertEqual(activated.activated[0].line.quantity, new_quantity)
        self.assertEqual(activated.activated[0].operational_version_number, 2)


class PreviewTests(BulkCase):
    def test_the_preview_lists_the_three_lines_with_machines_shift_and_hash(self):
        plan = self.preview().plan
        self.assertEqual([(l.line_code, l.machine_code, l.action) for l in plan.lines], [("L1", "MP1", "activate"), ("L2", "MP1", "activate"), ("L3", "MP3", "activate")])
        self.assertTrue(plan.can_confirm)
        self.assertFalse(plan.noop)
        self.assertEqual({(l.shift_code, str(l.operating_date)) for l in plan.lines}, {("DIA", "2026-10-06")})
        self.assertRegex(plan.plan_hash, r"^[a-f0-9]{64}$")
        self.assertEqual((plan.expired, plan.conflicts), ((), ()))

    def test_the_preview_is_deterministic(self):
        self.assertEqual(self.preview().plan.plan_hash, self.preview().plan.plan_hash)

    def test_the_preview_writes_nothing_and_creates_no_operational_version(self):
        before = self.snapshot()
        self.preview()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE kind='operational'"), 0)

    def test_the_preview_runs_in_a_read_only_transaction_so_a_write_would_fail(self):
        def sneaky(connection, **kwargs):
            connection.execute("INSERT INTO vinto_txn.work_order_version (work_order_id, version_number, kind) VALUES (%s, 99, 'operational')", (self.order3.id,))
        with patch.object(_assignments, "_build_plan", sneaky):
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                self.preview()

    def test_the_preview_reports_already_active_expired_and_conflicts(self):
        self.activate(self.order3, 0)
        plan = self.preview().plan
        self.assertEqual([l.action for l in plan.lines], ["already_active", "activate", "activate"])
        self.assertIsNotNone(plan.lines[0].assignment_id)
        self.patch_now(NIGHT)
        plan = self.preview().plan
        self.assertEqual([l.action for l in plan.lines], ["activate"] * 3)
        self.assertEqual([e.line_code for e in plan.expired], ["L1"])

    def test_a_draft_or_unpublished_order_cannot_be_previewed(self):
        draft = self.order([line(MP1_CODES[0])], publish=False)
        with self.assertRaises(WorkOrderNotActivatableError):
            self.preview(draft)

    def test_an_unknown_order_is_not_found(self):
        with self.assertRaises(WorkOrderNotFoundError):
            service.preview_activate_all(self.connection, work_order_id=uuid4())
        with self.assertRaises(WorkOrderNotFoundError):
            service.preview_activate_all(self.connection, work_order_id="not-a-uuid")


class ConfirmTests(BulkCase):
    def test_the_confirmation_activates_all_three_lines_on_their_machines_in_one_transaction(self):
        plan_hash = self.preview().plan.plan_hash
        result = self.confirm(plan_hash, request_id="bulk-1")
        self.assertEqual(result.outcome, "applied")
        self.assertEqual([(a.line.line_code, a.machine_code) for a in result.activated], [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        self.assertEqual(self.active(), [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (self.order3.id,)), "in_progress")
        self.assertEqual(len({a.shift_code for a in result.activated}), 1)

    def test_a_line_already_active_in_the_current_shift_is_kept_and_not_duplicated(self):
        first = self.activate(self.order3, 0).assignment
        result = self.confirm(self.preview().plan.plan_hash)
        self.assertEqual([a.id for a in result.already_active], [first.id])
        self.assertEqual(len(result.activated), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE work_order_line_id=(SELECT work_order_line_id FROM vinto_txn.assignment WHERE id=%s)", (first.id,)), 1)

    def test_retrying_a_completed_confirmation_is_idempotent_and_writes_nothing(self):
        plan_hash = self.preview().plan.plan_hash
        first = self.confirm(plan_hash)
        before = self.snapshot()
        again = self.confirm(plan_hash)
        self.assertEqual(again.outcome, "already_in_effect")
        self.assertEqual(sorted(a.id for a in again.already_active), sorted(a.id for a in first.activated))
        self.assertEqual((again.activated, again.finished), ((), ()))
        self.assertEqual(self.snapshot(), before)

    def test_a_confirmation_with_nothing_to_do_applies_no_writes(self):
        self.confirm(self.preview().plan.plan_hash)
        noop_hash = self.preview().plan.plan_hash
        before = self.snapshot()
        self.assertEqual(self.confirm(noop_hash).outcome, "already_in_effect")
        self.assertEqual(self.snapshot(), before)

    def test_a_stale_plan_hash_is_a_409_without_writes(self):
        plan_hash = self.preview().plan.plan_hash
        self.activate(self.order3, 0, actor=self.supervisor_b)  # the state changed after the approved preview
        before = self.snapshot()
        with self.assertRaises(ActivationPlanChangedError) as caught:
            self.confirm(plan_hash)
        self.assertEqual((caught.exception.http_status, caught.exception.code), (409, "ACTIVATION_PLAN_CHANGED"))
        self.assertEqual(self.snapshot(), before)

    def test_a_hash_from_another_shift_or_order_or_garbage_is_rejected_without_writes(self):
        plan_hash = self.preview().plan.plan_hash
        other = self.same_machine_order(1, machine="MP3")
        before = self.snapshot()
        self.patch_now(NIGHT)  # the shift changed between preview and confirmation
        with self.assertRaises(ActivationPlanChangedError):
            self.confirm(plan_hash)
        with self.assertRaises(ActivationPlanChangedError):
            self.confirm(plan_hash, order=other)
        for garbage in ("", "x" * 64, plan_hash.upper(), None, plan_hash[:63]):
            with self.assertRaises(ActivationPlanChangedError):
                self.confirm(garbage)
        self.assertEqual(self.snapshot(), before)

    def test_the_gate_off_rejects_preview_and_confirmation_and_keeps_individual_activation(self):
        plan_hash = self.preview().plan.plan_hash
        self.gate(False)
        before = self.snapshot()
        with self.assertRaises(MultiMachineDisabledError):
            self.preview()
        with self.assertRaises(MultiMachineDisabledError):
            self.confirm(plan_hash)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.activate(self.order3, 0).created)  # the historical individual activation is untouched

    def test_baseline_and_operational_versions_stay_consistent(self):
        baseline = self.connection.execute("SELECT to_jsonb(l) FROM vinto_txn.work_order_line l WHERE work_order_version_id=%s ORDER BY id", (self.order3.baseline.id,)).fetchall()
        version = self.connection.execute("SELECT to_jsonb(v) FROM vinto_txn.work_order_version v WHERE id=%s", (self.order3.baseline.id,)).fetchall()
        plan_hash = self.preview().plan.plan_hash
        self.confirm(plan_hash)
        self.confirm(self.preview().plan.plan_hash)
        self.assertEqual(self.connection.execute("SELECT to_jsonb(l) FROM vinto_txn.work_order_line l WHERE work_order_version_id=%s ORDER BY id", (self.order3.baseline.id,)).fetchall(), baseline)
        self.assertEqual(self.connection.execute("SELECT to_jsonb(v) FROM vinto_txn.work_order_version v WHERE id=%s", (self.order3.baseline.id,)).fetchall(), version)
        operational = self.connection.execute(
            """SELECT v.version_number, v.published_at IS NOT NULL, l.line_code, m.code FROM vinto_txn.work_order_version v
               JOIN vinto_txn.work_order_line l ON l.work_order_version_id=v.id JOIN vinto_master.machine m ON m.id=l.machine_id
               WHERE v.work_order_id=%s AND v.kind='operational' ORDER BY l.line_code""", (self.order3.id,)).fetchall()
        self.assertEqual(operational, [(2, True, "L1", "MP1"), (2, True, "L2", "MP1"), (2, True, "L3", "MP3")])

    def test_actor_request_id_and_reason_are_audited_on_every_row_of_the_operation(self):
        plan_hash = self.preview().plan.plan_hash
        self.confirm(plan_hash, request_id="bulk-audit-1")
        rows = self.connection.execute(
            """SELECT actor_id, request_id, reason FROM vinto_audit.audit_event
               WHERE entity_table='assignment' AND action='INSERT' ORDER BY id""").fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual({(r[0], r[1]) for r in rows}, {(self.supervisor, "bulk-audit-1")})
        self.assertEqual({r[2] for r in rows}, {f"activate assignment [activate-all {plan_hash}]"})
        versions = self.connection.execute("SELECT DISTINCT request_id, actor_id FROM vinto_audit.audit_event WHERE entity_table IN ('work_order_version','work_order') AND request_id='bulk-audit-1'").fetchall()
        self.assertEqual(versions, [("bulk-audit-1", self.supervisor)])


class BlockedTests(BulkCase):
    def assert_rejected_without_writes(self, plan_hash, error):
        before = self.snapshot()
        with self.assertRaises(error):
            self.confirm(plan_hash)
        self.assertEqual(self.snapshot(), before)

    def test_another_order_active_on_a_machine_blocks_everything_and_is_never_finished(self):
        other = self.same_machine_order(1)
        theirs = self.activate(other, 0).assignment  # OT2 L1 active on MP1
        plan = self.preview().plan
        self.assertFalse(plan.can_confirm)
        self.assertEqual([(l.line_code, l.action, l.reason) for l in plan.lines], [("L1", "blocked", "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER"),
                                                                                  ("L2", "blocked", "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER"), ("L3", "activate", None)])
        self.assertEqual([(c.assignment_id, c.work_order_number, c.expired) for c in plan.conflicts], [(theirs.id, other.number, False)])
        self.assert_rejected_without_writes(plan.plan_hash, ActivationBlockedError)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (theirs.id,)), "active")

    def test_an_expired_assignment_of_another_order_is_still_a_conflict_and_is_not_finished(self):
        other = self.same_machine_order(1)
        theirs = self.activate(other, 0).assignment
        self.patch_now(NIGHT)
        plan = self.preview().plan
        self.assertEqual([(c.assignment_id, c.expired) for c in plan.conflicts], [(theirs.id, True)])
        self.assert_rejected_without_writes(plan.plan_hash, ActivationBlockedError)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (theirs.id,)), "active")

    def test_an_inactive_machine_blocks_everything(self):
        self.connection.execute("UPDATE vinto_master.machine SET active=false WHERE code='MP3'")
        plan = self.preview().plan
        self.assertEqual([(l.line_code, l.action, l.reason) for l in plan.lines], [("L1", "activate", None), ("L2", "activate", None), ("L3", "blocked", "MACHINE_INACTIVE")])
        self.assert_rejected_without_writes(plan.plan_hash, ActivationBlockedError)

    def test_a_line_without_a_resolvable_shift_is_not_eligible_and_blocks_everything(self):
        order = self.order([line(MP1_CODES[0], "MP1", "PV-1"), line(RB1_ARTICLE, "RB1", "PV-2")])
        self.connection.execute("UPDATE vinto_config.shift_schedule SET valid_from='2019-01-01', valid_to='2020-01-01' WHERE sector_id=(SELECT id FROM vinto_master.sector WHERE code='REBOBINADO')")
        plan = self.preview(order).plan
        self.assertEqual([(l.line_code, l.action) for l in plan.lines], [("L1", "activate"), ("L2", "blocked")])
        self.assertEqual(plan.lines[1].reason, "SHIFT_NOT_CONFIGURED")
        before = self.snapshot()
        with self.assertRaises(ActivationBlockedError):
            self.confirm(plan.plan_hash, order=order, sectors=("BOBINAS", "REBOBINADO"))
        self.assertEqual(self.snapshot(), before)

    def test_a_supervisor_without_one_of_the_machines_sectors_gets_a_404_that_reveals_nothing(self):
        order = self.order([line(MP1_CODES[0], "MP1", "PV-1"), line(RB1_ARTICLE, "RB1", "PV-2")])
        before = self.snapshot()
        for call in (lambda: service.preview_activate_all(self.connection, work_order_id=order.id, sectors=("BOBINAS",)),
                     lambda: service.activate_all(self.connection, actor_id=self.supervisor, work_order_id=order.id, plan_hash="a" * 64, sectors=("BOBINAS",))):
            with self.assertRaises(WorkOrderNotFoundError) as caught:
                call()
            self.assertNotIn("RB1", str(caught.exception) + getattr(caught.exception, "public_message", ""))
        self.assertEqual(self.snapshot(), before)

    def test_an_order_in_draft_cannot_be_confirmed(self):
        draft = self.order([line(MP1_CODES[0])], publish=False)
        with self.assertRaises(WorkOrderNotActivatableError):
            self.confirm("a" * 64, order=draft)


class AtomicityTests(BulkCase):
    def test_a_failure_on_the_last_line_rolls_back_every_activation_version_and_status_change(self):
        plan_hash = self.preview().plan.plan_hash
        before = self.snapshot()
        original = _assignments._activate_target
        calls = []

        def failing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("boom on the last line")
            return original(*args, **kwargs)

        with patch.object(_assignments, "_activate_target", failing):
            with self.assertRaises(RuntimeError):
                self.confirm(plan_hash)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.snapshot(), before)  # no assignment, no operational version, status still published, no audit
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (self.order3.id,)), "published")
        self.assertTrue(self.confirm(plan_hash).outcome == "applied")  # and the same approval still works afterwards

    def test_a_database_rejection_on_the_last_line_also_rolls_back_everything(self):
        plan_hash = self.preview().plan.plan_hash
        before = self.snapshot()
        original = _assignments._activate_target

        def corrupting(connection, **kwargs):
            if kwargs["target"].line_code == "L3":
                connection.execute("UPDATE vinto_txn.assignment SET machine_id=machine_id WHERE false")  # no-op, then force a constraint failure
                connection.execute("INSERT INTO vinto_txn.assignment (work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by) "
                                   "SELECT work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by FROM vinto_txn.assignment LIMIT 1")
            return original(connection, **kwargs)

        with patch.object(_assignments, "_activate_target", corrupting):
            with self.assertRaises(psycopg.Error):
                self.confirm(plan_hash)
        self.assertEqual(self.snapshot(), before)


class ShiftChangeTests(BulkCase):
    def test_a_new_shift_finishes_the_expired_lines_and_reactivates_every_line(self):
        self.confirm(self.preview().plan.plan_hash)
        old = [r[0] for r in self.connection.execute("SELECT id FROM vinto_txn.assignment ORDER BY id").fetchall()]
        old_rows = self.connection.execute("SELECT id, work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by FROM vinto_txn.assignment ORDER BY id").fetchall()
        self.patch_now(NIGHT)
        plan = self.preview().plan
        self.assertEqual((len(plan.expired), [l.action for l in plan.lines]), (3, ["activate"] * 3))
        result = self.confirm(plan.plan_hash)
        self.assertEqual({a.id for a in result.finished}, set(old))
        self.assertEqual(len(result.activated), 3)
        self.assertEqual({a.shift_code for a in result.activated}, {"NOCHE"})
        self.assertEqual(self.active(), [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        self.assertEqual(self.connection.execute("SELECT id, work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by FROM vinto_txn.assignment WHERE id = ANY(%s) ORDER BY id", (old,)).fetchall(), old_rows)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='finished' AND finished_at IS NULL"), 0)

    def test_a_partial_individual_activation_in_the_old_shift_does_not_leave_lines_behind(self):
        self.activate(self.order3, 0)  # only L1 in the day shift
        self.patch_now(NIGHT)
        result = self.confirm(self.preview().plan.plan_hash)
        self.assertEqual(len(result.activated), 3)
        self.assertEqual(len(result.finished), 1)


class ConcurrencyTests(BulkCase):
    def test_two_supervisors_confirming_the_same_plan_apply_it_once(self):
        plan_hash = self.preview().plan.plan_hash
        outcomes = self.run_threads([lambda c, a=a: self.confirm(plan_hash, connection=c, actor=a) for a in (self.supervisor, self.supervisor_b)])
        self.assertEqual([o[0] for o in outcomes], ["ok", "ok"])
        self.assertEqual(sorted(o[1].outcome for o in outcomes), ["already_in_effect", "applied"])
        self.assertEqual(self.active(), [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (self.order3.id,)), 1)

    def test_two_different_orders_competing_for_the_same_machine_leave_one_winner(self):
        rival = self.same_machine_order(2)
        hashes = (self.preview().plan.plan_hash, self.preview(rival).plan.plan_hash)
        outcomes = self.run_threads([lambda c: self.confirm(hashes[0], connection=c), lambda c: self.confirm(hashes[1], order=rival, connection=c)])
        self.assertEqual(sorted(o[0] for o in outcomes), ["error", "ok"])
        loser = next(o[1] for o in outcomes if o[0] == "error")
        self.assertIsInstance(loser, (ActivationPlanChangedError, ActivationBlockedError))
        owners = self.connection.execute(
            """SELECT DISTINCT v.work_order_id FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id WHERE a.status='active' AND a.machine_id=(SELECT id FROM vinto_master.machine WHERE code='MP1')""").fetchall()
        self.assertEqual(len(owners), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='finished'"), 0)

    def test_bulk_against_an_individual_activation_ends_in_one_of_the_two_coherent_states(self):
        plan_hash = self.preview().plan.plan_hash
        outcomes = self.run_threads([lambda c: self.confirm(plan_hash, connection=c),
                                     lambda c: service.activate(c, actor_id=self.supervisor_b, work_order_id=self.order3.id, baseline_line_id=self.order3.baseline.lines[0].id)])
        bulk, single = outcomes
        self.assertEqual(single[0], "ok")
        if bulk[0] == "ok":
            self.assertEqual(self.active(), [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        else:
            self.assertIsInstance(bulk[1], ActivationPlanChangedError)
            self.assertEqual(self.active(), [("L1", "MP1")])  # the approved plan no longer matched, nothing else was written
        self.assertEqual(self.scalar("SELECT count(*) FROM (SELECT 1 FROM vinto_txn.assignment WHERE status='active' GROUP BY work_order_line_id HAVING count(*) > 1) x"), 0)

    def test_bulk_against_finishing_an_assignment_ends_coherent(self):
        first = self.activate(self.order3, 0).assignment
        plan_hash = self.preview().plan.plan_hash
        outcomes = self.run_threads([lambda c: self.confirm(plan_hash, connection=c),
                                     lambda c: service.finish(c, actor_id=self.supervisor_b, assignment_id=first.id)])
        bulk, finish = outcomes
        self.assertEqual(finish[0], "ok")
        if bulk[0] == "ok":  # bulk first: L2/L3 added, then L1 finished
            self.assertEqual(self.active(), [("L2", "MP1"), ("L3", "MP3")])
        else:  # finish first: the approved plan (L1 already active) no longer holds
            self.assertIsInstance(bulk[1], ActivationPlanChangedError)
            self.assertEqual(self.active(), [])
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (first.id,)), "finished")

    def test_bulk_never_deadlocks_with_individual_activations_of_other_machines(self):
        other = self.same_machine_order(1, machine="MP3")
        plan_hash = self.preview().plan.plan_hash
        outcomes = self.run_threads([lambda c: self.confirm(plan_hash, connection=c),
                                     lambda c: service.activate(c, actor_id=self.supervisor_b, work_order_id=other.id, baseline_line_id=other.baseline.lines[0].id)])
        self.assertTrue(all(o is not None for o in outcomes))  # both finished (no hang); outcomes are coherent below
        kinds = {self.order3.id: [], other.id: []}
        for row in self.connection.execute(
                """SELECT DISTINCT v.work_order_id FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
                   JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
                   WHERE a.status='active' AND a.machine_id=(SELECT id FROM vinto_master.machine WHERE code='MP3')""").fetchall():
            kinds[row[0]].append(1)
        self.assertEqual(sum(1 for owners in kinds.values() if owners), 1)  # MP3 belongs to exactly one order


class CaptureIntegrityTests(BulkCase):
    def setUp(self):
        super().setUp()
        self._now_patch.stop()  # captures use the real clock; the activation must too

    def test_existing_captures_and_their_assignments_are_not_altered(self):
        from app.bobbins import service as bobbins_service
        articles = {a["code"]: a["version"] for a in base.BUNDLE.articles}
        with_grammage = [c for c in MP1_CODES if articles[c]["grammage_g_m2"] is not None][:2]
        order = self.order([line(with_grammage[0], "MP1", "PV-1"), line(with_grammage[1], "MP1", "PV-2")])
        first = self.activate(order, 0).assignment
        operator = self.make_user("OPERACION")
        values = {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25", "numero_de_cortes": "3", "metraje": 1000, "codigo_de_tubete": 37, "observaciones": "ok"}
        base.internal(bobbins_service).submit_bobbin_production(self.connection, actor_id=operator, capture_id=uuid4(), assignment_id=first.id, device_key=str(uuid4()), values=values)
        captures = self.connection.execute("SELECT to_jsonb(c) FROM vinto_txn.capture c ORDER BY id").fetchall()
        assignment = self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a WHERE id=%s", (first.id,)).fetchall()
        result = self.confirm(self.preview(order).plan.plan_hash, order=order)
        self.assertEqual([a.id for a in result.already_active], [first.id])
        self.assertEqual(self.connection.execute("SELECT to_jsonb(c) FROM vinto_txn.capture c ORDER BY id").fetchall(), captures)
        self.assertEqual(self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a WHERE id=%s", (first.id,)).fetchall(), assignment)


if __name__ == "__main__":
    unittest.main()
