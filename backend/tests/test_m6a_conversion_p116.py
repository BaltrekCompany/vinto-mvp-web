"""M6-A: a CANDIDATE VINTO-P1-16 (one waste weighing per capture) runs through the central production engine under an ISOLATED test configuration for Conversión.

Everything is installed in an ephemeral *_test database: a fictitious Conversión sector, two machines, three hypothesis shifts and the candidate P1-16 definition (tests/m6a_fixtures.py).
The sector and the form are enabled per test with patch.object (sectors._OPERATIONAL, capture_service.CENTRAL_FORM_CODES); the shipped configuration is asserted unchanged. Nothing
touches vinto, backend/seed_data or the real policy. This is NOT a homologation of P1-16: the contract, the shifts, correlative, signature, group and totals are pending VINTO decisions.
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
    from m2a_fixtures import install_production_form
    from m6a_fixtures import CONV_MACHINE, CONV_MACHINE_NO_FORM, ENABLED_CONVERSION_SECTORS, P116_CODE, P116_VALUES, install_conversion_fixture, install_p116
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form
    from tests.m6a_fixtures import CONV_MACHINE, CONV_MACHINE_NO_FORM, ENABLED_CONVERSION_SECTORS, P116_CODE, P116_VALUES, install_conversion_fixture, install_p116
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any patch
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
BUNDLE = load_bundle()
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
ARTICLE = MP1_CODES[0]
STATE = {}

# La Paz is UTC-4 all year. The operating date of a night shift is the day it STARTED (test hypothesis, same rule as Bobinas).
MORNING = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)      # 12:00 La Paz -> MANANA, 2026-10-06
AFTERNOON = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)    # 15:00 La Paz -> TARDE,  2026-10-06
NIGHT_EVENING = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)  # 23:00 La Paz -> NOCHE,  2026-10-06
NIGHT_AFTER_MIDNIGHT = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 02:00 La Paz (10-07) -> NOCHE, operating date 2026-10-06
NEXT_MORNING = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)  # 06:00 La Paz (10-07) -> MANANA, 2026-10-07


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m6a_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine, article=ARTICLE):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": article, "quantity": 10, "due_date": "2026-11-01"}]}


class P116Case(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m6a")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        install_conversion_fixture(cls.connection, [ARTICLE])
        install_p116(cls.connection)
        cls.scope = patch.object(_sectors, "_OPERATIONAL", ENABLED_CONVERSION_SECTORS)  # TEST-ONLY: Conversión operational in this process
        cls.scope.start()
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", ENABLED_CONVERSION_SECTORS), ("SUPERVISION", "SUPERVISION", ENABLED_CONVERSION_SECTORS),
                                       ("OPERACION", "OPERACION", ENABLED_CONVERSION_SECTORS), ("CALIDAD", "CALIDAD", ENABLED_CONVERSION_SECTORS),
                                       ("OPERACION_SOLO_BOBINAS", "OPERACION", ("BOBINAS",)), ("OPERACION_SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"m6a.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.scope.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P116_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine=CONV_MACHINE, at=None):
        """Jefatura creates + publishes an OT, Supervisión activates it (optionally at a given instant: the shift and operating date are resolved from it)."""
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

    def payload(self, assignment, form_code=P116_CODE, **changes):
        body = {"capture_id": str(uuid4()), "form_code": form_code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(P116_VALUES)}
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
            """SELECT f.key, d.value_type||':'||coalesce(d.value_text, d.value_decimal::text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


class ConfigurationTests(P116Case):
    async def test_the_shipped_configuration_is_unchanged(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31"}))  # CLOUD-DEP G.12-C4: +5 candidatos de Bobinas habilitados para QA  # P1-16 is NOT in the production policy
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))  # Conversión is NOT operational in the real configuration

    async def test_without_the_test_configuration_p116_is_unreachable(self):
        order, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):  # sector still enabled in this process, policy shipped
            reply = await self.post(self.payload(assignment))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):  # policy enabled but the real operational scope
            self.assertEqual((await self.post(self.payload(assignment))).status, 404)
            outside = await call("GET", f"/api/assignments/active?machine_code={CONV_MACHINE}", cookie=await self.cookie("OPERACION"))
            self.assertEqual((outside.status, outside.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
            created = await call("POST", "/api/work-orders", json_body=order_body(CONV_MACHINE), cookie=await self.cookie("JEFATURA"))
            self.assertEqual(created.status, 422)  # an OT of a non-operational sector cannot be created
            listed = await call("GET", "/api/production/machines", cookie=await self.cookie("OPERACION"))
            self.assertEqual([s["code"] for s in listed.json()["sectors"]], ["BOBINAS"])  # only the real operational sector is offered
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)


class AvailabilityTests(P116Case):
    async def test_the_backend_publishes_conversion_with_p116_only_on_the_linked_machine(self):
        reply = await self.get("/api/production/machines?articles=true")
        self.assertEqual(reply.status, 200, reply.text)
        sectors = {s["code"]: s for s in reply.json()["sectors"]}
        self.assertIn("CONVERSION", sectors)
        machines = {m["code"]: m for m in sectors["CONVERSION"]["machines"]}
        self.assertEqual(sorted(machines), sorted([CONV_MACHINE, CONV_MACHINE_NO_FORM]))
        self.assertEqual([f["code"] for f in machines[CONV_MACHINE]["forms"]], [P116_CODE])
        self.assertEqual(machines[CONV_MACHINE_NO_FORM]["forms"], [])  # no relation: nothing offered
        self.assertEqual([a["code"] for a in machines[CONV_MACHINE]["articles"]], [ARTICLE])

    async def test_a_sector_without_grant_or_not_operational_is_not_listed(self):
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            codes = [s["code"] for s in (await self.get("/api/production/machines", who)).json()["sectors"]]
            self.assertNotIn("CONVERSION", codes, who)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            codes = [s["code"] for s in (await self.get("/api/production/machines")).json()["sectors"]]
            self.assertNotIn("CONVERSION", codes)
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):  # sector listed but the form is not enabled by the policy
            machines = {m["code"]: m for s in (await self.get("/api/production/machines")).json()["sectors"] if s["code"] == "CONVERSION" for m in s["machines"]}
            self.assertEqual(machines[CONV_MACHINE]["forms"], [])


class WriteTests(P116Case):
    async def test_201_the_typed_values_are_persisted_with_the_server_context(self):
        order, assignment = await self.assignment(at=MORNING)
        body = self.payload(assignment, values={"tipo_merma": "carton", "origen_merma": "cola", "peso_merma_kg": " 7.250 "})
        reply = await self.post(body, at=MORNING)
        self.assertEqual(reply.status, 201, reply.text)
        data = reply.json()
        self.assertEqual((data["created"], data["already_submitted"]), (True, False))
        capture = data["capture"]
        self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"]), (P116_CODE, "submitted", 1))
        self.assertEqual((capture["machine"]["code"], capture["assignment"]["id"], capture["work_order"]["id"]), (CONV_MACHINE, assignment["id"], order["id"]))
        self.assertEqual((capture["shift"]["code"], capture["operating_date"]), ("FICT_CONV_MANANA", "2026-10-06"))
        self.assertEqual((capture["line"]["line_code"], capture["line"]["pv_reference"], capture["line"]["article"]["code"]), ("L1", "PV-1", ARTICLE))
        self.assertEqual(capture["values"], {"tipo_merma": "carton", "origen_merma": "cola", "peso_merma_kg": "7.250"})
        self.assertEqual(self.rows(capture["id"]), {"tipo_merma": "text:carton", "origen_merma": "text:cola", "peso_merma_kg": "decimal:7.250"})  # typed columns
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (capture["id"],)), 3)
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.users["OPERACION"][0].user_id)

    async def test_every_option_of_the_legacy_screen_is_accepted(self):
        _, assignment = await self.assignment()
        for tipo in ("hoja_doble", "hoja_simple", "servilleta", "toalla", "carton", "plastico"):
            for origen in ("logs", "cola", "maquina"):
                reply = await self.post(self.payload(assignment, values={"tipo_merma": tipo, "origen_merma": origen, "peso_merma_kg": "1"}))
                self.assertEqual(reply.status, 201, (tipo, origen, reply.text))

    async def test_no_correlative_total_signature_or_group_is_invented(self):
        _, assignment = await self.assignment()
        capture = (await self.post(self.payload(assignment))).json()["capture"]
        self.assertEqual(sorted(capture["values"]), ["origen_merma", "peso_merma_kg", "tipo_merma"])
        self.assertEqual(sorted(self.rows(capture["id"])), ["origen_merma", "peso_merma_kg", "tipo_merma"])
        for invented in ("numero_correlativo", "total_merma_kg", "firma", "grupo", "operador", "turno", "maquina", "fecha"):
            with self.subTest(invented=invented):
                reply = await self.post(self.payload(assignment, values={**P116_VALUES, invented: "x"}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))

    async def test_200_identical_retry_creates_no_duplicate(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        first = await self.post(body)
        self.assertEqual(first.status, 201)
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        again = await self.post(body)
        self.assertEqual(again.status, 200)
        self.assertEqual((again.json()["created"], again.json()["already_submitted"]), (False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)

    async def test_409_same_capture_id_with_different_content_or_form(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        changed = await self.post({**body, "values": {**body["values"], "peso_merma_kg": "99.000"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.rows(body["capture_id"])["peso_merma_kg"], "decimal:12.500")

    async def test_422_invalid_values_persist_nothing(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        cases = [
            {k: v for k, v in P116_VALUES.items() if k != "tipo_merma"},
            {k: v for k, v in P116_VALUES.items() if k != "origen_merma"},
            {k: v for k, v in P116_VALUES.items() if k != "peso_merma_kg"},
            {**P116_VALUES, "tipo_merma": "Hoja doble"},  # the label is not the option key
            {**P116_VALUES, "tipo_merma": "papel"},  # unknown option
            {**P116_VALUES, "origen_merma": "Planta"},
            {**P116_VALUES, "peso_merma_kg": "12,5"},  # the backend accepts only the decimal point (the client normalizes the comma)
            {**P116_VALUES, "peso_merma_kg": "abc"},
            {**P116_VALUES, "peso_merma_kg": "1e3"},
            {**P116_VALUES, "peso_merma_kg": True},
            {**P116_VALUES, "peso_merma_kg": "   "},
            {**P116_VALUES, "peso_merma_kg": None},
            {**P116_VALUES, "tipo_merma": 3},
        ]
        for values in cases:
            with self.subTest(values=values):
                reply = await self.post(self.payload(assignment, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
                self.assertNotIn("SELECT", reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_payload_stays_closed(self):
        _, assignment = await self.assignment()
        for extra in ({"machine_code": CONV_MACHINE}, {"operating_date": "2026-01-01"}, {"shift_code": "FICT_CONV_NOCHE"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.post({**self.payload(assignment), **extra})).status, 422, extra)

    async def test_401_403_and_sector_scope(self):
        _, assignment = await self.assignment()
        self.assertEqual((await call("POST", "/api/captures", json_body=self.payload(assignment))).status, 401)
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            self.assertEqual((await self.post(self.payload(assignment), who)).status, 403, who)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):  # no grant on CONVERSION: the assignment does not exist for them
            self.assertEqual((await self.post(self.payload(assignment), who)).status, 404, who)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_a_user_without_grant_cannot_program_or_see_conversion(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.work_order")
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):  # OPERACION has no work_order.manage: refused before the sector is even looked at
            self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body(CONV_MACHINE), cookie=await self.cookie(who))).status, 403, who)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), before)
        order, _ = await self.assignment()  # a published Conversión OT exists; Operación without the grant cannot even see it
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await call("GET", f"/api/assignments/active?machine_code={CONV_MACHINE}", cookie=await self.cookie(who))).status, 422, who)

    async def test_a_machine_without_the_form_relation_is_not_available(self):
        _, assignment = await self.assignment(CONV_MACHINE_NO_FORM)  # WALLY: the form is published but NOT linked to it
        reply = await self.post(self.payload(assignment))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],)), 0)

    async def test_an_unpublished_form_is_not_available(self):
        _, assignment = await self.assignment()
        install_p116_draft = "VINTO-TEST-P116-DRAFT"
        install_production_form(self.connection, install_p116_draft, machine_codes=(CONV_MACHINE,), publish=False)  # linked but NOT published
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P116_CODE, install_p116_draft})):
            reply = await self.post(self.payload(assignment, form_code=install_p116_draft, values={}))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))

    async def test_an_f6_form_on_a_conversion_machine_is_not_available(self):
        _, assignment = await self.assignment()  # F6 is linked only to MP1/MP3
        reply = await self.post(self.payload(assignment, form_code=F6, values={"cantidad_fardos": 1}))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))

    async def test_concurrency_identical_posts_create_one_capture_and_distinct_ids_create_distinct_captures(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), 3)
        distinct = [self.payload(assignment, values={**P116_VALUES, "peso_merma_kg": f"{i}.5"}) for i in range(4)]
        replies = await asyncio.gather(*[self.post(b) for b in distinct])
        self.assertEqual([r.status for r in replies], [201] * 4)

    async def test_the_capture_is_audited_with_the_actor(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE actor_id = %s", (self.users["OPERACION"][0].user_id,)), 0)


class ShiftTests(P116Case):
    """The three HYPOTHESIS shifts (Mañana 06-14, Tarde 14-22, Noche 22-06) resolved by the existing backend resolver; nothing industrial is decided here."""

    async def test_the_assignment_shift_follows_the_three_hypothesis_schedules(self):
        for at, shift, date in ((MORNING, "FICT_CONV_MANANA", "2026-10-06"), (AFTERNOON, "FICT_CONV_TARDE", "2026-10-06"), (NIGHT_EVENING, "FICT_CONV_NOCHE", "2026-10-06"),
                                (NIGHT_AFTER_MIDNIGHT, "FICT_CONV_NOCHE", "2026-10-06"), (NEXT_MORNING, "FICT_CONV_MANANA", "2026-10-07")):
            with self.subTest(at=at.isoformat()):
                self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
                _, assignment = await self.assignment(at=at)
                self.assertEqual((assignment["shift"]["code"], assignment["operating_date"]), (shift, date))

    async def test_a_shift_change_makes_the_assignment_stale_and_nothing_is_stored(self):
        _, assignment = await self.assignment(at=MORNING)
        self.assertEqual((await self.post(self.payload(assignment), at=MORNING)).status, 201)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for later in (AFTERNOON, NIGHT_EVENING, NEXT_MORNING):  # next shift, the night, and the same shift the NEXT day
            reply = await self.post(self.payload(assignment), at=later)
            self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_STALE"), later.isoformat())
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_night_shift_crosses_midnight_with_the_same_operating_date(self):
        _, assignment = await self.assignment(at=NIGHT_EVENING)  # 23:00 La Paz on 10-06
        reply = await self.post(self.payload(assignment), at=NIGHT_AFTER_MIDNIGHT)  # 02:00 La Paz on 10-07: still the same shift and operating date
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual((reply.json()["capture"]["shift"]["code"], reply.json()["capture"]["operating_date"]), ("FICT_CONV_NOCHE", "2026-10-06"))
        stale = await self.post(self.payload(assignment), at=NEXT_MORNING)  # 06:00 La Paz: the morning of 10-07 starts
        self.assertEqual((stale.status, stale.json()["code"]), (409, "ASSIGNMENT_STALE"))

    async def test_a_finished_or_replaced_assignment_is_rejected(self):
        _, assignment = await self.assignment()
        await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=await self.cookie("SUPERVISION"))
        reply = await self.post(self.payload(assignment))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))
        self.assertEqual((await self.post(self.payload(assignment, assignment_id=str(uuid4())))).status, 404)


class ReadTests(P116Case):
    async def seed(self):
        _, assignment = await self.assignment()
        capture = (await self.post(self.payload(assignment))).json()["capture"]
        return assignment, capture

    async def test_get_by_id_and_filtered_list(self):
        _, capture = await self.seed()
        reply = await self.get(f"/api/captures/{capture['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, P116_CODE, capture["values"]))
        listed = (await self.get(f"/api/captures?form_code={P116_CODE}")).json()
        self.assertIn(capture["id"], [c["id"] for c in listed])
        self.assertEqual({c["form"]["code"] for c in listed}, {P116_CODE})
        self.assertEqual((await self.get(f"/api/captures?form_code={P116_CODE}&machine_code={CONV_MACHINE}")).json()[0]["id"], capture["id"])
        self.assertEqual((await self.get(f"/api/captures?form_code={P116_CODE}&machine_code={CONV_MACHINE_NO_FORM}")).json(), [])
        self.assertNotIn(capture["id"], [c["id"] for c in (await self.get("/api/captures")).json()])  # historic default: F6 only

    async def test_404_and_empty_results_outside_the_scope(self):
        _, capture = await self.seed()
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}", who)).status, 404, who)
            self.assertEqual((await self.get(f"/api/captures?form_code={P116_CODE}", who)).json(), [], who)
        self.assertEqual((await self.get(f"/api/captures/{uuid4()}")).status, 404)
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "JEFATURA")).status, 403)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):  # real operational scope: Conversión data behaves as non-existent
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={P116_CODE}")).json(), [])
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):  # real policy: the code is not enabled
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={P116_CODE}")).status, 422)


if __name__ == "__main__":
    unittest.main()
