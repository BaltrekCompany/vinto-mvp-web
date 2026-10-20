"""M3-A: repeatable groups in the central production engine (capture_service), against the EXISTING schema (field_group / capture_group_row / capture_detail).

A SYNTHETIC grouped form (tests/m3a_fixtures.py) is installed only in ephemeral *_test databases and enabled per test with patch.object; the real policy keeps F6 as the
only enabled form. Contract: `values` keeps the simple fields at the top level and carries the groups under the reserved property `_groups` {group_code: [row, ...]};
rows keep their order (row_number = position + 1). F6 and P1-10 (forms without groups) never see `_groups`. Nothing touches vinto.
"""

import asyncio
import copy
import secrets
import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app.assignments import service as _assignments
from app.auth.service import create_user
from app.capture_errors import CaptureIdempotencyConflictError, CaptureNotFoundError, CaptureValidationError, UnsupportedFormDefinitionError, UnsupportedFormError
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle
from app.work_orders import service as _work_orders
from app.work_orders.service import LineInput

try:
    from m3a_fixtures import GROUPED_CODE, GROUPS, SIMPLE_FIELDS, VALID, install_grouped_form
    from scope_helpers import internal
    from test_assignments_api import PROFILES, call, order_body
except ModuleNotFoundError:
    from tests.m3a_fixtures import GROUPED_CODE, GROUPS, SIMPLE_FIELDS, VALID, install_grouped_form
    from tests.scope_helpers import internal
    from tests.test_assignments_api import PROFILES, call, order_body

capture_service = internal(_capture_service)
assignments = internal(_assignments)
work_orders = internal(_work_orders)

BUNDLE = load_bundle()
STATE = {}
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
F6 = "VINTO-P1-06"
F6_VALUES = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}
ENABLED = frozenset({F6, GROUPED_CODE})
SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m3a_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def values(**changes):
    out = copy.deepcopy(VALID)
    out.update(changes)
    return out


def with_groups(**groups):
    out = copy.deepcopy(VALID)
    out["_groups"] = {**out["_groups"], **groups}
    return out


class GroupCase(unittest.TestCase):
    def setUp(self):
        self.database = copy_database(STATE["template"], "vinto_m3a")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.version = install_grouped_form(self.connection)
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED)
        policy.start()
        self.addCleanup(policy.stop)
        self.jefatura, self.supervisor, self.operator = (self.user(p) for p in ("JEFATURA", "SUPERVISION", "OPERACION"))
        self.device_key = str(uuid4())
        order = work_orders.create_work_order(self.connection, actor_id=self.jefatura, machine_code="MP1", lines=[LineInput("PV-1", MP1_CODES[0], 10, date(2026, 11, 1))])
        order = work_orders.publish_work_order(self.connection, actor_id=self.jefatura, work_order_id=order.id)
        self.assignment = assignments.activate(self.connection, actor_id=self.supervisor, work_order_id=order.id, baseline_line_id=order.baseline.lines[0].id).assignment

    def user(self, profile):
        return create_user(self.connection, username=f"m3a.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile, password="pw-" + secrets.token_urlsafe(18)).user_id

    def submit(self, payload=None, capture_id=None, form_code=GROUPED_CODE, **extra):
        return capture_service.submit_production_capture(
            self.connection, actor_id=extra.pop("actor", self.operator), capture_id=capture_id or uuid4(), form_code=form_code, assignment_id=self.assignment.id,
            device_key=self.device_key, values=copy.deepcopy(VALID if payload is None else payload), **extra)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_group_row", "vinto_txn.capture_detail", "vinto_master.device", "vinto_audit.audit_event")}

    def bad(self, payload, text=None, forbidden=()):
        before = self.counts()
        with self.assertRaises(CaptureValidationError) as raised:
            self.submit(payload)
        message = str(raised.exception)
        if text:
            self.assertIn(text, message)
        for secret in forbidden:
            self.assertNotIn(secret, message)  # a validation error names fields and rows, never the submitted value
        self.assertEqual(self.counts(), before, "a rejected capture persists nothing")
        return message


class PersistenceAndReadTests(GroupCase):
    def test_a_grouped_capture_is_created_with_simple_fields_groups_and_ordered_rows(self):
        result = self.submit()
        view = result.capture
        self.assertEqual((result.created, result.already_submitted, view.status, view.revision, view.form_code), (True, False, "submitted", 1, GROUPED_CODE))
        self.assertEqual(view.values, {
            "lote": "L-001", "nota": "sintético",
            "_groups": {"detalle": [{"item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a"}, {"item": "B", "cantidad": 5}], "extras": [{"etiqueta": "x", "valor": "0.10"}], "unico": []},
        })
        self.assertEqual(self.connection.execute(
            """SELECT g.code, r.row_number FROM vinto_txn.capture_group_row r JOIN vinto_config.field_group g ON g.id = r.field_group_id WHERE r.capture_id = %s ORDER BY g.display_order, r.row_number""",
            (view.id,)).fetchall(), [("detalle", 1), ("detalle", 2), ("extras", 1)])
        # every grouped detail is linked to its row AND group; simple details are not
        linked = self.connection.execute(
            """SELECT f.key, d.field_group_id IS NOT NULL, d.group_row_id IS NOT NULL, d.value_type FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s ORDER BY f.display_order""", (view.id,)).fetchall()
        self.assertEqual({k: (g, r) for k, g, r, _ in linked}, {"lote": (False, False), "nota": (False, False), "item": (True, True), "cantidad": (True, True), "peso": (True, True), "tipo": (True, True), "etiqueta": (True, True), "valor": (True, True)})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (view.id,)), 2 + 4 + 2 + 2)
        self.assertEqual(self.scalar("SELECT value_decimal::text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id=d.field_definition_id WHERE d.capture_id=%s AND f.key='peso'", (view.id,)), "1.50")

    def test_context_derives_from_the_assignment_and_audit_records_the_rows(self):
        before = self.counts()
        view = self.submit().capture
        self.assertEqual((view.machine_code, view.assignment_id, view.work_order_number), (self.assignment.machine_code, self.assignment.id, self.assignment.work_order_number if hasattr(self.assignment, "work_order_number") else view.work_order_number))
        self.assertGreater(self.counts()["vinto_audit.audit_event"], before["vinto_audit.audit_event"])
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture_group_row WHERE capture_id = %s LIMIT 1", (view.id,)), self.operator)

    def test_zero_rows_are_accepted_where_the_minimum_is_zero_and_all_groups_are_reported(self):
        view = self.submit(with_groups(extras=[])).capture
        self.assertEqual(view.values["_groups"]["extras"], [])
        view = self.submit({"lote": "L-2", "_groups": {"detalle": [{"item": "A", "cantidad": 1}]}}).capture  # extras and unico omitted
        self.assertEqual(view.values["_groups"], {"detalle": [{"item": "A", "cantidad": 1}], "extras": [], "unico": []})
        self.assertNotIn("nota", view.values)

    def test_one_row_many_rows_and_the_declared_maximum(self):
        self.assertEqual(len(self.submit(with_groups(detalle=[{"item": "A", "cantidad": 1}])).capture.values["_groups"]["detalle"]), 1)
        three = [{"item": f"I{i}", "cantidad": i} for i in range(1, 4)]
        self.assertEqual(len(self.submit(with_groups(detalle=three)).capture.values["_groups"]["detalle"]), 3)  # max_rows = 3 declared
        many = [{"etiqueta": f"e{i}"} for i in range(50)]
        self.assertEqual(len(self.submit(with_groups(extras=many)).capture.values["_groups"]["extras"]), 50)  # no declared maximum

    def test_duplicate_content_in_different_rows_is_allowed_and_keeps_both_rows(self):
        row = {"item": "A", "cantidad": 2, "peso": "1.50"}
        view = self.submit(with_groups(detalle=[row, dict(row), dict(row)])).capture
        self.assertEqual(view.values["_groups"]["detalle"], [{"item": "A", "cantidad": 2, "peso": "1.50"}] * 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (view.id,)), 3 + 1)

    def test_row_order_is_deterministic_and_preserved_on_reads(self):
        a, b = {"item": "A", "cantidad": 1}, {"item": "B", "cantidad": 2}
        first = self.submit(with_groups(detalle=[a, b])).capture
        second = self.submit(with_groups(detalle=[b, a])).capture
        self.assertEqual([r["item"] for r in first.values["_groups"]["detalle"]], ["A", "B"])
        self.assertEqual([r["item"] for r in second.values["_groups"]["detalle"]], ["B", "A"])
        for view in (first, second):
            read = capture_service.get_capture(self.connection, view.id)
            self.assertEqual(read.values, view.values)
            self.assertEqual(self.scalar("SELECT string_agg(r.row_number::text, ',' ORDER BY r.row_number) FROM vinto_txn.capture_group_row r JOIN vinto_config.field_group g ON g.id = r.field_group_id WHERE r.capture_id = %s AND g.code = 'detalle'", (view.id,)), "1,2")

    def test_get_by_id_and_filtered_list_rebuild_simple_fields_groups_and_rows(self):
        view = self.submit().capture
        self.assertEqual(capture_service.get_capture(self.connection, view.id).values, view.values)
        listed = capture_service.list_captures(self.connection, form_code=GROUPED_CODE)
        self.assertEqual([v.values for v in listed], [view.values])
        self.assertEqual(capture_service.list_captures(self.connection), [])  # the historic default is F6 only
        self.assertEqual(capture_service.list_captures(self.connection, form_code=GROUPED_CODE, machine_code="MP3"), [])

    def test_reads_respect_the_sector_scope(self):
        view = self.submit().capture
        for scope in ((), ("REBOBINADO",)):
            with self.assertRaises(CaptureNotFoundError):
                _capture_service.get_capture(self.connection, view.id, sectors=scope)
            self.assertEqual(_capture_service.list_captures(self.connection, form_code=GROUPED_CODE, sectors=scope), [])

    def test_the_code_must_still_be_enabled(self):
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            with self.assertRaises(UnsupportedFormError):
                self.submit()
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30", "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16", "VINTO-P1-29"}))  # CLOUD-DEP G.12-C4: +5 candidatos de Bobinas habilitados para QA


class ValidationTests(GroupCase):
    def test_minimum_rows_are_enforced(self):
        self.bad({"lote": "L", "_groups": {}}, "_groups.detalle: se requieren al menos 1 filas")
        self.bad({"lote": "L"}, "_groups.detalle: se requieren al menos 1 filas")
        self.bad(with_groups(detalle=[]), "_groups.detalle: se requieren al menos 1 filas")

    def test_maximum_rows_and_non_repeatable_groups(self):
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": i} for i in range(4)]), "_groups.detalle: máximo 3 filas")
        self.bad(with_groups(unico=[{"ref": "a"}, {"ref": "b"}]), "_groups.unico: máximo 1 filas")
        install_grouped_form(self.connection, "VINTO-TEST-GRP-ONCE", simple_fields=(), groups=(("g", "G", False, 0, None, (("campo", "Campo", "text", True, ()),)),))  # not repeatable and no declared maximum
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED | {"VINTO-TEST-GRP-ONCE"}), self.assertRaises(CaptureValidationError) as raised:
            self.submit({"_groups": {"g": [{"campo": "a"}, {"campo": "b"}]}}, form_code="VINTO-TEST-GRP-ONCE")
        self.assertIn("_groups.g: el grupo no es repetible", str(raised.exception))
        self.assertEqual(self.submit(with_groups(unico=[{"ref": "a"}])).capture.values["_groups"]["unico"], [{"ref": "a"}])
        self.bad(with_groups(extras=[{"etiqueta": "e"}] * (_capture_service.TECHNICAL_MAX_GROUP_ROWS + 1)), f"máximo {_capture_service.TECHNICAL_MAX_GROUP_ROWS} filas")  # technical cap only when no max is declared

    def test_required_fields_per_row_name_the_row(self):
        message = self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1}, {"cantidad": 2}, {"item": "C"}]), "_groups.detalle[2].item: obligatorio")
        self.assertIn("_groups.detalle[3].cantidad: obligatorio", message)
        self.assertNotIn("_groups.detalle[1]", message)
        self.bad(with_groups(extras=[{"valor": "1"}]), "_groups.extras[1].etiqueta: obligatorio")

    def test_required_simple_fields_still_apply_and_are_reported_with_the_group_errors(self):
        message = self.bad({"_groups": {"detalle": [{"cantidad": 1}]}})
        self.assertIn("lote: obligatorio", message)
        self.assertIn("_groups.detalle[1].item: obligatorio", message)

    def test_undeclared_groups_unknown_keys_and_misplaced_fields_are_rejected(self):
        self.bad(with_groups(inventado=[{"x": 1}]), "_groups.inventado: grupo no declarado")
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1, "inventado": 1}]), "_groups.detalle[1].inventado: campo desconocido")
        self.bad({**VALID, "item": "A"}, "item: campo del grupo detalle; se envía dentro de _groups")  # a grouped field at the top level
        self.bad({**VALID, "campo_inventado": 1}, "campo_inventado: campo desconocido")
        self.bad({**VALID, "_groups": [1, 2]}, "_groups: debe ser un objeto")
        self.bad({**VALID, "_groups": None}, "_groups: debe ser un objeto")
        self.bad(with_groups(detalle={"item": "A"}), "_groups.detalle: debe ser una lista de filas")
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1}, "no-es-fila", 5]), "_groups.detalle[2]: la fila debe ser un objeto")

    def test_internal_references_and_derived_metadata_supplied_by_the_client_are_rejected(self):
        for key in ("id", "row_number", "field_group_id", "group_row_id", "capture_id", "form_version_id", "field_definition_id", "created_by", "revision", "_groups"):
            with self.subTest(key=key):
                self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1, key: "x"}]), f"_groups.detalle[1].{key}: campo desconocido")
        for key in ("field_group_id", "group_row_id", "row_number", "revision", "status"):
            with self.subTest(top=key):
                self.bad({**VALID, key: "x"}, f"{key}: campo desconocido")

    def test_values_are_typed_by_the_definition_and_errors_never_echo_them(self):
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": "doce"}]), "_groups.detalle[1].cantidad: debe ser un entero", forbidden=("doce",))
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": True}]), "cantidad: debe ser un entero")
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1, "peso": "1e3"}]), "peso: debe ser un número decimal", forbidden=("1e3",))
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1, "peso": float("nan")}]), "peso: debe ser un número finito")
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1, "tipo": "z"}]), "tipo: valor no permitido", forbidden=("'z'",))
        self.bad(with_groups(detalle=[{"item": 5, "cantidad": 1}]), "item: debe ser texto")
        self.bad(with_groups(extras=[{"etiqueta": "e", "valor": "x" * 60}]), "valor: debe ser un número decimal")
        view = self.submit(with_groups(detalle=[{"item": "A", "cantidad": "7", "peso": "123456789.123456789"}])).capture  # integers as text and exact decimals are accepted
        self.assertEqual(view.values["_groups"]["detalle"][0], {"item": "A", "cantidad": 7, "peso": "123456789.123456789"})

    def test_empty_and_blank_rows_are_rejected(self):
        self.bad(with_groups(detalle=[{"item": "A", "cantidad": 1}, {}]), "_groups.detalle[2].item: obligatorio")
        self.bad(with_groups(extras=[{}]), "_groups.extras[1].etiqueta: obligatorio")
        self.bad(with_groups(unico=[{"ref": "   "}]), "_groups.unico[1].ref: obligatorio")
        self.bad(with_groups(detalle=[{"item": "  ", "cantidad": None}]), "_groups.detalle[1].item: obligatorio")

    def test_a_row_without_values_is_rejected_when_every_field_is_optional(self):
        install_grouped_form(self.connection, "VINTO-TEST-GRP-OPT", groups=(("g", "G", True, 0, None, (("opcional", "Opcional", "text", False, ()),)),), simple_fields=())
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED | {"VINTO-TEST-GRP-OPT"}):
            before = self.counts()
            with self.assertRaises(CaptureValidationError) as raised:
                self.submit({"_groups": {"g": [{}]}}, form_code="VINTO-TEST-GRP-OPT")
            self.assertIn("_groups.g[1]: la fila no tiene valores", str(raised.exception))
            self.assertEqual(self.counts(), before)
            self.assertEqual(self.submit({"_groups": {"g": [{"opcional": "x"}]}}, form_code="VINTO-TEST-GRP-OPT").capture.values["_groups"]["g"], [{"opcional": "x"}])

    def test_forms_without_groups_never_accept_the_reserved_property(self):
        before = self.counts()
        for payload in ({**F6_VALUES, "_groups": {}}, {**F6_VALUES, "_groups": {"x": [{"a": 1}]}}):
            with self.assertRaises(CaptureValidationError) as raised:
                self.submit(payload, form_code=F6)
            self.assertIn("_groups: campo desconocido", str(raised.exception))
        self.assertEqual(self.counts(), before)
        view = self.submit(F6_VALUES, form_code=F6).capture
        self.assertNotIn("_groups", view.values)  # F6 keeps its exact response shape

    def test_unsupported_definitions_are_reported_not_accepted(self):
        install_grouped_form(self.connection, "VINTO-TEST-GRP-COLLIDE", simple_fields=(("_groups", "Colisión", "text", False, ()),), groups=())
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED | {"VINTO-TEST-GRP-COLLIDE"}):
            with self.assertRaises(UnsupportedFormDefinitionError):
                self.submit({}, form_code="VINTO-TEST-GRP-COLLIDE")
        self.connection.execute("SET session_replication_role = replica")  # ephemeral *_test database only
        try:
            self.connection.execute("UPDATE vinto_config.field_definition SET source = 'calculated' WHERE key = 'peso' AND form_version_id = %s", (self.version,))
        finally:
            self.connection.execute("SET session_replication_role = DEFAULT")
        with self.assertRaises(UnsupportedFormDefinitionError):
            self.submit()
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    def test_other_engines_keep_rejecting_grouped_definitions(self):
        with self.assertRaises(UnsupportedFormDefinitionError):
            _capture_service.load_fields(self.connection, self.version)  # P1-03 and Quality call it without allow_groups
        self.assertTrue(_capture_service.load_fields(self.connection, self.version, allow_groups=True))


class IdempotencyAndAtomicityTests(GroupCase):
    def test_identical_retry_is_200_without_new_rows(self):
        capture_id = uuid4()
        first = self.submit(capture_id=capture_id)
        after = self.counts()
        again = self.submit(capture_id=capture_id)
        self.assertEqual((again.created, again.already_submitted, again.capture.id), (False, True, first.capture.id))
        self.assertEqual(again.capture.values, first.capture.values)
        self.assertEqual(self.counts(), after)
        # explicit empty optional groups are the same content as omitted ones
        self.assertEqual(self.submit(with_groups(extras=[{"etiqueta": "x", "valor": "0.10"}], unico=[]), capture_id=capture_id).already_submitted, True)
        self.assertEqual(self.counts(), after)

    def test_any_change_in_a_row_the_rows_or_their_order_is_a_conflict(self):
        capture_id = uuid4()
        self.submit(capture_id=capture_id)
        after = self.counts()
        variants = {
            "cell": with_groups(detalle=[{"item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a"}, {"item": "B", "cantidad": 6}]),
            "decimal": with_groups(detalle=[{"item": "A", "cantidad": 2, "peso": "1.51", "tipo": "a"}, {"item": "B", "cantidad": 5}]),
            "extra row": with_groups(detalle=[{"item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a"}, {"item": "B", "cantidad": 5}, {"item": "C", "cantidad": 1}]),
            "removed row": with_groups(detalle=[{"item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a"}]),
            "reordered": with_groups(detalle=[{"item": "B", "cantidad": 5}, {"item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a"}]),
            "other group": with_groups(extras=[{"etiqueta": "y", "valor": "0.10"}]),
            "added group row": with_groups(unico=[{"ref": "r"}]),
            "simple field": values(lote="L-002"),
        }
        for name, payload in variants.items():
            with self.subTest(name=name), self.assertRaises(CaptureIdempotencyConflictError):
                self.submit(payload, capture_id=capture_id)
        with self.assertRaises(CaptureIdempotencyConflictError):  # same id, another form
            self.submit(F6_VALUES, capture_id=capture_id, form_code=F6)
        self.assertEqual(self.counts(), after)
        self.assertEqual(capture_service.get_capture(self.connection, capture_id).values["_groups"]["detalle"][1], {"item": "B", "cantidad": 5})

    def test_a_failure_while_writing_rows_rolls_everything_back(self):
        real = _capture_service._insert_groups
        calls = []

        def fail_after_the_first_row(connection, capture_id, form_version_id, fields, groups, clean_groups):
            calls.append(1)
            first = {code: rows[:1] for code, rows in list(clean_groups.items())[:1]}
            real(connection, capture_id, form_version_id, fields, groups, first)  # one row IS written inside the transaction...
            raise RuntimeError("simulated failure while writing the rows")  # ...and then it fails

        before = self.counts()
        with patch.object(_capture_service, "_insert_groups", fail_after_the_first_row), self.assertRaises(RuntimeError):
            self.submit()
        self.assertEqual(calls, [1])
        self.assertEqual(self.counts(), before)  # capture, rows, details, device and audit: all rolled back
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row"), 0)
        self.assertEqual(self.submit().capture.revision, 1)  # and the same submission works afterwards

    def test_the_database_cardinality_rules_are_the_last_line_of_defence(self):
        # bypassing the engine, the existing trigger still refuses a submitted capture below the declared minimum
        capture_id = uuid4()
        for name, value in (("vinto.actor_id", str(self.operator)), ("vinto.request_id", "m3a-db-guard"), ("vinto.reason", "m3a fixture")):
            self.connection.execute("SELECT set_config(%s, %s, false)", (name, value))
        device = self.scalar("INSERT INTO vinto_master.device (external_key, machine_id, active) VALUES (%s, NULL, true) RETURNING id", (str(uuid4()),))
        schedule = self.scalar("SELECT shift_schedule_id FROM vinto_txn.assignment WHERE id = %s", (self.assignment.id,))
        self.connection.execute(
            """INSERT INTO vinto_txn.capture (id, form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status)
               SELECT %s, %s, a.machine_id, a.shift_schedule_id, %s, a.id, a.operating_date, clock_timestamp(), 'draft' FROM vinto_txn.assignment a WHERE a.id = %s""", (capture_id, self.version, device, self.assignment.id))
        self.assertIsNotNone(schedule)
        import psycopg
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute("UPDATE vinto_txn.capture SET status = 'submitted', submitted_at = clock_timestamp() WHERE id = %s", (capture_id,))


class GroupApiCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m3aapi")
        cls.connection = connect(cls.database)
        install_grouped_form(cls.connection)
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.users, cls.cookies = {}, {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (create_user(cls.connection, username=f"m3aapi.{profile.lower()}", display_name=profile.title(), profile_code=profile, password=password, sectors=("BOBINAS",)), password)
        password = "pw-" + secrets.token_urlsafe(18)
        cls.users["SIN_SECTOR"] = (create_user(cls.connection, username="m3aapi.sinsector", display_name="Sin sector", profile_code="OPERACION", password=password, sectors=()), password)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED)
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, who):
        if who not in self.cookies:
            created, password = self.users[who]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, who)
            self.cookies[who] = reply.set_cookie_value()
        return self.cookies[who]

    async def assignment(self):
        order = (await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=await self.cookie("JEFATURA"))).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201)
        return reply.json()["assignment"]

    def body(self, assignment, payload=None, **changes):
        out = {"capture_id": str(uuid4()), "form_code": GROUPED_CODE, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": copy.deepcopy(VALID if payload is None else payload)}
        out.update(changes)
        return out

    async def post(self, body, who="OPERACION"):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who))

    async def get(self, path, who="OPERACION"):
        return await call("GET", path, cookie=await self.cookie(who))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]


class ApiTests(GroupApiCase):
    async def test_201_200_and_409_with_groups_and_the_same_envelope(self):
        assignment = await self.assignment()
        body = self.body(assignment)
        created = await self.post(body)
        self.assertEqual(created.status, 201, created.text)
        data = created.json()
        self.assertEqual(set(data), {"created", "already_submitted", "capture"})
        self.assertEqual(set(data["capture"]), {"id", "status", "revision", "captured_at", "submitted_at", "form", "machine", "shift", "operating_date", "assignment", "work_order", "line", "values"})
        self.assertEqual((data["capture"]["revision"], data["capture"]["status"]), (1, "submitted"))
        self.assertEqual(data["capture"]["values"]["_groups"]["detalle"], [{"item": "A", "cantidad": 2, "peso": "1.50", "tipo": "a"}, {"item": "B", "cantidad": 5}])
        again = await self.post(body)
        self.assertEqual((again.status, again.json()["already_submitted"]), (200, True))
        rows = self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],))
        self.assertEqual(rows, 3)
        changed = copy.deepcopy(body)
        changed["values"]["_groups"]["detalle"][1]["cantidad"] = 6
        conflict = await self.post(changed)
        self.assertEqual((conflict.status, conflict.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), rows)

    async def test_422_is_safe_and_names_rows_without_echoing_values_or_sql(self):
        assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        bad = copy.deepcopy(VALID)
        bad["_groups"]["detalle"][1] = {"item": "B", "cantidad": "valor-secreto", "id": "x"}
        reply = await self.post(self.body(assignment, bad))
        self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertIn("_groups.detalle[2].cantidad", reply.text)
        self.assertNotIn("valor-secreto", reply.text)
        self.assertNotIn("SELECT", reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_permissions_and_sector_scope(self):
        assignment = await self.assignment()
        body = self.body(assignment)
        self.assertEqual((await call("POST", "/api/captures", json_body=body)).status, 401)
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            self.assertEqual((await self.post(body, who)).status, 403, who)
        self.assertEqual((await self.post(body, "SIN_SECTOR")).status, 404)
        created = (await self.post(body)).json()["capture"]
        self.assertEqual((await self.get(f"/api/captures/{created['id']}", "SIN_SECTOR")).status, 404)
        self.assertEqual((await self.get(f"/api/captures?form_code={GROUPED_CODE}", "SIN_SECTOR")).json(), [])
        self.assertEqual((await call("GET", f"/api/captures/{created['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/captures/{created['id']}", "JEFATURA")).status, 403)

    async def test_reads_rebuild_the_groups_and_f6_keeps_its_shape(self):
        assignment = await self.assignment()
        created = (await self.post(self.body(assignment))).json()["capture"]
        read = await self.get(f"/api/captures/{created['id']}")
        self.assertEqual((read.status, read.json()["values"]), (200, created["values"]))
        listed = (await self.get(f"/api/captures?form_code={GROUPED_CODE}")).json()
        self.assertEqual([c["values"] for c in listed if c["id"] == created["id"]], [created["values"]])
        f6 = (await self.post(self.body(assignment, F6_VALUES, form_code=F6))).json()["capture"]
        self.assertEqual(f6["values"], {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"})
        self.assertNotIn("_groups", f6["values"])
        default = (await self.get("/api/captures")).json()
        self.assertEqual({c["form"]["code"] for c in default}, {F6})

    async def test_concurrency_identical_posts_create_one_capture_with_its_rows_and_distinct_ids_create_distinct_captures(self):
        assignment = await self.assignment()
        body = self.body(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), 2 + 4 + 2 + 2)
        distinct = [self.body(assignment) for _ in range(4)]
        replies = await asyncio.gather(*[self.post(b) for b in distinct])
        self.assertEqual([r.status for r in replies], [201] * 4)
        for b in distinct:
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (b["capture_id"],)), 3)

    async def test_conflicting_parallel_submissions_with_the_same_id_leave_exactly_one_version(self):
        assignment = await self.assignment()
        capture_id = str(uuid4())
        a = self.body(assignment, capture_id=capture_id)
        b = copy.deepcopy(a)
        b["values"]["_groups"]["detalle"].append({"item": "Z", "cantidad": 9})
        replies = await asyncio.gather(self.post(a), self.post(b), self.post(a), self.post(b))
        statuses = sorted(r.status for r in replies)
        self.assertEqual(statuses.count(201), 1)
        self.assertTrue(all(s in (200, 201, 409) for s in statuses), statuses)
        rows = self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row r JOIN vinto_config.field_group g ON g.id = r.field_group_id WHERE r.capture_id = %s AND g.code = 'detalle'", (capture_id,))
        self.assertIn(rows, (2, 3))  # exactly one coherent version was stored: never a mix
        stored = (await self.get(f"/api/captures/{capture_id}")).json()["values"]["_groups"]["detalle"]
        self.assertEqual(len(stored), rows)


if __name__ == "__main__":
    unittest.main()
