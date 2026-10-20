"""DEV-B2: the CANDIDATE VINTO-P1-04 (Registro de consumo de fibra) runs through the existing central production engine for Bobinas MP1 / MP3.

The contract is the 9 MANUAL fields of the ORIGINAL definition (form_4_registro_de_consumo_de_fibra: 17 fields = 9 manual + 6 automatic + 2 calculated), NOT the legacy Fiber screen. The automatic
fields (fecha, turno, maquina, operador, hora_inicio, hora_fin) and the calculated ones (total_kg, total_final) are never stored as manual values and the backend rejects them if sent. hora_inicio /
hora_fin have NO confirmed source and are not generated; no total is calculated. Installed only in ephemeral *_test databases and enabled per test with patch.object on CENTRAL_FORM_CODES; the shipped
policy (only VINTO-P1-06) and sectors (only BOBINAS) are asserted unchanged. This is NOT a homologation.
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
    from devb2_fixtures import P104_CODE, P104_FIELDS, P104_VALUES, install_p104
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.devb2_fixtures import P104_CODE, P104_FIELDS, P104_VALUES, install_p104
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
BUNDLE = load_bundle()
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in ("MP1", "MP3")}
STATE = {}
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz -> DIA, 2026-10-06
NEXT_DAY = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)
AUTOMATIC = ("fecha", "turno", "maquina", "operador", "hora_inicio", "hora_fin")
CALCULATED = ("total_kg", "total_final")


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devb2_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE[machine], "quantity": 10, "due_date": "2026-11-01"}]}


class Base(unittest.IsolatedAsyncioTestCase):
    install = staticmethod(lambda connection: install_p104(connection))
    prefix = "vinto_devb2"

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], cls.prefix)
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        cls.install(cls.connection)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", ("BOBINAS",)), ("SUPERVISION", "SUPERVISION", ("BOBINAS",)), ("OPERACION", "OPERACION", ("BOBINAS",)),
                                       ("CALIDAD", "CALIDAD", ("BOBINAS",)), ("OPERACION_SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"devb2.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P104_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine="MP1", at=DAY):
        order = (await call("POST", "/api/work-orders", json_body=order_body(machine), cookie=await self.cookie("JEFATURA")))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        body = {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]}
        with patch.object(_assignments_service, "_now", return_value=at):
            reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body=body)
        self.assertEqual(reply.status, 201, reply.text)
        return order, reply.json()["assignment"]

    def payload(self, assignment, **changes):
        body = {"capture_id": str(uuid4()), "form_code": P104_CODE, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(P104_VALUES)}
        body.update(changes)
        return body

    async def post(self, body, who="OPERACION", at=DAY):
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


class ConfigurationAndAvailabilityTests(Base):
    async def test_the_shipped_configuration_is_unchanged_and_p104_is_unreachable_without_the_test_policy(self):
        # CLOUD-DEP G.12-C4: CENTRAL_FORM_CODES real ya incluye los candidatos de Bobinas habilitados;
        # lo que importa es que P104_CODE (fixture sintética) NO esté.
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30", "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16", "VINTO-P1-29"}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS", "REBOBINADO", "CONVERSION"))
        _, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            reply = await self.post(self.payload(assignment))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
            self.assertEqual((await self.get(f"/api/captures?form_code={P104_CODE}")).status, 422)
            machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
            self.assertEqual(machines, {"MP1": sorted(SHIPPED_POLICY & frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31"})), "MP3": sorted(SHIPPED_POLICY & frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31"}))})  # CLOUD-DEP G.12-C4-FINAL25: SHIPPED_POLICY entero ya no aplica solo a MP1/MP3 (P1-07/10/11/12/13/16/29/30 son de otros sectores)
            for codes in machines.values():
                self.assertNotIn(P104_CODE, codes)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    async def test_the_backend_publishes_p104_on_mp1_and_mp3_only_with_the_test_policy(self):
        machines = {m["code"]: m for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
        for machine in ("MP1", "MP3"):
            self.assertEqual([f["code"] for f in machines[machine]["forms"]], sorted([P104_CODE, F6]))  # ordered by form code
        self.assertEqual({f["code"]: f["name"] for f in machines["MP1"]["forms"]}[P104_CODE], "Registro de consumo de fibra (candidato DEV-B2)")
        self.assertEqual((await self.get("/api/production/machines", "OPERACION_SIN_SECTOR")).json()["sectors"], [])

    async def test_the_contract_is_the_nine_manual_fields_of_the_original_definition(self):
        self.assertEqual([f[0] for f in P104_FIELDS], ["fibra_corta_detalle", "fibra_larga_detalle", "recorte_ph", "recorte_servilleta", "recorte_toalla", "materia_prima_ph",
                                                       "materia_prima_servilleta", "materia_prima_toalla", "observaciones"])
        stored = [(r[0], r[1], r[2]) for r in self.connection.execute(
            """SELECT fd.key, fd.value_type, fd.required FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (P104_CODE,)).fetchall()]
        self.assertEqual(stored, [(k, t, r) for k, _, t, r, _ in P104_FIELDS])
        self.assertEqual([k for k, t, _ in stored if t == "decimal"], ["recorte_ph", "materia_prima_ph"])  # only the two PH quantities are decimals
        for key in AUTOMATIC + CALCULATED:
            self.assertNotIn(key, [k for k, _, _ in stored])


class WriteTests(Base):
    async def test_201_is_persisted_with_the_server_context_on_mp1_and_mp3(self):
        for machine in ("MP1", "MP3"):
            order, assignment = await self.assignment(machine)
            reply = await self.post(self.payload(assignment))
            self.assertEqual(reply.status, 201, reply.text)
            data = reply.json()
            self.assertEqual((data["created"], data["already_submitted"]), (True, False))
            capture = data["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"]), (P104_CODE, "submitted", 1))
            self.assertEqual((capture["machine"]["code"], capture["assignment"]["id"], capture["work_order"]["id"]), (machine, assignment["id"], order["id"]))
            self.assertEqual((capture["shift"]["code"], capture["operating_date"]), ("DIA", "2026-10-06"))
            self.assertEqual((capture["line"]["line_code"], capture["line"]["article"]["code"]), ("L1", ARTICLE[machine]))
            self.assertEqual(capture["values"], P104_VALUES)
            kinds = {k: ("decimal" if k in ("recorte_ph", "materia_prima_ph") else "textarea" if k == "observaciones" else "text") for k in P104_VALUES}
            expected = {k: (f"{kinds[k]}:{v}") for k, v in P104_VALUES.items()}
            self.assertEqual(self.rows(capture["id"]), expected)
            self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.users["OPERACION"][0].user_id)

    async def test_no_total_hour_or_automatic_value_is_generated_or_stored(self):
        _, assignment = await self.assignment()
        capture = (await self.post(self.payload(assignment))).json()["capture"]
        stored = self.rows(capture["id"])
        self.assertEqual(sorted(stored), sorted(P104_VALUES))  # exactly the manual values that were typed
        for key in AUTOMATIC + CALCULATED:
            self.assertNotIn(key, stored)
            self.assertNotIn(key, capture["values"])
        self.assertEqual(stored["recorte_servilleta"], "text:3 bultos (texto)")  # text is not interpreted
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (capture["id"],)), len(P104_VALUES))

    async def test_automatic_and_calculated_fields_sent_by_the_client_are_rejected(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for key in AUTOMATIC + CALCULATED + ("inventario", "consumo_calculado"):
            with self.subTest(key=key):
                reply = await self.post(self.payload(assignment, values={**P104_VALUES, key: "1"}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_optional_observaciones_may_be_omitted(self):
        _, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment, values={k: v for k, v in P104_VALUES.items() if k != "observaciones"}))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertNotIn("observaciones", reply.json()["capture"]["values"])

    async def test_422_invalid_values_persist_nothing(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        required = [f[0] for f in P104_FIELDS if f[3]]
        cases = [{k: v for k, v in P104_VALUES.items() if k != key} for key in required]  # each required field missing
        cases += [{**P104_VALUES, required[0]: "   "}, {**P104_VALUES, required[0]: None}, {**P104_VALUES, required[0]: 7}]
        for key in ("recorte_ph", "materia_prima_ph"):  # the two decimals
            cases += [{**P104_VALUES, key: bad} for bad in ("12,5", "abc", "1e3", "", True, None)]
        for values in cases:
            with self.subTest(values=values):
                reply = await self.post(self.payload(assignment, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_200_identical_retry_creates_no_duplicate_and_409_for_different_content(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        first = await self.post(body)
        self.assertEqual(first.status, 201)
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        again = await self.post(body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
        changed = await self.post({**body, "values": {**body["values"], "recorte_ph": "99.9"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.rows(body["capture_id"])["recorte_ph"], "decimal:12.5")

    async def test_roles_only_operacion_captures(self):
        _, assignment = await self.assignment()
        self.assertEqual((await call("POST", "/api/captures", json_body=self.payload(assignment))).status, 401)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            self.assertEqual((await self.post(self.payload(assignment), who)).status, 403, who)
        self.assertEqual((await self.post(self.payload(assignment), "OPERACION_SIN_SECTOR")).status, 404)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_a_stale_or_finished_assignment_is_rejected_and_nothing_is_stored(self):
        _, assignment = await self.assignment(at=DAY)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        reply = await self.post(self.payload(assignment), at=NEXT_DAY)
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_STALE"))
        await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=await self.cookie("SUPERVISION"))
        reply = await self.post(self.payload(assignment))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))
        self.assertEqual((await self.post(self.payload(assignment, assignment_id=str(uuid4())))).status, 404)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_payload_stays_closed(self):
        _, assignment = await self.assignment()
        for extra in ({"machine_code": "MP1"}, {"operating_date": "2026-01-01"}, {"shift_code": "NOCHE"}, {"form_version_id": str(uuid4())}, {"hora_inicio": "07:00"}):
            self.assertEqual((await self.post({**self.payload(assignment), **extra})).status, 422, extra)

    async def test_concurrency_identical_posts_create_one_capture(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), len(P104_VALUES))

    async def test_the_capture_is_audited_and_creates_no_consumption_inventory_or_bobbin(self):
        _, assignment = await self.assignment()
        before = (self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release"))
        self.assertEqual((await self.post(self.payload(assignment))).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before[0])
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE actor_id = %s", (self.users["OPERACION"][0].user_id,)), 0)
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release")), before[1:])


class ReadTests(Base):
    async def test_get_by_id_and_the_history_is_filtered_by_form(self):
        _, assignment = await self.assignment()
        capture = (await self.post(self.payload(assignment))).json()["capture"]
        other = (await self.post({"capture_id": str(uuid4()), "form_code": F6, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": {"cantidad_fardos": 1, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "1"}})).json()["capture"]
        reply = await self.get(f"/api/captures/{capture['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, P104_CODE, capture["values"]))
        listed = (await self.get(f"/api/captures?form_code={P104_CODE}")).json()
        self.assertEqual([c["id"] for c in listed], [capture["id"]])
        self.assertNotIn(other["id"], [c["id"] for c in listed])
        self.assertEqual((await self.get(f"/api/captures?form_code={P104_CODE}&machine_code=MP1")).json()[0]["id"], capture["id"])
        self.assertEqual((await self.get(f"/api/captures?form_code={P104_CODE}&machine_code=MP3")).json(), [])
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "OPERACION_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.get(f"/api/captures?form_code={P104_CODE}", "OPERACION_SIN_SECTOR")).json(), [])
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "JEFATURA")).status, 403)
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={P104_CODE}")).status, 422)


class UnlinkedMachineTests(Base):
    """P1-04 published ONLY for MP1: a capture on MP3 is not available (the backend, not the UI, decides)."""
    install = staticmethod(lambda connection: install_p104(connection, machine_codes=("MP1",)))
    prefix = "vinto_devb2u"

    async def test_availability_and_capture_follow_the_machine_link(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": sorted([P104_CODE, F6]), "MP3": [F6]})
        _, mp3 = await self.assignment("MP3")
        reply = await self.post(self.payload(mp3))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        _, mp1 = await self.assignment("MP1")
        self.assertEqual((await self.post(self.payload(mp1))).status, 201)


class UnpublishedFormTests(Base):
    install = staticmethod(lambda connection: install_p104(connection, publish=False))
    prefix = "vinto_devb2d"

    async def test_an_unpublished_form_is_neither_published_nor_available(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines["MP1"], [F6])
        _, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


if __name__ == "__main__":
    unittest.main()
