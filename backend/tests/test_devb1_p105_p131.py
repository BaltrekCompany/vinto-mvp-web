"""DEV-B1: the CANDIDATE VINTO-P1-05 (Registro de tubetes) and VINTO-P1-31 (Consumo de químicos) run through the existing central production engine for Bobinas MP1 / MP3.

Everything is installed in an ephemeral *_test database from the migrated reference template (tests/devb1_fixtures.py). The forms are enabled per test with patch.object on
capture_service.CENTRAL_FORM_CODES; the shipped policy (only VINTO-P1-06) and the shipped operational sectors (only BOBINAS) are asserted unchanged. Nothing touches vinto or backend/seed_data.
This is NOT a homologation: the contracts are the legacy manual fields as a technical starting point; catalogs, formulas, units, ranges and inventory are pending VINTO decisions.
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
    from devb1_fixtures import P105_CODE, P105_FIELDS, P105_VALUES, P131_CODE, P131_FIELDS, P131_VALUES, install_p105, install_p131
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.devb1_fixtures import P105_CODE, P105_FIELDS, P105_VALUES, P131_CODE, P131_FIELDS, P131_VALUES, install_p105, install_p131
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any patch
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
BUNDLE = load_bundle()
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in ("MP1", "MP3")}
STATE = {}
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz -> shift DIA, operating date 2026-10-06
NIGHT = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)  # 23:00 La Paz -> shift NOCHE, operating date 2026-10-06
NEXT_DAY = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)  # the next day: the DIA assignment of 10-06 is stale
FORMS = {P105_CODE: (P105_VALUES, P105_FIELDS), P131_CODE: (P131_VALUES, P131_FIELDS)}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devb1_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE[machine], "quantity": 10, "due_date": "2026-11-01"}]}


class Base(unittest.IsolatedAsyncioTestCase):
    install = staticmethod(lambda connection: (install_p105(connection), install_p131(connection)))
    prefix = "vinto_devb1"

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
            cls.users[name] = (create_user(cls.connection, username=f"devb1.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P105_CODE, P131_CODE}))  # TEST-ONLY policy
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

    def payload(self, assignment, code, **changes):
        body = {"capture_id": str(uuid4()), "form_code": code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(FORMS[code][0])}
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
    async def test_the_shipped_configuration_is_unchanged_and_the_forms_are_unreachable_without_the_test_policy(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({F6}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))
        _, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            for code in (P105_CODE, P131_CODE):
                reply = await self.post(self.payload(assignment, code))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)
                self.assertEqual((await self.get(f"/api/captures?form_code={code}")).status, 422, code)
            machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
            self.assertEqual(machines, {"MP1": [F6], "MP3": [F6]})  # the real policy publishes only F6
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    async def test_the_backend_publishes_both_forms_on_mp1_and_mp3_only_with_the_test_policy(self):
        sectors = (await self.get("/api/production/machines")).json()["sectors"]
        self.assertEqual([s["code"] for s in sectors], ["BOBINAS"])
        machines = {m["code"]: m for m in sectors[0]["machines"]}
        for machine in ("MP1", "MP3"):
            self.assertEqual([f["code"] for f in machines[machine]["forms"]], [P105_CODE, F6, P131_CODE])  # ordered by form code
        names = {f["code"]: f["name"] for f in machines["MP1"]["forms"]}
        self.assertEqual(names[P105_CODE], "Registro de tubetes (candidato DEV-B1)")
        self.assertEqual(names[P131_CODE], "Consumo de químicos (candidato DEV-B1)")

    async def test_a_user_without_sector_grant_sees_nothing_and_cannot_capture(self):
        _, assignment = await self.assignment()
        self.assertEqual((await self.get("/api/production/machines", "OPERACION_SIN_SECTOR")).json()["sectors"], [])
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for code in (P105_CODE, P131_CODE):
            self.assertEqual((await self.post(self.payload(assignment, code), "OPERACION_SIN_SECTOR")).status, 404, code)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_candidate_contracts_are_exactly_the_manual_legacy_fields(self):
        # P1-05: 10 manual (9 required + observaciones); P1-31: 9 manual (8 required + observaciones). The automatic legacy fields are NOT part of the contract.
        self.assertEqual(len(P105_FIELDS), 10)
        self.assertEqual(len(P131_FIELDS), 9)
        for code, expected in ((P105_CODE, [f[0] for f in P105_FIELDS]), (P131_CODE, [f[0] for f in P131_FIELDS])):
            stored = [r[0] for r in self.connection.execute(
                """SELECT fd.key FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id
                   WHERE f.code = %s ORDER BY fd.display_order""", (code,)).fetchall()]
            self.assertEqual(stored, expected)
            self.assertTrue(all(k not in stored for k in ("fecha", "turno", "maquina", "responsable", "responsable_mp1", "responsable_mp3")))


class WriteTests(Base):
    async def test_201_p105_is_persisted_with_the_server_context_on_mp1_and_mp3(self):
        for machine in ("MP1", "MP3"):
            order, assignment = await self.assignment(machine)
            reply = await self.post(self.payload(assignment, P105_CODE))
            self.assertEqual(reply.status, 201, reply.text)
            data = reply.json()
            self.assertEqual((data["created"], data["already_submitted"]), (True, False))
            capture = data["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"]), (P105_CODE, "submitted", 1))
            self.assertEqual((capture["machine"]["code"], capture["assignment"]["id"], capture["work_order"]["id"]), (machine, assignment["id"], order["id"]))
            self.assertEqual((capture["shift"]["code"], capture["operating_date"]), ("DIA", "2026-10-06"))
            self.assertEqual((capture["line"]["line_code"], capture["line"]["pv_reference"], capture["line"]["article"]["code"]), ("L1", "PV-1", ARTICLE[machine]))
            self.assertEqual(capture["values"], P105_VALUES)  # every value exactly as typed (text is not interpreted)
            self.assertEqual(self.rows(capture["id"]), {k: (f"textarea:{v}" if k == "observaciones" else f"text:{v}") for k, v in P105_VALUES.items()})
            self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.users["OPERACION"][0].user_id)

    async def test_201_p131_keeps_the_typed_flow_rates_and_never_calculates_a_consumption(self):
        for machine in ("MP1", "MP3"):
            _, assignment = await self.assignment(machine)
            reply = await self.post(self.payload(assignment, P131_CODE))
            self.assertEqual(reply.status, 201, reply.text)
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["code"], capture["machine"]["code"]), (P131_CODE, machine))
            self.assertEqual(capture["values"], {**P131_VALUES, "caudal_mp1_ml_min": "125.5", "caudal_mp3_ml_min": "98"})
            self.assertEqual(self.rows(capture["id"])["caudal_mp1_ml_min"], "decimal:125.5")  # flow rates are decimals
            self.assertEqual(self.rows(capture["id"])["consumo_total_kg"], "text:no es la suma")  # consumptions are free text: no sum, no conversion
            self.assertEqual(self.rows(capture["id"])["consumo_dia_mp1_kg"], "text:15,5 (texto)")

    async def test_optional_observaciones_may_be_omitted(self):
        _, assignment = await self.assignment()
        for code in (P105_CODE, P131_CODE):
            values = {k: v for k, v in FORMS[code][0].items() if k != "observaciones"}
            reply = await self.post(self.payload(assignment, code, values=values))
            self.assertEqual(reply.status, 201, (code, reply.text))
            self.assertNotIn("observaciones", reply.json()["capture"]["values"])

    async def test_automatic_or_invented_fields_are_rejected(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for code, invented in ((P105_CODE, ("fecha", "turno", "maquina", "responsable", "inventario", "total")), (P131_CODE, ("fecha", "responsable_mp1", "responsable_mp3", "consumo_calculado", "densidad"))):
            for key in invented:
                with self.subTest(code=code, key=key):
                    reply = await self.post(self.payload(assignment, code, values={**FORMS[code][0], key: "x"}))
                    self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_422_invalid_values_persist_nothing(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        cases = []
        for code, values in ((P105_CODE, P105_VALUES), (P131_CODE, P131_VALUES)):
            required = [f[0] for f in FORMS[code][1] if f[3]]
            cases += [(code, {k: v for k, v in values.items() if k != key}) for key in required]  # each required field missing
            cases += [(code, {**values, required[0]: "   "}), (code, {**values, required[0]: None}), (code, {**values, required[0]: 7})]
        cases += [(P131_CODE, {**P131_VALUES, "caudal_mp1_ml_min": bad}) for bad in ("12,5", "abc", "1e3", "", True)]
        cases += [(P131_CODE, {**P131_VALUES, "caudal_mp3_ml_min": bad}) for bad in ("abc", None)]
        for code, values in cases:
            with self.subTest(code=code, values=values):
                reply = await self.post(self.payload(assignment, code, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_200_identical_retry_creates_no_duplicate_and_409_for_different_content(self):
        _, assignment = await self.assignment()
        for code in (P105_CODE, P131_CODE):
            body = self.payload(assignment, code)
            first = await self.post(body)
            self.assertEqual(first.status, 201)
            before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
            again = await self.post(body)
            self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
            self.assertEqual(again.json()["capture"], first.json()["capture"])
            self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
            key = "cantidad_utilizada" if code == P105_CODE else "consumo_total_kg"
            changed = await self.post({**body, "values": {**body["values"], key: "otro"}})
            self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
            self.assertEqual(self.rows(body["capture_id"])[key], f"text:{FORMS[code][0][key]}")
            other = P131_CODE if code == P105_CODE else P105_CODE  # the same capture_id cannot be reused for another form
            self.assertEqual((await self.post({**self.payload(assignment, other), "capture_id": body["capture_id"]})).status, 409)

    async def test_roles_only_operacion_captures(self):
        _, assignment = await self.assignment()
        self.assertEqual((await call("POST", "/api/captures", json_body=self.payload(assignment, P105_CODE))).status, 401)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            for code in (P105_CODE, P131_CODE):
                self.assertEqual((await self.post(self.payload(assignment, code), who)).status, 403, (who, code))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_a_stale_or_finished_assignment_is_rejected_and_nothing_is_stored(self):
        _, assignment = await self.assignment(at=DAY)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        reply = await self.post(self.payload(assignment, P105_CODE), at=NEXT_DAY)
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_STALE"))
        night = await self.post(self.payload(assignment, P131_CODE), at=NIGHT)
        self.assertEqual((night.status, night.json()["code"]), (409, "ASSIGNMENT_STALE"))
        await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=await self.cookie("SUPERVISION"))
        reply = await self.post(self.payload(assignment, P105_CODE))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))
        self.assertEqual((await self.post(self.payload(assignment, P105_CODE, assignment_id=str(uuid4())))).status, 404)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_the_payload_stays_closed(self):
        _, assignment = await self.assignment()
        for extra in ({"machine_code": "MP1"}, {"operating_date": "2026-01-01"}, {"shift_code": "NOCHE"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.post({**self.payload(assignment, P105_CODE), **extra})).status, 422, extra)

    async def test_concurrency_identical_posts_create_one_capture(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment, P131_CODE)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), 9)

    async def test_the_capture_is_audited_with_the_actor_and_no_bobbin_or_quality_row_is_created(self):
        _, assignment = await self.assignment()
        before = (self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release"))
        for code in (P105_CODE, P131_CODE):
            self.assertEqual((await self.post(self.payload(assignment, code))).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before[0])
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE actor_id = %s", (self.users["OPERACION"][0].user_id,)), 0)
        # P1-05 declares a bobbin number as text: it creates no bobbin, no genealogy and no inventory; P1-31 creates no consumption record
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), self.scalar("SELECT count(*) FROM vinto_txn.quality_release")), before[1:])


class ReadTests(Base):
    async def seed(self):
        _, assignment = await self.assignment()
        return assignment, {code: (await self.post(self.payload(assignment, code))).json()["capture"] for code in (P105_CODE, P131_CODE)}

    async def test_get_by_id_and_the_history_is_filtered_by_form_without_mixing(self):
        _, captures = await self.seed()
        for code, capture in captures.items():
            reply = await self.get(f"/api/captures/{capture['id']}")
            self.assertEqual((reply.status, reply.json()["form"]["code"], reply.json()["values"]), (200, code, capture["values"]))
            listed = (await self.get(f"/api/captures?form_code={code}")).json()
            self.assertIn(capture["id"], [c["id"] for c in listed])
            self.assertEqual({c["form"]["code"] for c in listed}, {code})
            self.assertEqual({c["id"] for c in listed} & {c["id"] for c in captures.values() if c["id"] != capture["id"]}, set())
            self.assertEqual((await self.get(f"/api/captures?form_code={code}&machine_code=MP1")).json()[0]["id"], capture["id"])
            self.assertEqual((await self.get(f"/api/captures?form_code={code}&machine_code=MP3")).json(), [])
        self.assertNotIn(captures[P105_CODE]["id"], [c["id"] for c in (await self.get("/api/captures")).json()])  # historic default: F6 only

    async def test_the_history_is_empty_or_denied_outside_the_scope_and_the_role(self):
        _, captures = await self.seed()
        capture = captures[P105_CODE]
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "OPERACION_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.get(f"/api/captures?form_code={P105_CODE}", "OPERACION_SIN_SECTOR")).json(), [])
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "JEFATURA")).status, 403)
        self.assertEqual((await self.get(f"/api/captures/{uuid4()}")).status, 404)
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):  # the real policy does not enable the form: it behaves as non-existent
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={P105_CODE}")).status, 422)


class UnlinkedMachineTests(Base):
    """P1-31 published ONLY for MP1: a capture on MP3 is not available (the form must be linked to the machine and the backend, not the UI, decides)."""
    install = staticmethod(lambda connection: (install_p105(connection), install_p131(connection, machine_codes=("MP1",))))
    prefix = "vinto_devb1u"

    async def test_availability_and_capture_follow_the_machine_link(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P105_CODE, F6, P131_CODE], "MP3": [P105_CODE, F6]})
        _, mp3 = await self.assignment("MP3")
        reply = await self.post(self.payload(mp3, P131_CODE))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (mp3["id"],)), 0)
        self.assertEqual((await self.post(self.payload(mp3, P105_CODE))).status, 201)
        _, mp1 = await self.assignment("MP1")
        self.assertEqual((await self.post(self.payload(mp1, P131_CODE))).status, 201)


class UnpublishedFormTests(Base):
    """A linked but UNPUBLISHED version is never offered nor accepted."""
    install = staticmethod(lambda connection: (install_p105(connection, publish=False), install_p131(connection)))
    prefix = "vinto_devb1d"

    async def test_an_unpublished_form_is_neither_published_nor_available(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines["MP1"], [F6, P131_CODE])
        _, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment, P105_CODE))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


if __name__ == "__main__":
    unittest.main()
