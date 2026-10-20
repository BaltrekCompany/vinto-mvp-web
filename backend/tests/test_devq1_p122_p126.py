"""DEV-Q1: the CANDIDATE VINTO-P1-22 (Grado de refinación Schopper) and VINTO-P1-26 (Medición de secos) run through the machine-level Quality capture route
(/api/quality/machines/{machine}/captures) without a bobbin, an assignment or a work order.

Installed in an ephemeral *_test database (tests/devq1_fixtures.py) and enabled per test with patch.object on machine_capture_service.MACHINE_QUALITY_FORM_CODES; the shipped policy (empty) is asserted
unchanged, together with the production policy (only VINTO-P1-06) and the operational sectors. NOT a homologation: no formula, range, limit, catalog or approval criterion exists; porcentaje_de_secos is
never calculated and hora is the REGISTRATION time (clock_timestamp), not the real test time.
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
from app.quality import machine_capture_service as _machine_service

try:
    from devq1_fixtures import P122_CODE, P122_FIELDS, P122_VALUES, P126_CODE, P126_FIELDS, P126_VALUES, install_p122, install_p126
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.devq1_fixtures import P122_CODE, P122_FIELDS, P122_VALUES, P126_CODE, P126_FIELDS, P126_VALUES, install_p122, install_p126
    from tests.test_assignments_api import call

SHIPPED_MACHINE_POLICY = _machine_service.MACHINE_QUALITY_FORM_CODES  # captured at import, before any patch
SHIPPED_PRODUCTION_POLICY = _capture_service.CENTRAL_FORM_CODES
SHIPPED_SECTORS = _sectors.operational_sector_codes()
FORMS = {P122_CODE: (P122_VALUES, P122_FIELDS), P126_CODE: (P126_VALUES, P126_FIELDS)}
STATE = {}
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz -> DIA, operating date 2026-10-06
NIGHT = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)  # 23:00 La Paz -> NOCHE, 2026-10-06
AFTER_MIDNIGHT = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 02:00 La Paz on 10-07 -> NOCHE, operating date 2026-10-06
AUTOMATIC = ("fecha", "hora", "maquina", "responsable")


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devq1_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class Base(unittest.IsolatedAsyncioTestCase):
    install = staticmethod(lambda connection: (install_p122(connection), install_p126(connection)))
    prefix = "vinto_devq1"

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
            cls.users[name] = (create_user(cls.connection, username=f"devq1.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        policy = patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset({P122_CODE, P126_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)
        clock = patch.object(_capture_service, "_now", return_value=DAY)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    def body(self, code, **changes):
        body = {"capture_id": str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": dict(FORMS[code][0])}
        body.update(changes)
        return body

    async def post(self, body, machine="MP1", who="CALIDAD", at=DAY):
        self.clock.return_value = at  # one stable patch per test: nested per-request patches of concurrent requests would not unwind in order and would leak into later modules
        return await call("POST", f"/api/quality/machines/{machine}/captures", json_body=body, cookie=await self.cookie(who))

    async def get(self, path, who="CALIDAD"):
        return await call("GET", path, cookie=await self.cookie(who))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def rows(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, d.value_type||':'||coalesce(d.value_text, d.value_decimal::text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


class ConfigurationAndAvailabilityTests(Base):
    async def test_the_shipped_configuration_is_unchanged_and_the_forms_are_unreachable_without_the_test_policy(self):
        # CLOUD-DEP G.12-C4: MACHINE_QUALITY_FORM_CODES/CENTRAL_FORM_CODES reales ya incluyen los
        # candidatos habilitados para QA; lo que importa es que P122_CODE/P126_CODE (fixtures sintéticas) NO estén.
        self.assertEqual(SHIPPED_MACHINE_POLICY, frozenset({"VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27"}))
        # CLOUD-DEP G.12-C4-COMPLETE: SHIPPED_PRODUCTION_POLICY también incluye P1-07/10/30 (Rebobinado),
        # pero esos 3 solo están vinculados a BELOIT/OVER/COPASA/PERICHUN -- MP1/MP3 nunca los ofrecen.
        self.assertEqual(SHIPPED_PRODUCTION_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-06", "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30"}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS", "REBOBINADO"))
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", SHIPPED_MACHINE_POLICY):
            for code in (P122_CODE, P126_CODE):
                reply = await self.post(self.body(code))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)
                self.assertEqual((await self.get(f"/api/quality/machines/MP1/captures?form_code={code}")).status, 422, code)
            listed = (await self.get("/api/quality/machine-forms")).json()["sectors"]
            offered = [[f["code"] for f in m["forms"]] for s in listed for m in s["machines"]]
            self.assertEqual(offered, [sorted(SHIPPED_MACHINE_POLICY), sorted(SHIPPED_MACHINE_POLICY)])
            for codes in offered:
                self.assertNotIn(P122_CODE, codes)
                self.assertNotIn(P126_CODE, codes)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    async def test_the_backend_publishes_both_forms_on_mp1_and_mp3_only_to_quality_users_in_scope(self):
        listed = (await self.get("/api/quality/machine-forms")).json()["sectors"]
        self.assertEqual([s["code"] for s in listed], ["BOBINAS"])
        machines = {m["code"]: m for m in listed[0]["machines"]}
        for machine in ("MP1", "MP3"):
            self.assertEqual([f["code"] for f in machines[machine]["forms"]], [P122_CODE, P126_CODE])
        self.assertEqual({f["code"]: f["name"] for f in machines["MP1"]["forms"]}[P122_CODE], "Grado de refinación Schopper (candidato DEV-Q1)")
        self.assertEqual((await self.get("/api/quality/machine-forms", "CALIDAD_SIN_SECTOR")).json()["sectors"], [])
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.get("/api/quality/machine-forms", who)).status, 403, who)
        self.assertEqual((await call("GET", "/api/quality/machine-forms")).status, 401)

    async def test_the_production_availability_is_not_affected(self):
        reply = await call("GET", "/api/production/machines", cookie=await self.cookie("OPERACION"))
        offered = {m["code"]: sorted(f["code"] for f in m["forms"]) for s in reply.json()["sectors"] for m in s["machines"]}
        bobinas_forms = sorted(SHIPPED_PRODUCTION_POLICY & frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-06", "VINTO-P1-31"}))
        self.assertEqual({k: v for k, v in offered.items() if k in ("MP1", "MP3")}, {"MP1": bobinas_forms, "MP3": bobinas_forms})
        for codes in offered.values():
            self.assertNotIn(P122_CODE, codes)
            self.assertNotIn(P126_CODE, codes)

    async def test_the_candidate_contracts_are_exactly_the_manual_legacy_fields(self):
        self.assertEqual([f[0] for f in P122_FIELDS], ["numero_de_cuba", "masa_humeda", "volumen_desplazado", "grado_de_refinacion_sr", "amperaje", "observacion"])
        self.assertEqual([f[0] for f in P126_FIELDS], ["punto_de_muestreo", "masa_humeda", "masa_seca", "observaciones"])
        for code, fields in ((P122_CODE, P122_FIELDS), (P126_CODE, P126_FIELDS)):
            stored = [(r[0], r[1], r[2], r[3]) for r in self.connection.execute(
                """SELECT fd.key, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
                   JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (code,)).fetchall()]
            self.assertEqual(stored, [(k, t, r, "quality") for k, _, t, r, _ in fields])
            self.assertTrue(all(k not in AUTOMATIC + ("porcentaje_de_secos",) for k, *_ in stored))


class WriteTests(Base):
    async def test_201_is_persisted_with_the_server_context_without_bobbin_assignment_or_work_order(self):
        for code in (P122_CODE, P126_CODE):
            for machine in ("MP1", "MP3"):
                reply = await self.post(self.body(code), machine)
                self.assertEqual(reply.status, 201, (code, machine, reply.text))
                data = reply.json()
                self.assertEqual((data["created"], data["already_submitted"]), (True, False))
                capture = data["capture"]
                self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (code, "submitted", 1, machine))
                self.assertEqual((capture["shift"]["code"], capture["operating_date"]), ("DIA", "2026-10-06"))
                self.assertEqual(capture["recorded_by"], {"id": str(self.users["CALIDAD"][0].user_id), "display_name": "Calidad"})
                self.assertEqual(capture["values"], FORMS[code][0])
                self.assertEqual(capture["captured_at"].replace("Z", "+00:00"), DAY.isoformat())  # the REGISTRATION instant, not a test time
                row = self.connection.execute("SELECT assignment_id, bobbin_id, created_by, status, revision FROM vinto_txn.capture WHERE id = %s", (capture["id"],)).fetchone()
                self.assertEqual(row, (None, None, self.users["CALIDAD"][0].user_id, "submitted", 1))
                kinds = {k: v for k, _, v, *_ in FORMS[code][1]}
                self.assertEqual(self.rows(capture["id"]), {k: f"{kinds[k]}:{v}" for k, v in FORMS[code][0].items()})
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.work_order"), self.scalar("SELECT count(*) FROM vinto_txn.assignment"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin")), (0, 0, 0))

    async def test_the_operating_date_follows_the_night_shift_at_registration_time(self):
        for at, shift, date in ((DAY, "DIA", "2026-10-06"), (NIGHT, "NOCHE", "2026-10-06"), (AFTER_MIDNIGHT, "NOCHE", "2026-10-06")):
            reply = await self.post(self.body(P122_CODE), at=at)
            self.assertEqual((reply.status, reply.json()["capture"]["shift"]["code"], reply.json()["capture"]["operating_date"]), (201, shift, date), at.isoformat())

    async def test_no_percentage_total_hour_or_automatic_value_is_generated_or_stored(self):
        capture = (await self.post(self.body(P126_CODE))).json()["capture"]
        stored = self.rows(capture["id"])
        self.assertEqual(sorted(stored), sorted(P126_VALUES))
        self.assertEqual(stored["masa_seca"], "decimal:3.25")  # typed exactly: nothing derived from the two masses
        for key in AUTOMATIC + ("porcentaje_de_secos",):
            self.assertNotIn(key, stored)
            self.assertNotIn(key, capture["values"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (capture["id"],)), len(P126_VALUES))

    async def test_automatic_calculated_or_invented_fields_sent_by_the_client_are_rejected(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for code, extra in ((P122_CODE, AUTOMATIC + ("aprobado", "limite")), (P126_CODE, AUTOMATIC + ("porcentaje_de_secos", "aprobado", "limite"))):
            for key in extra:
                with self.subTest(code=code, key=key):
                    reply = await self.post(self.body(code, values={**FORMS[code][0], key: "1"}))
                    self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_optional_observations_may_be_omitted(self):
        for code, key in ((P122_CODE, "observacion"), (P126_CODE, "observaciones")):
            reply = await self.post(self.body(code, values={k: v for k, v in FORMS[code][0].items() if k != key}))
            self.assertEqual(reply.status, 201, (code, reply.text))
            self.assertNotIn(key, reply.json()["capture"]["values"])

    async def test_422_invalid_values_persist_nothing(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        cases = []
        for code, (values, fields) in FORMS.items():
            required = [f[0] for f in fields if f[3]]
            cases += [(code, {k: v for k, v in values.items() if k != key}) for key in required]
            cases += [(code, {**values, required[0]: "   "}), (code, {**values, required[0]: None}), (code, {**values, required[0]: 7})]
            for key in [f[0] for f in fields if f[2] == "decimal"]:
                cases += [(code, {**values, key: bad}) for bad in ("12,5", "abc", "1e3", "", True, None)]
        for code, values in cases:
            with self.subTest(code=code, values=values):
                reply = await self.post(self.body(code, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_200_identical_retry_creates_no_duplicate_and_409_for_different_content_or_actor(self):
        for code in (P122_CODE, P126_CODE):
            body = self.body(code)
            first = await self.post(body)
            self.assertEqual(first.status, 201)
            before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
            again = await self.post(body)
            self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
            self.assertEqual(again.json()["capture"], first.json()["capture"])
            self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
            changed = await self.post({**body, "values": {**body["values"], "masa_humeda": "99.9"}})
            self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
            self.assertEqual((await self.post(body, "MP3")).status, 409)  # same id, another machine
            other = P126_CODE if code == P122_CODE else P122_CODE
            self.assertEqual((await self.post({**self.body(other), "capture_id": body["capture_id"]})).status, 409)  # same id, another form

    async def test_roles_and_scope(self):
        body = self.body(P122_CODE)
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
            self.assertEqual((await self.post({**self.body(P122_CODE), **extra})).status, 422, extra)

    async def test_concurrency_identical_posts_create_one_capture(self):
        body = self.body(P126_CODE)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), len(P126_VALUES))

    async def test_the_capture_is_audited_and_never_touches_bobbins_or_quality_release(self):
        before = (self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release"))
        for code in (P122_CODE, P126_CODE):
            self.assertEqual((await self.post(self.body(code))).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before[0])
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE actor_id = %s", (self.users["CALIDAD"][0].user_id,)), 0)
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release")), before[1:])


class FormAvailabilityTests(Base):
    install = staticmethod(lambda connection: (install_p122(connection), install_p126(connection, machine_codes=("MP1",))))
    prefix = "vinto_devq1u"

    async def test_a_machine_without_the_form_link_is_not_available(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/quality/machine-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P122_CODE, P126_CODE], "MP3": [P122_CODE]})
        reply = await self.post(self.body(P126_CODE), "MP3")
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        self.assertEqual((await self.post(self.body(P126_CODE), "MP1")).status, 201)


class UnpublishedFormTests(Base):
    install = staticmethod(lambda connection: (install_p122(connection, publish=False), install_p126(connection)))
    prefix = "vinto_devq1d"

    async def test_an_unpublished_form_is_neither_published_nor_available(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/quality/machine-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines["MP1"], [P126_CODE])
        reply = await self.post(self.body(P122_CODE))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


class ReadTests(Base):
    async def test_get_by_id_and_the_history_is_filtered_by_machine_and_form_without_mixing(self):
        a = (await self.post(self.body(P122_CODE), "MP1")).json()["capture"]
        b = (await self.post(self.body(P126_CODE), "MP1")).json()["capture"]
        c = (await self.post(self.body(P122_CODE), "MP3")).json()["capture"]
        reply = await self.get(f"/api/quality/machine-captures/{a['id']}")
        self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, P122_CODE, a["values"]))
        listed = (await self.get("/api/quality/machines/MP1/captures")).json()
        self.assertEqual({x["id"] for x in listed}, {a["id"], b["id"]})
        self.assertEqual([x["id"] for x in (await self.get(f"/api/quality/machines/MP1/captures?form_code={P122_CODE}")).json()], [a["id"]])
        self.assertEqual([x["id"] for x in (await self.get(f"/api/quality/machines/MP3/captures?form_code={P122_CODE}")).json()], [c["id"]])
        self.assertEqual((await self.get(f"/api/quality/machines/MP3/captures?form_code={P126_CODE}")).json(), [])
        self.assertEqual(len((await self.get("/api/quality/machines/MP1/captures?limit=1")).json()), 1)
        self.assertEqual((await self.get("/api/quality/machines/MP1/captures?limit=0")).status, 422)
        self.assertEqual((await self.get("/api/quality/machines/MP1/captures?form_code=VINTO-P1-19")).status, 422)  # not enabled for machine-level controls

    async def test_the_history_is_denied_or_hidden_outside_the_scope_and_the_role(self):
        capture = (await self.post(self.body(P122_CODE))).json()["capture"]
        self.assertEqual((await self.get(f"/api/quality/machine-captures/{capture['id']}", "CALIDAD_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.get("/api/quality/machines/MP1/captures", "CALIDAD_SIN_SECTOR")).status, 422)
        for who in ("OPERACION", "JEFATURA", "SUPERVISION"):
            self.assertEqual((await self.get(f"/api/quality/machine-captures/{capture['id']}", who)).status, 403, who)
        self.assertEqual((await call("GET", f"/api/quality/machine-captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/quality/machine-captures/{uuid4()}")).status, 404)
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", SHIPPED_MACHINE_POLICY):  # the real policy: the control behaves as non-existent
            self.assertEqual((await self.get(f"/api/quality/machine-captures/{capture['id']}")).status, 404)

    async def test_machine_controls_do_not_leak_into_production_bobbin_or_inbox_reads(self):
        capture = (await self.post(self.body(P122_CODE))).json()["capture"]
        self.assertEqual((await self.get(f"/api/quality/captures/{capture['id']}")).status, 404)  # the bobbin-bound view does not see it
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))).status, 404)  # nor the production read
        self.assertEqual((await self.get("/api/quality/bobbins")).json(), [])
        self.assertEqual((await self.get(f"/api/quality/bobbins/{uuid4()}/captures")).status, 404)


if __name__ == "__main__":
    unittest.main()
