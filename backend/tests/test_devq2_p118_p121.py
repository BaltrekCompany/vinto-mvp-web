"""DEV-Q2: the CANDIDATE VINTO-P1-18 (Porcentaje de consistencia) runs through the machine-level Quality capture route (/api/quality/machines/{machine}/captures) and the CANDIDATE VINTO-P1-21
(Perfil de gramaje y humedad) through the bobbin-level Quality capture route (/api/quality/bobbins/{bobbin_id}/captures), each reusing its existing service.

Installed in an ephemeral *_test database (tests/devq2_fixtures.py) and enabled per test with patch.object (machine policy MACHINE_QUALITY_FORM_CODES / bobbin policy ENABLED_BOBBIN_CANDIDATE_FORM_CODES); the
shipped policies (both empty), the production policy (only VINTO-P1-06) and the operational sectors are asserted unchanged. NOT a homologation: no formula, range, limit, catalog or approval criterion exists;
consistencia / humedad / promedio_gramaje / promedio_humedad are never calculated, hora is the REGISTRATION time and quality_release is never modified.
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
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.quality import capture_service as _quality_service
from app.quality import machine_capture_service as _machine_service

try:
    import test_f3_bobbins_api as f3
    from devq2_fixtures import P118_CODE, P118_FIELDS, P118_VALUES, P121_CODE, P121_FIELDS, P121_VALUES, install_p118, install_p121
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    from tests.devq2_fixtures import P118_CODE, P118_FIELDS, P118_VALUES, P121_CODE, P121_FIELDS, P121_VALUES, install_p118, install_p121
    from tests.test_assignments_api import call

SHIPPED_MACHINE_POLICY = _machine_service.MACHINE_QUALITY_FORM_CODES  # captured at import, before any patch
SHIPPED_BOBBIN_POLICY = _quality_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES
SHIPPED_PRODUCTION_POLICY = _capture_service.CENTRAL_FORM_CODES
SHIPPED_SECTORS = _sectors.operational_sector_codes()
STATE = {}
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz -> DIA, operating date 2026-10-06
AUTOMATIC = ("fecha", "hora", "maquina", "responsable")
P118_CALCULATED = ("consistencia",)
P121_CALCULATED = ("humedad", "promedio_gramaje", "promedio_humedad")
ENABLE_P121 = frozenset({P121_CODE})


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devq2_tpl")
    f3.STATE["template"] = STATE["template"]  # the bobbin-level classes reuse the F3 infrastructure with this bare template


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])
        f3.STATE.pop("template", None)


# ---------------------------------------------------------------- P1-18 · machine level


class MachineBase(unittest.IsolatedAsyncioTestCase):
    install = staticmethod(lambda connection: install_p118(connection))
    prefix = "vinto_devq2m"

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], cls.prefix)
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        cls.install(cls.connection)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("CALIDAD", "CALIDAD", ("BOBINAS",)), ("CALIDAD_SIN_SECTOR", "CALIDAD", ()), ("OPERACION", "OPERACION", ("BOBINAS",)), ("JEFATURA", "JEFATURA", ("BOBINAS",)),
                                       ("SUPERVISION", "SUPERVISION", ("BOBINAS",)), ("DATA_BALTREK", "DATA_BALTREK", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"devq2m.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        policy = patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset({P118_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)
        clock = patch.object(_capture_service, "_now", return_value=DAY)  # one stable patch for the whole test (nested patches of concurrent requests would not unwind in order)
        clock.start()
        self.addCleanup(clock.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    def body(self, **changes):
        body = {"capture_id": str(uuid4()), "form_code": P118_CODE, "device_key": str(uuid4()), "values": dict(P118_VALUES)}
        body.update(changes)
        return body

    async def post(self, body, machine="MP1", who="CALIDAD"):
        return await call("POST", f"/api/quality/machines/{machine}/captures", json_body=body, cookie=await self.cookie(who))

    async def get(self, path, who="CALIDAD"):
        return await call("GET", path, cookie=await self.cookie(who))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def rows(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, d.value_type||':'||coalesce(d.value_text, d.value_decimal::text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


class P118ConfigurationTests(MachineBase):
    async def test_the_shipped_configuration_is_unchanged_and_the_form_is_unreachable_without_the_test_policy(self):
        self.assertEqual(SHIPPED_MACHINE_POLICY, frozenset())  # NO machine-level quality form is enabled in the real configuration
        self.assertEqual(SHIPPED_BOBBIN_POLICY, frozenset())  # nor any bobbin-level candidate
        self.assertEqual(SHIPPED_PRODUCTION_POLICY, frozenset({"VINTO-P1-06"}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", SHIPPED_MACHINE_POLICY):
            reply = await self.post(self.body())
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
            self.assertEqual((await self.get(f"/api/quality/machines/MP1/captures?form_code={P118_CODE}")).status, 422)
            listed = (await self.get("/api/quality/machine-forms")).json()["sectors"]
            self.assertEqual([m["forms"] for s in listed for m in s["machines"]], [[], []])  # published but not enabled: nothing is offered
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    async def test_the_backend_publishes_the_form_on_mp1_and_mp3_only_to_quality_users_in_scope(self):
        listed = (await self.get("/api/quality/machine-forms")).json()["sectors"]
        self.assertEqual([s["code"] for s in listed], ["BOBINAS"])
        machines = {m["code"]: m for m in listed[0]["machines"]}
        for machine in ("MP1", "MP3"):
            self.assertEqual([f["code"] for f in machines[machine]["forms"]], [P118_CODE])
        self.assertEqual(machines["MP1"]["forms"][0]["name"], "Porcentaje de consistencia (candidato DEV-Q2)")
        self.assertEqual((await self.get("/api/quality/machine-forms", "CALIDAD_SIN_SECTOR")).json()["sectors"], [])
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.get("/api/quality/machine-forms", who)).status, 403, who)
        self.assertEqual((await call("GET", "/api/quality/machine-forms")).status, 401)

    async def test_the_production_availability_is_not_affected(self):
        reply = await call("GET", "/api/production/machines", cookie=await self.cookie("OPERACION"))
        self.assertEqual({m["code"]: [f["code"] for f in m["forms"]] for s in reply.json()["sectors"] for m in s["machines"]}, {"MP1": ["VINTO-P1-06"], "MP3": ["VINTO-P1-06"]})

    async def test_the_candidate_contract_is_exactly_the_manual_legacy_fields(self):
        self.assertEqual([f[0] for f in P118_FIELDS], ["producto", "numero_de_cuba", "punto_de_muestreo", "masa_humeda_g", "masa_seca_g", "papel_filtro_g", "papel_muestra_g", "peso_muestra_g", "observaciones"])
        stored = [(r[0], r[1], r[2], r[3], r[4]) for r in self.connection.execute(
            """SELECT fd.key, fd.label, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (P118_CODE,)).fetchall()]
        self.assertEqual(stored, [(k, label, t, r, "quality") for k, label, t, r, _ in P118_FIELDS])
        self.assertTrue(all(k not in AUTOMATIC + P118_CALCULATED for k, *_ in stored))
        self.assertEqual([t for k, _, t, *_ in stored if k in ("papel_filtro_g", "papel_muestra_g")], ["text", "text"])  # NOT converted to decimal because of their name


class P118WriteTests(MachineBase):
    async def test_201_is_persisted_with_the_server_context_without_bobbin_assignment_or_work_order(self):
        for machine in ("MP1", "MP3"):
            reply = await self.post(self.body(), machine)
            self.assertEqual(reply.status, 201, (machine, reply.text))
            data = reply.json()
            self.assertEqual((data["created"], data["already_submitted"]), (True, False))
            capture = data["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (P118_CODE, "submitted", 1, machine))
            self.assertEqual((capture["shift"]["code"], capture["operating_date"]), ("DIA", "2026-10-06"))
            self.assertEqual(capture["recorded_by"], {"id": str(self.users["CALIDAD"][0].user_id), "display_name": "Calidad"})
            self.assertEqual(capture["values"], P118_VALUES)
            self.assertEqual(capture["captured_at"].replace("Z", "+00:00"), DAY.isoformat())  # the REGISTRATION instant, not a test time
            row = self.connection.execute("SELECT assignment_id, bobbin_id, created_by, status, revision FROM vinto_txn.capture WHERE id = %s", (capture["id"],)).fetchone()
            self.assertEqual(row, (None, None, self.users["CALIDAD"][0].user_id, "submitted", 1))
            kinds = {k: t for k, _, t, *_ in P118_FIELDS}
            self.assertEqual(self.rows(capture["id"]), {k: f"{kinds[k]}:{v}" for k, v in P118_VALUES.items()})
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.work_order"), self.scalar("SELECT count(*) FROM vinto_txn.assignment"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin")), (0, 0, 0))

    async def test_the_text_weights_are_stored_as_typed_and_the_masses_are_not_combined_into_a_consistency(self):
        capture = (await self.post(self.body())).json()["capture"]
        stored = self.rows(capture["id"])
        self.assertEqual(stored["papel_filtro_g"], "text:1,10 (texto)")  # free text: a comma or a note is kept, nothing is parsed
        self.assertEqual(stored["papel_muestra_g"], "text:4.35")
        self.assertEqual((stored["masa_humeda_g"], stored["masa_seca_g"], stored["peso_muestra_g"]), ("decimal:100.50", "decimal:3.25", "decimal:0.0032"))
        self.assertEqual(sorted(stored), sorted(P118_VALUES))
        for key in AUTOMATIC + P118_CALCULATED:
            self.assertNotIn(key, stored)
            self.assertNotIn(key, capture["values"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (capture["id"],)), len(P118_VALUES))

    async def test_automatic_calculated_or_invented_fields_sent_by_the_client_are_rejected(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for key in AUTOMATIC + P118_CALCULATED + ("aprobado", "limite", "porcentaje"):
            with self.subTest(key=key):
                reply = await self.post(self.body(values={**P118_VALUES, key: "1"}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_optional_observations_may_be_omitted(self):
        reply = await self.post(self.body(values={k: v for k, v in P118_VALUES.items() if k != "observaciones"}))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertNotIn("observaciones", reply.json()["capture"]["values"])

    async def test_422_invalid_values_persist_nothing(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        required = [f[0] for f in P118_FIELDS if f[3]]
        cases = [{k: v for k, v in P118_VALUES.items() if k != key} for key in required]
        cases += [{**P118_VALUES, required[0]: "   "}, {**P118_VALUES, required[0]: None}, {**P118_VALUES, required[0]: 7}]
        for key in [f[0] for f in P118_FIELDS if f[2] == "decimal"]:
            cases += [{**P118_VALUES, key: bad} for bad in ("12,5", "abc", "1e3", "", True, None)]
        for key in ("papel_filtro_g", "papel_muestra_g"):  # text fields: a number is not a string
            cases += [{**P118_VALUES, key: 4.35}, {**P118_VALUES, key: ""}]
        for values in cases:
            with self.subTest(values=values):
                reply = await self.post(self.body(values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_200_identical_retry_creates_no_duplicate_and_409_for_different_content_machine_or_form(self):
        body = self.body()
        first = await self.post(body)
        self.assertEqual(first.status, 201)
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        again = await self.post(body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
        changed = await self.post({**body, "values": {**body["values"], "masa_humeda_g": "99.9"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual((await self.post(body, "MP3")).status, 409)  # same id, another machine

    async def test_roles_and_scope(self):
        body = self.body()
        self.assertEqual((await call("POST", "/api/quality/machines/MP1/captures", json_body=body)).status, 401)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):  # quality.capture belongs to CALIDAD only
            self.assertEqual((await self.post(body, who=who)).status, 403, who)
        reply = await self.post(body, who="CALIDAD_SIN_SECTOR")  # no BOBINAS grant: the machine is outside the scope
        self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        self.assertEqual((await self.post(body, "MP99")).status, 404)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_payload_stays_closed(self):
        for extra in ({"machine_code": "MP1"}, {"assignment_id": str(uuid4())}, {"bobbin_id": str(uuid4())}, {"operating_date": "2026-01-01"}, {"hora": "07:00"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.post({**self.body(), **extra})).status, 422, extra)

    async def test_concurrency_identical_posts_create_one_capture(self):
        body = self.body()
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), len(P118_VALUES))

    async def test_the_capture_is_audited_and_never_touches_bobbins_or_quality_release(self):
        before = (self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release"))
        self.assertEqual((await self.post(self.body())).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before[0])
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE actor_id = %s", (self.users["CALIDAD"][0].user_id,)), 0)
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release")), before[1:])

    async def test_the_bobbin_candidate_cannot_be_posted_through_the_machine_route(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        reply = await self.post(self.body(form_code=P121_CODE, values=dict(P121_VALUES)))
        self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))  # P1-21 belongs to the bobbin route: it is not in the machine policy
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)


class P118FormAvailabilityTests(MachineBase):
    install = staticmethod(lambda connection: install_p118(connection, machine_codes=("MP1",)))
    prefix = "vinto_devq2u"

    async def test_a_machine_without_the_form_link_is_not_available(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/quality/machine-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P118_CODE], "MP3": []})
        reply = await self.post(self.body(), "MP3")
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        self.assertEqual((await self.post(self.body(), "MP1")).status, 201)


class P118UnpublishedFormTests(MachineBase):
    install = staticmethod(lambda connection: install_p118(connection, publish=False))
    prefix = "vinto_devq2d"

    async def test_an_unpublished_form_is_neither_published_nor_available(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/quality/machine-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [], "MP3": []})
        reply = await self.post(self.body())
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


class P118ReadTests(MachineBase):
    async def test_get_by_id_and_the_history_is_filtered_by_machine_and_form(self):
        a = (await self.post(self.body(), "MP1")).json()["capture"]
        c = (await self.post(self.body(), "MP3")).json()["capture"]
        reply = await self.get(f"/api/quality/machine-captures/{a['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, P118_CODE, a["values"]))
        self.assertEqual([x["id"] for x in (await self.get(f"/api/quality/machines/MP1/captures?form_code={P118_CODE}")).json()], [a["id"]])
        self.assertEqual([x["id"] for x in (await self.get("/api/quality/machines/MP3/captures")).json()], [c["id"]])
        self.assertEqual(len((await self.get("/api/quality/machines/MP1/captures?limit=1")).json()), 1)
        self.assertEqual((await self.get("/api/quality/machines/MP1/captures?form_code=VINTO-P1-19")).status, 422)  # not enabled for machine-level controls
        self.assertEqual((await self.get(f"/api/quality/machines/MP1/captures?form_code={P121_CODE}")).status, 422)  # a bobbin-level candidate is not a machine-level control

    async def test_the_history_is_denied_or_hidden_outside_the_scope_and_the_role(self):
        capture = (await self.post(self.body())).json()["capture"]
        self.assertEqual((await self.get(f"/api/quality/machine-captures/{capture['id']}", "CALIDAD_SIN_SECTOR")).status, 404)
        for who in ("OPERACION", "JEFATURA", "SUPERVISION"):
            self.assertEqual((await self.get(f"/api/quality/machine-captures/{capture['id']}", who)).status, 403, who)
        self.assertEqual((await call("GET", f"/api/quality/machine-captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/quality/machine-captures/{uuid4()}")).status, 404)
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", SHIPPED_MACHINE_POLICY):  # the real policy: the control behaves as non-existent
            self.assertEqual((await self.get(f"/api/quality/machine-captures/{capture['id']}")).status, 404)

    async def test_machine_controls_do_not_leak_into_production_bobbin_or_inbox_reads(self):
        capture = (await self.post(self.body())).json()["capture"]
        self.assertEqual((await self.get(f"/api/quality/captures/{capture['id']}")).status, 404)  # the bobbin-bound view does not see it
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))).status, 404)  # nor the production read
        self.assertEqual((await self.get("/api/quality/bobbins")).json(), [])
        self.assertEqual((await self.get(f"/api/quality/bobbins/{uuid4()}/captures")).status, 404)


# ---------------------------------------------------------------- P1-21 · bobbin level


class BobbinBase(f3.BobbinApiCase):
    install = staticmethod(lambda connection: install_p121(connection))

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.install(cls.connection)
        password = "pw-" + secrets.token_urlsafe(18)
        cls.users["CALIDAD_SIN_SECTOR"] = (create_user(cls.connection, username="devq2b.sin_sector", display_name="Calidad Sin Sector", profile_code="CALIDAD", password=password, sectors=()), password)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        policy = patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", ENABLE_P121)  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    async def bobbin(self, machine="MP1"):
        _, assignment = await self.assignment(machine)
        reply = await self.post(self.payload(assignment))
        self.assertEqual(reply.status, 201, reply.text)
        return assignment, reply.json()["bobbin"]

    def body(self, bobbin, **changes):
        body = {"capture_id": str(uuid4()), "form_code": P121_CODE, "device_key": str(uuid4()), "values": {**P121_VALUES, "numero_de_bobina": bobbin["code"]}}
        body.update(changes)
        return body

    async def submit(self, bobbin_id, body, who="CALIDAD"):
        return await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie(who))

    async def read(self, path, who="CALIDAD"):
        return await call("GET", path, cookie=await self.cookie(who))

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_master.device", "vinto_txn.quality_release", "vinto_txn.bobbin")}

    def release(self, bobbin_id):
        return self.connection.execute("SELECT status, decided_by, decided_at, decision_reason, updated_at FROM vinto_txn.quality_release WHERE bobbin_id=%s", (bobbin_id,)).fetchone()

    def rows(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, d.value_type||':'||coalesce(d.value_text, d.value_decimal::text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


class P121ConfigurationTests(BobbinBase):
    async def test_the_shipped_bobbin_policy_is_empty_and_the_candidate_is_unreachable_without_the_test_policy(self):
        _, bobbin = await self.bobbin()
        self.assertEqual(SHIPPED_BOBBIN_POLICY, frozenset())
        self.assertEqual(_quality_service.BOBBIN_CANDIDATE_FORM_CODES, frozenset({P121_CODE, "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28"}))  # P1-24 / P1-25 (DEV-Q3) and P1-28 (DEV-CLOSE) added later
        created = await self.submit(bobbin["id"], self.body(bobbin))
        self.assertEqual(created.status, 201, created.text)
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", SHIPPED_BOBBIN_POLICY):  # the real policy
            before = self.counts()
            reply = await self.submit(bobbin["id"], self.body(bobbin))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
            self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={P121_CODE}")).status, 422)
            self.assertEqual((await self.read(f"/api/quality/captures/{created.json()['capture']['id']}")).status, 404)  # a capture of a non-enabled candidate behaves as non-existent
            self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures")).json(), [])
            self.assertEqual((await self.read("/api/quality/bobbin-forms")).json()["sectors"][0]["machines"][0]["forms"], [])
            self.assertEqual(self.counts(), before)

    async def test_the_backend_publishes_the_candidate_on_mp1_and_mp3_only_to_quality_users_in_scope(self):
        listed = (await self.read("/api/quality/bobbin-forms")).json()["sectors"]
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in listed for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P121_CODE], "MP3": [P121_CODE]})
        self.assertEqual((await self.read("/api/quality/bobbin-forms", "CALIDAD_SIN_SECTOR")).json()["sectors"], [])
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.read("/api/quality/bobbin-forms", who)).status, 403, who)
        self.assertEqual((await call("GET", "/api/quality/bobbin-forms")).status, 401)

    async def test_the_candidate_contract_is_exactly_the_manual_legacy_fields(self):
        self.assertEqual([f[0] for f in P121_FIELDS], ["numero_de_bobina", "posicion_de_perfil", "gramaje", "peso_seco", "observaciones"])
        stored = [tuple(r) for r in self.connection.execute(
            """SELECT fd.key, fd.label, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (P121_CODE,)).fetchall()]
        self.assertEqual(stored, [(k, label, t, r, "quality") for k, label, t, r, _ in P121_FIELDS])
        self.assertTrue(all(k not in AUTOMATIC + P121_CALCULATED for k, *_ in stored))


class P121WriteTests(BobbinBase):
    async def test_201_is_persisted_against_the_selected_bobbin_with_its_historic_context(self):
        for machine in ("MP1", "MP3"):
            assignment, bobbin = await self.bobbin(machine)
            before = self.release(bobbin["id"])
            reply = await self.submit(bobbin["id"], self.body(bobbin))
            self.assertEqual(reply.status, 201, (machine, reply.text))
            data = reply.json()
            self.assertEqual((data["created"], data["already_submitted"]), (True, False))
            capture = data["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (P121_CODE, "submitted", 1, machine))
            self.assertEqual(capture["bobbin"], {"id": bobbin["id"], "code": bobbin["code"]})
            self.assertEqual(capture["values"], {**P121_VALUES, "numero_de_bobina": bobbin["code"]})
            row = self.connection.execute("SELECT assignment_id, bobbin_id, created_by, operating_date FROM vinto_txn.capture WHERE id = %s", (capture["id"],)).fetchone()
            source = self.connection.execute("SELECT c.assignment_id, c.operating_date FROM vinto_txn.bobbin b JOIN vinto_txn.capture c ON c.id = b.source_capture_id WHERE b.id = %s", (bobbin["id"],)).fetchone()
            self.assertEqual((str(row[0]), str(row[1]), row[2]), (assignment["id"], bobbin["id"], self.users["CALIDAD"][0].user_id))
            self.assertEqual((row[0], row[3]), source)  # the context is the one of the F3 origin capture
            self.assertEqual(self.release(bobbin["id"]), before)  # quality_release is untouched: still pending, never released or rejected
            self.assertEqual(before[0], "pending")
            self.assertEqual(self.rows(capture["id"]), {"numero_de_bobina": f"text:{bobbin['code']}", "posicion_de_perfil": "text:posición ficticia", "gramaje": "decimal:85.5",
                                                        "peso_seco": "decimal:0.250", "observaciones": "textarea:dato ficticio DEV-Q2"})

    async def test_nothing_calculated_or_automatic_is_generated_or_stored(self):
        _, bobbin = await self.bobbin()
        capture = (await self.submit(bobbin["id"], self.body(bobbin))).json()["capture"]
        stored = self.rows(capture["id"])
        self.assertEqual(sorted(stored), sorted(P121_VALUES))
        for key in AUTOMATIC + P121_CALCULATED:
            self.assertNotIn(key, stored)
            self.assertNotIn(key, capture["values"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (capture["id"],)), len(P121_VALUES))

    async def test_automatic_calculated_or_invented_fields_sent_by_the_client_are_rejected(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        for key in AUTOMATIC + P121_CALCULATED + ("aprobado", "limite", "perfil"):
            with self.subTest(key=key):
                body = self.body(bobbin)
                body["values"][key] = "1"
                reply = await self.submit(bobbin["id"], body)
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.counts(), before)

    async def test_422_invalid_values_persist_nothing(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        base = self.body(bobbin)["values"]
        required = [f[0] for f in P121_FIELDS if f[3]]
        cases = [{k: v for k, v in base.items() if k != key} for key in required]
        cases += [{**base, "posicion_de_perfil": "   "}, {**base, "posicion_de_perfil": None}, {**base, "posicion_de_perfil": 7}]
        for key in ("gramaje", "peso_seco"):
            cases += [{**base, key: bad} for bad in ("85,5", "abc", "1e3", "", True, None)]
        for values in cases:
            with self.subTest(values=values):
                reply = await self.submit(bobbin["id"], self.body(bobbin, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.counts(), before)

    async def test_a_declared_bobbin_number_that_contradicts_the_selected_bobbin_is_rejected(self):
        _, a = await self.bobbin("MP1")
        _, b = await self.bobbin("MP3")
        before = self.counts()
        wrong = [str(int(a["code"]) + 1000), "999999", "", "abc"]
        if b["code"] != a["code"]:
            wrong.append(b["code"])  # the code of ANOTHER real bobbin
        for declared in wrong:
            with self.subTest(declared=declared):
                reply = await self.submit(a["id"], self.body(a, values={**P121_VALUES, "numero_de_bobina": declared}))
                self.assertEqual(reply.status, 422, (declared, reply.text))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (b["id"],)), 0)  # never associated with a different bobbin
        ok = await self.submit(a["id"], self.body(a))
        self.assertEqual(ok.status, 201)
        self.assertEqual(ok.json()["capture"]["bobbin"]["id"], a["id"])

    async def test_unknown_out_of_scope_and_legacy_bobbins_are_404_and_persist_nothing(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        for bobbin_id in (str(uuid4()), "not-a-uuid"):
            reply = await self.submit(bobbin_id, self.body(bobbin))
            self.assertEqual((reply.status, reply.json()["code"]), (404, "BOBBIN_NOT_FOUND"), bobbin_id)
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('LEGACY-Q2')")  # historic bobbin without a sequence number: not evaluable here
        legacy = self.scalar("SELECT id FROM vinto_txn.bobbin WHERE code='LEGACY-Q2'")
        self.assertEqual((await self.submit(legacy, self.body({"code": "LEGACY-Q2"}))).status, 404)
        self.assertEqual((await self.submit(bobbin["id"], self.body(bobbin), "CALIDAD_SIN_SECTOR")).status, 404)  # the bobbin is outside the user's sector grants
        self.assertEqual({k: v for k, v in self.counts().items() if k != "vinto_txn.bobbin"}, {k: v for k, v in before.items() if k != "vinto_txn.bobbin"})

    async def test_the_historic_context_survives_a_finished_assignment(self):
        assignment, bobbin = await self.bobbin()
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s", (assignment["id"],))
        reply = await self.submit(bobbin["id"], self.body(bobbin))
        self.assertEqual(reply.status, 201, reply.text)
        stored = self.connection.execute("SELECT assignment_id FROM vinto_txn.capture WHERE id = %s", (reply.json()["capture"]["id"],)).fetchone()[0]
        self.assertEqual(str(stored), assignment["id"])

    async def test_200_identical_retry_creates_no_duplicate_and_409_for_different_content_or_bobbin(self):
        _, a = await self.bobbin("MP1")
        _, b = await self.bobbin("MP1")
        body = self.body(a)
        first = await self.submit(a["id"], body)
        self.assertEqual(first.status, 201)
        before = (self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        again = await self.submit(a["id"], body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        self.assertEqual((self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
        changed = await self.submit(a["id"], {**body, "values": {**body["values"], "gramaje": "99.9"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        other = await self.submit(b["id"], {**body, "values": {**body["values"], "numero_de_bobina": b["code"]}})  # same capture_id against another bobbin
        self.assertEqual((other.status, other.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (b["id"],)), 0)

    async def test_roles_and_scope(self):
        _, bobbin = await self.bobbin()
        body = self.body(bobbin)
        self.assertEqual((await call("POST", f"/api/quality/bobbins/{bobbin['id']}/captures", json_body=body)).status, 401)
        before = self.counts()
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):  # quality.capture belongs to CALIDAD only
            self.assertEqual((await self.submit(bobbin["id"], body, who)).status, 403, who)
        self.assertEqual(self.counts(), before)

    async def test_the_payload_stays_closed(self):
        _, bobbin = await self.bobbin()
        for extra in ({"bobbin_id": bobbin["id"]}, {"machine_code": "MP1"}, {"assignment_id": str(uuid4())}, {"operating_date": "2026-01-01"}, {"hora": "07:00"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.submit(bobbin["id"], {**self.body(bobbin), **extra})).status, 422, extra)

    async def test_concurrency_identical_posts_create_one_capture(self):
        _, bobbin = await self.bobbin()
        body = self.body(bobbin)
        replies = await asyncio.gather(*[self.submit(bobbin["id"], body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), len(P121_VALUES))

    async def test_the_capture_is_audited_and_never_modifies_the_bobbin_or_quality_release(self):
        _, bobbin = await self.bobbin()
        bobbin_row = self.connection.execute("SELECT * FROM vinto_txn.bobbin WHERE id = %s", (bobbin["id"],)).fetchone()
        release, audits = self.release(bobbin["id"]), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        self.assertEqual((await self.submit(bobbin["id"], self.body(bobbin))).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audits)
        self.assertEqual(self.connection.execute("SELECT * FROM vinto_txn.bobbin WHERE id = %s", (bobbin["id"],)).fetchone(), bobbin_row)
        self.assertEqual(self.release(bobbin["id"]), release)


class P121ReadTests(BobbinBase):
    async def test_get_by_id_and_the_bobbin_history_is_filtered_by_bobbin_and_form_without_mixing(self):
        _, a = await self.bobbin("MP1")
        _, b = await self.bobbin("MP1")
        ca = (await self.submit(a["id"], self.body(a))).json()["capture"]
        cb = (await self.submit(b["id"], self.body(b))).json()["capture"]
        reply = await self.read(f"/api/quality/captures/{ca['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["bobbin"], reply.json()["values"]), (200, P121_CODE, {"id": a["id"], "code": a["code"]}, ca["values"]))
        self.assertEqual([x["id"] for x in (await self.read(f"/api/quality/bobbins/{a['id']}/captures")).json()], [ca["id"]])
        self.assertEqual([x["id"] for x in (await self.read(f"/api/quality/bobbins/{b['id']}/captures?form_code={P121_CODE}")).json()], [cb["id"]])
        self.assertEqual((await self.read(f"/api/quality/bobbins/{b['id']}/captures?form_code=VINTO-P1-19")).json(), [])  # a different form: filtered out, not an error
        self.assertEqual((await self.read(f"/api/quality/bobbins/{b['id']}/captures?form_code=")).status, 422)

    async def test_the_history_is_denied_or_hidden_outside_the_scope_and_the_role(self):
        _, bobbin = await self.bobbin()
        capture = (await self.submit(bobbin["id"], self.body(bobbin))).json()["capture"]
        self.assertEqual((await self.read(f"/api/quality/captures/{capture['id']}", "CALIDAD_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures", "CALIDAD_SIN_SECTOR")).status, 404)
        for who in ("OPERACION", "JEFATURA", "SUPERVISION"):
            self.assertEqual((await self.read(f"/api/quality/captures/{capture['id']}", who)).status, 403, who)
        self.assertEqual((await call("GET", f"/api/quality/captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.read(f"/api/quality/captures/{uuid4()}")).status, 404)
        self.assertEqual((await self.read(f"/api/quality/bobbins/{uuid4()}/captures")).status, 404)

    async def test_bobbin_candidates_do_not_mix_with_machine_level_reads_or_production(self):
        _, bobbin = await self.bobbin()
        capture = (await self.submit(bobbin["id"], self.body(bobbin))).json()["capture"]
        self.assertEqual((await self.read(f"/api/quality/machine-captures/{capture['id']}")).status, 404)  # the machine-level view does not see it
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset({P118_CODE})):
            self.assertEqual((await self.read(f"/api/quality/machine-captures/{capture['id']}")).status, 404)
            self.assertEqual((await self.read("/api/quality/machines/MP1/captures")).json(), [])
            reply = await call("POST", "/api/quality/machines/MP1/captures", json_body={"capture_id": str(uuid4()), "form_code": P121_CODE, "device_key": str(uuid4()), "values": dict(P121_VALUES)},
                               cookie=await self.cookie("CALIDAD"))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))).status, 404)  # nor the production read


class P121FormAvailabilityTests(BobbinBase):
    install = staticmethod(lambda connection: install_p121(connection, machine_codes=("MP1",)))

    async def test_a_bobbin_whose_machine_has_no_form_link_gets_409_and_the_other_works(self):
        _, mp1 = await self.bobbin("MP1")
        _, mp3 = await self.bobbin("MP3")
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P121_CODE], "MP3": []})
        reply = await self.submit(mp3["id"], self.body(mp3))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        self.assertEqual((await self.submit(mp1["id"], self.body(mp1))).status, 201)


class P121UnpublishedFormTests(BobbinBase):
    install = staticmethod(lambda connection: install_p121(connection, publish=False))

    async def test_an_unpublished_candidate_is_neither_published_nor_available(self):
        _, bobbin = await self.bobbin()
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [], "MP3": []})
        reply = await self.submit(bobbin["id"], self.body(bobbin))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


if __name__ == "__main__":
    unittest.main()
