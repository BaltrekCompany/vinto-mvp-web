"""Integracion HTTP + PostgreSQL17: Calidad decide por bobina, no por OT/linea.

Base exclusiva de pruebas creada con build_reference_template; nunca se conecta a produccion.
"""
from uuid import uuid4

try:
    import test_f3_bobbins_api as f3
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    from tests.test_assignments_api import call

from app.ephemeral_db import build_reference_template, drop_database


def setUpModule():
    f3.STATE["template"] = build_reference_template("vinto_qdecision_tpl")


def tearDownModule():
    if f3.STATE.get("template"):
        drop_database(f3.STATE.pop("template"))


class DecisionHttpTests(f3.BobbinApiCase):
    async def make_bobbin(self):
        _, assignment = await self.assignment("MP1")
        created = await self.post(self.payload(assignment))
        self.assertEqual(created.status, 201, created.text)
        return created.json()["bobbin"]["id"]

    def decision_body(self, action="release", decision_id=None):
        body = {"decision_id": str(decision_id or uuid4()), "action": action}
        if action == "reject":
            body.update(rejection_type="reutilizable", classification="humedad",
                        detail="Lectura fuera de rango", corrective_action="Separar lote para reproceso")
        return body

    async def decide(self, bobbin_id, body, profile="CALIDAD"):
        return await call("POST", f"/api/quality/bobbins/{bobbin_id}/decision",
                          json_body=body, cookie=await self.cookie(profile))

    def row(self, bobbin_id):
        return self.connection.execute(
            """SELECT status, decided_by, decided_at, decision_request_id,
                      rejection_type, rejection_classification, rejection_detail, corrective_action
               FROM vinto_txn.quality_release WHERE bobbin_id=%s""", (bobbin_id,)).fetchone()

    async def test_release_moves_only_one_bobbin_and_tracks_actor(self):
        first = await self.make_bobbin()
        second = await self.make_bobbin()
        result = await self.decide(first, self.decision_body())
        self.assertEqual((result.status, result.json()), (200, {
            "bobbin_id": first, "status": "released", "already_decided": False}))
        row = self.row(first)
        self.assertEqual(row[0], "released")
        self.assertEqual(row[1], self.users["CALIDAD"][0].user_id)
        self.assertIsNotNone(row[2])
        self.assertEqual(row[4:], (None, None, None, None))
        self.assertEqual(self.row(second)[0], "pending")
        self.assertNotIn(first, [x["bobbin"]["id"] for x in (await call(
            "GET", "/api/quality/bobbins", cookie=await self.cookie("CALIDAD"))).json()])
        listed = (await call("GET", "/api/quality/bobbins?status=released",
                             cookie=await self.cookie("CALIDAD"))).json()
        self.assertIn(first, [x["bobbin"]["id"] for x in listed])

    async def test_reject_four_fields_audited_and_exact_retry(self):
        bobbin_id = await self.make_bobbin()
        body = self.decision_body("reject")
        first = await self.decide(bobbin_id, body)
        self.assertEqual((first.status, first.json()["status"]), (200, "rejected"))
        stored = self.row(bobbin_id)
        self.assertEqual(stored[0], "rejected")
        self.assertEqual(stored[4:], ("reutilizable", "humedad", "Lectura fuera de rango", "Separar lote para reproceso"))
        before = self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0]
        retry = await self.decide(bobbin_id, body)
        self.assertEqual((retry.status, retry.json()["already_decided"]), (200, True))
        self.assertEqual(before, self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0])
        changed = await self.decide(bobbin_id, {**body, "detail": "otro detalle"})
        self.assertEqual(changed.status, 409)
        other_id = await self.decide(bobbin_id, self.decision_body("reject"))
        self.assertEqual(other_id.status, 409)

    async def test_unauthenticated_other_profiles_and_invalid_payloads_do_not_write(self):
        bobbin_id = await self.make_bobbin()
        path = f"/api/quality/bobbins/{bobbin_id}/decision"
        before = self.row(bobbin_id)
        self.assertEqual((await call("POST", path, json_body=self.decision_body())).status, 401)
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION", "DATA_BALTREK"):
            self.assertEqual((await self.decide(bobbin_id, self.decision_body(), profile)).status, 403, profile)
        valid = self.decision_body("reject")
        for data in ({**valid, "classification": "inventada"}, {**valid, "detail": " "},
                     {**valid, "corrective_action": None}, {**valid, "unexpected": "x"},
                     {**self.decision_body(), "detail": "No permitido"}):
            self.assertEqual((await self.decide(bobbin_id, data)).status, 422, data)
        self.assertEqual(self.row(bobbin_id), before)

    async def test_unknown_and_non_numbered_bobbin_are_not_decidable(self):
        missing = await self.decide(str(uuid4()), self.decision_body())
        self.assertEqual(missing.status, 404)
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('QDEC-LEGACY')")
        legacy = self.connection.execute("SELECT id FROM vinto_txn.bobbin WHERE code='QDEC-LEGACY'").fetchone()[0]
        self.connection.execute("INSERT INTO vinto_txn.quality_release (bobbin_id) VALUES (%s)", (legacy,))
        self.assertEqual((await self.decide(str(legacy), self.decision_body())).status, 404)


    async def test_two_concurrent_decisions_allow_only_one_winner(self):
        import asyncio
        bobbin_id = await self.make_bobbin()
        cookie = await self.cookie("CALIDAD")  # login antes de iniciar las peticiones simultaneas
        path = f"/api/quality/bobbins/{bobbin_id}/decision"
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        release = self.decision_body()
        reject = self.decision_body("reject")
        outcomes = await asyncio.gather(
            call("POST", path, json_body=release, cookie=cookie),
            call("POST", path, json_body=reject, cookie=cookie),
        )
        self.assertEqual(sorted(x.status for x in outcomes), [200, 409])
        self.assertIn(self.row(bobbin_id)[0], ("released", "rejected"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event") - before, 1)

    async def test_two_identical_concurrent_retries_are_idempotent(self):
        import asyncio
        bobbin_id = await self.make_bobbin()
        cookie = await self.cookie("CALIDAD")
        body = self.decision_body("reject")
        path = f"/api/quality/bobbins/{bobbin_id}/decision"
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        results = await asyncio.gather(
            call("POST", path, json_body=body, cookie=cookie),
            call("POST", path, json_body=body, cookie=cookie),
        )
        self.assertEqual([x.status for x in results], [200, 200])
        self.assertEqual(sorted(x.json()["already_decided"] for x in results), [False, True])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event") - before, 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
