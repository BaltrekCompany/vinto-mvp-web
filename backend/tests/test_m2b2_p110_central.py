"""M2-B2: VINTO-P1-10 runs through the central production engine (M2-A) under an ISOLATED test configuration.

Everything is installed in an ephemeral *_test database: a fictitious Rebobinado sector/machine/shifts and a CANDIDATE P1-10 definition (tests/m2b2_fixtures.py).
The sector and the form are enabled per test with patch.object (sectors._OPERATIONAL, capture_service.CENTRAL_FORM_CODES); the shipped configuration is asserted
unchanged. Nothing touches vinto, backend/seed_data or the real policy. This is NOT a homologation of P1-10: numbering, weight, responsible, signature, machines,
product/line relation and shifts are pending VINTO decisions and are not decided here.
"""

import asyncio
import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app import sectors as _sectors
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle

try:
    from m2a_fixtures import install_production_form
    from m2b2_fixtures import ENABLED_SECTORS, P110_CODE, P110_VALUES, REB_MACHINE, install_p110, install_rebobinado_fixture
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form
    from tests.m2b2_fixtures import ENABLED_SECTORS, P110_CODE, P110_VALUES, REB_MACHINE, install_p110, install_rebobinado_fixture
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any patch
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
F6_VALUES = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}
BUNDLE = load_bundle()
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
ARTICLE = MP1_CODES[0]
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m2b2_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine, article=ARTICLE):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": article, "quantity": 10, "due_date": "2026-11-01"}]}


class P110Case(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m2b2")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        install_rebobinado_fixture(cls.connection, [ARTICLE])
        install_p110(cls.connection)
        cls.scope = patch.object(_sectors, "_OPERATIONAL", ENABLED_SECTORS)  # TEST-ONLY: Rebobinado operational in this process
        cls.scope.start()
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", ENABLED_SECTORS), ("SUPERVISION", "SUPERVISION", ENABLED_SECTORS), ("OPERACION", "OPERACION", ENABLED_SECTORS),
                                       ("CALIDAD", "CALIDAD", ENABLED_SECTORS), ("OPERACION_SOLO_BOBINAS", "OPERACION", ("BOBINAS",)), ("OPERACION_SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"m2b2.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.scope.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P110_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine=REB_MACHINE):
        order = (await call("POST", "/api/work-orders", json_body=order_body(machine), cookie=await self.cookie("JEFATURA")))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"),
                           json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return order, reply.json()["assignment"]

    def payload(self, assignment, form_code=P110_CODE, **changes):
        body = {"capture_id": str(uuid4()), "form_code": form_code, "assignment_id": assignment["id"], "device_key": str(uuid4()),
                "values": dict(P110_VALUES if form_code == P110_CODE else F6_VALUES)}
        body.update(changes)
        return body

    async def post(self, body, who="OPERACION"):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who))

    async def get(self, path, who="OPERACION"):
        return await call("GET", path, cookie=await self.cookie(who))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def rows(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, coalesce(d.value_text, d.value_decimal::text, d.value_integer::text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


class ConfigurationTests(P110Case):
    async def test_the_shipped_configuration_is_unchanged(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31"}))  # CLOUD-DEP G.12-C4: +5 candidatos de Bobinas habilitados para QA  # P1-10 is NOT in the production policy
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))  # Rebobinado is NOT operational in the real configuration

    async def test_without_the_test_configuration_p110_is_unreachable(self):
        order, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):  # sector still enabled in this process, policy shipped
            reply = await self.post(self.payload(assignment))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):  # policy enabled but the real operational scope
            self.assertEqual((await self.post(self.payload(assignment))).status, 404)
            outside = await call("GET", f"/api/assignments/active?machine_code={REB_MACHINE}", cookie=await self.cookie("OPERACION"))
            self.assertEqual((outside.status, outside.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))  # the machine of a non-operational sector is rejected
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)


class WriteTests(P110Case):
    async def test_201_and_the_exact_values_are_persisted_with_the_server_context(self):
        order, assignment = await self.assignment()
        body = self.payload(assignment, values={**P110_VALUES, "peso_fardo": "  12,50 kg  ", "numero_de_fardo": "00-0042", "codigo_numero_de_producto": "Ab 1/2"})
        reply = await self.post(body)
        self.assertEqual(reply.status, 201, reply.text)
        data = reply.json()
        self.assertEqual((data["created"], data["already_submitted"]), (True, False))
        capture = data["capture"]
        self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"]), (P110_CODE, "submitted", 1))
        self.assertEqual((capture["machine"]["code"], capture["assignment"]["id"], capture["work_order"]["id"]), (REB_MACHINE, assignment["id"], order["id"]))
        self.assertEqual(capture["shift"]["code"], assignment["shift"]["code"])
        self.assertTrue(capture["shift"]["code"].startswith("FICT_"))  # the fictitious test shift
        # text is stored as sent (only trimmed): no numeric conversion, no format, no uniqueness
        self.assertEqual(capture["values"], {"codigo_numero_de_producto": "Ab 1/2", "numero_de_fardo": "00-0042", "peso_fardo": "12,50 kg", "observaciones": "Dato de prueba"})
        self.assertEqual(self.rows(capture["id"]), capture["values"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (capture["id"],)), 4)
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.users["OPERACION"][0].user_id)

    async def test_the_optional_observaciones_may_be_omitted_and_duplicates_of_content_are_allowed(self):
        _, assignment = await self.assignment()
        values = {k: v for k, v in P110_VALUES.items() if k != "observaciones"}
        first = await self.post(self.payload(assignment, values=values))
        second = await self.post(self.payload(assignment, values=values))  # same content, new capture_id: no uniqueness rule is invented
        self.assertEqual((first.status, second.status), (201, 201))
        self.assertNotIn("observaciones", first.json()["capture"]["values"])

    async def test_200_identical_retry_creates_no_duplicate(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        again = await self.post(body)
        self.assertEqual(again.status, 200)
        self.assertEqual((again.json()["created"], again.json()["already_submitted"]), (False, True))
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)

    async def test_409_same_capture_id_with_different_content_form_or_actor(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        changed = await self.post({**body, "values": {**body["values"], "numero_de_fardo": "OTRO"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        cross = await self.post({**body, "form_code": F6, "values": dict(F6_VALUES)})
        self.assertEqual((cross.status, cross.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.rows(body["capture_id"])["numero_de_fardo"], "EJEMPLO-000")

    async def test_422_invalid_values_persist_nothing(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        cases = [
            {k: v for k, v in P110_VALUES.items() if k != "codigo_numero_de_producto"},
            {**P110_VALUES, "numero_de_fardo": "   "},
            {**P110_VALUES, "peso_fardo": 12.5},  # the weight is declared as TEXT: a JSON number is not accepted
            {**P110_VALUES, "peso_fardo": None},
            {**P110_VALUES, "numero_de_fardo": 42},
            {**P110_VALUES, "observaciones": ["x"]},
            {**P110_VALUES, "codigo_numero_de_producto": "x" * 10_001},
            {**P110_VALUES, "campo_inventado": "x"},
            {**P110_VALUES, "fecha": "2026-01-01"},  # contextual fields are NOT client values
            {**P110_VALUES, "maquina": "COPASA"},
            {**P110_VALUES, "responsable": "otra persona"},
            {**P110_VALUES, "firma": "firmado"},
        ]
        for values in cases:
            with self.subTest(values=list(values)):
                reply = await self.post(self.payload(assignment, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
                self.assertNotIn("SELECT", reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_payload_stays_closed(self):
        _, assignment = await self.assignment()
        for extra in ({"machine_code": "COPASA"}, {"operating_date": "2026-01-01"}, {"responsable": "x"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.post({**self.payload(assignment), **extra})).status, 422, extra)

    async def test_401_403_and_sector_scope(self):
        _, assignment = await self.assignment()
        self.assertEqual((await call("POST", "/api/captures", json_body=self.payload(assignment))).status, 401)
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            self.assertEqual((await self.post(self.payload(assignment), who)).status, 403, who)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):  # no grant on REBOBINADO: the assignment does not exist for them
            self.assertEqual((await self.post(self.payload(assignment), who)).status, 404, who)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_a_machine_without_the_form_relation_is_not_available(self):
        _, assignment = await self.assignment()
        install_production_form(self.connection, "VINTO-TEST-P110-NOREL", machine_codes=("MP1",))  # published, but NOT linked to the Rebobinado machine
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P110_CODE, "VINTO-TEST-P110-NOREL"})):
            reply = await self.post(self.payload(assignment, form_code="VINTO-TEST-P110-NOREL", values={}))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))

    async def test_an_f6_form_on_a_rebobinado_machine_is_not_available(self):
        _, assignment = await self.assignment()  # F6 is linked only to MP1/MP3: the engine's form-machine relation protects the separation
        reply = await self.post(self.payload(assignment, form_code=F6))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))

    async def test_concurrency_identical_posts_create_one_capture_and_distinct_ids_create_distinct_captures(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), 4)
        distinct = [self.payload(assignment, values={**P110_VALUES, "numero_de_fardo": f"EJ-{i}"}) for i in range(4)]
        replies = await asyncio.gather(*[self.post(b) for b in distinct])
        self.assertEqual([r.status for r in replies], [201] * 4)
        self.assertEqual(self.scalar("SELECT count(DISTINCT id) FROM vinto_txn.capture WHERE id = ANY(%s)", ([b["capture_id"] for b in distinct],)), 4)

    async def test_the_capture_is_audited_with_the_actor(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before)
        actors = {r[0] for r in self.connection.execute("SELECT DISTINCT actor_id FROM vinto_audit.audit_event WHERE actor_id IS NOT NULL AND request_id LIKE 'capture:%%' OR actor_id = %s", (self.users["OPERACION"][0].user_id,)).fetchall()}
        self.assertIn(self.users["OPERACION"][0].user_id, actors)


class ReadTests(P110Case):
    async def seed(self):
        _, assignment = await self.assignment()
        capture = (await self.post(self.payload(assignment))).json()["capture"]
        return assignment, capture

    async def test_get_by_id_and_filtered_list(self):
        _, capture = await self.seed()
        reply = await self.get(f"/api/captures/{capture['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, P110_CODE, capture["values"]))
        listed = (await self.get(f"/api/captures?form_code={P110_CODE}")).json()
        self.assertIn(capture["id"], [c["id"] for c in listed])
        self.assertEqual({c["form"]["code"] for c in listed}, {P110_CODE})
        self.assertEqual((await self.get(f"/api/captures?form_code={P110_CODE}&machine_code={REB_MACHINE}")).json()[0]["id"], capture["id"])
        self.assertEqual((await self.get(f"/api/captures?form_code={P110_CODE}&machine_code=MP1")).json(), [])

    async def test_f6_and_p110_are_separate(self):
        _, capture = await self.seed()
        order = (await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=await self.cookie("JEFATURA"))).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        activated = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        mp1 = activated.json()["assignment"]
        f6 = (await self.post(self.payload(mp1, form_code=F6))).json()
        self.assertEqual(f6["capture"]["form"]["code"], F6)
        default = (await self.get("/api/captures")).json()  # historic default: F6 only
        self.assertEqual({c["form"]["code"] for c in default}, {F6})
        self.assertNotIn(capture["id"], [c["id"] for c in default])
        only_p110 = (await self.get(f"/api/captures?form_code={P110_CODE}")).json()
        self.assertEqual({c["form"]["code"] for c in only_p110}, {P110_CODE})
        self.assertNotIn(f6["capture"]["id"], [c["id"] for c in only_p110])
        self.assertEqual((await self.get(f"/api/captures/{f6['capture']['id']}")).json()["form"]["code"], F6)
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).json()["form"]["code"], P110_CODE)

    async def test_404_and_empty_results_outside_the_scope(self):
        _, capture = await self.seed()
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}", who)).status, 404, who)
            self.assertEqual((await self.get(f"/api/captures?form_code={P110_CODE}", who)).json(), [], who)
        self.assertEqual((await self.get(f"/api/captures/{uuid4()}")).status, 404)
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}")).status, 401)
        self.assertEqual((await call("GET", f"/api/captures?form_code={P110_CODE}")).status, 401)
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "JEFATURA")).status, 403)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):  # real operational scope: Rebobinado data behaves as non-existent
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={P110_CODE}")).json(), [])
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):  # real policy: the capture is not exposed, the code is not enabled
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={P110_CODE}")).status, 422)


if __name__ == "__main__":
    unittest.main()
