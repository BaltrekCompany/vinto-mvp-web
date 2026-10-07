"""F3 (VINTO-P1-03) bobbin production, domain level: capture + bobbin + quality_release in one transaction, per-machine /
per-management numbering, inherited grammage, idempotency, atomicity and concurrency.

Runs in ephemeral *_test databases copied from a migrated template with the reference bundle. Nothing touches vinto.
"""

import secrets
import threading
import unittest
from datetime import date, datetime, time, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import capture_service
from app.assignments import service as assignments
from app.auth.service import create_user
from app.bobbins import service as bobbins
from app.capture_errors import (AssignmentNotActiveError, AssignmentStaleError, CaptureIdempotencyConflictError, CaptureValidationError,
                                FormNotAvailableError)
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.work_orders import service as work_orders
from app.work_orders.service import LineInput

BUNDLE = load_bundle()
STATE = {}
ARTICLES = {a["code"]: a["version"] for a in BUNDLE.articles}
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
MP3_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP3")
WITH_GRAMMAGE = next(c for c in MP1_CODES if ARTICLES[c]["grammage_g_m2"] is not None)
WITHOUT_GRAMMAGE = next(c for c in MP1_CODES + MP3_CODES if ARTICLES[c]["grammage_g_m2"] is None)
WITHOUT_GRAMMAGE_MACHINE = "MP1" if WITHOUT_GRAMMAGE in MP1_CODES else "MP3"
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz, 2026-10-06 -> management 2026
LAST_DAY_OF_MANAGEMENT = datetime(2027, 3, 31, 16, 0, tzinfo=timezone.utc)  # 2027-03-31 -> management 2026
FIRST_DAY_OF_MANAGEMENT = datetime(2027, 4, 1, 16, 0, tzinfo=timezone.utc)  # 2027-04-01 -> management 2027
VALID = {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25", "numero_de_cortes": "3", "observaciones": "sin novedades"}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_f3_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class BobbinCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_f3")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.jefatura = self.user("JEFATURA")
        self.supervisor = self.user("SUPERVISION")
        self.operator = self.user("OPERACION")
        self.device_key = str(uuid4())

    def user(self, profile):
        return create_user(self.connection, username=f"f3.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile,
                           password="pw-" + secrets.token_urlsafe(18)).user_id

    def assignment(self, machine="MP1", at=None, article=None):
        codes = MP1_CODES if machine == "MP1" else MP3_CODES
        order = work_orders.create_work_order(self.connection, actor_id=self.jefatura, machine_code=machine,
                                              lines=[LineInput("PV-1", article or codes[0], 10, date(2026, 11, 1))])
        order = work_orders.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        kwargs = dict(actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id)
        if at is None:
            return order, assignments.activate(self.connection, **kwargs).assignment
        with patch.object(assignments, "_now", return_value=at):
            return order, assignments.activate(self.connection, **kwargs).assignment

    def submit(self, assignment, values=VALID, capture_id=None, actor=None, device_key=None, connection=None, now=None):
        kwargs = dict(actor_id=actor or self.operator, capture_id=capture_id or uuid4(), assignment_id=assignment.id,
                      device_key=device_key or self.device_key, values=values)
        if now is not None:
            with patch.object(capture_service, "_now", return_value=now):
                return bobbins.submit_bobbin_production(connection or self.connection, **kwargs)
        return bobbins.submit_bobbin_production(connection or self.connection, **kwargs)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in (
            "vinto_txn.capture", "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_txn.quality_release", "vinto_txn.bobbin_sequence",
            "vinto_master.device", "vinto_audit.audit_event")}

    def sequence_value(self, machine="MP1", year=2026):
        row = self.connection.execute(
            """SELECT s.last_value FROM vinto_txn.bobbin_sequence s JOIN vinto_master.machine m ON m.id = s.machine_id
               WHERE m.code = %s AND s.management_start_year = %s""", (machine, year)).fetchone()
        return None if row is None else row[0]


class CreationTests(BobbinCase):
    def test_valid_f3_on_mp1_creates_capture_bobbin_and_pending_release(self):
        order, assignment = self.assignment("MP1")
        result = self.submit(assignment)
        self.assertEqual((result.created, result.already_submitted), (True, False))
        capture, bobbin = result.capture, result.bobbin
        self.assertEqual((capture.status, capture.revision, capture.form_code, capture.machine_code), ("submitted", 1, "VINTO-P1-03", "MP1"))
        self.assertEqual((bobbin.code, bobbin.sequence_number, bobbin.machine_code, bobbin.capture_id), ("1", 1, "MP1", capture.id))
        self.assertEqual(bobbin.quality_status, "pending")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE bobbin_id=%s AND status='pending'", (bobbin.id,)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release"), 1)
        self.assertEqual(self.scalar("SELECT revision FROM vinto_txn.capture WHERE id=%s", (capture.id,)), 1)

    def test_valid_f3_on_mp3(self):
        _, assignment = self.assignment("MP3")
        result = self.submit(assignment)
        self.assertEqual((result.bobbin.machine_code, result.bobbin.code, result.capture.revision), ("MP3", "1", 1))

    def test_context_comes_from_the_assignment_and_the_authenticated_user(self):
        order, assignment = self.assignment("MP1")
        result = self.submit(assignment)
        capture = result.capture
        self.assertEqual((capture.shift_code, capture.operating_date, capture.assignment_id), (assignment.shift_code, assignment.operating_date, assignment.id))
        self.assertEqual((capture.work_order_number, capture.line_code, capture.pv_reference), (order.number, "L1", "PV-1"))
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.bobbin WHERE id=%s", (result.bobbin.id,)), self.operator)
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.quality_release WHERE bobbin_id=%s", (result.bobbin.id,)), self.operator)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin WHERE source_capture_id=%s", (capture.id,)), 1)

    def test_the_manual_fields_are_typed_in_the_capture_and_in_the_bobbin(self):
        _, assignment = self.assignment("MP1")
        result = self.submit(assignment)
        rows = {r[0]: r[1:] for r in self.connection.execute(
            """SELECT f.key,d.value_type,d.value_text,d.value_decimal,d.value_time FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id=d.field_definition_id WHERE d.capture_id=%s""", (result.capture.id,)).fetchall()}
        self.assertEqual(set(rows), {"hora_inicio", "hora_fin", "diametro", "peso_kg", "numero_de_cortes", "observaciones"})  # nothing derived is copied
        self.assertEqual(rows["hora_inicio"], ("time", None, None, time(7, 15)))
        self.assertEqual(rows["diametro"], ("decimal", None, Decimal("1200.5"), None))
        self.assertEqual(rows["numero_de_cortes"], ("text", "3", None, None))
        b = result.bobbin
        self.assertEqual((b.start_time, b.end_time, b.diameter_mm, b.weight_kg, b.number_of_cuts, b.notes),
                         (time(7, 15), time(8, 40), "1200.5", "845.25", "3", "sin novedades"))

    def test_observations_are_optional(self):
        _, assignment = self.assignment("MP1")
        values = {k: v for k, v in VALID.items() if k != "observaciones"}
        self.assertIsNone(self.submit(assignment, values=values).bobbin.notes)

    def test_hours_are_manual_and_unconstrained(self):
        _, assignment = self.assignment("MP1")
        crossing = self.submit(assignment, values={**VALID, "hora_inicio": "23:30", "hora_fin": "00:20"}).bobbin  # crosses midnight
        self.assertEqual((crossing.start_time, crossing.end_time), (time(23, 30), time(0, 20)))
        same = self.submit(assignment, values={**VALID, "hora_inicio": "10:00", "hora_fin": "10:00"}).bobbin
        self.assertEqual(same.start_time, same.end_time)
        unrelated = self.submit(assignment, values={**VALID, "hora_inicio": "03:00", "hora_fin": "04:00"}).bobbin  # not the previous bobbin's end
        self.assertEqual(unrelated.start_time, time(3, 0))

    def test_description_and_grammage_are_inherited_and_snapshotted(self):
        _, assignment = self.assignment("MP1", article=WITH_GRAMMAGE)
        result = self.submit(assignment)
        expected = Decimal(str(ARTICLES[WITH_GRAMMAGE]["grammage_g_m2"]))
        self.assertEqual(result.capture.article_description, ARTICLES[WITH_GRAMMAGE]["description"])
        self.assertEqual(result.bobbin.article_description, ARTICLES[WITH_GRAMMAGE]["description"])
        self.assertEqual(result.bobbin.article_code, WITH_GRAMMAGE)
        self.assertEqual(Decimal(result.bobbin.grammage_g_m2), expected)
        self.assertEqual(self.scalar("SELECT grammage_g_m2 FROM vinto_txn.bobbin WHERE id=%s", (result.bobbin.id,)), expected)
        self.assertEqual(self.scalar("SELECT article_version_id FROM vinto_txn.bobbin WHERE id=%s", (result.bobbin.id,)),
                         self.scalar("SELECT l.article_version_id FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id WHERE a.id=%s", (assignment.id,)))

    def test_an_article_without_grammage_still_registers_with_null(self):
        _, assignment = self.assignment(WITHOUT_GRAMMAGE_MACHINE, article=WITHOUT_GRAMMAGE)
        result = self.submit(assignment)
        self.assertIsNone(result.bobbin.grammage_g_m2)
        self.assertIsNone(self.scalar("SELECT grammage_g_m2 FROM vinto_txn.bobbin WHERE id=%s", (result.bobbin.id,)))

    def test_the_stored_grammage_is_a_snapshot_not_a_live_join(self):
        _, assignment = self.assignment("MP1", article=WITH_GRAMMAGE)
        bobbin = self.submit(assignment).bobbin
        with self.assertRaises(psycopg.errors.CheckViolation):  # specs are immutable history
            self.connection.execute("UPDATE vinto_master.article_version_spec SET grammage_g_m2 = 99")
        self.assertEqual(self.scalar("SELECT grammage_g_m2 FROM vinto_txn.bobbin WHERE id=%s", (bobbin.id,)), Decimal(str(ARTICLES[WITH_GRAMMAGE]["grammage_g_m2"])))


class ValidationTests(BobbinCase):
    def test_missing_required_values_are_rejected(self):
        _, assignment = self.assignment("MP1")
        before = self.counts()
        for key in ("hora_inicio", "hora_fin", "diametro", "peso_kg", "numero_de_cortes"):
            with self.assertRaisesRegex(CaptureValidationError, key):
                self.submit(assignment, values={k: v for k, v in VALID.items() if k != key})
        self.assertEqual(self.counts(), before)

    def test_derived_fields_cannot_be_sent(self):
        _, assignment = self.assignment("MP1")
        before = self.counts()
        for extra in ("fecha", "turno", "maquina", "operador", "codigo_de_bobina", "codigo_producto", "descripcion_producto", "gramaje",
                      "orden_trabajo", "linea_ot", "pv", "operating_date", "revision", "status"):
            with self.assertRaisesRegex(CaptureValidationError, "campo desconocido"):
                self.submit(assignment, values={**VALID, extra: "x"})
        self.assertEqual(self.counts(), before)

    def test_types_are_enforced(self):
        _, assignment = self.assignment("MP1")
        for changes in ({"hora_inicio": "25:00"}, {"hora_fin": "abc"}, {"diametro": "ancho"}, {"peso_kg": "1,5"}, {"numero_de_cortes": 3},
                        {"peso_kg": "-0.5"}, {"hora_inicio": "07:00+01:00"}):
            with self.assertRaises(CaptureValidationError, msg=changes):
                self.submit(assignment, values={**VALID, **changes})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 0)

    def test_no_functional_range_was_invented_for_the_diameter(self):
        # VINTO only confirmed diametro as manual, required, decimal and MM: no range. A negative value is used here ONLY as a technical
        # probe that no range rule exists; it does NOT mean VINTO declared such a value operationally valid. peso_kg keeps its non-negative
        # rule because vinto_txn.bobbin.weight_kg already had CHECK (weight_kg >= 0) since 0001.
        _, assignment = self.assignment("MP1")
        for raw in ("-1", "0", "0.0001", "99999999"):
            self.assertEqual(self.submit(assignment, values={**VALID, "diametro": raw}).bobbin.diameter_mm, raw)
        with self.assertRaisesRegex(CaptureValidationError, "peso_kg"):
            self.submit(assignment, values={**VALID, "peso_kg": "-0.01"})
        self.assertNotIn("diameter_mm >=", self.scalar("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='bobbin_f3_row_complete'"))

    def test_number_of_cuts_stays_text(self):
        _, assignment = self.assignment("MP1")
        self.assertEqual(self.submit(assignment, values={**VALID, "numero_de_cortes": "2 + 1"}).bobbin.number_of_cuts, "2 + 1")

    def test_f3_is_published_only_for_its_machines(self):
        _, assignment = self.assignment("MP1")
        self.connection.execute("UPDATE vinto_config.form SET active=false WHERE code='VINTO-P1-03'")
        with self.assertRaises(FormNotAvailableError):
            self.submit(assignment)


class AssignmentTests(BobbinCase):
    def test_a_finished_assignment_is_rejected(self):
        _, assignment = self.assignment("MP1")
        assignments.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment.id)
        before = self.counts()
        with self.assertRaises(AssignmentNotActiveError):
            self.submit(assignment)
        self.assertEqual(self.counts(), before)

    def test_a_replaced_assignment_is_rejected(self):
        _, first = self.assignment("MP1")
        self.assignment("MP1", article=MP1_CODES[1])  # activating another line finishes the first assignment
        with self.assertRaises(AssignmentNotActiveError):
            self.submit(first)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 0)

    def test_a_stale_assignment_from_another_shift_is_rejected(self):
        _, assignment = self.assignment("MP1", at=DAY)
        with self.assertRaises(AssignmentStaleError):
            self.submit(assignment, now=FIRST_DAY_OF_MANAGEMENT)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 0)
        self.assertIsNone(self.sequence_value())


class NumberingTests(BobbinCase):
    def test_per_machine_sequences_are_independent(self):
        _, mp1 = self.assignment("MP1")
        _, mp3 = self.assignment("MP3")
        self.assertEqual([self.submit(mp1).bobbin.code, self.submit(mp1).bobbin.code, self.submit(mp1).bobbin.code], ["1", "2", "3"])
        self.assertEqual(self.submit(mp3).bobbin.code, "1")  # MP3 starts at 1 in the same management
        self.assertEqual(self.submit(mp3).bobbin.code, "2")
        self.assertEqual(self.submit(mp1).bobbin.code, "4")

    def test_code_is_the_plain_number_without_prefix_year_or_machine(self):
        _, assignment = self.assignment("MP1")
        for _ in range(11):
            bobbin = self.submit(assignment).bobbin
        self.assertEqual((bobbin.code, bobbin.sequence_number), ("11", 11))

    def test_march_31_belongs_to_the_previous_management_and_april_1_restarts(self):
        _, march = self.assignment("MP1", at=LAST_DAY_OF_MANAGEMENT)
        first = self.submit(march, now=LAST_DAY_OF_MANAGEMENT).bobbin
        second = self.submit(march, now=LAST_DAY_OF_MANAGEMENT).bobbin
        self.assertEqual((first.management_start_year, first.code, second.code), (2026, "1", "2"))
        _, april = self.assignment("MP1", at=FIRST_DAY_OF_MANAGEMENT)
        restarted = self.submit(april, now=FIRST_DAY_OF_MANAGEMENT).bobbin
        self.assertEqual((restarted.management_start_year, restarted.code), (2027, "1"))
        self.assertEqual(self.submit(april, now=FIRST_DAY_OF_MANAGEMENT).bobbin.code, "2")
        # the same machine holds code "1" in both managements
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id=b.machine_id WHERE m.code='MP1' AND b.code='1'"), 2)

    def test_the_management_rule_in_the_database(self):
        for day, year in (("2026-04-01", 2026), ("2027-03-31", 2026), ("2027-04-01", 2027), ("2026-12-31", 2026), ("2027-01-01", 2026), ("2028-02-29", 2027)):
            self.assertEqual(self.scalar("SELECT vinto_txn.management_start_year(%s::date)", (day,)), year, day)

    def test_the_management_comes_from_the_central_operating_date_not_the_clock(self):
        # 2027-04-01 02:00 La Paz is still the previous operating date (NOCHE of 2027-03-31): management 2026
        late_night = datetime(2027, 4, 1, 6, 0, tzinfo=timezone.utc)
        _, assignment = self.assignment("MP1", at=late_night)
        self.assertEqual(assignment.operating_date, date(2027, 3, 31))
        bobbin = self.submit(assignment, now=late_night).bobbin
        self.assertEqual(bobbin.management_start_year, 2026)

    def test_unique_scope_is_enforced_by_the_database(self):
        indexes = dict(self.connection.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='bobbin' AND schemaname='vinto_txn'").fetchall())
        self.assertIn("UNIQUE", indexes["bobbin_machine_management_sequence_uidx"])
        self.assertIn("(machine_id, management_start_year, sequence_number)", indexes["bobbin_machine_management_sequence_uidx"])
        self.assertIn("UNIQUE", indexes["bobbin_source_capture_uidx"])

    def test_the_counter_cannot_be_reset_or_deleted(self):
        _, assignment = self.assignment("MP1")
        self.submit(assignment)
        for statement in ("UPDATE vinto_txn.bobbin_sequence SET last_value = 1", "DELETE FROM vinto_txn.bobbin_sequence"):
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.connection.execute(statement)
        self.assertEqual(self.sequence_value(), 1)

    def test_concurrent_posts_on_the_same_machine_get_distinct_numbers(self):
        _, assignment = self.assignment("MP1")
        errors, results, barrier = [], [], threading.Barrier(6)

        def worker():
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    results.append(self.submit(assignment, connection=connection, device_key=str(uuid4())).bobbin.sequence_number)
            except Exception as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.scalar("SELECT count(DISTINCT code) FROM vinto_txn.bobbin"), 6)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE status='pending'"), 6)
        self.assertEqual(self.sequence_value(), 6)


class IdempotencyTests(BobbinCase):
    def test_an_exact_retry_returns_the_same_bobbin_without_writing(self):
        _, assignment = self.assignment("MP1")
        capture_id = uuid4()
        first = self.submit(assignment, capture_id=capture_id)
        before = self.counts()
        second = self.submit(assignment, capture_id=capture_id)
        self.assertEqual((second.created, second.already_submitted), (False, True))
        self.assertEqual((second.bobbin, second.capture), (first.bobbin, first.capture))
        self.assertEqual(self.counts(), before)  # no second bobbin, release, counter bump or audit event
        self.assertEqual(self.sequence_value(), 1)

    def test_a_retry_after_the_assignment_finished_still_returns_the_bobbin(self):
        _, assignment = self.assignment("MP1")
        capture_id = uuid4()
        first = self.submit(assignment, capture_id=capture_id)
        assignments.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment.id)
        self.assertEqual(self.submit(assignment, capture_id=capture_id).bobbin.id, first.bobbin.id)

    def test_the_same_capture_id_with_different_content_conflicts_and_keeps_the_counter(self):
        _, assignment = self.assignment("MP1")
        capture_id = uuid4()
        self.submit(assignment, capture_id=capture_id)
        other_operator = self.user("OPERACION")
        _, other = self.assignment("MP3")
        before = self.counts()
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(assignment, capture_id=capture_id, values={**VALID, "peso_kg": "1.00"})
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(assignment, capture_id=capture_id, actor=other_operator)
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(other, capture_id=capture_id)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.sequence_value(), 1)

    def test_an_f6_capture_id_cannot_be_reused_for_f3(self):
        _, assignment = self.assignment("MP1")
        capture_id = uuid4()
        capture_service.submit_production_capture(
            self.connection, actor_id=self.operator, capture_id=capture_id, form_code="VINTO-P1-06", assignment_id=assignment.id,
            device_key=self.device_key, values={"cantidad_fardos": 1, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "1"})
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(assignment, capture_id=capture_id)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 0)

    def test_concurrent_identical_retries_create_one_bobbin(self):
        _, assignment = self.assignment("MP1")
        capture_id = uuid4()
        errors, results, barrier = [], [], threading.Barrier(4)

        def worker():
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    r = self.submit(assignment, capture_id=capture_id, connection=connection)
                    results.append((r.created, r.bobbin.code))
            except Exception as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [(False, "1")] * 3 + [(True, "1")])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release"), 1)
        self.assertEqual(self.sequence_value(), 1)


class AtomicityTests(BobbinCase):
    def assert_nothing_written(self, assignment, patched, error=RuntimeError):
        self.submit(assignment)  # one committed bobbin so the counter exists and a leak would be visible
        before = self.counts()
        with patched:
            with self.assertRaises(error):
                self.submit(assignment, device_key=str(uuid4()))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.sequence_value(), 1)
        retried = self.submit(assignment)
        self.assertEqual(retried.bobbin.code, "2")  # the failed attempt did not consume number 2

    def test_a_bobbin_failure_rolls_everything_back(self):
        _, assignment = self.assignment("MP1")
        self.assert_nothing_written(assignment, patch.object(bobbins, "_insert_bobbin", side_effect=RuntimeError("bobbin")))

    def test_a_quality_release_failure_rolls_everything_back(self):
        _, assignment = self.assignment("MP1")
        self.assert_nothing_written(assignment, patch.object(bobbins, "_insert_quality_release", side_effect=RuntimeError("release")))

    def test_a_detail_failure_rolls_back_the_counter(self):
        _, assignment = self.assignment("MP1")
        self.assert_nothing_written(assignment, patch.object(capture_service, "_insert_details", side_effect=RuntimeError("detail")))

    def test_the_first_ever_failure_leaves_no_counter_row(self):
        _, assignment = self.assignment("MP1")
        with patch.object(bobbins, "_insert_quality_release", side_effect=RuntimeError("release")):
            with self.assertRaises(RuntimeError):
                self.submit(assignment)
        self.assertEqual(self.counts()["vinto_txn.bobbin_sequence"], 0)
        self.assertEqual(self.submit(assignment).bobbin.code, "1")

    def test_a_validation_error_before_the_counter_consumes_nothing(self):
        _, assignment = self.assignment("MP1")
        with self.assertRaises(CaptureValidationError):
            self.submit(assignment, values={**VALID, "peso_kg": "x"})
        self.assertIsNone(self.sequence_value())

    def test_a_bobbin_without_quality_release_cannot_commit(self):
        _, assignment = self.assignment("MP1")
        before = self.counts()
        with patch.object(bobbins, "_insert_quality_release", lambda connection, bobbin_id: None):
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.submit(assignment)  # deferred constraint fails at COMMIT
        self.assertEqual(self.counts(), before)


class SchemaPreservationTests(BobbinCase):
    def test_legacy_rows_survive_and_the_global_code_unique_is_gone(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM pg_constraint WHERE conname='bobbin_code_key'"), 0)
        # a legacy-shaped row (no machine/sequence) is still valid and keeps global code uniqueness among legacy rows
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('LEGACY-1')")
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('LEGACY-1')")
        _, assignment = self.assignment("MP1")
        self.assertEqual(self.submit(assignment).bobbin.code, "1")
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('1')")  # legacy "1" does not clash with the numbered "1"
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 3)

    def test_new_rows_must_be_complete_and_coherent_with_the_capture(self):
        _, assignment = self.assignment("MP1")
        bobbin = self.submit(assignment).bobbin
        row = self.connection.execute("SELECT source_capture_id, article_version_id FROM vinto_txn.bobbin WHERE id=%s", (bobbin.id,)).fetchone()
        mp3 = self.scalar("SELECT id FROM vinto_master.machine WHERE code='MP3'")
        mp1 = self.scalar("SELECT id FROM vinto_master.machine WHERE code='MP1'")
        base = dict(code="9", capture=row[0], article=row[1], machine=mp1, year=2026, seq=9)
        insert = """INSERT INTO vinto_txn.bobbin (code, source_capture_id, article_version_id, weight_kg, machine_id, management_start_year, sequence_number,
                    start_time, end_time, diameter_mm, number_of_cuts) VALUES (%(code)s,%(capture)s,%(article)s,1,%(machine)s,%(year)s,%(seq)s,'01:00','02:00',1,'1')"""
        for change in ({"machine": mp3}, {"year": 2027}, {"code": "10"}):
            with self.assertRaises(psycopg.errors.Error, msg=change):
                with self.connection.transaction():
                    self.connection.execute(insert, {**base, **change})
        with self.assertRaises(psycopg.errors.CheckViolation):  # identity is immutable
            self.connection.execute("UPDATE vinto_txn.bobbin SET machine_id=%s WHERE id=%s", (mp3, bobbin.id))

    def test_f6_still_works_and_f6_listing_excludes_f3(self):
        _, assignment = self.assignment("MP1")
        f3 = self.submit(assignment)
        f6 = capture_service.submit_production_capture(
            self.connection, actor_id=self.operator, capture_id=uuid4(), form_code="VINTO-P1-06", assignment_id=assignment.id, device_key=self.device_key,
            values={"cantidad_fardos": 1, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "1"})
        self.assertEqual(f6.capture.revision, 1)
        self.assertEqual([c.id for c in capture_service.list_captures(self.connection)], [f6.capture.id])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 1)
        self.assertNotEqual(f3.capture.id, f6.capture.id)

    def test_no_history_is_deleted_by_registering_bobbins(self):
        _, assignment = self.assignment("MP1")
        self.submit(assignment)
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        self.submit(assignment)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE action='DELETE'"), 0)


if __name__ == "__main__":
    unittest.main()
