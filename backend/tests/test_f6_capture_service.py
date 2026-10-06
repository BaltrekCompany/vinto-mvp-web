"""F6 (VINTO-P1-06) central capture, domain level: context derived from the assignment, dynamic validation, typed details,
idempotency, devices, atomicity and concurrency.

Runs in ephemeral *_test databases copied from a migrated template with the reference bundle. Nothing touches vinto.
"""

import inspect
import secrets
import threading
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import capture_service
from app.assignments import service as assignments
from app.assignments.errors import AssignmentNotFoundError
from app.auth.service import create_user
from app.capture_errors import (AssignmentNotActiveError, AssignmentStaleError, CaptureIdempotencyConflictError, CaptureNotFoundError,
                                CaptureValidationError, DeviceInactiveError, DeviceMachineMismatchError, FormNotAvailableError,
                                UnsupportedFormDefinitionError, UnsupportedFormError)
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.shifts import SHIFT_NOT_CONFIGURED, ShiftResolutionError
from app.work_orders import service as work_orders
from app.work_orders.service import LineInput

BUNDLE = load_bundle()
STATE = {}
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
MP3_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP3")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz, DIA, 2026-10-06
NIGHT = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)  # 21:00 La Paz, NOCHE, 2026-10-06
NEXT_DAY = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz, DIA, 2026-10-07
VALID = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "sin novedades"}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_cap_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class CaptureCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_cap")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.jefatura = self.user("JEFATURA")
        self.supervisor = self.user("SUPERVISION")
        self.operator = self.user("OPERACION")
        self.device_key = str(uuid4())

    def user(self, profile):
        return create_user(self.connection, username=f"cap.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile,
                           password="pw-" + secrets.token_urlsafe(18)).user_id

    def assignment(self, machine="MP1", at=None, lines=2):
        codes = MP1_CODES if machine == "MP1" else MP3_CODES
        order = work_orders.create_work_order(self.connection, actor_id=self.jefatura, machine_code=machine,
                                              lines=[LineInput(f"PV-{i + 1}", codes[i], 10 * (i + 1), date(2026, 11, 1)) for i in range(lines)])
        order = work_orders.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        if at is None:
            result = assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id)
        else:
            with patch.object(assignments, "_now", return_value=at):
                result = assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id)
        return order, result.assignment

    def submit(self, assignment, values=VALID, capture_id=None, actor=None, device_key=None, connection=None, form_code="VINTO-P1-06", now=None):
        kwargs = dict(actor_id=actor or self.operator, capture_id=capture_id or uuid4(), form_code=form_code, assignment_id=assignment.id,
                      device_key=device_key or self.device_key, values=values)
        if now is not None:
            with patch.object(capture_service, "_now", return_value=now):
                return capture_service.submit_production_capture(connection or self.connection, **kwargs)
        return capture_service.submit_production_capture(connection or self.connection, **kwargs)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_master.device", "vinto_audit.audit_event")}

    def details(self, capture_id):
        return self.connection.execute(
            """SELECT f.key,d.value_type,d.value_text,d.value_decimal,d.value_integer,d.value_boolean,d.value_date,d.value_time,d.field_group_id,d.group_row_id
               FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id=d.field_definition_id WHERE d.capture_id=%s ORDER BY f.display_order""", (capture_id,)).fetchall()


class ContextTests(CaptureCase):
    def test_valid_f6_on_mp1_is_submitted_with_revision_one(self):
        _, assignment = self.assignment("MP1")
        result = self.submit(assignment)
        view = result.capture
        self.assertEqual((result.created, result.already_submitted), (True, False))
        self.assertEqual((view.status, view.revision, view.machine_code, view.form_code), ("submitted", 1, "MP1", "VINTO-P1-06"))
        self.assertIsNotNone(view.submitted_at)

    def test_valid_f6_on_mp3(self):
        _, assignment = self.assignment("MP3")
        view = self.submit(assignment).capture
        self.assertEqual((view.status, view.machine_code, view.revision), ("submitted", "MP3", 1))

    def test_captured_at_comes_from_the_postgres_clock(self):
        _, assignment = self.assignment()
        before = self.scalar("SELECT clock_timestamp()")
        view = self.submit(assignment).capture
        after = self.scalar("SELECT clock_timestamp()")
        self.assertTrue(before <= view.captured_at <= after)
        self.assertLessEqual(view.captured_at, view.submitted_at)

    def test_context_is_derived_from_the_assignment(self):
        order, assignment = self.assignment("MP1")
        view = self.submit(assignment).capture
        self.assertEqual((view.machine_code, view.machine_name), (assignment.machine_code, assignment.machine_name))
        self.assertEqual((view.shift_code, view.shift_name, view.operating_date), (assignment.shift_code, assignment.shift_name, assignment.operating_date))
        self.assertEqual((view.assignment_id, view.work_order_id, view.work_order_number), (assignment.id, order.id, order.number))
        self.assertEqual((view.line_id, view.line_code, view.pv_reference), (assignment.line.id, "L1", "PV-1"))
        self.assertEqual((view.article_code, view.article_description), (assignment.line.article_code, assignment.line.article_description))
        row = self.connection.execute("SELECT machine_id,shift_schedule_id,operating_date,assignment_id FROM vinto_txn.capture WHERE id=%s", (view.id,)).fetchone()
        expected = self.connection.execute("SELECT machine_id,shift_schedule_id,operating_date,id FROM vinto_txn.assignment WHERE id=%s", (assignment.id,)).fetchone()
        self.assertEqual(row, expected)

    def test_the_published_form_version_is_resolved_by_code_and_the_highest_published_wins(self):
        _, assignment = self.assignment()
        self.assertEqual(self.submit(assignment).capture.form_version_number, 1)
        c = self.connection
        form_id = self.scalar("SELECT id FROM vinto_config.form WHERE code='VINTO-P1-06'")
        v1 = self.scalar("SELECT id FROM vinto_config.form_version WHERE form_id=%s AND version_number=1", (form_id,))
        v2 = self.scalar("""INSERT INTO vinto_config.form_version (form_id,version_number,name,area,workflow_id,definition_checksum)
                            SELECT form_id,2,'Registro de control de fardos v2',area,workflow_id,%s FROM vinto_config.form_version WHERE id=%s RETURNING id""", ("2" * 64, v1))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id,machine_id) SELECT %s,machine_id FROM vinto_config.form_version_machine WHERE form_version_id=%s", (v2, v1))
        c.execute("""INSERT INTO vinto_config.field_definition (form_version_id,key,label,value_type,source,required,unit_id,display_order)
                     SELECT %s,key,label,value_type,source,required,unit_id,display_order FROM vinto_config.field_definition WHERE form_version_id=%s""", (v2, v1))
        c.execute("""INSERT INTO vinto_config.field_option (form_version_id,field_definition_id,option_key,label,display_order)
                     SELECT %s,n.id,o.option_key,o.label,o.display_order FROM vinto_config.field_option o
                     JOIN vinto_config.field_definition old ON old.id=o.field_definition_id JOIN vinto_config.field_definition n ON n.form_version_id=%s AND n.key=old.key
                     WHERE o.form_version_id=%s""", (v2, v2, v1))
        c.execute("UPDATE vinto_config.form_version SET status='published',published_at=clock_timestamp() WHERE id=%s", (v2,))
        self.assertEqual(self.submit(assignment).capture.form_version_number, 2)

    def test_the_client_cannot_provide_the_form_version_or_any_derived_field(self):
        parameters = set(inspect.signature(capture_service.submit_production_capture).parameters)
        self.assertEqual(parameters, {"connection", "actor_id", "capture_id", "form_code", "assignment_id", "device_key", "values", "request_id"})

    def test_only_f6_is_enabled(self):
        _, assignment = self.assignment()
        for code in ("VINTO-P1-03", "vinto-p1-06", "", None):
            with self.subTest(code=code), self.assertRaises(UnsupportedFormError):
                self.submit(assignment, form_code=code)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    def test_an_unpublished_or_missing_form_is_not_available(self):
        _, assignment = self.assignment()
        self.connection.execute("UPDATE vinto_config.form SET active=false WHERE code='VINTO-P1-06'")
        with self.assertRaises(FormNotAvailableError):
            self.submit(assignment)
        self.connection.execute("UPDATE vinto_config.form SET active=true WHERE code='VINTO-P1-06'")
        self.connection.execute("SET session_replication_role = replica")  # ephemeral *_test database only
        self.connection.execute("DELETE FROM vinto_config.form_version_machine WHERE machine_id=(SELECT id FROM vinto_master.machine WHERE code='MP1')")
        self.connection.execute("SET session_replication_role = DEFAULT")
        with self.assertRaises(FormNotAvailableError):
            self.submit(assignment)


class ValuesTests(CaptureCase):
    def setUp(self):
        super().setUp()
        _, self.assignment_view = self.assignment()

    def ok(self, values):
        return self.submit(self.assignment_view, values=values).capture

    def bad(self, values, text=None):
        with self.assertRaises(CaptureValidationError) as raised:
            self.submit(self.assignment_view, values=values)
        if text:
            self.assertIn(text, str(raised.exception))
        return raised.exception

    def test_the_four_required_values_are_enough_and_observaciones_is_optional(self):
        view = self.ok({k: v for k, v in VALID.items() if k != "observaciones"})
        self.assertNotIn("observaciones", view.values)
        self.assertEqual(len(self.details(view.id)), 4)

    def test_a_blank_observaciones_creates_no_detail(self):
        for blank in ("", "   ", None, "\n\t"):
            with self.subTest(blank=repr(blank)):
                view = self.ok({**VALID, "observaciones": blank})
                self.assertEqual({d[0] for d in self.details(view.id)}, {"cantidad_fardos", "punto_merma", "tipo_producto", "peso_kg"})

    def test_observaciones_is_trimmed_and_stored(self):
        view = self.ok({**VALID, "observaciones": "  hola  "})
        self.assertEqual(view.values["observaciones"], "hola")

    def test_missing_required_fields_are_422(self):
        for key in ("cantidad_fardos", "punto_merma", "tipo_producto", "peso_kg"):
            with self.subTest(key=key):
                self.bad({k: v for k, v in VALID.items() if k != key}, f"{key}: obligatorio")
        self.bad({}, "cantidad_fardos: obligatorio")
        self.bad({**VALID, "peso_kg": ""}, "peso_kg: obligatorio")
        self.bad({**VALID, "peso_kg": None}, "peso_kg: obligatorio")

    def test_unknown_fields_are_422(self):
        error = self.bad({**VALID, "machine_code": "MP3", "foo": 1}, "campo desconocido")
        self.assertIn("foo", str(error))
        self.assertIn("machine_code", str(error))

    def test_option_keys_are_validated_and_labels_are_not_accepted(self):
        for value in ("otro", "Recorte de máquina", "RECORTE_MAQUINA", "bobina rechazada", 3, ["recorte_maquina"], {"a": 1}):
            with self.subTest(punto_merma=repr(value)):
                self.bad({**VALID, "punto_merma": value})
        for value in ("Hoja doble", "papel", "hoja_triple"):
            with self.subTest(tipo_producto=value):
                self.bad({**VALID, "tipo_producto": value})
        for punto in ("bobina_rechazada", "recorte_maquina"):
            for tipo in ("servilleta", "hoja_doble", "hoja_simple"):
                self.assertEqual(self.ok({**VALID, "punto_merma": punto, "tipo_producto": tipo}).values["punto_merma"], punto)

    def test_integer_rules(self):
        for good, expected in ((10, 10), ("12", 12), (0, 0), (-3, -3), (" 7 ", 7)):
            with self.subTest(good=repr(good)):
                self.assertEqual(self.ok({**VALID, "cantidad_fardos": good}).values["cantidad_fardos"], expected)
        for wrong in (True, False, 1.5, 10.0, "1.5", "abc", "1e3", [1], {"a": 1}, 2 ** 70):
            with self.subTest(wrong=repr(wrong)):
                self.bad({**VALID, "cantidad_fardos": wrong})

    def test_decimal_rules(self):
        for good, expected in (("125.50", "125.50"), (125.5, "125.5"), (100, "100"), ("0.001", "0.001"), ("-2.5", "-2.5"), (1e-05, "0.00001"), (" 7.25 ", "7.25")):
            with self.subTest(good=repr(good)):
                self.assertEqual(self.ok({**VALID, "peso_kg": good}).values["peso_kg"], expected)
        for wrong in (float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-inf", "1e5", "1,5", "abc", True, [1], {"a": 1}, "1" * 41):
            with self.subTest(wrong=repr(wrong)):
                self.bad({**VALID, "peso_kg": wrong})

    def test_no_functional_limits_are_invented(self):
        view = self.ok({**VALID, "cantidad_fardos": 0, "peso_kg": "0"})  # the seed does not define > 0 rules
        self.assertEqual((view.values["cantidad_fardos"], view.values["peso_kg"]), (0, "0"))

    def test_values_must_be_an_object(self):
        for wrong in ([], "x", None, 5):
            with self.subTest(wrong=repr(wrong)), self.assertRaises(CaptureValidationError):
                self.submit(self.assignment_view, values=wrong)

    def test_each_detail_uses_exactly_one_typed_column(self):
        view = self.ok(VALID)
        rows = {d[0]: d for d in self.details(view.id)}
        self.assertEqual(rows["cantidad_fardos"][1:8], ("integer", None, None, 10, None, None, None))
        self.assertEqual(rows["punto_merma"][1:8], ("text", "recorte_maquina", None, None, None, None, None))
        self.assertEqual(rows["tipo_producto"][1:8], ("text", "hoja_doble", None, None, None, None, None))
        self.assertEqual(rows["peso_kg"][1:8], ("decimal", None, Decimal("125.50"), None, None, None, None))
        self.assertEqual(rows["observaciones"][1:8], ("textarea", "sin novedades", None, None, None, None, None))
        for row in rows.values():
            self.assertEqual(sum(v is not None for v in row[2:8]), 1)
            self.assertEqual((row[8], row[9]), (None, None))  # no group

    def test_decimals_keep_their_precision(self):
        self.assertEqual(self.ok({**VALID, "peso_kg": "123456789.123456789"}).values["peso_kg"], "123456789.123456789")
        self.assertEqual(self.ok({**VALID, "peso_kg": "125.50"}).values["peso_kg"], "125.50")

    def test_rejected_values_leave_no_capture_and_no_device(self):
        before = self.counts()
        self.bad({**VALID, "peso_kg": "abc"})
        self.assertEqual(self.counts(), before)

    def test_unsupported_field_definitions_are_reported_not_accepted(self):
        for statement in ("UPDATE vinto_config.field_definition SET source='calculated' WHERE key='peso_kg'",):
            self.connection.execute("SET session_replication_role = replica")
            try:
                self.connection.execute(statement)
            finally:
                self.connection.execute("SET session_replication_role = DEFAULT")
            with self.assertRaises(UnsupportedFormDefinitionError):
                self.submit(self.assignment_view)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)


class AssignmentTests(CaptureCase):
    def test_a_finished_assignment_is_rejected(self):
        _, assignment = self.assignment()
        assignments.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment.id)
        with self.assertRaises(AssignmentNotActiveError):
            self.submit(assignment)

    def test_a_replaced_assignment_is_rejected(self):
        order, first = self.assignment()
        assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[1].id)
        with self.assertRaises(AssignmentNotActiveError):
            self.submit(first)

    def test_a_shift_change_makes_the_assignment_stale(self):
        _, assignment = self.assignment(at=DAY)
        self.assertEqual(self.submit(assignment, now=DAY).capture.shift_code, "DIA")
        with self.assertRaises(AssignmentStaleError):
            self.submit(assignment, now=NIGHT)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 1)

    def test_a_date_change_in_the_same_shift_makes_the_assignment_stale(self):
        _, assignment = self.assignment(at=DAY)
        with self.assertRaises(AssignmentStaleError):
            self.submit(assignment, now=NEXT_DAY)  # DIA again, but 2026-10-07

    def test_a_closed_order_is_rejected(self):
        order, assignment = self.assignment()
        self.connection.execute("UPDATE vinto_txn.work_order SET status='closed' WHERE id=%s", (order.id,))
        with self.assertRaises(AssignmentNotActiveError):
            self.submit(assignment)

    def test_a_baseline_line_cannot_be_the_context(self):
        order, assignment = self.assignment()
        assignments.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment.id)
        machine_id = self.scalar("SELECT id FROM vinto_master.machine WHERE code='MP1'")
        schedule = self.scalar("SELECT shift_schedule_id FROM vinto_txn.assignment WHERE id=%s", (assignment.id,))
        operating = self.scalar("SELECT operating_date FROM vinto_txn.assignment WHERE id=%s", (assignment.id,))
        baseline_assignment = self.scalar(
            """INSERT INTO vinto_txn.assignment (work_order_line_id,machine_id,shift_schedule_id,operating_date,assigned_by) VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (order.baseline.lines[0].id, machine_id, schedule, operating, self.supervisor))
        with self.assertRaises(AssignmentNotActiveError):
            capture_service.submit_production_capture(self.connection, actor_id=self.operator, capture_id=uuid4(), form_code="VINTO-P1-06",
                                                      assignment_id=baseline_assignment, device_key=self.device_key, values=VALID)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    def test_unknown_assignment(self):
        for value in (uuid4(), "nope"):
            with self.subTest(str(value)), self.assertRaises(AssignmentNotFoundError):
                capture_service.submit_production_capture(self.connection, actor_id=self.operator, capture_id=uuid4(), form_code="VINTO-P1-06",
                                                          assignment_id=value, device_key=self.device_key, values=VALID)

    def test_a_shift_configuration_failure_leaves_nothing_behind(self):
        _, assignment = self.assignment()
        self.connection.execute("UPDATE vinto_config.shift SET active=false")
        before = self.counts()
        with self.assertRaises(ShiftResolutionError) as raised:
            self.submit(assignment)
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)
        self.assertEqual(self.counts(), before)  # no capture, no details, no device, no audit


class DeviceTests(CaptureCase):
    def test_a_new_device_is_created_without_a_machine(self):
        _, assignment = self.assignment()
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.device WHERE external_key=%s", (self.device_key,)), 0)
        self.submit(assignment)
        row = self.connection.execute("SELECT machine_id,active,created_by,updated_by FROM vinto_master.device WHERE external_key=%s", (self.device_key,)).fetchone()
        self.assertEqual(row, (None, True, self.operator, self.operator))

    def test_an_existing_device_is_reused_across_machines(self):
        _, mp1 = self.assignment("MP1")
        _, mp3 = self.assignment("MP3")
        self.submit(mp1)
        self.submit(mp3)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.device WHERE external_key=%s", (self.device_key,)), 1)
        self.assertEqual(self.scalar("SELECT count(DISTINCT device_id) FROM vinto_txn.capture"), 1)

    def test_an_inactive_device_is_rejected(self):
        _, assignment = self.assignment()
        self.submit(assignment)
        self.connection.execute("UPDATE vinto_master.device SET active=false WHERE external_key=%s", (self.device_key,))
        before = self.counts()
        with self.assertRaises(DeviceInactiveError):
            self.submit(assignment)
        self.assertEqual(self.counts(), before)

    def test_a_machine_bound_device_only_works_on_its_machine(self):
        _, mp1 = self.assignment("MP1")
        _, mp3 = self.assignment("MP3")
        self.connection.execute("INSERT INTO vinto_master.device (external_key,machine_id) SELECT %s,id FROM vinto_master.machine WHERE code='MP3'", (self.device_key,))
        with self.assertRaises(DeviceMachineMismatchError):
            self.submit(mp1)
        self.assertEqual(self.submit(mp3).capture.machine_code, "MP3")

    def test_the_same_device_key_in_parallel_creates_one_device_and_no_errors(self):
        _, assignment = self.assignment()
        errors, barrier, results = [], threading.Barrier(5), []

        def worker():
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    results.append(self.submit(assignment, connection=connection).created)
            except Exception as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(results, [True] * 5)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.device WHERE external_key=%s", (self.device_key,)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 5)


class IdempotencyTests(CaptureCase):
    def test_a_retry_returns_the_same_capture_without_writing(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        first = self.submit(assignment, capture_id=capture_id)
        before = self.counts()
        second = self.submit(assignment, capture_id=capture_id)
        self.assertEqual((second.created, second.already_submitted, second.capture.id), (False, True, first.capture.id))
        self.assertEqual(second.capture, first.capture)
        self.assertEqual(self.counts(), before)  # no new audit events either

    def test_a_retry_with_equivalent_values_is_the_same_request(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        self.submit(assignment, capture_id=capture_id)
        again = self.submit(assignment, capture_id=capture_id, values={**VALID, "peso_kg": 125.5, "cantidad_fardos": "10", "observaciones": " sin novedades "})
        self.assertEqual((again.created, again.already_submitted), (False, True))

    def test_a_retry_after_the_assignment_changed_still_returns_the_original(self):
        order, assignment = self.assignment(at=DAY)
        capture_id = uuid4()
        first = self.submit(assignment, capture_id=capture_id, now=DAY)
        assignments.finish(self.connection, actor_id=self.supervisor, assignment_id=assignment.id)
        retry = self.submit(assignment, capture_id=capture_id, now=NIGHT)
        self.assertEqual((retry.already_submitted, retry.capture.id), (True, first.capture.id))

    def test_the_same_id_with_different_values_is_a_conflict(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        self.submit(assignment, capture_id=capture_id)
        before = self.counts()
        for changed in ({**VALID, "cantidad_fardos": 11}, {**VALID, "observaciones": "otra"}, {k: v for k, v in VALID.items() if k != "observaciones"},
                        {**VALID, "peso_kg": "abc"}, {**VALID, "extra": 1}):
            with self.subTest(changed=str(changed)[:40]), self.assertRaises(CaptureIdempotencyConflictError):
                self.submit(assignment, capture_id=capture_id, values=changed)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.submit(assignment, capture_id=capture_id).capture.values["cantidad_fardos"], 10)  # nothing was overwritten

    def test_the_same_id_with_another_assignment_is_a_conflict(self):
        _, one = self.assignment("MP1")
        _, two = self.assignment("MP3")
        capture_id = uuid4()
        self.submit(one, capture_id=capture_id)
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(two, capture_id=capture_id)

    def test_the_same_id_by_another_actor_is_a_conflict(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        self.submit(assignment, capture_id=capture_id)
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(assignment, capture_id=capture_id, actor=self.user("OPERACION"))

    def test_the_same_id_with_another_device_is_a_conflict(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        self.submit(assignment, capture_id=capture_id)
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(assignment, capture_id=capture_id, device_key=str(uuid4()))

    def test_two_identical_simultaneous_requests_create_one_capture(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        errors, barrier, results = [], threading.Barrier(4), []

        def worker():
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    r = self.submit(assignment, capture_id=capture_id, connection=connection)
                    results.append((r.created, r.already_submitted))
            except Exception as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [(False, True)] * 3 + [(True, False)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), 5)
        self.assertEqual(self.scalar("SELECT revision FROM vinto_txn.capture"), 1)


class AtomicityTests(CaptureCase):
    def test_a_detail_failure_rolls_back_the_header_and_the_new_device(self):
        _, assignment = self.assignment()
        before = self.counts()
        with patch.object(capture_service, "_insert_details", side_effect=RuntimeError("detail could not be written")):
            with self.assertRaises(RuntimeError):
                self.submit(assignment)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.device WHERE external_key=%s", (self.device_key,)), 0)

    def test_the_deferred_required_check_is_the_last_defence_and_rolls_everything_back(self):
        _, assignment = self.assignment()
        before = self.counts()
        real = capture_service.validate_values
        with patch.object(capture_service, "validate_values", side_effect=lambda fields, values: {k: v for k, v in real(fields, values).items() if k != "peso_kg"}):
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.submit(assignment)  # fails at COMMIT: required peso_kg has no detail
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.device WHERE external_key=%s", (self.device_key,)), 0)

    def test_a_failed_attempt_can_be_retried_with_the_same_capture_id(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        with self.assertRaises(CaptureValidationError):
            self.submit(assignment, capture_id=capture_id, values={**VALID, "peso_kg": "abc"})
        result = self.submit(assignment, capture_id=capture_id)
        self.assertEqual((result.created, result.capture.revision), (True, 1))


class AuditTests(CaptureCase):
    def test_the_audit_trail_covers_capture_details_transition_and_device(self):
        _, assignment = self.assignment()
        mark = self.scalar("SELECT coalesce(max(id),0) FROM vinto_audit.audit_event")
        view = self.submit(assignment).capture
        events = self.connection.execute(
            """SELECT entity_table,action,actor_id,reason,request_id,old_data->>'status',new_data->>'status' FROM vinto_audit.audit_event
               WHERE id>%s AND entity_table IN ('capture','capture_detail','device') ORDER BY id""", (mark,)).fetchall()
        tables = [(e[0], e[1]) for e in events]
        self.assertEqual(tables.count(("device", "INSERT")), 1)
        self.assertEqual(tables.count(("capture", "INSERT")), 1)
        self.assertEqual(tables.count(("capture_detail", "INSERT")), 5)
        self.assertEqual(tables.count(("capture", "UPDATE")), 1)
        update = next(e for e in events if e[:2] == ("capture", "UPDATE"))
        self.assertEqual((update[5], update[6]), ("draft", "submitted"))
        self.assertTrue(all(e[2] == self.operator and e[3] == "submit production capture" and e[4].startswith("capture:") for e in events))
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id=%s", (view.id,)), self.operator)
        self.assertEqual(self.scalar("SELECT revision FROM vinto_txn.capture WHERE id=%s", (view.id,)), 1)
        dump = " ".join(f"{o} {n}" for o, n in self.connection.execute("SELECT old_data::text,new_data::text FROM vinto_audit.audit_event").fetchall()).lower()
        for forbidden in ("password", "token", "argon2", "cookie"):
            self.assertNotIn(forbidden, dump)


class QueryTests(CaptureCase):
    def test_get_and_list(self):
        _, one = self.assignment("MP1")
        _, three = self.assignment("MP3")
        first = self.submit(one).capture
        second = self.submit(three, values={**VALID, "observaciones": None}).capture
        self.assertEqual(capture_service.get_capture(self.connection, first.id), first)
        listed = capture_service.list_captures(self.connection)
        self.assertEqual([c.id for c in listed], [second.id, first.id])  # newest first
        self.assertEqual([c.id for c in capture_service.list_captures(self.connection, machine_code="MP1")], [first.id])
        self.assertEqual([c.id for c in capture_service.list_captures(self.connection, assignment_id=three.id)], [second.id])
        self.assertEqual([c.id for c in capture_service.list_captures(self.connection, operating_date=first.operating_date)], [second.id, first.id])
        self.assertEqual(capture_service.list_captures(self.connection, operating_date=date(2000, 1, 1)), [])
        self.assertEqual(len(capture_service.list_captures(self.connection, limit=1)), 1)

    def test_drafts_are_not_listed_and_unknown_ids_are_404(self):
        _, assignment = self.assignment()
        self.submit(assignment)
        self.assertEqual(len(capture_service.list_captures(self.connection)), 1)
        for value in (uuid4(), "nope", None):
            with self.subTest(str(value)), self.assertRaises(CaptureNotFoundError):
                capture_service.get_capture(self.connection, value)

    def test_other_forms_are_not_visible_through_this_endpoint(self):
        _, assignment = self.assignment()
        view = self.submit(assignment).capture
        self.connection.execute("UPDATE vinto_config.form SET code='VINTO-P1-99' WHERE code='VINTO-P1-06'")
        with self.assertRaises(CaptureNotFoundError):
            capture_service.get_capture(self.connection, view.id)
        self.assertEqual(capture_service.list_captures(self.connection), [])


class ConcurrencyWithAssignmentsTests(CaptureCase):
    def test_a_capture_racing_with_finish_is_serialised(self):
        for _ in range(3):
            _, assignment = self.assignment()
            capture_id = uuid4()
            outcomes, errors, barrier = [], [], threading.Barrier(2)

            def capture():
                try:
                    with connect(self.database) as connection:
                        barrier.wait(timeout=10)
                        try:
                            self.submit(assignment, capture_id=capture_id, connection=connection)
                            outcomes.append("captured")
                        except AssignmentNotActiveError:
                            outcomes.append("rejected")
                except Exception as error:
                    errors.append(repr(error))

            def finish():
                try:
                    with connect(self.database) as connection:
                        barrier.wait(timeout=10)
                        assignments.finish(connection, actor_id=self.supervisor, assignment_id=assignment.id)
                except Exception as error:
                    errors.append(repr(error))

            threads = [threading.Thread(target=capture), threading.Thread(target=finish)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
            self.assertEqual(errors, [])
            self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (assignment.id,)), "finished")
            exists = self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (capture_id,))
            self.assertEqual((outcomes, exists), (["captured"], 1) if exists else (["rejected"], 0))
            if exists:  # the capture was committed BEFORE the assignment was finished: never after
                self.assertLessEqual(self.scalar("SELECT c.submitted_at FROM vinto_txn.capture c WHERE c.id=%s", (capture_id,)),
                                     self.scalar("SELECT finished_at FROM vinto_txn.assignment WHERE id=%s", (assignment.id,)))

    def test_a_capture_racing_with_a_replacing_activation_is_serialised(self):
        order, assignment = self.assignment()
        capture_id = uuid4()
        outcomes, errors, barrier = [], [], threading.Barrier(2)

        def capture():
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    try:
                        self.submit(assignment, capture_id=capture_id, connection=connection)
                        outcomes.append("captured")
                    except AssignmentNotActiveError:
                        outcomes.append("rejected")
            except Exception as error:
                errors.append(repr(error))

        def activate():
            try:
                with connect(self.database) as connection:
                    barrier.wait(timeout=10)
                    assignments.activate(connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[1].id)
            except Exception as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=capture), threading.Thread(target=activate)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(s[0] for s in self.connection.execute("SELECT status FROM vinto_txn.assignment").fetchall()), ["active", "finished"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 1 if outcomes == ["captured"] else 0)


if __name__ == "__main__":
    unittest.main()
