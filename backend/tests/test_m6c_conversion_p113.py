"""M6-C: a CANDIDATE VINTO-P1-13 (declared coil + three declared balances + one pallet + observations) runs through the central production engine under an ISOLATED test configuration.

Everything is installed in an ephemeral *_test database: the fictitious Conversión context of M6-A (tests/m6a_fixtures.py), P1-16 and P1-12 on GAMBINI, and the candidate P1-13 definition linked to WALLY
only (tests/m6c_fixtures.py). Sector and forms are enabled per test with patch.object; the shipped configuration is asserted unchanged. This is NOT a homologation of P1-13: the coil number and the three
balances are DECLARATIONS; nothing here computes consumption, balance, inventory, genealogy, weights, a pallet number or a correlative, and nothing relates the capture to a real bobbin.
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
    from m6a_fixtures import CONV_SECTOR, CONV_MACHINE, CONV_MACHINE_NO_FORM, ENABLED_CONVERSION_SECTORS, P116_CODE, P116_VALUES, install_conversion_fixture, install_p116
    from m6b_fixtures import P112_CODE, P112_DRAFT_CODE, P112_VALUES, install_p112, install_p112_draft
    from m6c_fixtures import P113_CODE, P113_DRAFT_CODE, P113_MACHINE, P113_VALUES, install_p113, install_p113_draft
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.m6a_fixtures import CONV_SECTOR, CONV_MACHINE, CONV_MACHINE_NO_FORM, ENABLED_CONVERSION_SECTORS, P116_CODE, P116_VALUES, install_conversion_fixture, install_p116
    from tests.m6b_fixtures import P112_CODE, P112_DRAFT_CODE, P112_VALUES, install_p112, install_p112_draft
    from tests.m6c_fixtures import P113_CODE, P113_DRAFT_CODE, P113_MACHINE, P113_VALUES, install_p113, install_p113_draft
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any patch
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
BUNDLE = load_bundle()
ARTICLE = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")[0]
STATE = {}

# La Paz is UTC-4 all year (same hypotheses as M6-A).
MORNING = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)       # 12:00 La Paz -> MANANA, 2026-10-06
AFTERNOON = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)     # 15:00 La Paz -> TARDE
NIGHT_EVENING = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)  # 23:00 La Paz -> NOCHE, 2026-10-06
NIGHT_AFTER_MIDNIGHT = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 02:00 La Paz (10-07) -> NOCHE, operating date 2026-10-06
NEXT_MORNING = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)  # 06:00 La Paz (10-07) -> MANANA, 2026-10-07


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m6c_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine, article=ARTICLE):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": article, "quantity": 10, "due_date": "2026-11-01"}]}


class P113Case(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m6c")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        install_conversion_fixture(cls.connection, [ARTICLE])
        install_p116(cls.connection)
        install_p112(cls.connection)
        install_p112_draft(cls.connection)
        install_p113(cls.connection)
        install_p113_draft(cls.connection)
        cls.scope = patch.object(_sectors, "_OPERATIONAL", ENABLED_CONVERSION_SECTORS)  # TEST-ONLY: Conversión operational in this process
        cls.scope.start()
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", ENABLED_CONVERSION_SECTORS), ("SUPERVISION", "SUPERVISION", ENABLED_CONVERSION_SECTORS),
                                       ("OPERACION", "OPERACION", ENABLED_CONVERSION_SECTORS), ("CALIDAD", "CALIDAD", ENABLED_CONVERSION_SECTORS),
                                       ("OPERACION_SOLO_BOBINAS", "OPERACION", ("BOBINAS",)), ("OPERACION_SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"m6c.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.scope.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P116_CODE, P112_CODE, P112_DRAFT_CODE, P113_CODE, P113_DRAFT_CODE}))  # TEST-ONLY policy (the draft codes are enabled but never published)
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine=P113_MACHINE, at=None):
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

    def payload(self, assignment, form_code=P113_CODE, **changes):
        values = {P113_CODE: P113_VALUES, P112_CODE: P112_VALUES, P116_CODE: P116_VALUES}.get(form_code, {})
        body = {"capture_id": str(uuid4()), "form_code": form_code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(values)}
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

    def rows(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, d.value_type||':'||coalesce(d.value_integer::text, d.value_time::text, d.value_decimal::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


INVENTORY_TABLES = ("vinto_txn.bobbin", "vinto_txn.bobbin_relation", "vinto_txn.quality_release", "vinto_txn.bobbin_sequence")
EIGHT = ["cantidad_jabas", "hora_fin", "hora_inicio", "ingreso_kg", "numero_bobina", "observaciones", "saldo_final_kg", "saldo_inicial_kg"]


class ConfigurationTests(P113Case):
    async def test_the_shipped_configuration_is_unchanged(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30", "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16", "VINTO-P1-29"}))  # CLOUD-DEP G.12-C4: +5 candidatos de Bobinas habilitados para QA  # none of the candidate forms is in the production policy
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS", "REBOBINADO", "CONVERSION"))

    async def test_without_the_test_configuration_p113_is_unreachable(self):
        _, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            reply = await self.post(self.payload(assignment))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertEqual((await self.post(self.payload(assignment))).status, 404)
            self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body(P113_MACHINE), cookie=await self.cookie("JEFATURA"))).status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)


class AvailabilityTests(P113Case):
    async def machines(self, who="OPERACION"):
        return {m["code"]: m for s in (await self.get("/api/production/machines", who)).json()["sectors"] if s["code"] == CONV_SECTOR for m in s["machines"]}

    async def test_wally_offers_only_p113_and_gambini_keeps_p112_and_p116(self):
        machines = await self.machines()
        self.assertEqual([f["code"] for f in machines[P113_MACHINE]["forms"]], [P113_CODE])
        self.assertEqual([f["code"] for f in machines[CONV_MACHINE]["forms"]], [P112_CODE, P116_CODE])  # P1-13 is NOT linked to GAMBINI; P1-12 / P1-16 are NOT linked to WALLY
        for hidden in (P113_DRAFT_CODE, P112_DRAFT_CODE):
            self.assertNotIn(hidden, str(machines))  # linked but never published: not offered

    async def test_p113_is_not_offered_without_grant_or_with_a_non_operational_sector_or_policy(self):
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertNotIn(CONV_SECTOR, [s["code"] for s in (await self.get("/api/production/machines", who)).json()["sectors"]], who)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertNotIn(CONV_SECTOR, [s["code"] for s in (await self.get("/api/production/machines")).json()["sectors"]])
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P116_CODE, P112_CODE})):  # P1-13 not in the policy: WALLY has nothing again
            self.assertEqual((await self.machines())[P113_MACHINE]["forms"], [])


class WriteTests(P113Case):
    async def test_201_the_eight_typed_values_are_persisted_with_the_server_context(self):
        order, assignment = await self.assignment(at=MORNING)
        reply = await self.post(self.payload(assignment, values={**P113_VALUES, "saldo_inicial_kg": " 100.500 ", "numero_bobina": "  Ab-1/2  "}), at=MORNING)
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual((reply.json()["created"], reply.json()["already_submitted"]), (True, False))
        self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"]), (P113_CODE, "submitted", 1))
        self.assertEqual((capture["machine"]["code"], capture["assignment"]["id"], capture["work_order"]["id"]), (P113_MACHINE, assignment["id"], order["id"]))
        self.assertEqual((capture["shift"]["code"], capture["operating_date"]), ("FICT_CONV_MANANA", "2026-10-06"))
        self.assertEqual((capture["line"]["line_code"], capture["line"]["pv_reference"], capture["line"]["article"]["code"]), ("L1", "PV-1", ARTICLE))
        self.assertEqual(capture["values"], {"numero_bobina": "Ab-1/2", "saldo_inicial_kg": "100.500", "ingreso_kg": "20", "saldo_final_kg": "150.25", "cantidad_jabas": 40,
                                             "hora_inicio": "08:15:00", "hora_fin": "09:05:00", "observaciones": "Dato de prueba"})
        self.assertEqual(self.rows(capture["id"]), {"numero_bobina": "text:Ab-1/2", "saldo_inicial_kg": "decimal:100.500", "ingreso_kg": "decimal:20", "saldo_final_kg": "decimal:150.25",
                                                    "cantidad_jabas": "integer:40", "hora_inicio": "time:08:15:00", "hora_fin": "time:09:05:00", "observaciones": "textarea:Dato de prueba"})
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.users["OPERACION"][0].user_id)

    async def test_the_optional_observaciones_may_be_omitted(self):
        _, assignment = await self.assignment()
        values = {k: v for k, v in P113_VALUES.items() if k != "observaciones"}
        reply = await self.post(self.payload(assignment, values=values))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertNotIn("observaciones", reply.json()["capture"]["values"])
        self.assertEqual(sorted(self.rows(reply.json()["capture"]["id"])), [k for k in EIGHT if k != "observaciones"])

    async def test_no_industrial_rule_is_invented(self):
        _, assignment = await self.assignment()
        for values in ({**P113_VALUES, "saldo_inicial_kg": "10", "ingreso_kg": "0", "saldo_final_kg": "999999"},  # the final balance may be greater than the initial one
                       {**P113_VALUES, "saldo_inicial_kg": "0", "ingreso_kg": "0", "saldo_final_kg": "0"},
                       {**P113_VALUES, "saldo_inicial_kg": "-5", "ingreso_kg": "-1.5", "saldo_final_kg": "-0.25"},  # no minimum: structural only
                       {**P113_VALUES, "saldo_inicial_kg": "1.123456789", "ingreso_kg": "7", "saldo_final_kg": "3.14159"},  # no precision rule, no rounding
                       {**P113_VALUES, "cantidad_jabas": -5, "hora_inicio": "22:00", "hora_fin": "06:00"},  # the pallet keeps the P1-12 structural behaviour
                       {**P113_VALUES, "numero_bobina": "cualquier cosa 123"}):
            reply = await self.post(self.payload(assignment, values=values))
            self.assertEqual(reply.status, 201, (values, reply.text))
        stored = self.connection.execute("SELECT value_decimal::text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE f.key = 'saldo_final_kg' AND d.value_decimal IS NOT NULL ORDER BY d.created_at").fetchall()
        self.assertIn(("3.14159",), stored)  # stored as sent

    async def test_only_the_eight_declared_values_are_accepted(self):
        _, assignment = await self.assignment()
        for invented in ("consumo_bobina", "consumo_kg", "saldo_disponible", "merma_bobina", "peso_total_pallet", "peso_nominal_jaba", "numero_pallet", "insumo", "cantidad_insumo", "tipo_bobina",
                         "operador", "turno", "maquina", "fecha", "firma", "grupo"):
            with self.subTest(invented=invented):
                reply = await self.post(self.payload(assignment, values={**P113_VALUES, invented: "x"}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        for extra in ({"machine_code": P113_MACHINE}, {"operating_date": "2026-01-01"}, {"consumo": "1"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.post({**self.payload(assignment), **extra})).status, 422, extra)

    async def test_422_invalid_values_persist_nothing(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        cases = []
        for required in ("numero_bobina", "saldo_inicial_kg", "ingreso_kg", "saldo_final_kg", "cantidad_jabas", "hora_inicio", "hora_fin"):
            cases.append({k: v for k, v in P113_VALUES.items() if k != required})
        cases += [{**P113_VALUES, "numero_bobina": "   "}, {**P113_VALUES, "numero_bobina": 12}, {**P113_VALUES, "numero_bobina": "x" * 10_001},
                  {**P113_VALUES, "saldo_inicial_kg": "12,5"}, {**P113_VALUES, "saldo_inicial_kg": "abc"}, {**P113_VALUES, "ingreso_kg": "1e3"}, {**P113_VALUES, "saldo_final_kg": True},
                  {**P113_VALUES, "saldo_final_kg": None}, {**P113_VALUES, "cantidad_jabas": "cuarenta"}, {**P113_VALUES, "cantidad_jabas": 4.5}, {**P113_VALUES, "hora_inicio": "25:00"},
                  {**P113_VALUES, "hora_fin": "mediodía"}, {**P113_VALUES, "observaciones": ["x"]}]
        for values in cases:
            with self.subTest(values=values):
                reply = await self.post(self.payload(assignment, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
                self.assertNotIn("SELECT", reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_200_identical_retry_creates_no_duplicate(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        first = await self.post(body)
        self.assertEqual(first.status, 201)
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        again = await self.post(body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)

    async def test_409_same_capture_id_with_different_content_or_another_form(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        changed = await self.post({**body, "values": {**body["values"], "saldo_final_kg": "1"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        cross = await self.post({**body, "form_code": P112_CODE, "values": dict(P112_VALUES)})
        self.assertEqual((cross.status, cross.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.rows(body["capture_id"])["saldo_final_kg"], "decimal:150.25")

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
        _, wally = await self.assignment(P113_MACHINE)
        _, gambini = await self.assignment(CONV_MACHINE)
        crossed = [(await self.post(self.payload(gambini, form_code=P113_CODE))),  # P1-13 on GAMBINI
                   (await self.post(self.payload(wally, form_code=P112_CODE))), (await self.post(self.payload(wally, form_code=P116_CODE))),  # P1-12 / P1-16 on WALLY
                   (await self.post(self.payload(wally, form_code=P113_DRAFT_CODE, values={})))]  # linked to WALLY but never published
        for reply in crossed:
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"), reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = ANY(%s)", ([wally["id"], gambini["id"]],)), 0)

    async def test_f6_on_a_conversion_machine_is_not_available(self):
        _, assignment = await self.assignment()
        reply = await self.post({"capture_id": str(uuid4()), "form_code": F6, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": {"cantidad_fardos": 1}})
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))

    async def test_the_capture_is_audited_with_the_actor(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        self.assertEqual((await self.post(self.payload(assignment))).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE actor_id = %s", (self.users["OPERACION"][0].user_id,)), 0)

    async def test_concurrency_identical_posts_create_one_capture(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), 8)


class NoInventoryNoGenealogyTests(P113Case):
    def snapshot(self):
        return tuple(self.scalar(f"SELECT count(*) FROM {table}") for table in INVENTORY_TABLES)

    async def test_a_p113_capture_creates_no_bobbin_relation_inventory_consumption_or_second_capture(self):
        _, assignment = await self.assignment()
        before = self.snapshot()
        captures_before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        reply = await self.post(self.payload(assignment, values={**P113_VALUES, "numero_bobina": "BM-2609-001"}))  # looks like an F3 code on purpose: it must NOT be looked up or linked
        self.assertEqual(reply.status, 201, reply.text)
        capture_id = reply.json()["capture"]["id"]
        self.assertEqual(self.snapshot(), before)  # no bobbin, no relation (genealogy), no quality release, no sequence
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), captures_before + 1)  # exactly ONE capture: no automatic P1-12 / P1-16
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code IN (%s, %s)", (P112_CODE, P116_CODE)), 0)
        self.assertEqual(self.scalar("SELECT bobbin_id IS NULL FROM vinto_txn.capture WHERE id = %s", (capture_id,)), True)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (capture_id,)), 0)  # no groups, no per-coil rows
        self.assertEqual(sorted(self.rows(capture_id)), EIGHT)  # no consumption, balance, merma, weight or pallet number is stored
        self.assertFalse(any(key in reply.json()["capture"]["values"] for key in ("consumo", "consumo_bobina", "peso_total_pallet", "numero_pallet", "saldo_disponible")))

    async def test_p112_and_p116_stay_independent_of_p113_on_gambini(self):
        _, gambini = await self.assignment(CONV_MACHINE)
        pallet = (await self.post(self.payload(gambini, form_code=P112_CODE))).json()["capture"]
        waste = (await self.post(self.payload(gambini, form_code=P116_CODE))).json()["capture"]
        self.assertEqual((pallet["form"]["code"], waste["form"]["code"]), (P112_CODE, P116_CODE))
        self.assertEqual(sorted(self.rows(pallet["id"])), ["cantidad_jabas", "hora_fin", "hora_inicio"])
        self.assertEqual(sorted(self.rows(waste["id"])), ["origen_merma", "peso_merma_kg", "tipo_merma"])
        _, wally = await self.assignment(P113_MACHINE)
        record = (await self.post(self.payload(wally))).json()["capture"]
        by_form = {code: {c["id"] for c in (await self.get(f"/api/captures?form_code={code}")).json()} for code in (P112_CODE, P113_CODE, P116_CODE)}
        self.assertEqual((pallet["id"] in by_form[P112_CODE], waste["id"] in by_form[P116_CODE], record["id"] in by_form[P113_CODE]), (True, True, True))
        self.assertEqual(by_form[P112_CODE] & by_form[P113_CODE], set())
        self.assertEqual(by_form[P116_CODE] & by_form[P113_CODE], set())
        self.assertEqual(by_form[P112_CODE] & by_form[P116_CODE], set())


class ShiftTests(P113Case):
    async def test_a_shift_change_makes_the_assignment_stale_and_nothing_is_stored(self):
        _, assignment = await self.assignment(at=MORNING)
        self.assertEqual((await self.post(self.payload(assignment), at=MORNING)).status, 201)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for later in (AFTERNOON, NIGHT_EVENING, NEXT_MORNING):
            reply = await self.post(self.payload(assignment), at=later)
            self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_STALE"), later.isoformat())
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

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


class ReadTests(P113Case):
    async def test_get_by_id_filtered_list_and_scope(self):
        _, assignment = await self.assignment()
        capture = (await self.post(self.payload(assignment))).json()["capture"]
        reply = await self.get(f"/api/captures/{capture['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, P113_CODE, capture["values"]))
        self.assertEqual((await self.get(f"/api/captures?form_code={P113_CODE}&machine_code={P113_MACHINE}")).json()[0]["id"], capture["id"])
        self.assertEqual((await self.get(f"/api/captures?form_code={P113_CODE}&machine_code={CONV_MACHINE}")).json(), [])
        self.assertNotIn(capture["id"], [c["id"] for c in (await self.get("/api/captures")).json()])  # historic default: F6 only
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}", who)).status, 404, who)
            self.assertEqual((await self.get(f"/api/captures?form_code={P113_CODE}", who)).json(), [], who)
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "JEFATURA")).status, 403)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            self.assertEqual((await self.get(f"/api/captures?form_code={P113_CODE}")).status, 422)


if __name__ == "__main__":
    unittest.main()
