"""M2-A: the central production engine serves more than one form, driven by an EXPLICIT policy (capture_service.CENTRAL_FORM_CODES).

A synthetic production form (tests/m2a_fixtures.py) is installed ONLY in ephemeral *_test databases copied from the migrated reference template;
the real policy keeps F6 as the single enabled form and the tests enable the synthetic code per test with patch.object. Nothing touches vinto.
"""

import secrets
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app import capture_service as _capture_service
from app.assignments import service as _assignments
from app.assignments.errors import AssignmentNotFoundError
from app.auth.service import create_user
from app.capture_errors import (CaptureIdempotencyConflictError, CaptureNotFoundError, CaptureValidationError, FormNotAvailableError,
                                UnsupportedFormError)
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.seed.bundle import load_bundle
from app.work_orders import service as _work_orders
from app.work_orders.service import LineInput

try:
    from m2a_fixtures import SYNTHETIC_CODE, SYNTHETIC_QUALITY_CODE, SYNTHETIC_VALUES, install_production_form
    from scope_helpers import internal
except ModuleNotFoundError:
    from tests.m2a_fixtures import SYNTHETIC_CODE, SYNTHETIC_QUALITY_CODE, SYNTHETIC_VALUES, install_production_form
    from tests.scope_helpers import internal

capture_service = internal(_capture_service)
assignments = internal(_assignments)
work_orders = internal(_work_orders)

BUNDLE = load_bundle()
STATE = {}
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
MP3_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP3")
F6 = "VINTO-P1-06"
F6_VALUES = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "sin novedades"}
ENABLED = frozenset({F6, SYNTHETIC_CODE})
SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any test patches it


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m2a_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class MultiformCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_m2a")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.jefatura = self.user("JEFATURA")
        self.supervisor = self.user("SUPERVISION")
        self.operator = self.user("OPERACION")
        self.device_key = str(uuid4())
        install_production_form(self.connection)  # synthetic form, published for MP1 and MP3, in THIS ephemeral database only
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED)
        policy.start()
        self.addCleanup(policy.stop)

    def user(self, profile):
        return create_user(self.connection, username=f"m2a.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile,
                           password="pw-" + secrets.token_urlsafe(18)).user_id

    def assignment(self, machine="MP1"):
        codes = MP1_CODES if machine == "MP1" else MP3_CODES
        order = work_orders.create_work_order(self.connection, actor_id=self.jefatura, machine_code=machine,
                                              lines=[LineInput("PV-1", codes[0], 10, date(2026, 11, 1))])
        order = work_orders.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        result = assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id)
        return order, result.assignment

    def submit(self, assignment, form_code=SYNTHETIC_CODE, values=None, capture_id=None, **extra):
        values = dict(SYNTHETIC_VALUES if form_code == SYNTHETIC_CODE else F6_VALUES) if values is None else values
        return capture_service.submit_production_capture(
            self.connection, actor_id=extra.pop("actor", self.operator), capture_id=capture_id or uuid4(), form_code=form_code,
            assignment_id=assignment.id, device_key=extra.pop("device_key", self.device_key), values=values, **extra)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_master.device", "vinto_audit.audit_event")}


class PolicyTests(MultiformCase):
    def test_the_shipped_policy_enables_only_f6(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30", "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16", "VINTO-P1-29"}))  # CLOUD-DEP G.12-C4: +5 candidatos de Bobinas habilitados para QA  # no synthetic code and no P1-10 in the real policy
        self.assertEqual(_capture_service.FORM_CODE, F6)

    def test_a_published_form_is_not_accepted_unless_the_policy_enables_it(self):
        _, assignment = self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6})):  # synthetic form exists and is published, but is not enabled
            before = self.counts()
            with self.assertRaises(UnsupportedFormError):
                self.submit(assignment)
            self.assertEqual(self.counts(), before)
            for code in ("VINTO-P1-10", "vinto-test-prod-x1", " " + SYNTHETIC_CODE, "", None):
                with self.subTest(code=code), self.assertRaises(UnsupportedFormError):
                    self.submit(assignment, form_code=code, values={})
            self.assertEqual(self.counts(), before)

    def test_enabling_the_synthetic_code_does_not_change_the_f6_behaviour(self):
        _, assignment = self.assignment()
        view = self.submit(assignment, form_code=F6).capture
        self.assertEqual((view.form_code, view.status, view.revision, view.values["peso_kg"]), (F6, "submitted", 1, "125.50"))


class SecondFormTests(MultiformCase):
    def test_a_second_form_is_captured_with_the_context_of_the_assignment(self):
        order, assignment = self.assignment("MP1")
        result = self.submit(assignment)
        view = result.capture
        self.assertEqual((result.created, result.already_submitted), (True, False))
        self.assertEqual((view.form_code, view.status, view.revision), (SYNTHETIC_CODE, "submitted", 1))
        self.assertEqual((view.machine_code, view.shift_code, view.operating_date), (assignment.machine_code, assignment.shift_code, assignment.operating_date))
        self.assertEqual((view.assignment_id, view.work_order_id, view.line_id, view.pv_reference), (assignment.id, order.id, assignment.line.id, "PV-1"))
        self.assertEqual((view.article_code, view.article_description), (assignment.line.article_code, assignment.line.article_description))
        self.assertEqual(view.values, {"codigo_lote": "LOTE-001", "unidades": 12, "peso_kg": "34.250", "tipo": "alfa", "observaciones": "sintetico"})
        types = dict(self.connection.execute(
            "SELECT f.key, d.value_type FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s", (view.id,)).fetchall())
        self.assertEqual(types, {"codigo_lote": "text", "unidades": "integer", "peso_kg": "decimal", "tipo": "text", "observaciones": "textarea"})
        self.assertEqual(self.scalar("SELECT value_decimal FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id=d.field_definition_id WHERE d.capture_id=%s AND f.key='peso_kg'", (view.id,)).as_tuple().exponent, -3)

    def test_the_client_cannot_override_the_context_through_values(self):
        _, assignment = self.assignment()
        for key in ("machine_code", "operating_date", "work_order_id", "shift_code", "assignment_id", "article_code"):
            with self.subTest(key=key), self.assertRaises(CaptureValidationError) as raised:
                self.submit(assignment, values={**SYNTHETIC_VALUES, key: "x"})
            self.assertIn(f"{key}: campo desconocido", str(raised.exception))

    def test_it_is_persisted_and_audited_like_f6(self):
        _, assignment = self.assignment()
        audit_before = self.counts()["vinto_audit.audit_event"]
        view = self.submit(assignment).capture
        self.assertEqual(self.connection.execute("SELECT status, revision, created_by FROM vinto_txn.capture WHERE id = %s", (view.id,)).fetchone(), ("submitted", 1, self.operator))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (view.id,)), 5)
        self.assertGreater(self.counts()["vinto_audit.audit_event"], audit_before)

    def test_identical_retry_is_idempotent_and_a_changed_content_is_a_conflict(self):
        _, assignment = self.assignment()
        capture_id = uuid4()
        first = self.submit(assignment, capture_id=capture_id)
        after_first = self.counts()
        again = self.submit(assignment, capture_id=capture_id)
        self.assertEqual((again.created, again.already_submitted, again.capture.id), (False, True, first.capture.id))
        self.assertEqual(self.counts(), after_first)
        with self.assertRaises(CaptureIdempotencyConflictError):
            self.submit(assignment, capture_id=capture_id, values={**SYNTHETIC_VALUES, "unidades": 13})
        with self.assertRaises(CaptureIdempotencyConflictError):  # same id, different form
            self.submit(assignment, form_code=F6, capture_id=capture_id)
        with self.assertRaises(CaptureIdempotencyConflictError):  # same id, different actor
            self.submit(assignment, capture_id=capture_id, actor=self.supervisor)
        self.assertEqual(self.counts(), after_first)
        self.assertEqual(self.scalar("SELECT value_integer FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id=d.field_definition_id WHERE d.capture_id=%s AND f.key='unidades'", (capture_id,)), 12)

    def test_invalid_values_are_422_and_persist_nothing(self):
        _, assignment = self.assignment()
        before = self.counts()
        bad = [({k: v for k, v in SYNTHETIC_VALUES.items() if k != "codigo_lote"}, "codigo_lote: obligatorio"),
               ({**SYNTHETIC_VALUES, "unidades": "doce"}, "unidades: debe ser un entero"),
               ({**SYNTHETIC_VALUES, "unidades": True}, "unidades: debe ser un entero"),
               ({**SYNTHETIC_VALUES, "peso_kg": "1e3"}, "peso_kg: debe ser un número decimal"),
               ({**SYNTHETIC_VALUES, "peso_kg": float("nan")}, "peso_kg: debe ser un número finito"),
               ({**SYNTHETIC_VALUES, "tipo": "gamma"}, "tipo: valor no permitido"),
               ({**SYNTHETIC_VALUES, "campo_inventado": 1}, "campo_inventado: campo desconocido"),
               ({**SYNTHETIC_VALUES, "codigo_lote": 5}, "codigo_lote: debe ser texto")]
        for values, text in bad:
            with self.subTest(text=text), self.assertRaises(CaptureValidationError) as raised:
                self.submit(assignment, values=values)
            self.assertIn(text, str(raised.exception))
        with self.assertRaises(CaptureValidationError):
            self.submit(assignment, values=[1, 2])
        self.assertEqual(self.counts(), before)

    def test_the_optional_field_may_be_omitted(self):
        _, assignment = self.assignment()
        view = self.submit(assignment, values={k: v for k, v in SYNTHETIC_VALUES.items() if k != "observaciones"}).capture
        self.assertNotIn("observaciones", view.values)

    def test_the_form_must_be_published_and_linked_to_the_machine_of_the_assignment(self):
        _, mp3 = self.assignment("MP3")
        self.connection.execute("SET session_replication_role = replica")  # ephemeral *_test database only
        self.connection.execute("""DELETE FROM vinto_config.form_version_machine WHERE machine_id = (SELECT id FROM vinto_master.machine WHERE code = 'MP3')
                                   AND form_version_id = (SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s)""", (SYNTHETIC_CODE,))
        self.connection.execute("SET session_replication_role = DEFAULT")
        with self.assertRaises(FormNotAvailableError):
            self.submit(mp3)
        self.assertEqual(self.submit(mp3, form_code=F6).capture.form_code, F6)  # F6 is unaffected
        _, mp1 = self.assignment("MP1")
        self.assertEqual(self.submit(mp1).capture.machine_code, "MP1")
        self.connection.execute("UPDATE vinto_config.form SET active = false WHERE code = %s", (SYNTHETIC_CODE,))
        with self.assertRaises(FormNotAvailableError):
            self.submit(mp1)

    def test_an_unpublished_draft_version_is_not_available(self):
        install_production_form(self.connection, "VINTO-TEST-PROD-DRAFT", publish=False)
        _, assignment = self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED | {"VINTO-TEST-PROD-DRAFT"}), self.assertRaises(FormNotAvailableError):
            self.submit(assignment, form_code="VINTO-TEST-PROD-DRAFT", values={})

    def test_a_quality_area_form_cannot_be_captured_through_the_production_engine(self):
        install_production_form(self.connection, SYNTHETIC_QUALITY_CODE, area="quality")
        _, assignment = self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED | {SYNTHETIC_QUALITY_CODE}), self.assertRaises(FormNotAvailableError):
            self.submit(assignment, form_code=SYNTHETIC_QUALITY_CODE, values={})


class ReadTests(MultiformCase):
    def two_captures(self):
        _, assignment = self.assignment()
        f6 = self.submit(assignment, form_code=F6).capture
        second = self.submit(assignment).capture
        return assignment, f6, second

    def test_get_by_id_resolves_each_enabled_form_without_mixing_them(self):
        _, f6, second = self.two_captures()
        self.assertEqual(capture_service.get_capture(self.connection, f6.id).form_code, F6)
        self.assertEqual(capture_service.get_capture(self.connection, second.id).form_code, SYNTHETIC_CODE)
        self.assertEqual(capture_service.get_capture(self.connection, second.id).values["codigo_lote"], "LOTE-001")

    def test_the_default_list_keeps_the_historic_f6_behaviour(self):
        _, f6, second = self.two_captures()
        listed = capture_service.list_captures(self.connection)
        self.assertEqual([v.id for v in listed], [f6.id])
        self.assertEqual({v.form_code for v in listed}, {F6})

    def test_the_form_filter_lists_only_that_form_and_combines_with_the_other_filters(self):
        assignment, f6, second = self.two_captures()
        third = self.submit(assignment).capture
        listed = capture_service.list_captures(self.connection, form_code=SYNTHETIC_CODE)
        self.assertEqual([v.id for v in listed], [third.id, second.id])  # newest first
        self.assertEqual([v.id for v in capture_service.list_captures(self.connection, form_code=F6)], [f6.id])
        self.assertEqual(len(capture_service.list_captures(self.connection, form_code=SYNTHETIC_CODE, machine_code="MP1", assignment_id=assignment.id)), 2)
        self.assertEqual(capture_service.list_captures(self.connection, form_code=SYNTHETIC_CODE, machine_code="MP3"), [])
        self.assertEqual(capture_service.list_captures(self.connection, form_code=SYNTHETIC_CODE, operating_date=date(2000, 1, 1)), [])
        self.assertEqual(len(capture_service.list_captures(self.connection, form_code=SYNTHETIC_CODE, limit=1)), 1)

    def test_a_form_that_is_not_enabled_cannot_be_filtered_or_read(self):
        _, f6, second = self.two_captures()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6})):
            for code in (SYNTHETIC_CODE, "VINTO-P1-03", "VINTO-P1-10", "", "vinto-p1-06"):
                with self.subTest(code=code), self.assertRaises(UnsupportedFormError):
                    capture_service.list_captures(self.connection, form_code=code)
            with self.assertRaises(CaptureNotFoundError):  # the capture exists, but its form is not enabled: it is not exposed
                capture_service.get_capture(self.connection, second.id)
            self.assertEqual(capture_service.get_capture(self.connection, f6.id).id, f6.id)

    def test_a_quality_capture_is_never_exposed_by_the_production_reads(self):
        install_production_form(self.connection, SYNTHETIC_QUALITY_CODE, area="quality")
        _, f6, _ = self.two_captures()
        quality_version = self.scalar("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s", (SYNTHETIC_QUALITY_CODE,))
        quality_id = uuid4()
        for name, value in (('vinto.actor_id', str(self.operator)), ('vinto.request_id', 'm2a-quality-fixture'), ('vinto.reason', 'm2a fixture')):
            self.connection.execute('SELECT set_config(%s, %s, false)', (name, value))  # audit context required by the capture triggers
        self.connection.execute(
            """INSERT INTO vinto_txn.capture (id, form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status)
               SELECT %s, %s, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, 'draft' FROM vinto_txn.capture WHERE id = %s""", (quality_id, quality_version, f6.id))
        self.connection.execute("UPDATE vinto_txn.capture SET status = 'submitted', submitted_at = clock_timestamp() WHERE id = %s", (quality_id,))
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED | {SYNTHETIC_QUALITY_CODE}):  # even if someone enabled the code by mistake
            with self.assertRaises(CaptureNotFoundError):
                capture_service.get_capture(self.connection, quality_id)
            self.assertEqual(capture_service.list_captures(self.connection, form_code=SYNTHETIC_QUALITY_CODE), [])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (quality_id,)), 1)  # it exists; it is only not reachable from here

    def test_unknown_or_malformed_ids_are_404(self):
        for value in (uuid4(), "no-es-un-uuid", "", "count"):
            with self.subTest(value=value), self.assertRaises(CaptureNotFoundError):
                capture_service.get_capture(self.connection, value)


class SectorScopeTests(MultiformCase):
    def test_reads_and_writes_require_an_operational_granted_sector(self):
        _, assignment = self.assignment()
        view = self.submit(assignment).capture
        for scope in ((), ("REBOBINADO",), ("CONVERSION",), ("REBOBINADO", "CONVERSION")):  # no grant, or granted but NOT operational
            with self.subTest(scope=scope):
                with self.assertRaises(CaptureNotFoundError):
                    _capture_service.get_capture(self.connection, view.id, sectors=scope)
                self.assertEqual(_capture_service.list_captures(self.connection, form_code=SYNTHETIC_CODE, sectors=scope), [])
                with self.assertRaises(AssignmentNotFoundError):
                    _capture_service.submit_production_capture(self.connection, actor_id=self.operator, capture_id=uuid4(), form_code=SYNTHETIC_CODE,
                                                               assignment_id=assignment.id, device_key=self.device_key, values=dict(SYNTHETIC_VALUES), sectors=scope)
        self.assertEqual(_capture_service.get_capture(self.connection, view.id, sectors=("BOBINAS",)).id, view.id)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 1)


if __name__ == "__main__":
    unittest.main()
