"""MF-13-03.B PR8: captures over SEVERAL active lines of one work order (what Operación now selects from).

No backend code changed in PR8: these tests pin that the existing capture contract already resolves the line by `assignment_id` and re-validates everything at write time, which is what
makes the frontend selection safe (a selection is never an authorization). Ephemeral *_test databases from a migrated template; nothing touches vinto, vinto_piloto or any server.
"""

import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.capture_errors import AssignmentNotActiveError, AssignmentStaleError
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import AuthenticatedUser, create_user
from app.authz.capture_gate import OperationGate
from app.authz.errors import AuthorizationDenied
from app.authz.policies import Operation
from app.bobbins import service as _bobbins
from app.ephemeral_db import build_reference_template, connect, drop_database

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base

service, line, internal = base.service, base.line, base.internal
bobbins = internal(_bobbins)
P103 = "VINTO-P1-03"
VALUES = {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25", "numero_de_cortes": "3", "observaciones": "ok"}
ARTICLES = {a["code"]: a["version"] for a in base.BUNDLE.articles}
WITH_GRAMMAGE = [c for c in base.MP1_CODES if ARTICLES[c]["grammage_g_m2"] is not None][:2]


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_p8_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])


class LinesCase(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        self.order = self.order([line(WITH_GRAMMAGE[0], pv="PV-1"), line(WITH_GRAMMAGE[1], pv="PV-2")])
        self.first, self.second = self.activate(self.order, 0).assignment, self.activate(self.order, 1).assignment
        self._now_patch.stop()  # captures resolve the shift with the real clock, as in production
        self.operator = create_user(self.connection, username=f"p8.{uuid4().hex[:10]}", display_name="Operator Fixture", profile_code="OPERACION", sectors=("BOBINAS",),
                                    password="pw-" + uuid4().hex).user_id
        self.admin = self.make_user("DATA_BALTREK")

    def reactivate_now(self):
        """setUp activated both lines at the patched instant (a past date); re-activate with the real clock so they are current for the captures."""
        for assignment in (self.first, self.second):
            service.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment.id)
        self.first, self.second = self.activate(self.order, 0).assignment, self.activate(self.order, 1).assignment

    def submit(self, assignment, capture_id=None, connection=None, gate=None, operator=None, device_key=None):
        return bobbins.submit_bobbin_production(connection or self.connection, actor_id=operator or self.operator, capture_id=capture_id or uuid4(), assignment_id=assignment.id,
                                                device_key=device_key or str(uuid4()), values=VALUES, sectors=frozenset({"BOBINAS"}), gate=gate)

    def captures_of(self, assignment):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment.id,))

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


class StaleSelectionTests(LinesCase):
    """The frontend selection can go stale at any moment; the backend decides at write time."""

    def test_each_selected_line_is_captured_against_its_own_assignment(self):
        self.reactivate_now()
        self.submit(self.second)
        self.submit(self.first)
        self.assertEqual((self.captures_of(self.first), self.captures_of(self.second)), (1, 1))

    def test_a_line_activated_in_another_shift_or_date_is_rejected_as_stale_and_nothing_is_written(self):
        with self.assertRaises(AssignmentStaleError):  # activated at the patched 2026-10-06, captured with today's clock
            self.submit(self.first)
        self.assertEqual((self.captures_of(self.first), self.captures_of(self.second)), (0, 0))

    def test_a_line_finished_while_the_operator_was_filling_the_form_is_rejected_but_its_sibling_still_works(self):
        self.reactivate_now()
        service.finish(self.connection, actor_id=self.supervisor, assignment_id=self.first.id)
        with self.assertRaises(AssignmentNotActiveError):
            self.submit(self.first)
        self.submit(self.second)
        self.assertEqual((self.captures_of(self.first), self.captures_of(self.second)), (0, 1))


class ConcurrencyTests(LinesCase):
    def setUp(self):
        super().setUp()
        self.reactivate_now()

    def test_concurrent_captures_on_two_lines_both_succeed_without_crossing_assignments(self):
        outcomes = self.run_threads([lambda c: self.submit(self.first, connection=c), lambda c: self.submit(self.second, connection=c),
                                     lambda c: self.submit(self.first, connection=c), lambda c: self.submit(self.second, connection=c)])
        self.assertEqual([o[0] for o in outcomes], ["ok"] * 4, [o[1] for o in outcomes if o[0] == "error"])
        self.assertEqual((self.captures_of(self.first), self.captures_of(self.second)), (2, 2))

    def test_a_double_submit_with_the_same_capture_id_registers_once(self):
        capture_id, device = uuid4(), str(uuid4())
        outcomes = self.run_threads([lambda c: self.submit(self.first, capture_id=capture_id, device_key=device, connection=c)] * 2)
        self.assertEqual([o[0] for o in outcomes], ["ok", "ok"], [o[1] for o in outcomes if o[0] == "error"])
        self.assertEqual(self.captures_of(self.first), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (capture_id,)), 1)

    def test_a_capture_racing_with_the_finish_of_its_line_is_either_saved_or_rejected_never_half_saved(self):
        outcomes = self.run_threads([lambda c: self.submit(self.first, connection=c),
                                     lambda c: service.finish(c, actor_id=self.supervisor, assignment_id=self.first.id)])
        self.assertEqual(outcomes[1][0], "ok")
        if outcomes[0][0] == "error":
            self.assertIsInstance(outcomes[0][1], AssignmentNotActiveError)
            self.assertEqual(self.captures_of(self.first), 0)
        else:
            self.assertEqual(self.captures_of(self.first), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture c LEFT JOIN vinto_txn.capture_detail d ON d.capture_id = c.id WHERE d.capture_id IS NULL"), 0)


class AuthorizationTests(LinesCase):
    """A selection is not an authorization: with the machine/form gate in enforce, grants decide per capture."""

    def setUp(self):
        super().setUp()
        self.reactivate_now()
        self.principal = AuthenticatedUser(self.operator, "op", "Operator", ("OPERACION",), frozenset({"production.capture", "assignment.read"}), False, frozenset({"BOBINAS"}))
        self.connection.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(self.admin),))

    def op_gate(self, mode="enforce"):
        return OperationGate(self.principal, mode, "pr8-request", Operation.BOBBIN_PRODUCTION)

    def grant(self):
        return grant_machine_form(self.connection, user_id=self.operator, machine_code="MP1", form_code=P103, actor_id=self.admin)

    def test_without_a_grant_no_line_can_be_captured_even_if_it_is_active_and_current(self):
        for assignment in (self.first, self.second):
            with self.assertRaises(AuthorizationDenied):
                self.submit(assignment, gate=self.op_gate())
        self.assertEqual((self.captures_of(self.first), self.captures_of(self.second)), (0, 0))

    def test_a_grant_revoked_after_the_line_was_chosen_blocks_the_next_capture_but_keeps_the_saved_one(self):
        self.grant()
        self.submit(self.first, gate=self.op_gate())
        revoke_machine_form(self.connection, user_id=self.operator, machine_code="MP1", form_code=P103, actor_id=self.admin)
        with self.assertRaises(AuthorizationDenied):
            self.submit(self.second, gate=self.op_gate())
        self.assertEqual((self.captures_of(self.first), self.captures_of(self.second)), (1, 0))


if __name__ == "__main__":
    unittest.main()
