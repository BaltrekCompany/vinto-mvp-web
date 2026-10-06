"""Work order domain (baseline only): creation, numbering, lines, publication, immutability and concurrency.

Runs in ephemeral *_test databases copied from a migrated template that already holds the reference bundle
(sector BOBINAS, machines MP1/MP3, 93 articles). Nothing touches vinto.
"""

import secrets
import threading
import unittest
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg

from app.auth.service import create_user
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.work_orders import service
from app.work_orders.errors import (ArticleNotAllowedForMachineError, ArticleNotFoundError, InvalidWorkOrderLineError,
                                    MachineNotFoundError, MachineOutsideScopeError, WorkOrderAlreadyPublishedError,
                                    WorkOrderNotFoundError, WorkOrderNotPublishableError)
from app.work_orders.service import LineInput

BUNDLE = load_bundle()
STATE = {}
DUE = date(2026, 10, 30)


def articles_of(machine):
    codes = [r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == machine]
    return {a["code"]: a for a in BUNDLE.articles if a["code"] in codes}


MP1_ARTICLES, MP3_ARTICLES = articles_of("MP1"), articles_of("MP3")
MP1_CODES, MP3_CODES = sorted(MP1_ARTICLES), sorted(MP3_ARTICLES)
UN_ARTICLE = next(code for code, a in MP3_ARTICLES.items() if a["version"]["unit"] == "UN")


def setUpModule():
    STATE["template"] = build_reference_template("vinto_wo_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def line(code=None, pv="PV-001", quantity=100, due=DUE):
    return LineInput(pv, code or MP1_CODES[0], quantity, due)


class WorkOrderCase(unittest.TestCase):
    """Each test gets its own database (copied from the template) so numbering and listings start clean."""

    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_wo")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.actor = self.make_actor("JEFATURA")

    def make_actor(self, profile="JEFATURA"):
        created = create_user(self.connection, username=f"wo.{uuid4().hex[:10]}", display_name="WO Fixture", profile_code=profile,
                              password="pw-" + secrets.token_urlsafe(18))
        return created.user_id

    def create(self, lines=None, machine="MP1", **kwargs):
        return service.create_work_order(self.connection, actor_id=self.actor, machine_code=machine, lines=lines or [line()], **kwargs)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.work_order", "vinto_txn.work_order_version", "vinto_txn.work_order_line")}


class CreateTests(WorkOrderCase):
    def test_creates_a_draft_work_order_with_a_baseline_v1(self):
        view = self.create()
        self.assertEqual((view.status, view.machine_code, view.baseline.version_number), ("draft", "MP1", 1))
        self.assertIsNone(view.baseline.published_at)
        row = self.connection.execute("SELECT kind,published_at FROM vinto_txn.work_order_version WHERE id=%s", (view.baseline.id,)).fetchone()
        self.assertEqual(row, ("baseline", None))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (view.id,)), 1)
        self.assertEqual(len(view.baseline.lines), 1)

    def test_actor_is_recorded_in_created_by_and_updated_by(self):
        view = self.create()
        for table, key in (("work_order", view.id), ("work_order_version", view.baseline.id), ("work_order_line", view.baseline.lines[0].id)):
            self.assertEqual(self.connection.execute(f"SELECT created_by,updated_by FROM vinto_txn.{table} WHERE id=%s", (key,)).fetchone(),
                             (self.actor, self.actor), table)

    def test_unit_and_description_come_from_the_article_version(self):
        view = self.create([line(UN_ARTICLE)], machine="MP3")
        created = view.baseline.lines[0]
        self.assertEqual(created.unit, "UN")
        self.assertEqual(created.article_description, MP3_ARTICLES[UN_ARTICLE]["version"]["description"])
        self.assertEqual(created.article_code, UN_ARTICLE)
        kg = self.create([line(MP1_CODES[0])]).baseline.lines[0]
        self.assertEqual(kg.unit, "KG")

    def test_the_line_freezes_the_article_version_that_existed_when_it_was_created(self):
        code = MP1_CODES[0]
        first = self.create([line(code)])
        first_version = self.scalar("SELECT article_version_id FROM vinto_txn.work_order_line WHERE id=%s", (first.baseline.lines[0].id,))
        article_id = self.scalar("SELECT id FROM vinto_master.article WHERE code=%s", (code,))
        v2 = self.scalar("""INSERT INTO vinto_master.article_version (article_id,version_number,description,unit_id)
                            SELECT %s,2,'DESCRIPCION VERSION 2',unit_id FROM vinto_master.article_version WHERE article_id=%s AND version_number=1 RETURNING id""",
                         (article_id, article_id))
        second = self.create([line(code)])
        self.assertEqual(self.scalar("SELECT article_version_id FROM vinto_txn.work_order_line WHERE id=%s", (first.baseline.lines[0].id,)), first_version)
        self.assertEqual(self.scalar("SELECT article_version_id FROM vinto_txn.work_order_line WHERE id=%s", (second.baseline.lines[0].id,)), v2)
        self.assertEqual(service.get_work_order(self.connection, first.id).baseline.lines[0].article_description, MP1_ARTICLES[code]["version"]["description"])
        self.assertEqual(second.baseline.lines[0].article_description, "DESCRIPCION VERSION 2")

    def test_several_lines_and_pvs_get_sequential_line_codes_in_array_order(self):
        codes = MP1_CODES[:3]
        view = self.create([line(codes[0], "PV-A", 10), line(codes[1], "PV-B", Decimal("20.5")), line(codes[2], "PV-A", 30)])
        self.assertEqual([l.line_code for l in view.baseline.lines], ["L1", "L2", "L3"])
        self.assertEqual([l.pv_reference for l in view.baseline.lines], ["PV-A", "PV-B", "PV-A"])
        self.assertEqual([l.article_code for l in view.baseline.lines], codes)
        self.assertEqual([l.quantity for l in view.baseline.lines], [Decimal("10"), Decimal("20.5"), Decimal("30")])

    def test_number_format_uses_the_postgres_clock_and_starts_at_0001(self):
        year = self.scalar("SELECT extract(year FROM clock_timestamp())::int")
        self.assertEqual([self.create().number for _ in range(3)], [f"OT-{year}-0001", f"OT-{year}-0002", f"OT-{year}-0003"])

    def test_numbering_continues_from_the_highest_existing_number_of_the_year(self):
        year = self.scalar("SELECT extract(year FROM clock_timestamp())::int")
        machine_id = self.scalar("SELECT id FROM vinto_master.machine WHERE code='MP1'")
        self.connection.execute("INSERT INTO vinto_txn.work_order (number,machine_id) VALUES (%s,%s),(%s,%s),(%s,%s)",
                                (f"OT-{year}-0007", machine_id, f"OT-{year - 1}-0099", machine_id, "OT-LEGACY-1", machine_id))
        self.assertEqual(self.create().number, f"OT-{year}-0008")

    def test_whitespace_in_pv_is_trimmed(self):
        self.assertEqual(self.create([line(pv="  PV-9  ")]).baseline.lines[0].pv_reference, "PV-9")

    def test_invalid_quantities_are_rejected(self):
        for quantity in (0, -1, Decimal("-0.5"), Decimal("0.000"), Decimal("NaN"), Decimal("Infinity"), "abc", True, None, Decimal("1.2345"), Decimal("1" * 16)):
            with self.subTest(repr(quantity)), self.assertRaises(InvalidWorkOrderLineError):
                self.create([line(quantity=quantity)])
        self.assertEqual(self.counts(), {"vinto_txn.work_order": 0, "vinto_txn.work_order_version": 0, "vinto_txn.work_order_line": 0})

    def test_empty_or_blank_pv_and_bad_dates_are_rejected(self):
        for pv in ("", "   ", None, "x" * 101):
            with self.subTest(pv=repr(pv)), self.assertRaises(InvalidWorkOrderLineError):
                self.create([line(pv=pv)])
        for due in (None, "2026-10-30", 20261030):
            with self.subTest(due=repr(due)), self.assertRaises(InvalidWorkOrderLineError):
                self.create([line(due=due)])

    def test_at_least_one_line_is_required(self):
        with self.assertRaises(InvalidWorkOrderLineError):
            service.create_work_order(self.connection, actor_id=self.actor, machine_code="MP1", lines=[])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), 0)

    def test_unknown_article(self):
        with self.assertRaises(ArticleNotFoundError):
            self.create([line("NO-EXISTE-001")])

    def test_article_not_allowed_for_the_machine(self):
        with self.assertRaises(ArticleNotAllowedForMachineError):
            self.create([line(MP3_CODES[0])], machine="MP1")
        with self.assertRaises(ArticleNotAllowedForMachineError):
            self.create([line(MP1_CODES[0])], machine="MP3")

    def test_inactive_article_and_non_product_article_are_rejected(self):
        code = MP1_CODES[1]
        self.connection.execute("UPDATE vinto_master.article SET active=false WHERE code=%s", (code,))
        with self.assertRaises(InvalidWorkOrderLineError):
            self.create([line(code)])
        self.connection.execute("UPDATE vinto_master.article SET active=true,is_product=false,is_material=true WHERE code=%s", (code,))
        with self.assertRaises(InvalidWorkOrderLineError):
            self.create([line(code)])

    def test_article_without_a_version_is_rejected(self):
        article_id = self.scalar("INSERT INTO vinto_master.article (code,is_product) VALUES ('TECH-NOVERSION',true) RETURNING id")
        self.connection.execute("INSERT INTO vinto_master.article_machine (article_id,machine_id) SELECT %s,id FROM vinto_master.machine WHERE code='MP1'", (article_id,))
        with self.assertRaises(InvalidWorkOrderLineError):
            self.create([line("TECH-NOVERSION")])

    def test_unknown_machine(self):
        for code in ("NO-EXISTE", "", None):
            with self.subTest(code=code), self.assertRaises(MachineNotFoundError):
                self.create(machine=code)

    def test_machine_outside_bobinas_or_inactive(self):
        sector_id = self.scalar("INSERT INTO vinto_master.sector (code,name) VALUES ('OTRO','Otro sector') RETURNING id")
        self.connection.execute("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'OTRO1','Otra máquina')", (sector_id,))
        with self.assertRaises(MachineOutsideScopeError):
            self.create(machine="OTRO1")
        self.connection.execute("UPDATE vinto_master.machine SET active=false WHERE code='MP1'")
        with self.assertRaises(MachineOutsideScopeError):
            self.create(machine="MP1")

    def test_a_failing_second_line_rolls_everything_back(self):
        before = self.counts()
        with self.assertRaises(ArticleNotAllowedForMachineError):
            self.create([line(MP1_CODES[0], "PV-OK"), line(MP3_CODES[0], "PV-BAD")])  # first valid, second not allowed on MP1
        with self.assertRaises(InvalidWorkOrderLineError):
            self.create([line(MP1_CODES[0]), line(MP1_CODES[1]), line(quantity=0)])
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.create().number.split("-")[-1], "0001")  # no number was consumed by the failed attempts


class AddLineTests(WorkOrderCase):
    def test_adds_the_next_line_code_to_a_draft(self):
        view = self.create([line(), line(MP1_CODES[1], "PV-2")])
        updated = service.add_line(self.connection, actor_id=self.actor, work_order_id=view.id, line=line(MP1_CODES[2], "PV-3", 7))
        self.assertEqual([l.line_code for l in updated.baseline.lines], ["L1", "L2", "L3"])
        self.assertEqual(updated.baseline.lines[-1].pv_reference, "PV-3")
        self.assertEqual(updated.status, "draft")

    def test_line_validation_applies_to_added_lines_too(self):
        view = self.create()
        for bad, error in ((line(MP3_CODES[0]), ArticleNotAllowedForMachineError), (line("NOPE"), ArticleNotFoundError),
                           (line(quantity=-5), InvalidWorkOrderLineError)):
            with self.assertRaises(error):
                service.add_line(self.connection, actor_id=self.actor, work_order_id=view.id, line=bad)
        self.assertEqual(len(service.get_work_order(self.connection, view.id).baseline.lines), 1)

    def test_added_line_records_the_actor_and_reason(self):
        view = self.create()
        other = self.make_actor("JEFATURA")
        updated = service.add_line(self.connection, actor_id=other, work_order_id=view.id, line=line(MP1_CODES[1]))
        created_by = self.scalar("SELECT created_by FROM vinto_txn.work_order_line WHERE id=%s", (updated.baseline.lines[1].id,))
        self.assertEqual(created_by, other)
        self.assertEqual(self.scalar("SELECT reason FROM vinto_audit.audit_event WHERE entity_table='work_order_line' AND entity_key->>'id'=%s",
                                     (str(updated.baseline.lines[1].id),)), "work order add baseline line")

    def test_unknown_or_malformed_ids_are_not_found(self):
        for value in (uuid4(), str(uuid4()), "not-a-uuid", "", None):
            with self.subTest(repr(value)), self.assertRaises(WorkOrderNotFoundError):
                service.add_line(self.connection, actor_id=self.actor, work_order_id=value, line=line())

    def test_adding_after_publication_is_rejected_and_changes_nothing(self):
        view = self.create()
        service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        before = self.counts()
        with self.assertRaises(WorkOrderAlreadyPublishedError):
            service.add_line(self.connection, actor_id=self.actor, work_order_id=view.id, line=line(MP1_CODES[1]))
        self.assertEqual(self.counts(), before)


class PublishTests(WorkOrderCase):
    def test_publish_sets_published_at_and_status(self):
        view = self.create([line(), line(MP1_CODES[1], "PV-2")])
        published = service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        self.assertEqual(published.status, "published")
        self.assertIsNotNone(published.baseline.published_at)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.work_order WHERE id=%s", (view.id,)), "published")
        self.assertEqual(self.scalar("SELECT published_at IS NOT NULL FROM vinto_txn.work_order_version WHERE id=%s", (view.baseline.id,)), True)
        self.assertEqual(self.scalar("SELECT updated_by FROM vinto_txn.work_order WHERE id=%s", (view.id,)), self.actor)

    def test_publish_does_not_touch_the_lines(self):
        view = self.create([line(), line(MP1_CODES[1], "PV-2", 5)])
        before = self.connection.execute("SELECT * FROM vinto_txn.work_order_line WHERE work_order_version_id=%s ORDER BY line_code", (view.baseline.id,)).fetchall()
        published = service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        after = self.connection.execute("SELECT * FROM vinto_txn.work_order_line WHERE work_order_version_id=%s ORDER BY line_code", (view.baseline.id,)).fetchall()
        self.assertEqual(before, after)
        self.assertEqual([l.line_code for l in published.baseline.lines], ["L1", "L2"])

    def test_repeated_publish_is_idempotent_and_writes_nothing(self):
        view = self.create()
        first = service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        audit_before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        second = service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        self.assertEqual(second.baseline.published_at, first.baseline.published_at)
        self.assertEqual(second, first)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audit_before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (view.id,)), 1)

    def test_publish_unknown_order(self):
        with self.assertRaises(WorkOrderNotFoundError):
            service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=uuid4())

    def test_baseline_is_immutable_after_publication_even_at_database_level(self):
        view = self.create()
        service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        line_id = view.baseline.lines[0].id
        for statement in ("UPDATE vinto_txn.work_order_line SET quantity=1 WHERE id=%s", "DELETE FROM vinto_txn.work_order_line WHERE id=%s"):
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.connection.execute(statement, (line_id,))
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute("UPDATE vinto_txn.work_order_version SET published_at=NULL WHERE id=%s", (view.baseline.id,))
        again = service.get_work_order(self.connection, view.id)
        self.assertEqual(again.baseline.lines[0].quantity, Decimal("100"))

    def test_incoherent_lines_block_publication(self):
        view = self.create([line(MP1_CODES[0]), line(MP1_CODES[1], "PV-2")])
        self.connection.execute("UPDATE vinto_master.article SET active=false WHERE code=%s", (MP1_CODES[1],))
        with self.assertRaises(WorkOrderNotPublishableError) as raised:
            service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        self.assertIn("L2", str(raised.exception))
        self.assertEqual(service.get_work_order(self.connection, view.id).status, "draft")
        self.connection.execute("DELETE FROM vinto_master.article_machine WHERE article_id=(SELECT id FROM vinto_master.article WHERE code=%s)", (MP1_CODES[1],))
        self.connection.execute("UPDATE vinto_master.article SET active=true WHERE code=%s", (MP1_CODES[1],))
        with self.assertRaises(WorkOrderNotPublishableError):
            service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)

    def test_other_statuses_are_not_republished(self):
        view = self.create()
        service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)
        self.connection.execute("UPDATE vinto_txn.work_order SET status='closed' WHERE id=%s", (view.id,))
        with self.assertRaises(WorkOrderNotPublishableError):
            service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id)


class QueryTests(WorkOrderCase):
    def test_list_is_newest_first_and_filters_by_machine_and_status(self):
        first = self.create(machine="MP1")
        second = self.create([line(MP3_CODES[0])], machine="MP3")
        third = self.create(machine="MP1")
        service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=first.id)
        self.assertEqual([v.number for v in service.list_work_orders(self.connection)], [third.number, second.number, first.number])
        self.assertEqual([v.number for v in service.list_work_orders(self.connection, machine_code="MP1")], [third.number, first.number])
        self.assertEqual([v.number for v in service.list_work_orders(self.connection, machine_code="MP3")], [second.number])
        self.assertEqual([v.number for v in service.list_work_orders(self.connection, status="published")], [first.number])
        self.assertEqual([v.number for v in service.list_work_orders(self.connection, machine_code="MP1", status="draft")], [third.number])
        self.assertEqual(service.list_work_orders(self.connection, machine_code="NOPE"), [])
        self.assertEqual(len(service.list_work_orders(self.connection, limit=2)), 2)
        with self.assertRaises(InvalidWorkOrderLineError):
            service.list_work_orders(self.connection, status="weird")

    def test_list_and_detail_have_the_same_complete_model(self):
        view = self.create([line(), line(MP1_CODES[1], "PV-2", 3)])
        listed = service.list_work_orders(self.connection)[0]
        self.assertEqual(listed, service.get_work_order(self.connection, view.id))
        self.assertEqual((listed.machine_code, listed.machine_name), ("MP1", "MP1"))
        self.assertEqual(listed.baseline.lines[1].unit, "KG")

    def test_orders_outside_bobinas_are_invisible(self):
        sector_id = self.scalar("INSERT INTO vinto_master.sector (code,name) VALUES ('OTRO','Otro sector') RETURNING id")
        machine_id = self.scalar("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'OTRO1','Otra') RETURNING id", (sector_id,))
        foreign = self.scalar("INSERT INTO vinto_txn.work_order (number,machine_id) VALUES ('OT-2099-0001',%s) RETURNING id", (machine_id,))
        self.connection.execute("INSERT INTO vinto_txn.work_order_version (work_order_id,version_number,kind) VALUES (%s,1,'baseline')", (foreign,))
        self.assertEqual(service.list_work_orders(self.connection), [])
        with self.assertRaises(WorkOrderNotFoundError):
            service.get_work_order(self.connection, foreign)


class AuditTests(WorkOrderCase):
    def test_audit_records_actor_request_id_and_reasons_without_secrets(self):
        view = self.create(request_id="req-create")
        service.add_line(self.connection, actor_id=self.actor, work_order_id=view.id, line=line(MP1_CODES[1]), request_id="req-add")
        service.publish_work_order(self.connection, actor_id=self.actor, work_order_id=view.id, request_id="req-publish")
        rows = self.connection.execute(
            """SELECT DISTINCT reason,request_id,actor_id FROM vinto_audit.audit_event
               WHERE entity_schema='vinto_txn' ORDER BY reason""").fetchall()
        self.assertEqual(rows, [("work order add baseline line", "req-add", self.actor), ("work order create", "req-create", self.actor),
                                ("work order publish baseline", "req-publish", self.actor)])
        dump = " ".join(f"{o} {n}" for o, n in self.connection.execute("SELECT old_data::text,new_data::text FROM vinto_audit.audit_event WHERE entity_schema='vinto_txn'").fetchall())
        for forbidden in ("password", "token", "argon2", "cookie"):
            self.assertNotIn(forbidden, dump.lower())

    def test_default_request_id_is_generated(self):
        view = self.create()
        request_id = self.scalar("SELECT request_id FROM vinto_audit.audit_event WHERE entity_table='work_order' AND entity_key->>'id'=%s", (str(view.id),))
        self.assertTrue(request_id.startswith("work_order:"))
        UUID(request_id.split(":", 1)[1])


class ConcurrencyTests(WorkOrderCase):
    def run_threads(self, targets):
        errors, barrier = [], threading.Barrier(len(targets))
        results = [None] * len(targets)

        def runner(index, target):
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    results[index] = target(connection)
            except Exception as error:  # reported by the caller's assertion
                errors.append(repr(error))

        threads = [threading.Thread(target=runner, args=(i, t)) for i, t in enumerate(targets)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        return results

    def test_simultaneous_creations_get_distinct_consecutive_numbers(self):
        workers = 5
        results = self.run_threads([lambda c: service.create_work_order(c, actor_id=self.actor, machine_code="MP1", lines=[line()])] * workers)
        numbers = sorted(v.number for v in results)
        year = self.scalar("SELECT extract(year FROM clock_timestamp())::int")
        self.assertEqual(numbers, [f"OT-{year}-{n:04d}" for n in range(1, workers + 1)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), workers)

    def test_simultaneous_added_lines_get_distinct_line_codes(self):
        view = self.create()
        workers = 5
        targets = [lambda c, i=i: service.add_line(c, actor_id=self.actor, work_order_id=view.id, line=line(MP1_CODES[i % 5], f"PV-C{i}", i + 1)) for i in range(workers)]
        self.run_threads(targets)
        final = service.get_work_order(self.connection, view.id)
        self.assertEqual([l.line_code for l in final.baseline.lines], [f"L{n}" for n in range(1, workers + 2)])
        self.assertEqual(len({l.pv_reference for l in final.baseline.lines}), workers + 1)

    def test_concurrent_publish_gives_one_coherent_result(self):
        view = self.create([line(), line(MP1_CODES[1], "PV-2")])
        results = self.run_threads([lambda c: service.publish_work_order(c, actor_id=self.actor, work_order_id=view.id)] * 4)
        self.assertEqual({r.baseline.published_at for r in results}, {results[0].baseline.published_at})
        self.assertTrue(all(r.status == "published" for r in results))
        self.assertEqual(self.scalar("""SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='work_order_version' AND action='UPDATE'
                                        AND entity_key->>'id'=%s""", (str(view.baseline.id),)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='work_order' AND action='UPDATE' AND entity_key->>'id'=%s",
                                     (str(view.id),)), 1)

    def test_add_line_racing_with_publish_never_leaves_a_line_in_a_published_baseline_unsafely(self):
        view = self.create()
        targets = [lambda c: service.publish_work_order(c, actor_id=self.actor, work_order_id=view.id)]
        outcomes = []

        def adder(c):
            try:
                service.add_line(c, actor_id=self.actor, work_order_id=view.id, line=line(MP1_CODES[1], "PV-RACE"))
                outcomes.append("added")
            except WorkOrderAlreadyPublishedError:
                outcomes.append("rejected")

        self.run_threads(targets + [adder])
        final = service.get_work_order(self.connection, view.id)
        self.assertEqual(final.status, "published")
        # Either the line made it in before publication, or it was rejected: never a half-state.
        self.assertEqual(len(final.baseline.lines), 2 if outcomes == ["added"] else 1)
        self.assertEqual(len(outcomes), 1)


if __name__ == "__main__":
    unittest.main()
