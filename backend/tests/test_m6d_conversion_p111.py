"""M6-D: a CANDIDATE VINTO-P1-11 (one repeatable group `bobinas` of DECLARED coils + optional observaciones) runs through the central production engine (M3-A repeatable groups) under an ISOLATED test configuration.

Everything is installed in an ephemeral *_test database: the fictitious Conversión context of M6-A (tests/m6a_fixtures.py), P1-16 / P1-12 on GAMBINI, P1-13 on WALLY, and the candidate P1-11 definition linked to GAMBINI
only (tests/m6d_fixtures.py). Sector and forms are enabled per test with patch.object; the shipped configuration is asserted unchanged. This is NOT a homologation of P1-11: the coil numbers and the balances are
DECLARATIONS; nothing here computes consumption, balance, merma, inventory or genealogy, and nothing relates the capture to a real bobbin. `min_rows = 1` and the two positions are decisions of this candidate contract
only; the 1000-row cap is the engine's TECHNICAL limit, not an industrial maximum.
"""

import asyncio
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app import sectors as _sectors
from app.assignments import service as _assignments_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle

try:
    from m6a_fixtures import CONV_MACHINE, CONV_MACHINE_NO_FORM, ENABLED_CONVERSION_SECTORS, P116_CODE, P116_VALUES, install_conversion_fixture, install_p116
    from m6b_fixtures import P112_CODE, P112_DRAFT_CODE, P112_VALUES, install_p112, install_p112_draft
    from m6c_fixtures import P113_CODE, P113_VALUES, install_p113
    from m6d_fixtures import P111_CODE, P111_DRAFT_CODE, P111_MACHINE, P111_ROWS, P111_VALUES, install_p111, install_p111_draft
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.m6a_fixtures import CONV_MACHINE, CONV_MACHINE_NO_FORM, ENABLED_CONVERSION_SECTORS, P116_CODE, P116_VALUES, install_conversion_fixture, install_p116
    from tests.m6b_fixtures import P112_CODE, P112_DRAFT_CODE, P112_VALUES, install_p112, install_p112_draft
    from tests.m6c_fixtures import P113_CODE, P113_VALUES, install_p113
    from tests.m6d_fixtures import P111_CODE, P111_DRAFT_CODE, P111_MACHINE, P111_ROWS, P111_VALUES, install_p111, install_p111_draft
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any patch
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
BUNDLE = load_bundle()
ARTICLE = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")[0]
STATE = {}
INVENTORY_TABLES = ("vinto_txn.bobbin", "vinto_txn.bobbin_relation", "vinto_txn.quality_release", "vinto_txn.bobbin_sequence")

# La Paz is UTC-4 all year (same hypotheses as M6-A).
MORNING = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)       # 12:00 La Paz -> MANANA, 2026-10-06
AFTERNOON = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)     # 15:00 La Paz -> TARDE
NIGHT_EVENING = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)  # 23:00 La Paz -> NOCHE, 2026-10-06
NIGHT_AFTER_MIDNIGHT = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 02:00 La Paz (10-07) -> NOCHE, operating date 2026-10-06
NEXT_MORNING = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)  # 06:00 La Paz (10-07) -> MANANA, 2026-10-07


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m6d_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine, article=ARTICLE):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": article, "quantity": 10, "due_date": "2026-11-01"}]}


def values_with(rows=None, **simple):
    """P1-11 values: the default demonstration rows, or the given ones (an empty list is a group WITHOUT rows)."""
    return {**{k: v for k, v in P111_VALUES.items() if k != "_groups"}, **simple, "_groups": {"bobinas": [dict(r) for r in (P111_ROWS if rows is None else rows)]}}


class P111Case(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m6d")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        install_conversion_fixture(cls.connection, [ARTICLE])
        install_p116(cls.connection)
        install_p112(cls.connection)
        install_p112_draft(cls.connection)
        install_p113(cls.connection)
        install_p111(cls.connection)
        install_p111_draft(cls.connection)
        cls.scope = patch.object(_sectors, "_OPERATIONAL", ENABLED_CONVERSION_SECTORS)  # TEST-ONLY: Conversión operational in this process
        cls.scope.start()
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", ENABLED_CONVERSION_SECTORS), ("SUPERVISION", "SUPERVISION", ENABLED_CONVERSION_SECTORS),
                                       ("OPERACION", "OPERACION", ENABLED_CONVERSION_SECTORS), ("CALIDAD", "CALIDAD", ENABLED_CONVERSION_SECTORS),
                                       ("OPERACION_SOLO_BOBINAS", "OPERACION", ("BOBINAS",)), ("OPERACION_SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"m6d.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.scope.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P116_CODE, P112_CODE, P112_DRAFT_CODE, P113_CODE, P111_CODE, P111_DRAFT_CODE}))  # TEST-ONLY policy (the draft codes are enabled but never published)
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine=P111_MACHINE, at=None):
        order = (await call("POST", "/api/work-orders", json_body=order_body(machine), cookie=await self.cookie("JEFATURA")))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        body = {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]}
        if at is None:
            reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body=body)
        else:
            with patch.object(_assignments_service, "_now", return_value=at):
                reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body=body)
        self.assertEqual(reply.status, 201, reply.text)
        return order, reply.json()["assignment"]

    def payload(self, assignment, form_code=P111_CODE, **changes):
        values = {P111_CODE: values_with, P112_CODE: lambda: dict(P112_VALUES), P113_CODE: lambda: dict(P113_VALUES), P116_CODE: lambda: dict(P116_VALUES)}.get(form_code, lambda: {})()
        body = {"capture_id": str(uuid4()), "form_code": form_code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": values}
        body.update(changes)
        return body

    async def post(self, body, who="OPERACION", at=None):
        if at is None:
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who))
        with patch.object(_capture_service, "_now", return_value=at):
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who))

    async def get(self, path, who="OPERACION"):
        return await call("GET", path, cookie=await self.cookie(who))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def simple_rows(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, d.value_type||':'||coalesce(d.value_decimal::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND d.group_row_id IS NULL""", (capture_id,)).fetchall())

    def group_rows(self, capture_id):
        """[(row_number, 'key=type:value|...')] in row order, read straight from the typed columns."""
        return [(number, detail) for number, detail in self.connection.execute(
            """SELECT r.row_number, (SELECT string_agg(f.key||'='||d.value_type||':'||coalesce(d.value_decimal::text, d.value_text), '|' ORDER BY f.display_order)
                                     FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.group_row_id = r.id)
               FROM vinto_txn.capture_group_row r WHERE r.capture_id = %s ORDER BY r.row_number""", (capture_id,)).fetchall()]

    def inventory(self):
        return tuple(self.scalar(f"SELECT count(*) FROM {table}") for table in INVENTORY_TABLES)


def expected_row(row):
    return f"numero_bobina=text:{row['numero_bobina']}|posicion=text:{row['posicion']}|saldo_inicial_kg=decimal:{row['saldo_inicial_kg']}|ingreso_kg=decimal:{row['ingreso_kg']}|saldo_final_kg=decimal:{row['saldo_final_kg']}"


class ConfigurationTests(P111Case):
    async def test_the_shipped_configuration_is_unchanged(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({F6}))  # none of the candidate forms is in the production policy
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))  # Conversión is NOT operational in the real configuration

    async def test_without_the_test_configuration_p111_is_unreachable(self):
        _, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            reply = await self.post(self.payload(assignment))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertEqual((await self.post(self.payload(assignment))).status, 404)
            self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body(P111_MACHINE), cookie=await self.cookie("JEFATURA"))).status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)


class AvailabilityTests(P111Case):
    async def machines(self, who="OPERACION"):
        return {m["code"]: m for s in (await self.get("/api/production/machines", who)).json()["sectors"] if s["code"] == "CONVERSION" for m in s["machines"]}

    async def test_p111_is_offered_only_on_gambini_beside_p112_and_p116_and_wally_keeps_p113(self):
        machines = await self.machines()
        self.assertEqual([f["code"] for f in machines[CONV_MACHINE]["forms"]], [P111_CODE, P112_CODE, P116_CODE])  # P1-11 is NOT linked to WALLY
        self.assertEqual([f["code"] for f in machines[CONV_MACHINE_NO_FORM]["forms"]], [P113_CODE])
        self.assertNotIn(P111_DRAFT_CODE, str(machines))  # linked but never published: not offered

    async def test_p111_is_not_offered_without_grant_or_with_a_non_operational_sector_or_policy(self):
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertNotIn("CONVERSION", [s["code"] for s in (await self.get("/api/production/machines", who)).json()["sectors"]], who)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertNotIn("CONVERSION", [s["code"] for s in (await self.get("/api/production/machines")).json()["sectors"]])
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P116_CODE, P112_CODE, P113_CODE})):  # P1-11 not in the policy: it disappears, the others stay
            self.assertEqual([f["code"] for f in (await self.machines())[CONV_MACHINE]["forms"]], [P112_CODE, P116_CODE])


class GroupWriteTests(P111Case):
    async def test_201_one_row_is_persisted_with_the_server_context(self):
        order, assignment = await self.assignment(at=MORNING)
        one = [P111_ROWS[0]]
        reply = await self.post(self.payload(assignment, values=values_with(one)), at=MORNING)
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual((reply.json()["created"], reply.json()["already_submitted"]), (True, False))
        self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"]), (P111_CODE, "submitted", 1))
        self.assertEqual((capture["machine"]["code"], capture["assignment"]["id"], capture["work_order"]["id"]), (P111_MACHINE, assignment["id"], order["id"]))
        self.assertEqual((capture["shift"]["code"], capture["operating_date"]), ("FICT_CONV_MANANA", "2026-10-06"))
        self.assertEqual((capture["line"]["line_code"], capture["line"]["pv_reference"], capture["line"]["article"]["code"]), ("L1", "PV-1", ARTICLE))
        self.assertEqual(capture["values"], {"observaciones": "Dato de prueba", "_groups": {"bobinas": one}})
        self.assertEqual(self.group_rows(capture["id"]), [(1, expected_row(one[0]))])
        self.assertEqual(self.simple_rows(capture["id"]), {"observaciones": "textarea:Dato de prueba"})
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.users["OPERACION"][0].user_id)

    async def test_several_rows_keep_their_order_and_the_same_position_may_repeat(self):
        _, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment))  # the default rows: superior, superior, inferior
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual([r["numero_bobina"] for r in capture["values"]["_groups"]["bobinas"]], ["BOBINA-FICTICIA-001", "BOBINA-FICTICIA-002", "BOBINA-FICTICIA-003"])
        self.assertEqual(self.group_rows(capture["id"]), [(i, expected_row(row)) for i, row in enumerate(P111_ROWS, start=1)])
        self.assertEqual([r["posicion"] for r in capture["values"]["_groups"]["bobinas"]], ["superior", "superior", "inferior"])  # two rows with the same position are allowed
        # reading it back by id and in the filtered list returns the very same rows in the very same order
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).json()["values"], capture["values"])
        listed = (await self.get(f"/api/captures?form_code={P111_CODE}&machine_code={P111_MACHINE}")).json()
        self.assertEqual([c for c in listed if c["id"] == capture["id"]][0]["values"], capture["values"])

    async def test_no_uniqueness_of_the_coil_number_is_imposed_between_rows_or_captures(self):
        _, assignment = await self.assignment()
        twin = {**P111_ROWS[0]}
        self.assertEqual((await self.post(self.payload(assignment, values=values_with([twin, twin, {**twin, "posicion": "inferior"}])))).status, 201)  # the same number three times
        self.assertEqual((await self.post(self.payload(assignment, values=values_with([twin])))).status, 201)  # and again in another capture
        self.assertEqual((await self.post(self.payload(assignment, values=values_with([{**twin, "numero_bobina": "BM-2609-001"}])))).status, 201)

    async def test_the_group_cannot_be_empty_or_absent_min_rows_is_one(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for values in (values_with([]), {"observaciones": "x"}, {"_groups": {"bobinas": []}}, {}):
            reply = await self.post(self.payload(assignment, values=values))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), values)
        self.assertIn("al menos 1 filas", (await self.post(self.payload(assignment, values=values_with([])))).json()["detail"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_technical_cap_is_respected_and_is_not_an_industrial_maximum(self):
        _, assignment = await self.assignment()
        cap = _capture_service.TECHNICAL_MAX_GROUP_ROWS
        self.assertEqual(cap, 1000)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        reply = await self.post(self.payload(assignment, values=values_with([P111_ROWS[0]] * (cap + 1))))
        self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertIn(f"máximo {cap} filas", reply.json()["detail"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)
        self.assertIsNone(self.scalar("SELECT max_rows FROM vinto_config.field_group g JOIN vinto_config.form_version fv ON fv.id = g.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s", (P111_CODE,)))  # no functional maximum is declared
        self.assertEqual(self.scalar("SELECT min_rows FROM vinto_config.field_group g JOIN vinto_config.form_version fv ON fv.id = g.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s", (P111_CODE,)), 1)
        many = await self.post(self.payload(assignment, values=values_with([P111_ROWS[0]] * 50)))  # a plain, large capture is fine
        self.assertEqual(many.status, 201, many.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (many.json()["capture"]["id"],)), 50)

    async def test_a_position_outside_the_catalog_is_rejected(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for bad in ("no_aplica", "Superior", "SUPERIOR", "centro", "", None, 1):
            with self.subTest(position=bad):
                reply = await self.post(self.payload(assignment, values=values_with([{**P111_ROWS[0], "posicion": bad}])))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_no_industrial_rule_is_invented_on_the_balances(self):
        _, assignment = await self.assignment()
        rows = [{**P111_ROWS[0], "saldo_inicial_kg": "10", "ingreso_kg": "0", "saldo_final_kg": "999999"},  # final greater than initial: allowed
                {**P111_ROWS[0], "saldo_inicial_kg": "0", "ingreso_kg": "0", "saldo_final_kg": "0"},
                {**P111_ROWS[0], "saldo_inicial_kg": "-5", "ingreso_kg": "-1.5", "saldo_final_kg": "-0.25"},  # no minimum: structural only
                {**P111_ROWS[0], "saldo_inicial_kg": "1.123456789", "ingreso_kg": "7", "saldo_final_kg": "3.14159"}]  # no precision rule, no rounding
        reply = await self.post(self.payload(assignment, values=values_with(rows)))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(reply.json()["capture"]["values"]["_groups"]["bobinas"], rows)  # returned exactly as declared
        stored = [row[1] for row in self.group_rows(reply.json()["capture"]["id"])]
        self.assertIn("saldo_inicial_kg=decimal:1.123456789", stored[3])
        self.assertIn("saldo_final_kg=decimal:3.14159", stored[3])
        self.assertIn("saldo_final_kg=decimal:999999", stored[0])

    async def test_computed_or_additional_values_are_rejected(self):
        _, assignment = await self.assignment()
        base = values_with()
        for key in ("consumo", "consumo_bobina", "saldo_disponible", "merma_total", "tipo_bobina", "peso_total", "total_rollos", "operador", "turno", "maquina", "fecha", "firma", "grupo"):
            with self.subTest(simple=key):  # as a simple value
                reply = await self.post(self.payload(assignment, values={**base, key: "x"}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        for key in ("consumo_kg", "consumo", "tipo", "rodela", "peso_kg", "bobbin_id", "row_number", "id"):
            with self.subTest(row=key):  # inside a row (including internal references)
                rows = [{**P111_ROWS[0], key: "x"}]
                reply = await self.post(self.payload(assignment, values=values_with(rows)))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        for bad in ({"rodelas": [dict(P111_ROWS[0])]}, {"insumos": []}):  # undeclared groups
            reply = await self.post(self.payload(assignment, values={**base, "_groups": {**base["_groups"], **bad}}))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        # a grouped key sent as a simple value is refused as well
        self.assertEqual((await self.post(self.payload(assignment, values={**base, "numero_bobina": "x"}))).status, 422)
        for extra in ({"machine_code": P111_MACHINE}, {"operating_date": "2026-01-01"}, {"consumo": "1"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.post({**self.payload(assignment), **extra})).status, 422, extra)

    async def test_422_invalid_rows_persist_nothing(self):
        _, assignment = await self.assignment()
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row"))
        row = P111_ROWS[0]
        cases = [{k: v for k, v in row.items() if k != required} for required in ("numero_bobina", "posicion", "saldo_inicial_kg", "ingreso_kg", "saldo_final_kg")]
        cases += [{**row, "numero_bobina": "   "}, {**row, "numero_bobina": 12}, {**row, "numero_bobina": "x" * 10_001}, {**row, "saldo_inicial_kg": "12,5"}, {**row, "saldo_inicial_kg": "abc"},
                  {**row, "ingreso_kg": "1e3"}, {**row, "saldo_final_kg": True}, {**row, "saldo_final_kg": None}, {}, {"numero_bobina": ""}]
        for bad_row in cases:
            with self.subTest(row=bad_row):
                reply = await self.post(self.payload(assignment, values=values_with([P111_ROWS[1], bad_row])))  # the second row is invalid: the whole capture is refused
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
                self.assertNotIn("SELECT", reply.text)
        self.assertEqual((await self.post(self.payload(assignment, values={**values_with(), "observaciones": ["x"]}))).status, 422)
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row")), before)

    async def test_the_optional_observaciones_may_be_omitted(self):
        _, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment, values={"_groups": {"bobinas": [dict(P111_ROWS[0])]}}))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(reply.json()["capture"]["values"], {"_groups": {"bobinas": [P111_ROWS[0]]}})
        self.assertEqual(self.simple_rows(reply.json()["capture"]["id"]), {})


class IdempotencyTests(P111Case):
    async def test_200_identical_retry_creates_no_duplicate_rows(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        first = await self.post(body)
        self.assertEqual(first.status, 201)
        snapshot = lambda: (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row"),
                            self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        before = snapshot()
        again = await self.post(body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), 1 + 3 * 5)  # observaciones + 3 rows x 5 values

    async def test_409_same_capture_id_with_other_content_reordered_rows_or_another_form(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        changed = await self.post({**body, "values": values_with([{**P111_ROWS[0], "saldo_final_kg": "1"}, P111_ROWS[1], P111_ROWS[2]])})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        reordered = await self.post({**body, "values": values_with([P111_ROWS[2], P111_ROWS[0], P111_ROWS[1]])})  # the order is content
        self.assertEqual((reordered.status, reordered.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        fewer = await self.post({**body, "values": values_with(list(P111_ROWS[:2]))})
        self.assertEqual((fewer.status, fewer.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        cross = await self.post({**body, "form_code": P112_CODE, "values": dict(P112_VALUES)})
        self.assertEqual((cross.status, cross.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.group_rows(body["capture_id"]), [(i, expected_row(row)) for i, row in enumerate(P111_ROWS, start=1)])  # nothing changed

    async def test_concurrency_identical_posts_create_one_capture_with_its_rows_once(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)


class ScopeAndAvailabilityTests(P111Case):
    async def test_401_403_and_sector_scope(self):
        _, assignment = await self.assignment()
        self.assertEqual((await call("POST", "/api/captures", json_body=self.payload(assignment))).status, 401)
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            self.assertEqual((await self.post(self.payload(assignment), who)).status, 403, who)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):  # no grant on CONVERSION: the assignment does not exist for them
            self.assertEqual((await self.post(self.payload(assignment), who)).status, 404, who)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_forms_not_linked_to_the_machine_or_not_published_are_not_available(self):
        _, gambini = await self.assignment(CONV_MACHINE)
        _, wally = await self.assignment(CONV_MACHINE_NO_FORM)
        crossed = [await self.post(self.payload(wally, form_code=P111_CODE)),  # P1-11 on WALLY (not linked)
                   await self.post(self.payload(gambini, form_code=P113_CODE)),  # P1-13 on GAMBINI (not linked)
                   await self.post(self.payload(gambini, form_code=P111_DRAFT_CODE, values=values_with()))]  # linked to GAMBINI but never published
        for reply in crossed:
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"), reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = ANY(%s)", ([wally["id"], gambini["id"]],)), 0)
        f6 = await self.post({"capture_id": str(uuid4()), "form_code": F6, "assignment_id": gambini["id"], "device_key": str(uuid4()), "values": {"cantidad_fardos": 1}})
        self.assertEqual((f6.status, f6.json()["code"]), (409, "FORM_NOT_AVAILABLE"))

    async def test_the_capture_is_audited_with_the_actor_rows_included(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before)
        actor = self.users["OPERACION"][0].user_id
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE actor_id = %s", (actor,)), 0)
        self.assertGreaterEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'capture_group_row' AND actor_id = %s", (actor,)), 3)
        self.assertEqual(self.scalar("SELECT count(DISTINCT created_by) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), 1)


class ShiftTests(P111Case):
    async def test_a_shift_change_makes_the_assignment_stale_and_no_row_is_stored(self):
        _, assignment = await self.assignment(at=MORNING)
        self.assertEqual((await self.post(self.payload(assignment), at=MORNING)).status, 201)
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row"))
        for later in (AFTERNOON, NIGHT_EVENING, NEXT_MORNING):
            reply = await self.post(self.payload(assignment), at=later)
            self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_STALE"), later.isoformat())
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row")), before)

    async def test_the_night_shift_crosses_midnight_with_the_same_operating_date(self):
        _, assignment = await self.assignment(at=NIGHT_EVENING)
        reply = await self.post(self.payload(assignment), at=NIGHT_AFTER_MIDNIGHT)
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual((reply.json()["capture"]["shift"]["code"], reply.json()["capture"]["operating_date"]), ("FICT_CONV_NOCHE", "2026-10-06"))

    async def test_a_finished_assignment_is_rejected(self):
        _, assignment = await self.assignment()
        await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=await self.cookie("SUPERVISION"))
        reply = await self.post(self.payload(assignment))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))


class NoInventoryNoGenealogyTests(P111Case):
    async def test_a_p111_capture_creates_no_bobbin_relation_inventory_consumption_or_other_capture(self):
        _, assignment = await self.assignment()
        before = self.inventory()
        captures_before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        rows = [{**P111_ROWS[0], "numero_bobina": "BM-2609-001"}, {**P111_ROWS[1], "numero_bobina": "1"}, {**P111_ROWS[2], "numero_bobina": "RP-0001"}]  # F3-looking codes on purpose: they must NOT be looked up or linked
        reply = await self.post(self.payload(assignment, values=values_with(rows)))
        self.assertEqual(reply.status, 201, reply.text)
        capture_id = reply.json()["capture"]["id"]
        self.assertEqual(self.inventory(), before)  # no bobbin, no relation (genealogy), no quality release, no sequence
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), captures_before + 1)  # exactly ONE capture: no automatic P1-13 / P1-12 / P1-16
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code IN (%s, %s, %s)", (P112_CODE, P113_CODE, P116_CODE)), 0)
        self.assertEqual(self.scalar("SELECT bobbin_id IS NULL FROM vinto_txn.capture WHERE id = %s", (capture_id,)), True)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin WHERE code = ANY(%s)", (["BM-2609-001", "1", "RP-0001"],)), 0)  # nothing was created under those codes
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (capture_id,)), 3)
        self.assertFalse(any(key in str(reply.json()["capture"]["values"]) for key in ("consumo", "saldo_disponible", "merma", "bobbin_id")))
        stored_keys = {row[0] for row in self.connection.execute("SELECT f.key FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s", (capture_id,)).fetchall()}
        self.assertEqual(stored_keys, {"observaciones", "numero_bobina", "posicion", "saldo_inicial_kg", "ingreso_kg", "saldo_final_kg"})  # no consumption, balance or diff is stored

    async def test_p113_p112_and_p116_stay_independent_of_p111(self):
        _, gambini = await self.assignment(CONV_MACHINE)
        _, wally = await self.assignment(CONV_MACHINE_NO_FORM)
        coils = (await self.post(self.payload(gambini))).json()["capture"]
        pallet = (await self.post(self.payload(gambini, form_code=P112_CODE))).json()["capture"]
        waste = (await self.post(self.payload(gambini, form_code=P116_CODE))).json()["capture"]
        napkins = (await self.post(self.payload(wally, form_code=P113_CODE))).json()["capture"]
        self.assertEqual([c["form"]["code"] for c in (coils, pallet, waste, napkins)], [P111_CODE, P112_CODE, P116_CODE, P113_CODE])
        by_form = {code: {c["id"] for c in (await self.get(f"/api/captures?form_code={code}")).json()} for code in (P111_CODE, P112_CODE, P113_CODE, P116_CODE)}
        self.assertEqual((coils["id"] in by_form[P111_CODE], pallet["id"] in by_form[P112_CODE], napkins["id"] in by_form[P113_CODE], waste["id"] in by_form[P116_CODE]), (True, True, True, True))
        sets = list(by_form.values())
        self.assertTrue(all(not (a & b) for i, a in enumerate(sets) for b in sets[i + 1:]))  # no capture belongs to two forms
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = ANY(%s)", ([pallet["id"], waste["id"], napkins["id"]],)), 0)  # only P1-11 has group rows
        self.assertEqual(self.group_rows(coils["id"])[0][0], 1)
        self.assertEqual(sorted(self.simple_rows(napkins["id"])), ["cantidad_jabas", "hora_fin", "hora_inicio", "ingreso_kg", "numero_bobina", "observaciones", "saldo_final_kg", "saldo_inicial_kg"])


class ReadTests(P111Case):
    async def test_get_by_id_filtered_list_and_scope(self):
        _, assignment = await self.assignment()
        capture = (await self.post(self.payload(assignment))).json()["capture"]
        reply = await self.get(f"/api/captures/{capture['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, P111_CODE, capture["values"]))
        self.assertEqual((await self.get(f"/api/captures?form_code={P111_CODE}&machine_code={P111_MACHINE}")).json()[0]["id"], capture["id"])
        self.assertEqual((await self.get(f"/api/captures?form_code={P111_CODE}&machine_code={CONV_MACHINE_NO_FORM}")).json(), [])
        self.assertNotIn(capture["id"], [c["id"] for c in (await self.get("/api/captures")).json()])  # historic default: F6 only
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}", who)).status, 404, who)
            self.assertEqual((await self.get(f"/api/captures?form_code={P111_CODE}", who)).json(), [], who)
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "JEFATURA")).status, 403)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            self.assertEqual((await self.get(f"/api/captures?form_code={P111_CODE}")).status, 422)


if __name__ == "__main__":
    unittest.main()
