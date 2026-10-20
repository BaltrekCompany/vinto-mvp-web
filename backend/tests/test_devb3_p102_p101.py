"""DEV-B3: the CANDIDATE VINTO-P1-02 (Parámetros de operación de máquina MP1, 48 manual fields) and VINTO-P1-01 (Operación e inspección de máquina MP3, 86 manual fields) run through the existing central
Production engine (/api/captures, assignment context) for the real Bobinas machines.

Installed in an ephemeral *_test database (tests/devb3_fixtures.py, generated from the legacy definitions) and enabled per test with patch.object on capture_service.CENTRAL_FORM_CODES; the shipped policy
(only VINTO-P1-06) and sectors (only BOBINAS) are asserted unchanged. NOT a homologation: no range, limit, catalog, conversion, signature, review or automatic velocity exists; text fields that look numeric stay
text; the three manual cuchilla hours of P1-01 are real `time` values (value_time); the registration hour is never presented as an operation hour; no bobbin or quality_release is touched.
"""

import asyncio
import secrets
import unittest
from datetime import datetime, time, timezone
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
    from devb3_fixtures import P101_CODE, P101_FIELDS, P101_VALUES, P102_CODE, P102_FIELDS, P102_VALUES, TIME_KEYS, install_p101, install_p102
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.devb3_fixtures import P101_CODE, P101_FIELDS, P101_VALUES, P102_CODE, P102_FIELDS, P102_VALUES, TIME_KEYS, install_p101, install_p102
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES  # captured at import, before any patch
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
BUNDLE = load_bundle()
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in ("MP1", "MP3")}
FORMS = {P102_CODE: (P102_VALUES, P102_FIELDS, "MP1", "MP3"), P101_CODE: (P101_VALUES, P101_FIELDS, "MP3", "MP1")}  # code -> values, fields, own machine, the other machine
AUTOMATIC = ("nombre_operador", "fecha", "hora", "turno", "velocidad_maquina", "firma_operador", "revisado", "operador", "responsable", "maquina")
STATE = {}
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz -> DIA, 2026-10-06
NEXT_DAY = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devb3_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE[machine], "quantity": 10, "due_date": "2026-11-01"}]}


class Base(unittest.IsolatedAsyncioTestCase):
    install = staticmethod(lambda connection: (install_p102(connection), install_p101(connection)))
    prefix = "vinto_devb3"

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
            cls.users[name] = (create_user(cls.connection, username=f"devb3.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P102_CODE, P101_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)
        # one stable clock patch per test (nested per-request patches of concurrent requests would not unwind in order and would leak into later modules)
        capture_clock, assignment_clock = patch.object(_capture_service, "_now", return_value=DAY), patch.object(_assignments_service, "_now", return_value=DAY)
        self.clock = capture_clock.start()
        assignment_clock.start()
        self.addCleanup(capture_clock.stop)
        self.addCleanup(assignment_clock.stop)

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
            """SELECT f.key, d.value_type||':'||coalesce(d.value_text, d.value_decimal::text, d.value_time::text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


class ConfigurationAndAvailabilityTests(Base):
    async def test_the_shipped_configuration_is_unchanged_and_the_forms_are_unreachable_without_the_test_policy(self):
        # CLOUD-DEP G.12-C4: CENTRAL_FORM_CODES real ya incluye los candidatos de Bobinas habilitados;
        # lo que importa es que los códigos de fixture sintéticos (P101_CODE/P102_CODE) NO estén.
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30", "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16", "VINTO-P1-29"}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS", "REBOBINADO", "CONVERSION"))
        for code, (_, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
                reply = await self.post(self.payload(assignment, code))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)
                self.assertEqual((await self.get(f"/api/captures?form_code={code}")).status, 422)
                machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
                self.assertEqual(machines, {"MP1": sorted(SHIPPED_POLICY & frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31"})), "MP3": sorted(SHIPPED_POLICY & frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", F6, "VINTO-P1-31"}))})  # CLOUD-DEP G.12-C4-FINAL25: SHIPPED_POLICY entero ya no aplica solo a MP1/MP3 (P1-07/10/11/12/13/16/29/30 son de otros sectores)
                for codes in machines.values():
                    self.assertNotIn(code, codes)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    async def test_the_backend_publishes_p102_only_on_mp1_and_p101_only_on_mp3(self):
        machines = {m["code"]: sorted(f["code"] for f in m["forms"]) for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": sorted([F6, P102_CODE]), "MP3": sorted([F6, P101_CODE])})
        self.assertEqual([s["code"] for s in (await self.get("/api/production/machines", "OPERACION_SIN_SECTOR")).json()["sectors"]], [])

    async def test_the_candidate_contracts_are_exactly_the_manual_legacy_fields(self):
        self.assertEqual((len(P102_FIELDS), len(P101_FIELDS)), (48, 86))
        for code, (_, fields, _, _) in FORMS.items():
            stored = [tuple(r) for r in self.connection.execute(
                """SELECT fd.key, fd.label, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
                   JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (code,)).fetchall()]
            self.assertEqual(stored, [(k, label, t, r, "production") for k, label, t, r, _ in fields], code)
            self.assertTrue(all(k not in AUTOMATIC for k, *_ in stored), code)
        kinds = {f[0]: f[2] for f in P101_FIELDS}
        self.assertEqual([k for k, t in kinds.items() if t == "time"], list(TIME_KEYS))
        for key in ("peso_balas_fibra_corta", "peso_balas_fibra_larga", "tiempo_de_pulpeo_fibra_corta", "tiempo_de_pulpeo_fibra_larga", "opertado"):
            self.assertEqual(kinds[key], "text", key)  # NOT decimal because of their names; `opertado` keeps the source spelling
        kinds02 = {f[0]: f[2] for f in P102_FIELDS}
        for key in ("producto", "apertura_gas", "apertura_termocompresor", "relacion_chorro_tela", "altura_caja_entrada", "apertura_labio", "dosificacion_release", "novedades") + tuple(k for k in kinds02 if k.startswith("limpieza_")):
            self.assertEqual(kinds02[key], "text", key)
        self.assertEqual(sorted({t for _, _, t, *_ in P102_FIELDS + P101_FIELDS}), ["decimal", "text", "time"])


class WriteTests(Base):
    async def test_201_and_the_exact_typed_values_are_persisted_with_the_assignment_context(self):
        for code, (values, fields, own, _) in FORMS.items():
            order, assignment = await self.assignment(own)
            before = self.counts()
            reply = await self.post(self.payload(assignment, code))
            self.assertEqual(reply.status, 201, (code, reply.text))
            data = reply.json()
            self.assertEqual((data["created"], data["already_submitted"]), (True, False))
            capture = data["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (code, "submitted", 1, own))
            self.assertEqual((capture["assignment"]["id"], capture["work_order"]["number"], capture["shift"]["code"], capture["operating_date"]), (assignment["id"], order["number"], "DIA", "2026-10-06"))
            expected = {k: (v + ":00" if k in TIME_KEYS else v) for k, v in values.items()}  # the backend serializes a time as HH:MM:SS
            self.assertEqual(capture["values"], expected)
            kinds = {k: t for k, _, t, *_ in fields}
            self.assertEqual(self.rows(capture["id"]), {k: f"{kinds[k]}:{expected[k]}" for k in values}, code)
            self.assertEqual(len(values), len(fields))
            after = self.counts()
            self.assertEqual({k: after[k] - before[k] for k in after}, {"vinto_txn.capture": 1, "vinto_txn.capture_detail": len(fields), "vinto_txn.bobbin": 0, "vinto_txn.quality_release": 0})

    async def test_the_three_cuchilla_hours_are_real_time_values_and_get_and_history_keep_them(self):
        _, assignment = await self.assignment("MP3")
        values = {**P101_VALUES, TIME_KEYS[0]: "06:05", TIME_KEYS[1]: "23:59", TIME_KEYS[2]: "00:00"}
        body = self.payload(assignment, P101_CODE, values=values)
        capture = (await self.post(body)).json()["capture"]
        stored = self.connection.execute(
            """SELECT f.key, d.value_time, d.value_text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id
               WHERE d.capture_id = %s AND f.value_type = 'time' ORDER BY f.display_order""", (capture["id"],)).fetchall()
        self.assertEqual(stored, [(TIME_KEYS[0], time(6, 5), None), (TIME_KEYS[1], time(23, 59), None), (TIME_KEYS[2], time(0, 0), None)])  # value_time, never text
        self.assertEqual([capture["values"][k] for k in TIME_KEYS], ["06:05:00", "23:59:00", "00:00:00"])
        got = await self.get(f"/api/captures/{capture['id']}")
        self.assertEqual([got.json()["values"][k] for k in TIME_KEYS], ["06:05:00", "23:59:00", "00:00:00"])
        listed = {x["id"]: x for x in (await self.get(f"/api/captures?form_code={P101_CODE}")).json()}
        self.assertEqual([listed[capture["id"]]["values"][k] for k in TIME_KEYS], ["06:05:00", "23:59:00", "00:00:00"])
        again = await self.post(body)  # HH:MM retried against the HH:MM:SS stored value is the SAME capture
        self.assertEqual((again.status, again.json()["already_submitted"]), (200, True))
        with_seconds = await self.post({**body, "values": {**values, TIME_KEYS[0]: "06:05:00"}})
        self.assertEqual((with_seconds.status, with_seconds.json()["already_submitted"]), (200, True))
        moved = await self.post({**body, "values": {**values, TIME_KEYS[0]: "06:06"}})
        self.assertEqual((moved.status, moved.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))

    async def test_invalid_hours_are_rejected_and_persist_nothing(self):
        _, assignment = await self.assignment("MP3")
        before = self.counts()
        bad = ["24:00", "25:10", "12:60", "7:5", "7:30", "07", "0730", "T07:30", "07:30:61", "07:30:00.5", "07:30+01:00", "07:30Z", "12h30", "abc", "", None, 730, 7.5, True, ["07:30"]]
        for key in TIME_KEYS:
            for value in bad:
                with self.subTest(key=key, value=value):
                    reply = await self.post(self.payload(assignment, P101_CODE, values={**P101_VALUES, key: value}))
                    self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
        for key in TIME_KEYS:  # obligatory: omitting any of the three is rejected
            reply = await self.post(self.payload(assignment, P101_CODE, values={k: v for k, v in P101_VALUES.items() if k != key}))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), key)
        self.assertEqual(self.counts(), before)

    async def test_surrounding_whitespace_is_trimmed_like_every_other_value_and_the_hour_is_stored_normalized(self):
        _, assignment = await self.assignment("MP3")
        capture = (await self.post(self.payload(assignment, P101_CODE, values={**P101_VALUES, TIME_KEYS[0]: " 07:30 "}))).json()["capture"]  # the engine strips every string before parsing
        self.assertEqual(capture["values"][TIME_KEYS[0]], "07:30:00")

    async def test_numeric_looking_fields_declared_text_are_stored_as_typed_text(self):
        _, assignment = await self.assignment("MP3")
        values = {**P101_VALUES, "peso_balas_fibra_corta": "850,5 kg", "peso_balas_fibra_larga": "no medido", "tiempo_de_pulpeo_fibra_corta": "35 min", "tiempo_de_pulpeo_fibra_larga": "1,5 h"}
        capture = (await self.post(self.payload(assignment, P101_CODE, values=values))).json()["capture"]
        stored = self.rows(capture["id"])
        for key in ("peso_balas_fibra_corta", "peso_balas_fibra_larga", "tiempo_de_pulpeo_fibra_corta", "tiempo_de_pulpeo_fibra_larga"):
            self.assertEqual(stored[key], f"text:{values[key]}", key)
        _, assignment = await self.assignment("MP1")
        values = {**P102_VALUES, "apertura_gas": "35 %", "dosificacion_release": "1,2", "limpieza_sotano": "ok"}
        stored = self.rows((await self.post(self.payload(assignment, P102_CODE, values=values))).json()["capture"]["id"])
        self.assertEqual((stored["apertura_gas"], stored["dosificacion_release"], stored["limpieza_sotano"], stored["producto"]), ("text:35 %", "text:1,2", "text:ok", f"text:{values['producto']}"))

    async def test_automatic_unresolved_or_invented_fields_sent_by_the_client_are_rejected(self):
        for code, (values, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            before = self.counts()
            for key in AUTOMATIC + ("hora_inicio", "total", "aprobado", "limite"):
                if key in values:
                    continue
                reply = await self.post(self.payload(assignment, code, values={**values, key: "1"}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), (code, key))
            self.assertEqual(self.counts(), before)
            capture = (await self.post(self.payload(assignment, code))).json()["capture"]
            for key in AUTOMATIC:
                self.assertNotIn(key, capture["values"])
                self.assertNotIn(key, self.rows(capture["id"]))

    async def test_422_invalid_values_and_every_field_is_required(self):
        for code, (values, fields, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            before = self.counts()
            for key in [f[0] for f in fields if f[3]]:
                reply = await self.post(self.payload(assignment, code, values={k: v for k, v in values.items() if k != key}))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), (code, key))
            text_key = next(f[0] for f in fields if f[2] == "text")
            for bad in ({**values, text_key: "   "}, {**values, text_key: None}, {**values, text_key: 7}):
                self.assertEqual((await self.post(self.payload(assignment, code, values=bad))).status, 422)
            for key in [f[0] for f in fields if f[2] == "decimal"]:
                for bad in ("12,5", "abc", "1e3", "", True, None):
                    self.assertEqual((await self.post(self.payload(assignment, code, values={**values, key: bad}))).status, 422, (code, key, bad))
            self.assertEqual(self.counts(), before)

    async def test_a_form_is_available_only_on_its_own_machine(self):
        for code, (_, _, _, other) in FORMS.items():
            _, assignment = await self.assignment(other)
            before = self.counts()
            reply = await self.post(self.payload(assignment, code))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"), code)
            self.assertEqual(self.counts(), before)

    async def test_a_stale_or_finished_assignment_is_rejected(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for code, (_, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            self.clock.return_value = NEXT_DAY
            reply = await self.post(self.payload(assignment, code))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_STALE"), code)
            self.clock.return_value = DAY
            self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s", (assignment["id"],))
            reply = await self.post(self.payload(assignment, code))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"), code)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_roles_and_sector_scope(self):
        for code, (_, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            body = self.payload(assignment, code)
            self.assertEqual((await call("POST", "/api/captures", json_body=body)).status, 401)
            for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
                self.assertEqual((await self.post(body, who)).status, 403, who)
            before = self.counts()
            self.assertEqual((await self.post(body, "OPERACION_SIN_SECTOR")).status, 404)
            self.assertEqual(self.counts(), before)

    async def test_idempotency_201_200_409(self):
        for code, (_, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            body = self.payload(assignment, code)
            first = await self.post(body)
            self.assertEqual(first.status, 201)
            before = (self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
            again = await self.post(body)
            self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
            self.assertEqual(again.json()["capture"], first.json()["capture"])
            self.assertEqual((self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
            key = next(f[0] for f in FORMS[code][1] if f[2] == "decimal")
            changed = await self.post({**body, "values": {**body["values"], key: "99.9"}})
            self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"), code)
            other = P101_CODE if code == P102_CODE else P102_CODE
            self.assertEqual((await self.post({**self.payload(assignment, other), "capture_id": body["capture_id"]})).status, 409)

    async def test_concurrency_identical_posts_create_one_capture(self):
        for code, (values, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            body = self.payload(assignment, code)
            replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
            self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201], code)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), len(values))

    async def test_the_payload_stays_closed_and_nothing_touches_bobbins_or_quality_release(self):
        before = self.counts()
        for code, (_, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            for extra in ({"machine_code": own}, {"bobbin_id": str(uuid4())}, {"hora": "07:00"}, {"operating_date": "2026-01-01"}, {"form_version_id": str(uuid4())}):
                self.assertEqual((await self.post({**self.payload(assignment, code), **extra})).status, 422, (code, extra))
            self.assertEqual((await self.post(self.payload(assignment, code))).status, 201)
        after = self.counts()
        self.assertEqual((after["vinto_txn.bobbin"], after["vinto_txn.quality_release"]), (before["vinto_txn.bobbin"], before["vinto_txn.quality_release"]))


class ReadTests(Base):
    async def test_get_by_id_and_the_history_is_filtered_by_form_without_mixing(self):
        captured = {}
        for code, (_, _, own, _) in FORMS.items():
            _, assignment = await self.assignment(own)
            captured[code] = (await self.post(self.payload(assignment, code))).json()["capture"]
        for code, capture in captured.items():
            got = await self.get(f"/api/captures/{capture['id']}")
            self.assertEqual((got.status, got.json()["form"]["code"], got.json()["values"]), (200, code, capture["values"]))
            listed = (await self.get(f"/api/captures?form_code={code}")).json()
            self.assertIn(capture["id"], {x["id"] for x in listed})
            self.assertEqual({x["form"]["code"] for x in listed}, {code})
            self.assertEqual((await self.get(f"/api/captures/{capture['id']}", "OPERACION_SIN_SECTOR")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={code}", "OPERACION_SIN_SECTOR")).json(), [])
            self.assertEqual((await self.get(f"/api/quality/captures/{capture['id']}", "CALIDAD")).status, 404)  # not a Quality capture
        self.assertEqual((await self.get(f"/api/captures/{uuid4()}")).status, 404)


class UnavailableTests(Base):
    install = staticmethod(lambda connection: (install_p102(connection, publish=False), install_p101(connection, machine_codes=("MP1",))))
    prefix = "vinto_devb3u"

    async def test_an_unpublished_form_or_a_machine_without_the_link_is_not_available(self):
        machines = {m["code"]: sorted(f["code"] for f in m["forms"]) for s in (await self.get("/api/production/machines")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": sorted([F6, P101_CODE]), "MP3": [F6]})  # P1-02 unpublished; P1-01 linked to MP1 only in this database
        _, assignment = await self.assignment("MP1")
        reply = await self.post(self.payload(assignment, P102_CODE))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        _, assignment = await self.assignment("MP3")
        reply = await self.post(self.payload(assignment, P101_CODE))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


if __name__ == "__main__":
    unittest.main()
