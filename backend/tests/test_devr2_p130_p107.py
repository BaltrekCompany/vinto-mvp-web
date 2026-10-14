"""DEV-R2: the CANDIDATE VINTO-P1-30 (Producción Perichun, PERICHUN) and VINTO-P1-07 (Registro de producción de bobinas refiladas, COPASA / BELOIT / OVER) run through the central Production capture
engine (/api/captures, assignment context) under an ISOLATED test configuration.

Everything is installed in an ephemeral *_test database: a fictitious Rebobinado sector, four machines and two shifts, and the candidate definitions (tests/devr2_fixtures.py). The sector and the forms are
enabled per test with patch.object (sectors._OPERATIONAL, capture_service.CENTRAL_FORM_CODES); the shipped configuration (BOBINAS only, policy {VINTO-P1-06}) is asserted unchanged and nothing is imported
into a business database. NOT a homologation and NOT a genealogy: start / end hours have no approved source and are never generated, `numero_de_bobina` / `etiqueta_numero_de_bobina` are free text that creates no
bobbin, and no mother / child bobbin, relation, correlative, mass balance, inventory movement or quality_release change exists.
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
    from devr2_fixtures import (CRIA_NUMBERS, ENABLED_SECTORS, P107_CODE, P107_FIELDS, P107_MACHINES, P107_VALUES, P130_CODE, P130_FIELDS, P130_MACHINES, P130_VALUES, install_p107, install_p130,
                                install_rebobinado_machines)
    from m2b2_fixtures import P110_CODE, P110_VALUES, install_p110
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.devr2_fixtures import (CRIA_NUMBERS, ENABLED_SECTORS, P107_CODE, P107_FIELDS, P107_MACHINES, P107_VALUES, P130_CODE, P130_FIELDS, P130_MACHINES, P130_VALUES, install_p107, install_p130,
                                      install_rebobinado_machines)
    from tests.m2b2_fixtures import P110_CODE, P110_VALUES, install_p110
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any patch
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
BUNDLE = load_bundle()
ARTICLE = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")[0]
FORMS = {P130_CODE: (P130_VALUES, P130_FIELDS, P130_MACHINES), P107_CODE: (P107_VALUES, P107_FIELDS, P107_MACHINES)}
AUTOMATIC = ("fecha", "hora_inicio", "hora_termino", "hora_final", "turno", "operador", "responsable", "maquina")
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devr2_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine, article=ARTICLE):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": article, "quantity": 10, "due_date": "2026-11-01"}]}


class Base(unittest.IsolatedAsyncioTestCase):
    install = staticmethod(lambda connection: (install_p130(connection), install_p107(connection)))
    prefix = "vinto_devr2"

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], cls.prefix)
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        install_rebobinado_machines(cls.connection, [ARTICLE])
        install_p110(cls.connection)  # P1-10 on COPASA, for the regression check
        cls.install(cls.connection)
        cls.scope = patch.object(_sectors, "_OPERATIONAL", ENABLED_SECTORS)  # TEST-ONLY: Rebobinado operational in this process
        cls.scope.start()
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", ENABLED_SECTORS), ("SUPERVISION", "SUPERVISION", ENABLED_SECTORS), ("OPERACION", "OPERACION", ENABLED_SECTORS),
                                       ("CALIDAD", "CALIDAD", ENABLED_SECTORS), ("OPERACION_SOLO_BOBINAS", "OPERACION", ("BOBINAS",)), ("OPERACION_SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"devr2.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.scope.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P110_CODE, P130_CODE, P107_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine):
        order = await call("POST", "/api/work-orders", json_body=order_body(machine), cookie=await self.cookie("JEFATURA"))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"),
                           json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return order, reply.json()["assignment"]

    def payload(self, assignment, code, **changes):
        body = {"capture_id": str(uuid4()), "form_code": code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(FORMS[code][0])}
        body.update(changes)
        return body

    async def post(self, body, who="OPERACION"):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who))

    async def get(self, path, who="OPERACION"):
        return await call("GET", path, cookie=await self.cookie(who))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_txn.quality_release")}

    def rows(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, d.value_type||':'||coalesce(d.value_text, d.value_decimal::text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())

    def cases(self):
        return [(code, machine) for code, (_, _, machines) in FORMS.items() for machine in machines]


class ConfigurationTests(Base):
    async def test_the_shipped_configuration_is_unchanged_and_the_real_seed_has_no_rebobinado(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({F6}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))  # REBOBINADO is recognised but NOT operational
        self.assertNotIn(P130_CODE, {r["code"] for r in BUNDLE.forms}) if hasattr(BUNDLE, "forms") else None
        self.assertNotIn("PERICHUN", {r["code"] for r in BUNDLE.machines}) if hasattr(BUNDLE, "machines") else None

    async def test_without_the_test_configuration_the_forms_are_unreachable(self):
        for code, machine in self.cases():
            _, assignment = await self.assignment(machine)
            with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):  # sector enabled in this process, policy shipped
                reply = await self.post(self.payload(assignment, code))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), (code, machine))
            with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):  # policy enabled but the real operational scope
                self.assertEqual((await self.post(self.payload(assignment, code))).status, 404, (code, machine))
                outside = await call("GET", f"/api/assignments/active?machine_code={machine}", cookie=await self.cookie("OPERACION"))
                self.assertEqual((outside.status, outside.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    async def test_the_candidate_contracts_are_exactly_the_manual_legacy_fields(self):
        self.assertEqual((len(P130_FIELDS), len(P107_FIELDS)), (10, 36))
        crias = [f[0] for f in P107_FIELDS if f[0].startswith("peso_cria_")]
        self.assertEqual(len(crias), 21)
        self.assertEqual(crias, [f"peso_cria_{n}" for n in list(range(1, 12)) + list(range(13, 23))])
        self.assertNotIn("peso_cria_12", [f[0] for f in P107_FIELDS])
        self.assertEqual(CRIA_NUMBERS, tuple(range(1, 12)) + tuple(range(13, 23)))
        for code, (_, fields, _) in FORMS.items():
            stored = [tuple(r) for r in self.connection.execute(
                """SELECT fd.key, fd.label, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
                   JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (code,)).fetchall()]
            self.assertEqual(stored, [(k, label, t, r, "production") for k, label, t, r, _ in fields], code)
            self.assertTrue(all(k not in AUTOMATIC for k, *_ in stored), code)
        kinds = {f[0]: f[2] for f in P130_FIELDS}
        self.assertEqual((kinds["peso_de_bobina"], kinds["numero_mrp"], kinds["numero_de_bobina"]), ("text", "text", "text"))  # NOT decimal because of their names

    async def test_the_backend_publishes_each_form_only_for_its_machines_and_only_in_the_users_scope(self):
        reply = await self.get("/api/production/machines")
        machines = {m["code"]: sorted(f["code"] for f in m["forms"]) for s in reply.json()["sectors"] if s["code"] == "REBOBINADO" for m in s["machines"]}
        self.assertEqual(machines, {"COPASA": [P110_CODE, P107_CODE], "BELOIT": [P107_CODE], "OVER": [P107_CODE], "PERICHUN": [P130_CODE]} | {"COPASA": sorted([P110_CODE, P107_CODE])})
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            sectors = [s["code"] for s in (await self.get("/api/production/machines", who)).json()["sectors"]]
            self.assertNotIn("REBOBINADO", sectors, who)


class WriteTests(Base):
    async def test_201_and_the_exact_typed_values_are_persisted_with_the_assignment_context_on_every_candidate_machine(self):
        for code, machine in self.cases():
            values, fields, _ = FORMS[code]
            order, assignment = await self.assignment(machine)
            before = self.counts()
            reply = await self.post(self.payload(assignment, code))
            self.assertEqual(reply.status, 201, (code, machine, reply.text))
            data = reply.json()
            self.assertEqual((data["created"], data["already_submitted"]), (True, False))
            capture = data["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (code, "submitted", 1, machine))
            self.assertEqual((capture["assignment"]["id"], capture["work_order"]["number"]), (assignment["id"], order["number"]))
            self.assertEqual(capture["values"], values)
            kinds = {k: t for k, _, t, *_ in fields}
            self.assertEqual(self.rows(capture["id"]), {k: f"{kinds[k]}:{v}" for k, v in values.items()}, (code, machine))
            after = self.counts()
            self.assertEqual({k: after[k] - before[k] for k in after}, {"vinto_txn.capture": 1, "vinto_txn.capture_detail": len(values), "vinto_txn.bobbin": 0, "vinto_txn.quality_release": 0})

    async def test_text_fields_are_stored_as_typed_and_nothing_is_calculated(self):
        _, assignment = await self.assignment("PERICHUN")
        capture = (await self.post(self.payload(assignment, P130_CODE))).json()["capture"]
        stored = self.rows(capture["id"])
        self.assertEqual((stored["peso_de_bobina"], stored["numero_mrp"], stored["numero_de_bobina"]), ("text:850,5 kg (texto)", "text:MRP-EJEMPLO-9", "text:B-EJEMPLO-30 (texto, no crea bobina)"))
        _, assignment = await self.assignment("COPASA")
        capture = (await self.post(self.payload(assignment, P107_CODE))).json()["capture"]
        stored = self.rows(capture["id"])
        self.assertEqual(sorted(stored), sorted(P107_VALUES))
        self.assertEqual(sum(1 for k in stored if k.startswith("peso_cria_")), 21)
        self.assertNotIn("peso_cria_12", stored)
        for key in ("total", "total_crias", "balance", "merma", "rendimiento"):
            self.assertNotIn(key, stored)

    async def test_no_start_end_hour_is_generated_stored_or_accepted(self):
        for code, machine in self.cases():
            _, assignment = await self.assignment(machine)
            capture = (await self.post(self.payload(assignment, code))).json()["capture"]
            for key in AUTOMATIC:
                self.assertNotIn(key, self.rows(capture["id"]))
                self.assertNotIn(key, capture["values"])
            before = self.counts()
            for key in AUTOMATIC + ("peso_cria_12", "total", "aprobado"):
                body = self.payload(assignment, code)
                body["values"][key] = "1"
                reply = await self.post(body)
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), (code, key))
            self.assertEqual(self.counts(), before)

    async def test_optional_observations_may_be_omitted_and_every_other_field_is_required(self):
        for code, machine in self.cases():
            values, fields, _ = FORMS[code]
            _, assignment = await self.assignment(machine)
            ok = await self.post(self.payload(assignment, code, values={k: v for k, v in values.items() if k != "observaciones"}))
            self.assertEqual(ok.status, 201, (code, ok.text))
            self.assertNotIn("observaciones", ok.json()["capture"]["values"])
            before = self.counts()
            for key in [f[0] for f in fields if f[3]]:
                reply = await self.post(self.payload(assignment, code, values={k: v for k, v in values.items() if k != key}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), (code, key))  # incl. each of the 21 cría weights: legacy obligatoriedad is kept
            self.assertEqual(self.counts(), before)

    async def test_422_invalid_values_persist_nothing(self):
        for code, machine in self.cases():
            values, fields, _ = FORMS[code]
            _, assignment = await self.assignment(machine)
            before = self.counts()
            cases = []
            text_key = next(f[0] for f in fields if f[2] == "text")
            cases += [{**values, text_key: "   "}, {**values, text_key: None}, {**values, text_key: 7}]
            for key in [f[0] for f in fields if f[2] == "decimal"]:
                cases += [{**values, key: bad} for bad in ("12,5", "abc", "1e3", "", True, None)]
            for bad in cases:
                with self.subTest(code=code, values=bad):
                    reply = await self.post(self.payload(assignment, code, values=bad))
                    self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
            self.assertEqual(self.counts(), before)

    async def test_a_form_is_available_only_on_its_own_machines(self):
        for code, wrong in ((P130_CODE, "COPASA"), (P107_CODE, "PERICHUN")):
            _, assignment = await self.assignment(wrong)
            before = self.counts()
            reply = await self.post(self.payload(assignment, code))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"), (code, wrong))
            self.assertEqual(self.counts(), before)

    async def test_idempotency_201_200_409(self):
        for code, machine in self.cases():
            _, assignment = await self.assignment(machine)
            body = self.payload(assignment, code)
            first = await self.post(body)
            self.assertEqual(first.status, 201)
            before = (self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
            again = await self.post(body)
            self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
            self.assertEqual(again.json()["capture"], first.json()["capture"])
            self.assertEqual((self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
            key = next(k for k in body["values"] if k.startswith(("gramaje", "peso")) and k != "peso_de_bobina")
            changed = await self.post({**body, "values": {**body["values"], key: "99.9"}})
            self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"), (code, machine))
            other = P107_CODE if code == P130_CODE else P130_CODE
            self.assertEqual((await self.post({**self.payload(assignment, other), "capture_id": body["capture_id"]})).status, 409)

    async def test_concurrency_identical_posts_create_one_capture(self):
        for code, machine in (("VINTO-P1-30", "PERICHUN"), ("VINTO-P1-07", "OVER")):
            _, assignment = await self.assignment(machine)
            body = self.payload(assignment, code)
            replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
            self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201], code)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), len(FORMS[code][0]))

    async def test_roles_sector_scope_and_a_finished_assignment(self):
        _, assignment = await self.assignment("COPASA")
        body = self.payload(assignment, P107_CODE)
        self.assertEqual((await call("POST", "/api/captures", json_body=body)).status, 401)
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            self.assertEqual((await self.post(body, who)).status, 403, who)
        before = self.counts()
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):  # no grant on REBOBINADO: the assignment does not exist for them
            self.assertEqual((await self.post(body, who)).status, 404, who)
        self.assertEqual(self.counts(), before)
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s", (assignment["id"],))
        reply = await self.post(self.payload(assignment, P107_CODE))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))
        self.assertEqual(self.counts(), before)

    async def test_the_payload_stays_closed(self):
        _, assignment = await self.assignment("PERICHUN")
        for extra in ({"machine_code": "PERICHUN"}, {"bobbin_id": str(uuid4())}, {"hora_inicio": "07:00"}, {"operating_date": "2026-01-01"}, {"form_version_id": str(uuid4())}):
            self.assertEqual((await self.post({**self.payload(assignment, P130_CODE), **extra})).status, 422, extra)

    async def test_no_bobbin_genealogy_or_release_is_ever_created_or_changed(self):
        before = self.counts()
        audits = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        for code, machine in self.cases():
            _, assignment = await self.assignment(machine)
            self.assertEqual((await self.post(self.payload(assignment, code))).status, 201)
        after = self.counts()
        self.assertEqual((after["vinto_txn.bobbin"], after["vinto_txn.quality_release"]), (before["vinto_txn.bobbin"], before["vinto_txn.quality_release"]))
        self.assertEqual(after["vinto_txn.capture"] - before["vinto_txn.capture"], 4)  # one capture per machine, nothing derived from them
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audits)
        tables = {r[0] for r in self.connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'vinto_txn'").fetchall()}
        for table in tables:  # no table of this schema was written other than the capture / detail / assignment / work-order / audit ones
            if table in {"bobbin", "quality_release"} or "genealog" in table or "parent" in table or "inventory" in table:
                self.assertEqual(self.scalar(f"SELECT count(*) FROM vinto_txn.{table}"), before.get(f"vinto_txn.{table}", 0), table)


class ReadTests(Base):
    async def seed(self):
        out = {}
        for code, machine in self.cases():
            _, assignment = await self.assignment(machine)
            out[(code, machine)] = (await self.post(self.payload(assignment, code))).json()["capture"]
        return out

    async def test_get_by_id_and_the_history_is_filtered_by_form_without_mixing(self):
        captured = await self.seed()
        for (code, machine), capture in captured.items():
            got = await self.get(f"/api/captures/{capture['id']}")
            self.assertEqual((got.status, got.json()["form"]["code"], got.json()["machine"]["code"], got.json()["values"]), (200, code, machine, capture["values"]))
        for code, (_, _, machines) in FORMS.items():
            listed = (await self.get(f"/api/captures?form_code={code}")).json()
            ids = {c["id"] for (c_code, _), c in captured.items() if c_code == code}
            self.assertTrue(ids <= {x["id"] for x in listed}, code)  # the class database is shared: other tests' captures of the SAME form may also be listed
            self.assertEqual({x["form"]["code"] for x in listed}, {code})  # never another form
            self.assertTrue({x["machine"]["code"] for x in listed} <= set(machines))
        self.assertEqual((await self.get("/api/captures?form_code=VINTO-P1-99")).status, 422)

    async def test_404_and_empty_results_outside_the_scope(self):
        captured = await self.seed()
        capture = next(iter(captured.values()))
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}", who)).status, 404, who)
            for code in FORMS:
                self.assertEqual((await self.get(f"/api/captures?form_code={code}", who)).json(), [], who)
        self.assertEqual((await self.get(f"/api/captures/{uuid4()}")).status, 404)
        self.assertEqual((await call("GET", f"/api/captures/{capture['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/quality/captures/{capture['id']}", "CALIDAD")).status, 404)  # not a Quality capture
        self.assertEqual((await self.get(f"/api/quality/machine-captures/{capture['id']}", "CALIDAD")).status, 404)


class UnavailableTests(Base):
    install = staticmethod(lambda connection: (install_p130(connection, publish=False), install_p107(connection, machine_codes=("COPASA",))))
    prefix = "vinto_devr2u"

    async def test_an_unpublished_form_or_a_machine_without_the_link_is_not_available(self):
        machines = {m["code"]: sorted(f["code"] for f in m["forms"]) for s in (await self.get("/api/production/machines")).json()["sectors"] if s["code"] == "REBOBINADO" for m in s["machines"]}
        self.assertEqual(machines["PERICHUN"], [])
        self.assertEqual(machines["BELOIT"], [])
        self.assertEqual(machines["COPASA"], sorted([P110_CODE, P107_CODE]))
        for code, machine in ((P130_CODE, "PERICHUN"), (P107_CODE, "BELOIT")):
            _, assignment = await self.assignment(machine)
            reply = await self.post(self.payload(assignment, code))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"), (code, machine))
        _, assignment = await self.assignment("COPASA")
        self.assertEqual((await self.post(self.payload(assignment, P107_CODE))).status, 201)


class RegressionTests(Base):
    async def test_p1_10_keeps_working_alongside_the_new_candidates(self):
        _, assignment = await self.assignment("COPASA")
        body = {"capture_id": str(uuid4()), "form_code": P110_CODE, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(P110_VALUES)}
        reply = await self.post(body)
        self.assertEqual((reply.status, reply.json()["capture"]["values"]), (201, P110_VALUES))
        self.assertEqual((await self.get(f"/api/captures?form_code={P110_CODE}")).json()[0]["id"], body["capture_id"])
        self.assertEqual((await self.get(f"/api/captures?form_code={P107_CODE}")).json(), [])  # histories do not mix


if __name__ == "__main__":
    unittest.main()
