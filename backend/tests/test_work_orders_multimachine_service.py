"""MF13-03.B PR2: multi-machine work orders in the domain service (machine per line, gate, scope, atomicity).

Runs in ephemeral *_test databases copied from a migrated template with the reference bundle (sector BOBINAS, machines MP1/MP3).
Each test adds a synthetic machine RB1 in the existing sector REBOBINADO and an inactive machine; nothing touches vinto.
"""

import secrets
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.assignments import service as _assignments
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.work_orders import service as _service
from app.work_orders.errors import (ArticleNotAllowedForMachineError, InvalidWorkOrderLineError, MachineNotFoundError, MachineOutsideScopeError,
                                    MultiMachineDisabledError, WorkOrderAlreadyPublishedError, WorkOrderNotFoundError)
from app.work_orders.service import LineInput

try:
    from scope_helpers import internal
except ModuleNotFoundError:
    from tests.scope_helpers import internal

service = internal(_service)
assignments = internal(_assignments)

BUNDLE = load_bundle()
STATE = {}
DUE = date(2026, 10, 30)
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # DIA, 2026-10-06 (same fixture as the assignment tests)


def codes_of(machine):
    return sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == machine)


MP1_CODES, MP3_CODES = codes_of("MP1"), codes_of("MP3")
MP1_ONLY = [c for c in MP1_CODES if c not in MP3_CODES]
MP3_ONLY = [c for c in MP3_CODES if c not in MP1_CODES]
RB1_ARTICLE = MP1_ONLY[1]  # enabled for RB1 by the fixture below; MP3 does not allow it


def setUpModule():
    STATE["template"] = build_reference_template("vinto_wm_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def line(code, machine=None, pv="PV-001"):
    return LineInput(pv, code, 10, DUE, machine)


class MultiMachineCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_wm")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.jefatura = self.make_user("JEFATURA")
        self.supervisor = self.make_user("SUPERVISION")
        c = self.connection
        c.execute("SELECT set_config('vinto.reason','mf13-03b fixture',false)")
        sector = c.execute("SELECT id FROM vinto_master.sector WHERE code='REBOBINADO'").fetchone()[0]
        bobinas = c.execute("SELECT id FROM vinto_master.sector WHERE code='BOBINAS'").fetchone()[0]
        c.execute("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'RB1','RB1')", (sector,))
        c.execute("INSERT INTO vinto_master.machine (sector_id,code,name,active) VALUES (%s,'MPX','MPX',false)", (bobinas,))
        c.execute("""INSERT INTO vinto_master.article_machine (article_id,machine_id)
                     SELECT a.id,m.id FROM vinto_master.article a, vinto_master.machine m WHERE a.code=%s AND m.code IN ('RB1','MPX')""", (RB1_ARTICLE,))

    def enable_gate(self, value=True):
        patcher = patch.object(settings, "work_orders_multi_machine_enabled", value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_user(self, profile):
        return create_user(self.connection, username=f"wm.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile,
                           password="pw-" + secrets.token_urlsafe(18)).user_id

    def create(self, lines, machine="MP1", **kwargs):
        return service.create_work_order(self.connection, actor_id=self.jefatura, machine_code=machine, lines=lines, **kwargs)

    def three_lines(self):
        return [line(MP1_CODES[0], "MP1", "PV-1"), line(MP1_CODES[1], "MP1", "PV-2"), line(MP3_ONLY[0], "MP3", "PV-3")]

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.work_order", "vinto_txn.work_order_version", "vinto_txn.work_order_line")}

    def line_machines(self, order):
        return self.connection.execute(
            """SELECT l.line_code,m.code FROM vinto_txn.work_order_line l JOIN vinto_master.machine m ON m.id=l.machine_id
               WHERE l.work_order_version_id=%s ORDER BY l.line_code""", (order.baseline.id,)).fetchall()


class LegacyContractTests(MultiMachineCase):
    def test_the_gate_is_off_by_default(self):
        self.assertIs(type(settings).model_fields["work_orders_multi_machine_enabled"].default, False)
        self.assertIs(settings.work_orders_multi_machine_enabled, False)

    def test_lines_without_machine_use_the_header_machine_with_the_gate_off(self):
        order = self.create([line(MP1_CODES[0]), line(MP1_CODES[1], pv="PV-2")])
        self.assertEqual(self.line_machines(order), [("L1", "MP1"), ("L2", "MP1")])
        self.assertEqual({l.machine_code for l in order.baseline.lines}, {"MP1"})
        self.assertEqual(order.machine_code, "MP1")

    def test_an_explicit_machine_equal_to_the_header_is_not_multi_machine(self):
        order = self.create([line(MP1_CODES[0], "MP1"), line(MP1_CODES[1], " MP1 ", "PV-2")])
        self.assertEqual(self.line_machines(order), [("L1", "MP1"), ("L2", "MP1")])
        self.assertEqual(service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id).status, "published")

    def test_a_legacy_order_still_activates_its_lines_and_the_view_reports_each_line_machine(self):
        order = service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=self.create([line(MP1_CODES[0])]).id)
        with patch.object(_assignments, "_now", return_value=DAY):
            assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 1)


class GateTests(MultiMachineCase):
    def test_a_multi_machine_request_is_rejected_when_the_gate_is_off_and_never_downgraded(self):
        before = self.counts()
        with self.assertRaises(MultiMachineDisabledError):
            self.create(self.three_lines())
        self.assertEqual(self.counts(), before)

    def test_add_line_to_another_machine_is_rejected_with_the_gate_off(self):
        order = self.create([line(MP1_CODES[0])])
        with self.assertRaises(MultiMachineDisabledError):
            service.add_line(self.connection, actor_id=self.jefatura, work_order_id=order.id, line=line(MP3_ONLY[0], "MP3"))
        self.assertEqual(len(self.line_machines(order)), 1)

    def test_publishing_a_multi_machine_draft_is_rejected_if_the_gate_is_turned_off(self):
        self.enable_gate()
        order = self.create(self.three_lines())
        with patch.object(settings, "work_orders_multi_machine_enabled", False):
            with self.assertRaises(MultiMachineDisabledError):
                service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (order.id,)), "draft")
        self.assertIsNone(self.scalar("SELECT published_at FROM vinto_txn.work_order_version WHERE id=%s", (order.baseline.id,)))


class CreateTests(MultiMachineCase):
    def setUp(self):
        super().setUp()
        self.enable_gate()

    def test_one_order_with_lines_in_mp1_mp1_and_mp3(self):
        order = self.create(self.three_lines())
        self.assertEqual(self.line_machines(order), [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        self.assertEqual([(l.line_code, l.machine_code, l.machine_name) for l in order.baseline.lines], [("L1", "MP1", "MP1"), ("L2", "MP1", "MP1"), ("L3", "MP3", "MP3")])
        self.assertEqual(order.machine_code, "MP1")  # header kept as the legacy/primary machine
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (order.id,)), 1)

    def test_the_explicit_line_machine_prevails_over_the_header(self):
        order = self.create([line(MP3_ONLY[0], "MP3")], machine="MP1")
        self.assertEqual((order.machine_code, order.baseline.lines[0].machine_code), ("MP1", "MP3"))

    def test_unknown_machine(self):
        before = self.counts()
        with self.assertRaises(MachineNotFoundError):
            self.create([line(MP1_CODES[0]), line(MP3_ONLY[0], "NOPE")])
        self.assertEqual(self.counts(), before)

    def test_inactive_machine(self):
        before = self.counts()
        with self.assertRaises(MachineOutsideScopeError):
            self.create([line(RB1_ARTICLE, "MPX")])
        self.assertEqual(self.counts(), before)

    def test_blank_machine_code_is_rejected(self):
        with self.assertRaises(MachineNotFoundError):
            self.create([line(MP1_CODES[0], "   ")])

    def test_article_not_allowed_for_the_machine_of_the_line(self):
        before = self.counts()
        with self.assertRaises(ArticleNotAllowedForMachineError):
            self.create([line(MP1_CODES[0], "MP1"), line(MP1_ONLY[0], "MP3")])  # allowed on MP1 only
        self.assertEqual(self.counts(), before)

    def test_a_machine_outside_the_actor_sectors_is_rejected(self):
        before = self.counts()
        with self.assertRaises(MachineOutsideScopeError):
            self.create([line(RB1_ARTICLE, "RB1"), line(MP1_CODES[0], "MP1")], machine="RB1", sectors=("REBOBINADO",))
        self.assertEqual(self.counts(), before)

    def test_a_failing_last_line_rolls_back_the_whole_order(self):
        before = self.counts()
        audit = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        lines = self.three_lines() + [LineInput("PV-4", MP3_ONLY[0], -1, DUE, "MP3")]
        with self.assertRaises(InvalidWorkOrderLineError):
            self.create(lines)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audit)

    def test_the_numbering_is_not_consumed_by_a_failed_multi_machine_order(self):
        first = self.create([line(MP1_CODES[0])])
        with self.assertRaises(ArticleNotAllowedForMachineError):
            self.create([line(MP1_ONLY[0], "MP3")])
        third = self.create([line(MP1_CODES[0])])
        self.assertEqual(int(third.number[-4:]), int(first.number[-4:]) + 1)


class DraftAndPublishTests(MultiMachineCase):
    def setUp(self):
        super().setUp()
        self.enable_gate()

    def test_add_a_line_on_another_machine_to_a_draft(self):
        order = self.create([line(MP1_CODES[0])])
        view = service.add_line(self.connection, actor_id=self.jefatura, work_order_id=order.id, line=line(MP3_ONLY[0], "MP3", "PV-2"))
        self.assertEqual([(l.line_code, l.machine_code) for l in view.baseline.lines], [("L1", "MP1"), ("L2", "MP3")])

    def test_add_line_without_machine_uses_the_header(self):
        order = self.create([line(MP3_ONLY[0], "MP3")], machine="MP1")
        view = service.add_line(self.connection, actor_id=self.jefatura, work_order_id=order.id, line=line(MP1_CODES[0]))
        self.assertEqual(view.baseline.lines[-1].machine_code, "MP1")

    def test_add_line_validates_the_article_against_the_line_machine(self):
        order = self.create([line(MP1_CODES[0])])
        with self.assertRaises(ArticleNotAllowedForMachineError):
            service.add_line(self.connection, actor_id=self.jefatura, work_order_id=order.id, line=line(MP1_ONLY[0], "MP3"))
        self.assertEqual(len(self.line_machines(order)), 1)

    def test_the_200_line_limit_still_applies(self):
        order = self.create([line(MP1_CODES[0])])
        self.connection.execute(
            """INSERT INTO vinto_txn.work_order_line (work_order_version_id,line_code,pv_reference,article_version_id,unit_id,quantity,due_date,machine_id)
               SELECT work_order_version_id,'L'||g,pv_reference,article_version_id,unit_id,quantity,due_date,machine_id
               FROM vinto_txn.work_order_line, generate_series(2,200) g WHERE work_order_version_id=%s AND line_code='L1'""", (order.baseline.id,))
        with self.assertRaises(InvalidWorkOrderLineError):
            service.add_line(self.connection, actor_id=self.jefatura, work_order_id=order.id, line=line(MP3_ONLY[0], "MP3"))

    def test_no_changes_after_publication_and_publication_is_idempotent(self):
        order = self.create(self.three_lines())
        published = service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        self.assertEqual([l.machine_code for l in published.baseline.lines], ["MP1", "MP1", "MP3"])
        audit = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        again = service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        self.assertEqual(again, published)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audit)
        with self.assertRaises(WorkOrderAlreadyPublishedError):
            service.add_line(self.connection, actor_id=self.jefatura, work_order_id=order.id, line=line(MP3_ONLY[0], "MP3"))
        self.assertEqual(self.line_machines(order), [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])

    def test_publication_validates_each_line_against_its_own_machine(self):
        order = self.create(self.three_lines())
        article_id = self.scalar("SELECT id FROM vinto_master.article WHERE code=%s", (MP3_ONLY[0],))
        mp3 = self.scalar("SELECT id FROM vinto_master.machine WHERE code='MP3'")
        self.connection.execute("DELETE FROM vinto_master.article_machine WHERE article_id=%s AND machine_id=%s", (article_id, mp3))
        from app.work_orders.errors import WorkOrderNotPublishableError
        with self.assertRaises(WorkOrderNotPublishableError) as caught:
            service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        self.assertIn("L3", str(caught.exception))
        self.assertNotIn("L1", str(caught.exception))


class ScopeIsolationTests(MultiMachineCase):
    """An order is visible or modifiable only if EVERY machine (header and lines) is inside the actor sectors."""

    def setUp(self):
        super().setUp()
        self.enable_gate()
        self.order = service.publish_work_order(
            self.connection, actor_id=self.jefatura, work_order_id=self.create([line(MP1_CODES[0], "MP1"), line(RB1_ARTICLE, "RB1", "PV-2")]).id)
        self.single = service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=self.create([line(MP1_CODES[1])]).id)

    def numbers(self, **kwargs):
        return {v.number for v in service.list_work_orders(self.connection, **kwargs)}

    def test_a_partially_authorized_actor_gets_neither_the_order_nor_its_lines(self):
        scope = ("BOBINAS",)
        with self.assertRaises(WorkOrderNotFoundError):
            service.get_work_order(self.connection, self.order.id, sectors=scope, multi_machine_visible=True)
        listed = self.numbers(sectors=scope, multi_machine_visible=True)
        self.assertEqual(listed, {self.single.number})
        self.assertNotIn("RB1", repr(service.list_work_orders(self.connection, sectors=scope, multi_machine_visible=True)))

    def test_an_actor_with_a_scope_that_misses_the_header_sector_gets_nothing_either(self):
        with self.assertRaises(WorkOrderNotFoundError):
            service.get_work_order(self.connection, self.order.id, sectors=("REBOBINADO",), multi_machine_visible=True)
        self.assertEqual(self.numbers(sectors=("REBOBINADO",), multi_machine_visible=True), set())

    def test_a_fully_authorized_manager_sees_every_line(self):
        view = service.get_work_order(self.connection, self.order.id, sectors=("BOBINAS", "REBOBINADO"), multi_machine_visible=True)
        self.assertEqual([l.machine_code for l in view.baseline.lines], ["MP1", "RB1"])

    def test_without_manager_visibility_a_multi_machine_order_is_hidden_even_with_full_scope(self):
        full = ("BOBINAS", "REBOBINADO")
        with self.assertRaises(WorkOrderNotFoundError):
            service.get_work_order(self.connection, self.order.id, sectors=full)  # default: not visible
        self.assertEqual(self.numbers(sectors=full), {self.single.number})
        self.assertEqual(self.numbers(sectors=full, multi_machine_visible=True), {self.order.number, self.single.number})

    def test_filtering_by_machine_matches_any_line_machine(self):
        full = ("BOBINAS", "REBOBINADO")
        self.assertIn(self.order.number, self.numbers(sectors=full, machine_code="RB1", multi_machine_visible=True))
        self.assertEqual(self.numbers(sectors=full, machine_code="MP3", multi_machine_visible=True), set())

    def test_mutations_are_not_possible_for_a_partially_authorized_actor(self):
        draft = self.create([line(MP1_CODES[0], "MP1"), line(RB1_ARTICLE, "RB1", "PV-2")])
        for call in (lambda: service.add_line(self.connection, actor_id=self.jefatura, work_order_id=draft.id, line=line(MP1_CODES[0]), sectors=("BOBINAS",)),
                     lambda: service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=draft.id, sectors=("BOBINAS",))):
            with self.assertRaises(WorkOrderNotFoundError):
                call()
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (draft.id,)), "draft")


class ActivationCompatibilityTests(MultiMachineCase):
    """PR3 supersedes the PR2 note: activation now uses the machine of the LINE (flag on) and refuses other machines with the flag off."""

    def published(self):
        return service.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=self.create(self.three_lines()).id)

    def test_with_the_gate_on_each_line_is_activated_on_its_own_machine(self):
        self.enable_gate()
        order = self.published()
        with patch.object(_assignments, "_now", return_value=DAY):
            for index in (0, 2):
                assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[index].id)
        rows = self.connection.execute(
            """SELECT l.line_code, m.code FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_master.machine m ON m.id=a.machine_id WHERE a.status='active' ORDER BY l.line_code""").fetchall()
        self.assertEqual(rows, [("L1", "MP1"), ("L3", "MP3")])
        operational = self.connection.execute(
            """SELECT l.line_code,m.code FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               JOIN vinto_master.machine m ON m.id=l.machine_id WHERE v.work_order_id=%s AND v.kind='operational' ORDER BY l.line_code""", (order.id,)).fetchall()
        self.assertEqual(operational, [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])  # the copy keeps each line machine

    def test_with_the_gate_off_a_multi_machine_order_only_activates_header_machine_lines(self):
        self.enable_gate()
        order = self.published()
        self.enable_gate(False)
        with patch.object(_assignments, "_now", return_value=DAY):
            assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id)
            with self.assertRaises(MultiMachineDisabledError):
                assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[2].id)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 1)


if __name__ == "__main__":
    unittest.main()
