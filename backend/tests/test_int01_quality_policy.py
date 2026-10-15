"""INT-01A: the bobbin-level Quality route (/api/quality/bobbins/{bobbin_id}/captures, /api/quality/captures/{id}) has a POSITIVE, explicit policy.

It only accepts (write, idempotent retry, read by id, history and filtered history) the CENTRAL forms VINTO-P1-19 / VINTO-P1-20 plus the bobbin candidates (P1-21 / P1-24 / P1-25 / P1-28) when ENABLED_BOBBIN_CANDIDATE_FORM_CODES
enables them. Publishing a quality form in PostgreSQL and linking it to the bobbin's machine is NOT enough: the machine-level forms (P1-18 / P1-22 / P1-26 / P1-27) and any unknown quality form are rejected (422
UNSUPPORTED_FORM) and their rows are invisible (404) on this route, even when they were inserted by other means. The machine-level API and quality_release are untouched.

Everything runs in ephemeral *_test databases; the shipped policies are asserted unchanged.
"""

import asyncio
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import capture_service as _capture_service
from app.ephemeral_db import build_reference_template, drop_database
from app.quality import capture_service as _quality_service
from app.quality import machine_capture_service as _machine_service

try:
    import test_devq2_p118_p121 as q2
    import test_f3_bobbins_api as f3
    from devclose_fixtures import P127_CODE, P127_VALUES, P128_CODE, P128_VALUES, install_p127, install_p128
    from devq1_fixtures import P122_CODE, P122_VALUES, P126_CODE, P126_VALUES, install_p122, install_p126
    from devq2_fixtures import P118_CODE, P118_VALUES, P121_CODE, P121_VALUES, _install, install_p118, install_p121
    from devq3_fixtures import P124_CODE, P124_VALUES, P125_CODE, P125_VALUES, install_p124, install_p125
    from test_assignments_api import call
    from test_quality_capture_api import P119, P119_VALUES, P120, P120_VALUES
except ModuleNotFoundError:
    import tests.test_devq2_p118_p121 as q2
    import tests.test_f3_bobbins_api as f3
    from tests.devclose_fixtures import P127_CODE, P127_VALUES, P128_CODE, P128_VALUES, install_p127, install_p128
    from tests.devq1_fixtures import P122_CODE, P122_VALUES, P126_CODE, P126_VALUES, install_p122, install_p126
    from tests.devq2_fixtures import P118_CODE, P118_VALUES, P121_CODE, P121_VALUES, _install, install_p118, install_p121
    from tests.devq3_fixtures import P124_CODE, P124_VALUES, P125_CODE, P125_VALUES, install_p124, install_p125
    from tests.test_assignments_api import call
    from tests.test_quality_capture_api import P119, P119_VALUES, P120, P120_VALUES

SHIPPED_CENTRAL = _quality_service.CENTRAL_BOBBIN_FORM_CODES  # captured at import, before any patch
SHIPPED_ENABLED = _quality_service.ENABLED_BOBBIN_CANDIDATE_FORM_CODES
SHIPPED_MACHINE = _machine_service.MACHINE_QUALITY_FORM_CODES
STATE = {}
UNKNOWN = "QA-UNKNOWN-QUALITY"
UNKNOWN_FIELDS = (("dato", "Dato", "text", True, ()),)
UNKNOWN_VALUES = {"dato": "x"}
CENTRAL = {P119: P119_VALUES, P120: P120_VALUES}
CANDIDATES = {P121_CODE: P121_VALUES, P124_CODE: P124_VALUES, P125_CODE: P125_VALUES, P128_CODE: P128_VALUES}
MACHINE_ONLY = {P118_CODE: P118_VALUES, P122_CODE: P122_VALUES, P126_CODE: P126_VALUES, P127_CODE: P127_VALUES}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_int01_tpl")
    q2.STATE["template"] = STATE["template"]
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])
        f3.STATE.pop("template", None)
        q2.STATE.pop("template", None)


def install_everything(connection):
    for install in (install_p118, install_p122, install_p126, install_p127, install_p121, install_p124, install_p125, install_p128):
        install(connection)  # every quality form below is PUBLISHED and LINKED to MP1 / MP3
    _install(connection, UNKNOWN, UNKNOWN_FIELDS, "Formulario quality desconocido (prueba INT-01)", ("MP1", "MP3"), True)


class Base(q2.BobbinBase):
    install = staticmethod(install_everything)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # q2.BobbinBase enables P1-21 only; this suite controls the policy explicitly in each test (default: the SHIPPED policy)
        policy = patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", SHIPPED_ENABLED)
        policy.start()
        self.addCleanup(policy.stop)

    def post_body(self, code, values, bobbin):
        return {"capture_id": str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": {**values, **({"numero_de_bobina": bobbin["code"]} if "numero_de_bobina" in values else {})}}

    async def insert_hostile_capture(self, code, bobbin, values):
        """A SUBMITTED, complete capture of `code` carrying bobbin_id (what a past bug, a looser policy or a manual load could have left behind): created through the real route under a TEMPORARY looser
        policy, then the policy is restored. The route must not expose it afterwards."""
        with patch.object(_quality_service, "CENTRAL_BOBBIN_FORM_CODES", SHIPPED_CENTRAL | {code}):
            reply = await self.submit(bobbin["id"], self.post_body(code, values, bobbin))
        self.assertEqual(reply.status, 201, (code, reply.text))
        return reply.json()["capture"]["id"]


class ShippedPolicyTests(Base):
    async def test_the_shipped_policies_are_exactly_the_central_forms_and_nothing_else(self):
        self.assertEqual(SHIPPED_CENTRAL, frozenset({"VINTO-P1-19", "VINTO-P1-20"}))
        self.assertEqual(SHIPPED_ENABLED, frozenset())
        self.assertEqual(SHIPPED_MACHINE, frozenset())
        self.assertEqual(_quality_service.BOBBIN_CANDIDATE_FORM_CODES, frozenset(CANDIDATES))
        self.assertEqual(_quality_service._allowed_codes(), ["VINTO-P1-19", "VINTO-P1-20"])  # with the real configuration the route admits exactly P1-19 and P1-20
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE status <> 'pending'"), 0)


class CentralFormsTests(Base):
    async def test_p1_19_and_p1_20_are_captured_and_read_on_mp1_and_mp3_without_any_extra_policy(self):
        for machine in ("MP1", "MP3"):
            _, bobbin = await self.bobbin(machine)
            for code, values in CENTRAL.items():
                body = self.post_body(code, values, bobbin)
                reply = await self.submit(bobbin["id"], body)
                self.assertEqual(reply.status, 201, (machine, code, reply.text))
                capture = reply.json()["capture"]
                again = await self.submit(bobbin["id"], body)
                self.assertEqual((again.status, again.json()["already_submitted"]), (200, True))
                got = await self.read(f"/api/quality/captures/{capture['id']}")
                self.assertEqual((got.status, got.json()["form"]["code"]), (200, code))
                filtered = await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")
                self.assertEqual([x["id"] for x in filtered.json()], [capture["id"]])
            everything = await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures")
            self.assertEqual({x["form"]["code"] for x in everything.json()}, set(CENTRAL))
            self.assertEqual(self.release(bobbin["id"])[0], "pending")

    async def test_idempotency_conflict_and_concurrency_still_work_for_allowed_forms(self):
        _, bobbin = await self.bobbin()
        body = self.post_body(P119, P119_VALUES, bobbin)
        self.assertEqual((await self.submit(bobbin["id"], body)).status, 201)
        changed = await self.submit(bobbin["id"], {**body, "values": {**body["values"], "peso_seco_medio": "1.00"}})
        self.assertEqual((changed.status, changed.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        racing = self.post_body(P120, P120_VALUES, bobbin)
        replies = await asyncio.gather(*[self.submit(bobbin["id"], racing) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])

    async def test_roles_and_sector_scope_are_preserved(self):
        _, bobbin = await self.bobbin()
        body = self.post_body(P119, P119_VALUES, bobbin)
        self.assertEqual((await call("POST", f"/api/quality/bobbins/{bobbin['id']}/captures", json_body=body)).status, 401)
        before = self.counts()
        for who in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.submit(bobbin["id"], body, who)).status, 403, who)
        self.assertEqual((await self.submit(bobbin["id"], body, "CALIDAD_SIN_SECTOR")).status, 404)
        self.assertEqual(self.counts(), before)
        ok = (await self.submit(bobbin["id"], body)).json()["capture"]
        self.assertEqual((await self.read(f"/api/quality/captures/{ok['id']}", "CALIDAD_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.read(f"/api/quality/captures/{ok['id']}", "OPERACION")).status, 403)


class CandidatePolicyTests(Base):
    async def test_the_bobbin_candidates_are_blocked_without_the_policy_and_work_with_it(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        for code, values in CANDIDATES.items():  # published and linked, but the policy is the shipped (empty) one
            reply = await self.submit(bobbin["id"], self.post_body(code, values, bobbin))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)
            self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")).status, 422, code)
        self.assertEqual(self.counts(), before)
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset(CANDIDATES)):  # TEST-ONLY policy
            made = {}
            for code, values in CANDIDATES.items():
                reply = await self.submit(bobbin["id"], self.post_body(code, values, bobbin))
                self.assertEqual(reply.status, 201, (code, reply.text))
                made[code] = reply.json()["capture"]["id"]
            for code, capture_id in made.items():
                self.assertEqual((await self.read(f"/api/quality/captures/{capture_id}")).status, 200, code)
                self.assertEqual([x["id"] for x in (await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")).json()], [capture_id], code)
        for capture_id in made.values():  # policy off again: the rows still exist but this route no longer exposes them
            self.assertEqual((await self.read(f"/api/quality/captures/{capture_id}")).status, 404)
        self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures")).json(), [])
        self.assertEqual(self.release(bobbin["id"])[0], "pending")


class MachineOnlyAndUnknownFormsTests(Base):
    async def test_published_and_linked_machine_forms_and_unknown_quality_forms_cannot_be_written_to_a_bobbin(self):
        _, bobbin = await self.bobbin()
        before = self.counts()
        forms = {**MACHINE_ONLY, UNKNOWN: UNKNOWN_VALUES}
        for patched in (SHIPPED_ENABLED, frozenset(CANDIDATES)):  # neither the shipped nor the fully enabled bobbin policy admits them
            with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", patched), patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset(MACHINE_ONLY)):
                for code, values in forms.items():
                    reply = await self.submit(bobbin["id"], self.post_body(code, values, bobbin))
                    self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)
                    self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")).status, 422, code)
        self.assertEqual(self.counts(), before)
        for code in forms:  # the forms really are published and linked: the block is the policy, not a missing publication
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version_machine fvm JOIN vinto_config.form_version fv ON fv.id=fvm.form_version_id JOIN vinto_config.form f ON f.id=fv.form_id WHERE f.code=%s AND fv.status='published'", (code,)), 2, code)

    async def test_a_prohibited_form_cannot_be_smuggled_through_an_idempotent_retry_with_an_existing_capture_id(self):
        _, bobbin = await self.bobbin()
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset(MACHINE_ONLY)):
            body = {"capture_id": str(uuid4()), "form_code": P118_CODE, "device_key": str(uuid4()), "values": dict(P118_VALUES)}
            made = await call("POST", "/api/quality/machines/MP1/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
            self.assertEqual(made.status, 201, made.text)
        reply = await self.submit(bobbin["id"], {**body, "values": dict(P118_VALUES)})  # same capture_id, same content: it must NOT be answered as 200 / 409
        self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
        # a legitimate retry of an allowed form with a capture_id owned by a machine-level capture is rejected as a conflict, never adopted
        clash = await self.submit(bobbin["id"], {**self.post_body(P119, P119_VALUES, bobbin), "capture_id": body["capture_id"]})
        self.assertEqual((clash.status, clash.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))

    async def test_rows_of_forbidden_forms_carrying_a_bobbin_are_invisible_by_id_and_in_every_history(self):
        _, bobbin = await self.bobbin()
        hostile = {code: await self.insert_hostile_capture(code, bobbin, values) for code, values in {**MACHINE_ONLY, UNKNOWN: UNKNOWN_VALUES}.items()}
        legit = (await self.submit(bobbin["id"], self.post_body(P119, P119_VALUES, bobbin))).json()["capture"]
        for code, capture_id in hostile.items():
            self.assertEqual((await self.read(f"/api/quality/captures/{capture_id}")).status, 404, code)
        listed = (await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures")).json()
        self.assertEqual([x["id"] for x in listed], [legit["id"]])  # only the allowed form appears in the general history
        for code in hostile:
            self.assertEqual((await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")).status, 422, code)
        with patch.object(_quality_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset(CANDIDATES)):
            self.assertEqual([x["id"] for x in (await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures")).json()], [legit["id"]])
        self.assertEqual(self.release(bobbin["id"])[0], "pending")

    async def test_the_machine_level_api_is_untouched_and_does_not_accept_bobbin_forms(self):
        with patch.object(_machine_service, "MACHINE_QUALITY_FORM_CODES", frozenset(MACHINE_ONLY)):
            for code, values in MACHINE_ONLY.items():
                body = {"capture_id": str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": dict(values)}
                reply = await call("POST", "/api/quality/machines/MP1/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
                self.assertEqual(reply.status, 201, (code, reply.text))
                got = await call("GET", f"/api/quality/machine-captures/{reply.json()['capture']['id']}", cookie=await self.cookie("CALIDAD"))
                self.assertEqual((got.status, got.json()["form"]["code"]), (200, code))
            for code in (P119, P120, *CANDIDATES):  # bobbin forms are not machine forms
                reply = await call("POST", "/api/quality/machines/MP1/captures", json_body={"capture_id": str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": {}},
                                   cookie=await self.cookie("CALIDAD"))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)

    async def test_quality_release_is_never_touched_by_any_of_it(self):
        _, bobbin = await self.bobbin()
        release, bobbin_row = self.release(bobbin["id"]), self.connection.execute("SELECT * FROM vinto_txn.bobbin WHERE id = %s", (bobbin["id"],)).fetchone()
        for code in (*MACHINE_ONLY, UNKNOWN):
            await self.submit(bobbin["id"], self.post_body(code, {**MACHINE_ONLY, UNKNOWN: UNKNOWN_VALUES}[code], bobbin))
        await self.submit(bobbin["id"], self.post_body(P120, P120_VALUES, bobbin))
        self.assertEqual(self.release(bobbin["id"]), release)
        self.assertEqual(self.connection.execute("SELECT * FROM vinto_txn.bobbin WHERE id = %s", (bobbin["id"],)).fetchone(), bobbin_row)


if __name__ == "__main__":
    unittest.main()
