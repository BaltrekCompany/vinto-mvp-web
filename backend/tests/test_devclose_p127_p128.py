"""DEV-CLOSE: the CANDIDATE VINTO-P1-27 (Análisis de agua para caldero, 23 manual fields) runs through the machine-level Quality capture route (/api/quality/machines/{machine}/captures) and the CANDIDATE
VINTO-P1-28 (Registro de bobinas rechazadas, 7 manual fields) is a DOCUMENTARY sheet that runs through the bobbin-level Quality capture route (/api/quality/bobbins/{bobbin_id}/captures) of F3 bobbins.

Installed in an ephemeral *_test database (tests/devclose_fixtures.py, generated from the legacy definitions) and enabled per test with patch.object (machine policy MACHINE_QUALITY_FORM_CODES / bobbin policy
ENABLED_BOBBIN_CANDIDATE_FORM_CODES); the shipped policies (both empty), the production policy and the operational sectors are asserted unchanged. NOT a homologation and NOT a rejection: the alkalinity is never
calculated; P1-28 declares a free-text «estado / disposición final» but NEVER changes quality_release, the bobbin or the inventory, creates no approval / signature, no rejection endpoint exists and the audit only
contains the normal capture events.
"""

import asyncio
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr  # noqa: F401  (kept for parity with the other modules)

from app import capture_service as _capture_service
from app import sectors as _sectors
from app.ephemeral_db import build_reference_template, drop_database
from app.quality import capture_service as _quality_service
from app.quality import machine_capture_service as _machine_service

try:
    import test_devq2_p118_p121 as q2
    import test_f3_bobbins_api as f3
    from devclose_fixtures import P127_CODE, P127_FIELDS, P127_VALUES, P128_CODE, P128_FIELDS, P128_VALUES, install_p127, install_p128
    from devq2_fixtures import install_p121
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_devq2_p118_p121 as q2
    import tests.test_f3_bobbins_api as f3
    from tests.devclose_fixtures import P127_CODE, P127_FIELDS, P127_VALUES, P128_CODE, P128_FIELDS, P128_VALUES, install_p127, install_p128
    from tests.devq2_fixtures import install_p121
    from tests.test_assignments_api import call

SHIPPED_MACHINE_POLICY = _machine_service.MACHINE_QUALITY_FORM_CODES  # captured at import, before any patch
SHIPPED_BOBBIN_POLICY = _quality_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES
SHIPPED_PRODUCTION_POLICY = _capture_service.CENTRAL_FORM_CODES
SHIPPED_SECTORS = _sectors.operational_sector_codes()
STATE = {}
AUTO27 = ("fecha", "turno", "responsable", "purga_caldero_alcalinidad_total")
AUTO28 = ("fecha", "hora", "maquina", "operador", "responsable_de_calidad", "visto_bueno_produccion")
DECISION_KEYS = ("estado", "status", "decision", "decided_by", "decision_reason", "aprobado", "rechazado", "liberado")


def setUpModule():
    STATE["template"] = build_reference_template("vinto_devclose_tpl")
    q2.STATE["template"] = STATE["template"]  # the machine-level base of DEV-Q2 copies this bare template
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])
        f3.STATE.pop("template", None)
        q2.STATE.pop("template", None)


# ---------------------------------------------------------------- P1-27 · machine level


class MachineBase(q2.MachineBase):
    install = staticmethod(lambda connection: install_p127(connection))
    prefix = "vinto_devclose_m"

    async def asyncSetUp(self):
        await super().asyncSetUp()
        policy = patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset({P127_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    def body27(self, **changes):
        body = {"capture_id": str(uuid4()), "form_code": P127_CODE, "device_key": str(uuid4()), "values": dict(P127_VALUES)}
        body.update(changes)
        return body


class P127ConfigurationTests(MachineBase):
    async def test_the_shipped_configuration_is_unchanged_and_the_form_is_unreachable_without_the_test_policy(self):
        self.assertEqual(SHIPPED_MACHINE_POLICY, frozenset())
        self.assertEqual(SHIPPED_BOBBIN_POLICY, frozenset())
        self.assertEqual(SHIPPED_PRODUCTION_POLICY, frozenset({"VINTO-P1-06"}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", SHIPPED_MACHINE_POLICY):
            reply = await self.post(self.body27())
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
            self.assertEqual((await self.get(f"/api/quality/machines/MP1/captures?form_code={P127_CODE}")).status, 422)
            self.assertEqual([m["forms"] for s in (await self.get("/api/quality/machine-forms")).json()["sectors"] for m in s["machines"]], [[], []])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)

    async def test_the_backend_publishes_the_form_on_mp1_and_mp3_only_to_quality_users_in_scope(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/quality/machine-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P127_CODE], "MP3": [P127_CODE]})
        self.assertEqual((await self.get("/api/quality/machine-forms", "CALIDAD_SIN_SECTOR")).json()["sectors"], [])
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.get("/api/quality/machine-forms", who)).status, 403, who)

    async def test_the_candidate_contract_is_exactly_the_23_manual_legacy_fields(self):
        self.assertEqual(len(P127_FIELDS), 23)
        stored = [tuple(r) for r in self.connection.execute(
            """SELECT fd.key, fd.label, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (P127_CODE,)).fetchall()]
        self.assertEqual(stored, [(k, label, t, r, "quality") for k, label, t, r, _ in P127_FIELDS])
        self.assertTrue(all(k not in AUTO27 for k, *_ in stored))
        kinds = {k: t for k, _, t, *_ in P127_FIELDS}
        for key, kind in kinds.items():
            if key.endswith(("_ph", "_dureza")):
                self.assertEqual(kind, "decimal", key)
            elif key.endswith(("solidos_disueltos", "conductividad", "cloruros")) or key == "calibracion_equipo_multiparametro":
                self.assertEqual(kind, "text", key)  # NOT decimal because they look like magnitudes
        self.assertEqual((kinds["observaciones"], [f[3] for f in P127_FIELDS if f[0] == "observaciones"]), ("textarea", [False]))
        self.assertTrue(all(k in kinds for k in ("condensado_mp1_ph", "condensado_mp3_ph", "condensado_mp1_conductividad", "condensado_mp3_conductividad")))


class P127WriteTests(MachineBase):
    async def test_201_the_complete_contract_is_persisted_on_each_machine_without_bobbin_assignment_or_work_order(self):
        for machine in ("MP1", "MP3"):
            reply = await self.post(self.body27(), machine)
            self.assertEqual(reply.status, 201, (machine, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (P127_CODE, "submitted", 1, machine))
            self.assertEqual(capture["recorded_by"], {"id": str(self.users["CALIDAD"][0].user_id), "display_name": "Calidad"})
            self.assertEqual(capture["values"], P127_VALUES)
            kinds = {k: t for k, _, t, *_ in P127_FIELDS}
            stored = self.rows(capture["id"])
            self.assertEqual(stored, {k: f"{kinds[k]}:{v}" for k, v in P127_VALUES.items()})
            self.assertEqual(len(stored), 23)  # the MP1 AND MP3 condensado fields are kept on whichever machine is selected: nothing is removed or inferred
            for key in ("condensado_mp1_ph", "condensado_mp1_dureza", "condensado_mp3_ph", "condensado_mp3_dureza"):
                self.assertIn(key, stored, (machine, key))
            row = self.connection.execute("SELECT assignment_id, bobbin_id, created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)).fetchone()
            self.assertEqual(row, (None, None, self.users["CALIDAD"][0].user_id))
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.work_order"), self.scalar("SELECT count(*) FROM vinto_txn.assignment"), self.scalar("SELECT count(*) FROM vinto_txn.bobbin")), (0, 0, 0))

    async def test_text_magnitudes_are_stored_as_typed_text_and_the_alkalinity_is_never_calculated_or_accepted(self):
        values = {**P127_VALUES, "ablandador_solidos_disueltos": "1.250 ppm", "purga_caldero_conductividad": "2,5 mS", "purga_caldero_cloruros": "n/d", "calibracion_equipo_multiparametro": "calibrado 06:30"}
        capture = (await self.post(self.body27(values=values))).json()["capture"]
        stored = self.rows(capture["id"])
        for key in ("ablandador_solidos_disueltos", "purga_caldero_conductividad", "purga_caldero_cloruros", "calibracion_equipo_multiparametro"):
            self.assertEqual(stored[key], f"text:{values[key]}", key)
        for key in AUTO27:
            self.assertNotIn(key, stored)
            self.assertNotIn(key, capture["values"])
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for key in AUTO27 + ("aprobado", "limite", "condensado"):
            reply = await self.post(self.body27(values={**P127_VALUES, key: "1"}))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), key)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_every_obligatory_field_is_required_observations_are_optional_and_invalid_values_persist_nothing(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for key in [f[0] for f in P127_FIELDS if f[3]]:
            reply = await self.post(self.body27(values={k: v for k, v in P127_VALUES.items() if k != key}))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), key)
        for key in [f[0] for f in P127_FIELDS if f[2] == "decimal"]:
            for bad in ("7,2", "abc", "1e3", "", True, None):
                self.assertEqual((await self.post(self.body27(values={**P127_VALUES, key: bad}))).status, 422, (key, bad))
        self.assertEqual((await self.post(self.body27(values={**P127_VALUES, "ablandador_solidos_disueltos": None}))).status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)
        ok = await self.post(self.body27(values={k: v for k, v in P127_VALUES.items() if k != "observaciones"}))
        self.assertEqual(ok.status, 201, ok.text)
        self.assertNotIn("observaciones", ok.json()["capture"]["values"])

    async def test_idempotency_201_200_409_and_concurrency(self):
        body = self.body27()
        first = await self.post(body)
        self.assertEqual(first.status, 201)
        before = (self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        again = await self.post(body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.capture"), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail"), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)
        changed = await self.post({**body, "values": {**body["values"], "purga_caldero_ph": "9.9"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual((await self.post(body, "MP3")).status, 409)  # same id, another machine
        racing = self.body27()
        replies = await asyncio.gather(*[self.post(racing) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (racing["capture_id"],)), 23)

    async def test_roles_scope_closed_payload_and_audit(self):
        body = self.body27()
        self.assertEqual((await call("POST", "/api/quality/machines/MP1/captures", json_body=body)).status, 401)
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.post(body, who=who)).status, 403, who)
        reply = await self.post(body, who="CALIDAD_SIN_SECTOR")
        self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        self.assertEqual((await self.post(body, "MP99")).status, 404)
        for extra in ({"machine_code": "MP1"}, {"assignment_id": str(uuid4())}, {"bobbin_id": str(uuid4())}, {"hora": "07:00"}):
            self.assertEqual((await self.post({**self.body27(), **extra})).status, 422, extra)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)
        audits = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        self.assertEqual((await self.post(self.body27())).status, 201)
        self.assertGreater(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), audits)

    async def test_get_history_and_no_mixing(self):
        a = (await self.post(self.body27(), "MP1")).json()["capture"]
        b = (await self.post(self.body27(), "MP3")).json()["capture"]
        got = await self.get(f"/api/quality/machine-captures/{a['id']}")
        self.assertEqual((got.status, got.json()["form"]["code"], got.json()["values"]), (200, P127_CODE, a["values"]))
        mp1 = (await self.get(f"/api/quality/machines/MP1/captures?form_code={P127_CODE}")).json()
        mp3 = (await self.get(f"/api/quality/machines/MP3/captures?form_code={P127_CODE}")).json()
        self.assertIn(a["id"], {x["id"] for x in mp1})
        self.assertNotIn(b["id"], {x["id"] for x in mp1})
        self.assertIn(b["id"], {x["id"] for x in mp3})
        self.assertEqual({x["form"]["code"] for x in mp1 + mp3}, {P127_CODE})
        self.assertEqual((await self.get(f"/api/quality/machine-captures/{a['id']}", "CALIDAD_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.get(f"/api/quality/captures/{a['id']}")).status, 404)  # not a bobbin capture
        self.assertEqual((await call("GET", f"/api/captures/{a['id']}", cookie=await self.cookie("OPERACION"))).status, 404)
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", SHIPPED_MACHINE_POLICY):
            self.assertEqual((await self.get(f"/api/quality/machine-captures/{a['id']}")).status, 404)


class P127UnavailableTests(MachineBase):
    install = staticmethod(lambda connection: install_p127(connection, machine_codes=("MP1",)))
    prefix = "vinto_devclose_mu"

    async def test_a_machine_without_the_link_is_not_available(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.get("/api/quality/machine-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P127_CODE], "MP3": []})
        reply = await self.post(self.body27(), "MP3")
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


# ---------------------------------------------------------------- P1-28 · bobbin level (documentary)


class BobbinBase(q2.BobbinBase):
    install = staticmethod(lambda connection: (install_p121(connection), install_p128(connection)))

    async def asyncSetUp(self):
        await super().asyncSetUp()
        policy = patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset({P128_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    def body28(self, bobbin, **changes):
        body = {"capture_id": str(uuid4()), "form_code": P128_CODE, "device_key": str(uuid4()), "values": {**P128_VALUES, "numero_de_bobina": bobbin["code"]}}
        body.update(changes)
        return body

    def bobbin_row(self, bobbin_id):
        return self.connection.execute("SELECT * FROM vinto_txn.bobbin WHERE id = %s", (bobbin_id,)).fetchone()

    def audit_counts(self):
        """Audit events per entity table (the F3 creation of the bobbin and its pending release legitimately appear here; a capture must add NONE for the bobbin or quality_release)."""
        return dict(self.connection.execute("SELECT entity_table, count(*) FROM vinto_audit.audit_event GROUP BY entity_table").fetchall())


class P128ConfigurationTests(BobbinBase):
    async def test_the_candidate_is_known_but_disabled_by_default_and_unreachable_without_the_test_policy(self):
        self.assertEqual(SHIPPED_BOBBIN_POLICY, frozenset())
        self.assertIn(P128_CODE, _quality_service.BOBBIN_CANDIDATE_FORM_CODES)
        self.assertEqual(_quality_service.BOBBIN_CODE_FIELDS[P128_CODE], "numero_de_bobina")
        _, bobbin = await self.bobbin()
        ok = await self.submit(bobbin["id"], self.body28(bobbin))
        self.assertEqual(ok.status, 201, ok.text)
        before = self.counts()
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", SHIPPED_BOBBIN_POLICY):  # published in PostgreSQL but disabled by policy
            reply = await self.submit(bobbin["id"], self.body28(bobbin))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
            self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={P128_CODE}")).status, 422)
            self.assertEqual((await self.read(f"/api/quality/captures/{ok.json()['capture']['id']}")).status, 404)
            self.assertEqual([m["forms"] for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]], [[], []])
            self.assertEqual(self.counts(), before)

    async def test_the_backend_publishes_it_on_mp1_and_mp3_only_to_quality_users_in_scope(self):
        machines = {m["code"]: [f["code"] for f in m["forms"]] for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]}
        self.assertEqual(machines, {"MP1": [P128_CODE], "MP3": [P128_CODE]})
        self.assertEqual((await self.read("/api/quality/bobbin-forms", "CALIDAD_SIN_SECTOR")).json()["sectors"], [])
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.read("/api/quality/bobbin-forms", who)).status, 403, who)

    async def test_the_candidate_contract_is_exactly_the_seven_manual_legacy_fields(self):
        self.assertEqual([f[0] for f in P128_FIELDS], ["numero_de_bobina", "producto", "detalle_motivo_de_rechazo", "accion_correctiva", "peso_rechazado", "estado_disposicion_final", "observaciones"])
        stored = [tuple(r) for r in self.connection.execute(
            """SELECT fd.key, fd.label, fd.value_type, fd.required, fv.area FROM vinto_config.field_definition fd JOIN vinto_config.form_version fv ON fv.id = fd.form_version_id
               JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s ORDER BY fd.display_order""", (P128_CODE,)).fetchall()]
        self.assertEqual(stored, [(k, label, t, r, "quality") for k, label, t, r, _ in P128_FIELDS])
        self.assertEqual({k: t for k, _, t, *_ in P128_FIELDS}["detalle_motivo_de_rechazo"], "textarea")
        self.assertEqual({k: t for k, _, t, *_ in P128_FIELDS}["estado_disposicion_final"], "text")  # free text, not a catalog or a status
        self.assertTrue(all(k not in AUTO28 for k, *_ in stored))


class P128WriteTests(BobbinBase):
    async def test_201_is_persisted_against_the_physical_bobbin_uuid_and_the_official_state_is_untouched(self):
        for machine in ("MP1", "MP3"):
            assignment, bobbin = await self.bobbin(machine)
            before = {"release": self.release(bobbin["id"]), "bobbin": self.bobbin_row(bobbin["id"]), "audit": self.audit_counts()}
            reply = await self.submit(bobbin["id"], self.body28(bobbin))
            self.assertEqual(reply.status, 201, (machine, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (P128_CODE, "submitted", 1, machine))
            self.assertEqual(capture["bobbin"], {"id": bobbin["id"], "code": bobbin["code"]})
            self.assertEqual(capture["values"], {**P128_VALUES, "numero_de_bobina": bobbin["code"]})
            row = self.connection.execute("SELECT assignment_id, bobbin_id, created_by FROM vinto_txn.capture WHERE id = %s", (capture["id"],)).fetchone()
            self.assertEqual((str(row[0]), str(row[1]), row[2]), (assignment["id"], bobbin["id"], self.users["CALIDAD"][0].user_id))
            kinds = {k: t for k, _, t, *_ in P128_FIELDS}
            self.assertEqual(self.rows(capture["id"]), {k: f"{kinds[k]}:{v}" for k, v in {**P128_VALUES, "numero_de_bobina": bobbin["code"]}.items()})
            # the sheet DECLARES «rechazado» but the official Quality state, the bobbin and the audit trail are exactly as before
            self.assertEqual(capture["values"]["estado_disposicion_final"], "rechazado (texto declarado en la ficha)")
            self.assertEqual(self.release(bobbin["id"]), before["release"])
            self.assertEqual(before["release"][0], "pending")
            self.assertEqual((self.release(bobbin["id"])[1], self.release(bobbin["id"])[2], self.release(bobbin["id"])[3]), (None, None, None))
            self.assertEqual(self.bobbin_row(bobbin["id"]), before["bobbin"])
            inbox = {i["bobbin"]["id"]: i for i in (await self.read("/api/quality/bobbins")).json()}
            self.assertEqual(inbox[bobbin["id"]]["quality"]["status"], "pending")  # still listed as pending Quality
            self.assertEqual((await self.read("/api/quality/bobbins?status=rejected")).json(), [])
            self.assertNotIn(bobbin["id"], {i["bobbin"]["id"] for i in (await self.read("/api/quality/bobbins?status=released")).json()})
            after = self.audit_counts()
            changed = {t for t in set(after) | set(before["audit"]) if after.get(t, 0) != before["audit"].get(t, 0)}
            self.assertEqual(changed, {"capture", "capture_detail"} | ({"device"} & changed))  # only the normal capture audit (insert / submit, details and, the first time, the device)
            self.assertEqual((after.get("quality_release", 0), after.get("bobbin", 0)), (before["audit"].get("quality_release", 0), before["audit"].get("bobbin", 0)))  # no audit event simulates a decision

    async def test_no_manual_field_is_interpreted_as_a_decision_signature_or_approval(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        release = self.release(bobbin["id"])
        for key in AUTO28 + DECISION_KEYS:
            body = self.body28(bobbin)
            body["values"][key] = "x"
            reply = await self.submit(bobbin["id"], body)
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), key)
        self.assertEqual(self.counts(), before)
        capture = (await self.submit(bobbin["id"], self.body28(bobbin))).json()["capture"]
        for key in AUTO28:
            self.assertNotIn(key, capture["values"])
            self.assertNotIn(key, self.rows(capture["id"]))
        self.assertEqual(self.release(bobbin["id"]), release)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE status <> 'pending' OR decided_by IS NOT NULL OR decided_at IS NOT NULL OR decision_reason IS NOT NULL"), 0)

    async def test_a_declared_bobbin_number_that_contradicts_the_selected_bobbin_is_rejected(self):
        _, a = await self.bobbin("MP1")
        _, b = await self.bobbin("MP3")
        before = self.counts()
        for declared in (str(int(a["code"]) + 1000), "999999", "", "abc", b["code"] if b["code"] != a["code"] else "x"):
            reply = await self.submit(a["id"], self.body28(a, values={**self.body28(a)["values"], "numero_de_bobina": declared}))
            self.assertEqual(reply.status, 422, (declared, reply.text))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (b["id"],)), 0)

    async def test_unknown_out_of_scope_and_legacy_bobbins_are_404(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        for bobbin_id in (str(uuid4()), "not-a-uuid"):
            reply = await self.submit(bobbin_id, self.body28(bobbin))
            self.assertEqual((reply.status, reply.json()["code"]), (404, "BOBBIN_NOT_FOUND"), bobbin_id)
        self.assertEqual((await self.submit(bobbin["id"], self.body28(bobbin), "CALIDAD_SIN_SECTOR")).status, 404)
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('LEGACY-CLOSE')")
        legacy = self.scalar("SELECT id FROM vinto_txn.bobbin WHERE code='LEGACY-CLOSE'")
        self.assertEqual((await self.submit(legacy, self.body28({"code": "LEGACY-CLOSE"}))).status, 404)
        self.assertEqual({k: v for k, v in self.counts().items() if k != "vinto_txn.bobbin"}, {k: v for k, v in before.items() if k != "vinto_txn.bobbin"})

    async def test_every_obligatory_field_is_required_and_invalid_values_persist_nothing(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        base = self.body28(bobbin)["values"]
        for key in [f[0] for f in P128_FIELDS if f[3]]:
            reply = await self.submit(bobbin["id"], self.body28(bobbin, values={k: v for k, v in base.items() if k != key}))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), key)
        for bad in ("12,5", "abc", "1e3", "", True, None):
            self.assertEqual((await self.submit(bobbin["id"], self.body28(bobbin, values={**base, "peso_rechazado": bad}))).status, 422, bad)
        for key in ("producto", "accion_correctiva", "estado_disposicion_final", "detalle_motivo_de_rechazo"):
            self.assertEqual((await self.submit(bobbin["id"], self.body28(bobbin, values={**base, key: "   "}))).status, 422, key)
        self.assertEqual(self.counts(), before)
        ok = await self.submit(bobbin["id"], self.body28(bobbin, values={k: v for k, v in base.items() if k != "observaciones"}))
        self.assertEqual(ok.status, 201, ok.text)
        self.assertNotIn("observaciones", ok.json()["capture"]["values"])

    async def test_idempotency_concurrency_roles_and_closed_payload(self):
        _, a = await self.bobbin()
        _, b = await self.bobbin()
        body = self.body28(a)
        first = await self.submit(a["id"], body)
        self.assertEqual(first.status, 201)
        again = await self.submit(a["id"], body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(again.json()["capture"], first.json()["capture"])
        changed = await self.submit(a["id"], {**body, "values": {**body["values"], "peso_rechazado": "1.00"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        other = await self.submit(b["id"], {**body, "values": {**body["values"], "numero_de_bobina": b["code"]}})
        self.assertEqual((other.status, other.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        racing = self.body28(a)
        replies = await asyncio.gather(*[self.submit(a["id"], racing) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (racing["capture_id"],)), 7)
        self.assertEqual((await call("POST", f"/api/quality/bobbins/{a['id']}/captures", json_body=self.body28(a))).status, 401)
        before = self.counts()
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.submit(a["id"], self.body28(a), who)).status, 403, who)
        for extra in ({"bobbin_id": a["id"]}, {"machine_code": "MP1"}, {"assignment_id": str(uuid4())}, {"status": "rejected"}, {"decision": "rechazar"}):
            self.assertEqual((await self.submit(a["id"], {**self.body28(a), **extra})).status, 422, extra)
        self.assertEqual(self.counts(), before)

    async def test_history_is_filtered_by_form_and_bobbin_and_does_not_mix_with_other_candidates_or_machine_reads(self):
        _, a = await self.bobbin()
        _, b = await self.bobbin()
        ids = lambda reply: [x["id"] for x in reply.json()]
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset({P128_CODE, "VINTO-P1-21"})):  # P1-21 (DEV-Q2) enabled together with P1-28 for this check
            c28 = (await self.submit(a["id"], self.body28(a))).json()["capture"]
            c21 = (await self.submit(a["id"], self.body(a))).json()["capture"]
            self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{a['id']}/captures?form_code={P128_CODE}")), [c28["id"]])
            self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{a['id']}/captures?form_code=VINTO-P1-21")), [c21["id"]])
            self.assertEqual(ids(await self.read(f"/api/quality/bobbins/{b['id']}/captures?form_code={P128_CODE}")), [])
        got = await self.read(f"/api/quality/captures/{c28['id']}")
        self.assertEqual((got.status, got.json()["bobbin"], got.json()["values"]), (200, {"id": a["id"], "code": a["code"]}, c28["values"]))
        self.assertEqual((await self.read(f"/api/quality/captures/{c28['id']}", "CALIDAD_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.read(f"/api/quality/captures/{c28['id']}", "OPERACION")).status, 403)
        self.assertEqual((await self.read(f"/api/quality/machine-captures/{c28['id']}")).status, 404)
        self.assertEqual((await call("GET", f"/api/captures/{c28['id']}", cookie=await self.cookie("OPERACION"))).status, 404)
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset({P127_CODE})):  # the machine policy does not know the documentary sheet
            reply = await call("POST", "/api/quality/machines/MP1/captures", json_body={"capture_id": str(uuid4()), "form_code": P128_CODE, "device_key": str(uuid4()), "values": dict(P128_VALUES)},
                               cookie=await self.cookie("CALIDAD"))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))


class P128UnavailableTests(BobbinBase):
    install = staticmethod(lambda connection: install_p128(connection, machine_codes=("MP1",)))

    async def test_a_bobbin_whose_machine_has_no_form_link_gets_409(self):
        _, mp1 = await self.bobbin("MP1")
        _, mp3 = await self.bobbin("MP3")
        reply = await self.submit(mp3["id"], self.body28(mp3))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        self.assertEqual((await self.submit(mp1["id"], self.body28(mp1))).status, 201)


class P128UnpublishedTests(BobbinBase):
    install = staticmethod(lambda connection: install_p128(connection, publish=False))

    async def test_an_unpublished_candidate_is_not_available(self):
        _, bobbin = await self.bobbin()
        self.assertEqual([m["forms"] for s in (await self.read("/api/quality/bobbin-forms")).json()["sectors"] for m in s["machines"]], [[], []])
        reply = await self.submit(bobbin["id"], self.body28(bobbin))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


if __name__ == "__main__":
    unittest.main()
