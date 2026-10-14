"""DEV-Q3: the CANDIDATE VINTO-P1-24 (Propiedades físicas en húmedo) and VINTO-P1-25 (Resistencia en húmedo-curado) run through the bobbin-level Quality capture route
(/api/quality/bobbins/{bobbin_id}/captures) of F3 bobbins of MP1 / MP3, reusing the DEV-Q2 service, policy and availability endpoint.

Installed in an ephemeral *_test database (tests/devq3_fixtures.py) and enabled per test with patch.object on capture_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES; the shipped policy (empty) is asserted
unchanged. NOT a homologation: no formula, range, limit, catalog, unit or approval criterion exists; no average, percentage or humidity is ever calculated, `hora` is the REGISTRATION time, rewinder bobbins do
not exist in this model (not covered) and quality_release is never modified. P1-19, P1-20 and P1-21 keep their behavior.
"""

import asyncio
import unittest
from uuid import uuid4

from unittest.mock import patch

from app.ephemeral_db import build_reference_template, drop_database
from app.quality import capture_service as _quality_service

try:
    import test_devq2_p118_p121 as q2
    import test_f3_bobbins_api as f3
    from devq2_fixtures import P121_CODE, P121_VALUES, install_p121
    from devq3_fixtures import P124_CODE, P124_FIELDS, P124_VALUES, P125_CODE, P125_FIELDS, P125_VALUES, install_p124, install_p125
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_devq2_p118_p121 as q2
    import tests.test_f3_bobbins_api as f3
    from tests.devq2_fixtures import P121_CODE, P121_VALUES, install_p121
    from tests.devq3_fixtures import P124_CODE, P124_FIELDS, P124_VALUES, P125_CODE, P125_FIELDS, P125_VALUES, install_p124, install_p125
    from tests.test_assignments_api import call

STATE = {}
FORMS = {P124_CODE: (P124_VALUES, P124_FIELDS, ("promedio_longitudinal_humedo", "promedio_transversal_humedo")),
         P125_CODE: (P125_VALUES, P125_FIELDS, ("promedio_resistencia_longitudinal_kgf", "promedio_resistencia_longitudinal_humeda_kgf", "porcentaje_de_resistencia_humeda"))}
AUTOMATIC = ("fecha", "hora", "maquina", "responsable")
ENABLE = frozenset({P124_CODE, P125_CODE})
SHIPPED_POLICY = _quality_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES  # captured at import, before any patch


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devq3_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])
        f3.STATE.pop("template", None)


def install_all(connection):
    install_p121(connection)
    install_p124(connection)
    install_p125(connection)


class Base(q2.BobbinBase):
    install = staticmethod(install_all)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        policy = patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", ENABLE | {P121_CODE})  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    def body_for(self, code, bobbin, **changes):
        body = {"capture_id": str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": {**FORMS[code][0], "numero_de_bobina": bobbin["code"]}}
        body.update(changes)
        return body


class ConfigurationTests(Base):
    async def test_the_shipped_policy_is_empty_and_the_candidates_are_known_but_unreachable_without_the_test_policy(self):
        self.assertEqual(SHIPPED_POLICY, frozenset())
        self.assertEqual(_quality_service.BOBBIN_CANDIDATE_FORM_CODES, frozenset({P121_CODE, P124_CODE, P125_CODE}))
        self.assertEqual({k: v for k, v in _quality_service.BOBBIN_CODE_FIELDS.items()}, {P121_CODE: "numero_de_bobina", P124_CODE: "numero_de_bobina", P125_CODE: "numero_de_bobina"})
        _, bobbin = await self.bobbin()
        before = self.counts()
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", SHIPPED_POLICY):
            for code in FORMS:
                reply = await self.submit(bobbin["id"], self.body_for(code, bobbin))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)
                self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")).status, 422, code)
            self.assertEqual([m["forms"] for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]], [[], []])
        self.assertEqual(self.counts(), before)

    async def test_the_backend_publishes_both_candidates_on_mp1_and_mp3_only_to_quality_users_in_scope(self):
        machines = {m["code"]: sorted(f["code"] for f in m["forms"]) for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P121_CODE, P124_CODE, P125_CODE], "MP3": [P121_CODE, P124_CODE, P125_CODE]})
        self.assertEqual((await self.read("/api/quality/bobbin-forms", "CALIDAD_SIN_SECTOR")).json()["sectors"], [])
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.read("/api/quality/bobbin-forms", who)).status, 403, who)

    async def test_the_candidate_contracts_are_exactly_the_manual_legacy_fields(self):
        self.assertEqual(len(P124_FIELDS), 12)
        self.assertEqual(len(P125_FIELDS), 14)
        for code, (_, fields, calculated) in FORMS.items():
            stored = [tuple(r) for r in self.connection.execute(
                """SELECT fd.key, fd.label, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
                   JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (code,)).fetchall()]
            self.assertEqual(stored, [(k, label, t, r, "quality") for k, label, t, r, _ in fields], code)
            self.assertTrue(all(k not in AUTOMATIC + calculated for k, *_ in stored), code)
        self.assertEqual([t for k, _, t, *_ in P125_FIELDS if k == "curado_min"], ["text"])  # NOT converted to decimal because of its name


class WriteTests(Base):
    async def test_201_is_persisted_typed_on_mp1_and_mp3_with_the_bobbin_historic_context(self):
        for code, (values, fields, _) in FORMS.items():
            for machine in ("MP1", "MP3"):
                assignment, bobbin = await self.bobbin(machine)
                before = self.release(bobbin["id"])
                reply = await self.submit(bobbin["id"], self.body_for(code, bobbin))
                self.assertEqual(reply.status, 201, (code, machine, reply.text))
                capture = reply.json()["capture"]
                self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (code, "submitted", 1, machine))
                self.assertEqual(capture["bobbin"], {"id": bobbin["id"], "code": bobbin["code"]})
                self.assertEqual(capture["values"], {**values, "numero_de_bobina": bobbin["code"]})
                row = self.connection.execute("SELECT assignment_id, bobbin_id, created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)).fetchone()
                self.assertEqual((str(row[0]), str(row[1]), row[2]), (assignment["id"], bobbin["id"], self.users["CALIDAD"][0].user_id))
                kinds = {k: t for k, _, t, *_ in fields}
                expected = {k: f"{kinds[k]}:{v}" for k, v in {**values, "numero_de_bobina": bobbin["code"]}.items()}
                self.assertEqual(self.rows(capture["id"]), expected)
                self.assertEqual(self.release(bobbin["id"]), before)  # quality_release untouched
                self.assertEqual(before[0], "pending")

    async def test_nothing_calculated_or_automatic_is_generated_stored_or_accepted(self):
        _, bobbin = await self.bobbin()
        for code, (values, _, calculated) in FORMS.items():
            capture = (await self.submit(bobbin["id"], self.body_for(code, bobbin))).json()["capture"]
            stored = self.rows(capture["id"])
            self.assertEqual(sorted(stored), sorted(values))
            for key in AUTOMATIC + calculated:
                self.assertNotIn(key, stored)
                self.assertNotIn(key, capture["values"])
            before = self.counts()
            for key in AUTOMATIC + calculated + ("aprobado", "limite"):
                body = self.body_for(code, bobbin)
                body["values"][key] = "1"
                reply = await self.submit(bobbin["id"], body)
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), (code, key))
            self.assertEqual(self.counts(), before)

    async def test_422_invalid_values_persist_nothing_and_the_text_field_is_not_numeric(self):
        _, bobbin = await self.bobbin()
        for code, (values, fields, _) in FORMS.items():
            before = self.counts()
            base = self.body_for(code, bobbin)["values"]
            cases = [{k: v for k, v in base.items() if k != f[0]} for f in fields if f[3]]
            cases += [{**base, "producto": "   "}, {**base, "producto": None}, {**base, "producto": 7}]
            for key in [f[0] for f in fields if f[2] == "decimal"]:
                cases += [{**base, key: bad} for bad in ("1,5", "abc", "1e3", "", True, None)]
            for values_bad in cases:
                with self.subTest(code=code, values=values_bad):
                    reply = await self.submit(bobbin["id"], self.body_for(code, bobbin, values=values_bad))
                    self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
            self.assertEqual(self.counts(), before)
        ok = await self.submit(bobbin["id"], self.body_for(P125_CODE, bobbin, values={**self.body_for(P125_CODE, bobbin)["values"], "curado_min": "no numérico"}))
        self.assertEqual(ok.status, 201, ok.text)  # curado_min is text: any text is stored as typed
        self.assertEqual(ok.json()["capture"]["values"]["curado_min"], "no numérico")

    async def test_optional_observations_may_be_omitted(self):
        _, bobbin = await self.bobbin()
        for code, (values, *_) in FORMS.items():
            body = self.body_for(code, bobbin)
            del body["values"]["observaciones"]
            reply = await self.submit(bobbin["id"], body)
            self.assertEqual(reply.status, 201, (code, reply.text))
            self.assertNotIn("observaciones", reply.json()["capture"]["values"])

    async def test_a_declared_bobbin_number_that_contradicts_the_selected_bobbin_is_rejected(self):
        _, a = await self.bobbin("MP1")
        _, b = await self.bobbin("MP3")
        for code in FORMS:
            before = self.counts()
            for declared in (str(int(a["code"]) + 1000), "999999", "", "abc", b["code"] if b["code"] != a["code"] else "x"):
                reply = await self.submit(a["id"], self.body_for(code, a, values={**self.body_for(code, a)["values"], "numero_de_bobina": declared}))
                self.assertEqual(reply.status, 422, (code, declared, reply.text))
            self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (b["id"],)), 0)  # never associated with a different bobbin

    async def test_unknown_out_of_scope_and_legacy_bobbins_are_404(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        for code in FORMS:
            for bobbin_id in (str(uuid4()), "not-a-uuid"):
                reply = await self.submit(bobbin_id, self.body_for(code, bobbin))
                self.assertEqual((reply.status, reply.json()["code"]), (404, "BOBBIN_NOT_FOUND"), (code, bobbin_id))
            self.assertEqual((await self.submit(bobbin["id"], self.body_for(code, bobbin), "CALIDAD_SIN_SECTOR")).status, 404, code)
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('LEGACY-Q3')")
        legacy = self.scalar("SELECT id FROM vinto_txn.bobbin WHERE code='LEGACY-Q3'")
        self.assertEqual((await self.submit(legacy, self.body_for(P124_CODE, {"code": "LEGACY-Q3"}))).status, 404)
        self.assertEqual({k: v for k, v in self.counts().items() if k != "vinto_txn.bobbin"}, {k: v for k, v in before.items() if k != "vinto_txn.bobbin"})

    async def test_idempotency_201_200_and_409(self):
        _, a = await self.bobbin()
        _, b = await self.bobbin()
        for code in FORMS:
            body = self.body_for(code, a)
            first = await self.submit(a["id"], body)
            self.assertEqual(first.status, 201)
            before = (self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
            again = await self.submit(a["id"], body)
            self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
            self.assertEqual(again.json()["capture"], first.json()["capture"])
            self.assertEqual((self.counts(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
            changed = await self.submit(a["id"], {**body, "values": {**body["values"], "crepado": "99.9"}})
            self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
            other = await self.submit(b["id"], {**body, "values": {**body["values"], "numero_de_bobina": b["code"]}})
            self.assertEqual((other.status, other.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
            other_form = P125_CODE if code == P124_CODE else P124_CODE
            self.assertEqual((await self.submit(a["id"], {**self.body_for(other_form, a), "capture_id": body["capture_id"]})).status, 409)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (b["id"],)), 0)

    async def test_concurrency_identical_posts_create_one_capture(self):
        _, bobbin = await self.bobbin()
        for code, (values, *_) in FORMS.items():
            body = self.body_for(code, bobbin)
            replies = await asyncio.gather(*[self.submit(bobbin["id"], body) for _ in range(5)])
            self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201], code)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), len(values))

    async def test_roles_and_audit_and_the_bobbin_and_release_stay_untouched(self):
        _, bobbin = await self.bobbin()
        row = self.connection.execute("SELECT * FROM vinto_txn.bobbin WHERE id = %s", (bobbin["id"],)).fetchone()
        release, audits = self.release(bobbin["id"]), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        for code in FORMS:
            body = self.body_for(code, bobbin)
            self.assertEqual((await call("POST", f"/api/quality/bobbins/{bobbin['id']}/captures", json_body=body)).status, 401)
            before = self.counts()
            for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
                self.assertEqual((await self.submit(bobbin["id"], body, who)).status, 403, (code, who))
            self.assertEqual(self.counts(), before)
            self.assertEqual((await self.submit(bobbin["id"], body)).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audits)
        self.assertEqual(self.connection.execute("SELECT * FROM vinto_txn.bobbin WHERE id = %s", (bobbin["id"],)).fetchone(), row)
        self.assertEqual(self.release(bobbin["id"]), release)

    async def test_the_payload_stays_closed(self):
        _, bobbin = await self.bobbin()
        for code in FORMS:
            for extra in ({"bobbin_id": bobbin["id"]}, {"machine_code": "MP1"}, {"assignment_id": str(uuid4())}, {"hora": "07:00"}, {"form_version_id": str(uuid4())}):
                self.assertEqual((await self.submit(bobbin["id"], {**self.body_for(code, bobbin), **extra})).status, 422, (code, extra))


class ReadTests(Base):
    async def test_history_is_independent_per_form_and_bobbin_and_does_not_mix_with_p1_21_or_machine_reads(self):
        _, a = await self.bobbin()
        _, b = await self.bobbin()
        c24 = (await self.submit(a["id"], self.body_for(P124_CODE, a))).json()["capture"]
        c25 = (await self.submit(a["id"], self.body_for(P125_CODE, a))).json()["capture"]
        c21 = (await self.submit(a["id"], self.body(a))).json()["capture"]  # P1-21 (DEV-Q2) on the same bobbin
        cb = (await self.submit(b["id"], self.body_for(P124_CODE, b))).json()["capture"]
        ids = lambda reply: [x["id"] for x in reply.json()]
        self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{a['id']}/captures?form_code={P124_CODE}")), [c24["id"]])
        self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{a['id']}/captures?form_code={P125_CODE}")), [c25["id"]])
        self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{a['id']}/captures?form_code={P121_CODE}")), [c21["id"]])
        self.assertEqual({x for x in ids(await self.read(f"/api/quality/bobbins/{a['id']}/captures"))}, {c24["id"], c25["id"], c21["id"]})
        self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{b['id']}/captures?form_code={P124_CODE}")), [cb["id"]])
        self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{b['id']}/captures?form_code={P125_CODE}")), [])
        for capture in (c24, c25):
            got = await self.read(f"/api/quality/captures/{capture['id']}")
            self.assertEqual((got.status, got.json()["form"]["code"], got.json()["values"]), (200, capture["form"]["code"], capture["values"]))
            self.assertEqual((await self.read(f"/api/quality/machine-captures/{capture['id']}")).status, 404)  # not a machine-level control
            self.assertEqual((await self.read(f"/api/quality/captures/{capture['id']}", "CALIDAD_SIN_SECTOR")).status, 404)
            self.assertEqual((await self.read(f"/api/quality/captures/{capture['id']}", "OPERACION")).status, 403)
            self.assertEqual((await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))).status, 404)
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset({P121_CODE})):  # P1-24 / P1-25 disabled, P1-21 untouched
            self.assertEqual((await self.read(f"/api/quality/captures/{c24['id']}")).status, 404)
            self.assertEqual({x for x in ids(await self.read(f"/api/quality/bobbins/{a['id']}/captures"))}, {c21["id"]})
            self.assertEqual((await self.read(f"/api/quality/captures/{c21['id']}")).status, 200)


class UnavailableTests(Base):
    install = staticmethod(lambda connection: (install_p121(connection), install_p124(connection, machine_codes=("MP1",)), install_p125(connection, publish=False)))

    async def test_a_form_without_the_machine_link_or_unpublished_is_not_available(self):
        _, mp1 = await self.bobbin("MP1")
        _, mp3 = await self.bobbin("MP3")
        machines = {m["code"]: sorted(f["code"] for f in m["forms"]) for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P121_CODE, P124_CODE], "MP3": [P121_CODE]})
        reply = await self.submit(mp3["id"], self.body_for(P124_CODE, mp3))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        reply = await self.submit(mp1["id"], self.body_for(P125_CODE, mp1))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        self.assertEqual((await self.submit(mp1["id"], self.body_for(P124_CODE, mp1))).status, 201)


class RegressionTests(Base):
    async def test_p1_21_keeps_its_behavior_alongside_the_new_candidates(self):
        _, bobbin = await self.bobbin()
        ok = await self.submit(bobbin["id"], self.body(bobbin))
        self.assertEqual(ok.status, 201)
        self.assertEqual(ok.json()["capture"]["values"], {**P121_VALUES, "numero_de_bobina": bobbin["code"]})
        bad = await self.submit(bobbin["id"], self.body(bobbin, values={**P121_VALUES, "numero_de_bobina": "999999"}))
        self.assertEqual(bad.status, 422)
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset({P124_CODE})):  # P1-21 disabled independently
            self.assertEqual((await self.submit(bobbin["id"], self.body(bobbin))).status, 422)
            self.assertEqual((await self.submit(bobbin["id"], self.body_for(P124_CODE, bobbin))).status, 201)


if __name__ == "__main__":
    unittest.main()
