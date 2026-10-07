"""GET /api/quality/bobbins: bandeja central de Calidad (solo lectura) sobre Bobinas F3 con quality_release.

La autoridad es quality_release.status, no la asignación actual. Reutiliza la infraestructura de test_f3_bobbins_api (misma base
efímera *_test, mismos usuarios y helpers). Nada toca la base `vinto`.
"""

import json
import unittest
from uuid import uuid4

try:
    import test_f3_bobbins_api as f3
    from test_assignments_api import call, order_body
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    from tests.test_assignments_api import call, order_body

from app.ephemeral_db import build_reference_template, drop_database
from app.quality import service as quality_service
from app.seed.bundle import load_bundle

BUNDLE = load_bundle()
NO_GRAMMAGE = next(a["code"] for a in BUNDLE.articles if a["version"]["grammage_g_m2"] is None)
NO_GRAMMAGE_MACHINE = next(r["machine_code"] for r in BUNDLE.article_machines if r["article_code"] == NO_GRAMMAGE)
F6_VALUES = {"cantidad_fardos": 1, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "1"}


def setUpModule():
    f3.STATE["template"] = build_reference_template("vinto_qinbox_tpl")  # f3.BobbinApiCase copia su base desde f3.STATE


def tearDownModule():
    if f3.STATE.get("template"):
        drop_database(f3.STATE["template"])
        f3.STATE.pop("template")


class InboxCase(f3.BobbinApiCase):
    async def create_bobbin(self, machine="MP1", **value_changes):
        order, assignment = await self.assignment(machine)
        body = self.payload(assignment)
        body["values"].update(value_changes)
        reply = await self.post(body)
        self.assertEqual(reply.status, 201)
        return assignment, reply.json()

    async def inbox(self, path="/api/quality/bobbins", profile="CALIDAD"):
        reply = await call("GET", path, cookie=await self.cookie(profile))
        self.assertEqual(reply.status, 200, path)
        return reply.json()

    @staticmethod
    def find(items, bobbin_id):
        return [i for i in items if i["bobbin"]["id"] == bobbin_id]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in (
            "vinto_txn.bobbin", "vinto_txn.quality_release", "vinto_txn.capture", "vinto_txn.bobbin_sequence", "vinto_audit.audit_event")}


class PermissionTests(InboxCase):
    async def test_unauthenticated_is_401(self):
        self.assertEqual((await call("GET", "/api/quality/bobbins")).status, 401)

    async def test_only_calidad_reads_the_inbox(self):
        self.assertEqual((await call("GET", "/api/quality/bobbins", cookie=await self.cookie("CALIDAD"))).status, 200)
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION", "DATA_BALTREK"):
            reply = await call("GET", "/api/quality/bobbins", cookie=await self.cookie(profile))
            self.assertEqual(reply.status, 403, profile)

    async def test_the_inbox_only_accepts_get(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            reply = await call(method, "/api/quality/bobbins", cookie=await self.cookie("CALIDAD"))
            self.assertIn(reply.status, (404, 405), method)


class ContentTests(InboxCase):
    async def test_a_new_f3_bobbin_appears_with_the_agreed_shape(self):
        assignment, created = await self.create_bobbin("MP1")
        bobbin, capture = created["bobbin"], created["capture"]
        found = self.find(await self.inbox(), bobbin["id"])
        self.assertEqual(len(found), 1)
        item = found[0]
        self.assertEqual(set(item), {"bobbin", "production", "quality"})
        b = item["bobbin"]
        self.assertEqual((b["id"], b["code"], b["machine"], b["sequence_number"], b["management_start_year"]),
                         (bobbin["id"], bobbin["code"], {"code": "MP1", "name": "MP1"}, bobbin["sequence_number"], bobbin["management_start_year"]))
        self.assertEqual((b["start_time"], b["end_time"], b["diameter_mm"], b["weight_kg"], b["number_of_cuts"], b["notes"]),
                         ("07:15:00", "08:40:00", "1200.5", "845.25", "3", "ok"))
        self.assertEqual(b["grammage_g_m2"], bobbin["grammage_g_m2"])
        self.assertIsNotNone(b["grammage_g_m2"])
        p = item["production"]
        self.assertEqual(p["capture_id"], capture["id"])
        self.assertEqual((p["operating_date"], p["shift"]), (capture["operating_date"], capture["shift"]))
        self.assertEqual(p["work_order"], capture["work_order"])
        self.assertEqual((p["line"]["id"], p["line"]["line_code"], p["line"]["pv_reference"], p["line"]["article"]),
                         (capture["line"]["id"], capture["line"]["line_code"], capture["line"]["pv_reference"], capture["line"]["article"]))
        self.assertTrue(p["captured_at"])
        self.assertEqual(item["quality"], {"status": "pending"})
        self.assertEqual(set(b), {"id", "code", "machine", "management_start_year", "sequence_number", "start_time", "end_time", "diameter_mm", "weight_kg",
                                  "grammage_g_m2", "number_of_cuts", "notes"})

    async def test_the_response_has_no_sensitive_or_audit_data(self):
        await self.create_bobbin()
        raw = (await call("GET", "/api/quality/bobbins", cookie=await self.cookie("CALIDAD"))).body.decode()
        for forbidden in ("created_by", "updated_by", "device", "password", "external_key", "audit", "created_at", "updated_at", "decided", "token", "hash"):
            self.assertNotIn(forbidden, raw, forbidden)

    async def test_decimals_are_exact_text(self):
        _, created = await self.create_bobbin(diametro="1200.123456789012345", peso_kg="0.10")
        item = self.find(await self.inbox(), created["bobbin"]["id"])[0]["bobbin"]
        self.assertEqual((item["diameter_mm"], item["weight_kg"]), ("1200.123456789012345", "0.10"))
        self.assertIsInstance(item["grammage_g_m2"], str)

    async def test_an_article_without_grammage_appears_with_null(self):
        order = (await call("POST", "/api/work-orders", cookie=await self.cookie("JEFATURA"), json_body={
            "machine_code": NO_GRAMMAGE_MACHINE, "lines": [{"pv_reference": "PV-NG", "article_code": NO_GRAMMAGE, "quantity": 1, "due_date": "2026-11-01"}]})).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        activated = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"),
                               json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(activated.status, 201)
        reply = await self.post(self.payload(activated.json()["assignment"]))
        self.assertEqual(reply.status, 201)
        bobbin_id = reply.json()["bobbin"]["id"]
        self.assertIsNone(reply.json()["bobbin"]["grammage_g_m2"])
        item = self.find(await self.inbox(), bobbin_id)
        self.assertEqual(len(item), 1)
        self.assertIsNone(item[0]["bobbin"]["grammage_g_m2"])
        self.assertEqual(item[0]["production"]["line"]["article"]["code"], NO_GRAMMAGE)


class IndependenceFromAssignmentTests(InboxCase):
    async def test_a_finished_assignment_keeps_its_bobbin_in_the_inbox(self):
        assignment, created = await self.create_bobbin()
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s", (assignment["id"],))
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (assignment["id"],)), "finished")
        self.assertEqual(len(self.find(await self.inbox(), created["bobbin"]["id"])), 1)

    async def test_a_new_active_assignment_does_not_hide_previous_bobbins(self):
        first_assignment, first = await self.create_bobbin("MP1")
        second_assignment, second = await self.create_bobbin("MP1")  # activar otra asignación en MP1 finaliza la anterior
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (first_assignment["id"],)), "finished")
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (second_assignment["id"],)), "active")
        items = await self.inbox()
        self.assertEqual(len(self.find(items, first["bobbin"]["id"])), 1)
        self.assertEqual(len(self.find(items, second["bobbin"]["id"])), 1)
        self.assertNotEqual(self.find(items, first["bobbin"]["id"])[0]["production"]["work_order"]["id"],
                            self.find(items, second["bobbin"]["id"])[0]["production"]["work_order"]["id"])


class StatusFilterTests(InboxCase):
    def decide(self, bobbin_id, status):
        # Fixture de LECTURA en la base de TEST: aún no existe el endpoint que libera/rechaza; el GET no modifica nada.
        user = self.users["CALIDAD"][0].user_id
        self.connection.execute("UPDATE vinto_txn.quality_release SET status=%s, decided_by=%s, decided_at=clock_timestamp(), decision_reason='fixture' WHERE bobbin_id=%s",
                                (status, user, bobbin_id))

    async def test_released_and_rejected_are_not_pending(self):
        _, pending = await self.create_bobbin()
        _, released = await self.create_bobbin()
        _, rejected = await self.create_bobbin()
        self.decide(released["bobbin"]["id"], "released")
        self.decide(rejected["bobbin"]["id"], "rejected")
        for path in ("/api/quality/bobbins", "/api/quality/bobbins?status=pending"):
            items = await self.inbox(path)
            self.assertEqual(len(self.find(items, pending["bobbin"]["id"])), 1, path)
            self.assertEqual(self.find(items, released["bobbin"]["id"]), [], path)
            self.assertEqual(self.find(items, rejected["bobbin"]["id"]), [], path)
            self.assertEqual({i["quality"]["status"] for i in items}, {"pending"})
        only_released = await self.inbox("/api/quality/bobbins?status=released")
        self.assertEqual([i["bobbin"]["id"] for i in self.find(only_released, released["bobbin"]["id"])], [released["bobbin"]["id"]])
        self.assertEqual({i["quality"]["status"] for i in only_released}, {"released"})
        only_rejected = await self.inbox("/api/quality/bobbins?status=rejected")
        self.assertEqual(len(self.find(only_rejected, rejected["bobbin"]["id"])), 1)
        self.assertEqual({i["quality"]["status"] for i in only_rejected}, {"rejected"})

    async def test_unknown_status_is_422(self):
        for bad in ("foo", "PENDING", "", "approved", "pending,released"):
            reply = await call("GET", f"/api/quality/bobbins?status={bad}", cookie=await self.cookie("CALIDAD"))
            self.assertEqual(reply.status, 422, bad)

    async def test_status_does_not_change_permissions(self):
        for status in ("pending", "released", "rejected"):
            self.assertEqual((await call("GET", f"/api/quality/bobbins?status={status}", cookie=await self.cookie("OPERACION"))).status, 403, status)
            self.assertEqual((await call("GET", f"/api/quality/bobbins?status={status}")).status, 401, status)


class ScopeAndReadOnlyTests(InboxCase):
    async def test_f6_captures_do_not_appear(self):
        _, assignment = await self.assignment("MP1")
        reply = await call("POST", "/api/captures", cookie=await self.cookie("OPERACION"), json_body={
            "capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": F6_VALUES})
        self.assertEqual(reply.status, 201)
        f6_capture = reply.json()["capture"]["id"]
        self.assertEqual([i for i in await self.inbox() if i["production"]["capture_id"] == f6_capture], [])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin WHERE source_capture_id=%s", (f6_capture,)), 0)

    async def test_legacy_unnumbered_bobbins_do_not_appear(self):
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('LEGACY-Q')")
        legacy = self.scalar("SELECT id FROM vinto_txn.bobbin WHERE code='LEGACY-Q'")
        self.connection.execute("INSERT INTO vinto_txn.quality_release (bobbin_id) VALUES (%s)", (legacy,))
        self.assertEqual([i for i in await self.inbox() if i["bobbin"]["code"] == "LEGACY-Q"], [])

    async def test_get_is_read_only(self):
        await self.create_bobbin()
        before = self.counts()
        snapshot = self.connection.execute("SELECT id, status, decided_by, decided_at, decision_reason, updated_at FROM vinto_txn.quality_release ORDER BY id").fetchall()
        for path in ("/api/quality/bobbins", "/api/quality/bobbins?status=pending", "/api/quality/bobbins?status=released"):
            await self.inbox(path)
        self.assertEqual(self.counts(), before)  # ni filas nuevas ni eventos de auditoría
        self.assertEqual(self.connection.execute("SELECT id, status, decided_by, decided_at, decision_reason, updated_at FROM vinto_txn.quality_release ORDER BY id").fetchall(), snapshot)

    async def test_the_inbox_order_is_deterministic(self):
        for _ in range(3):
            await self.create_bobbin()
        first = [i["bobbin"]["id"] for i in await self.inbox()]
        second = [i["bobbin"]["id"] for i in await self.inbox()]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))


class EmptyInboxTests(InboxCase):
    async def test_an_empty_inbox_is_200_with_a_list(self):
        self.connection.execute("UPDATE vinto_txn.quality_release SET status='rejected', decided_by=%s, decided_at=clock_timestamp() WHERE status='pending'",
                                (self.users["CALIDAD"][0].user_id,))
        reply = await call("GET", "/api/quality/bobbins", cookie=await self.cookie("CALIDAD"))
        self.assertEqual((reply.status, json.loads(reply.body)), (200, []))


class NoTruncationTests(InboxCase):
    async def test_the_listing_applies_no_artificial_limit(self):
        import inspect
        source = inspect.getsource(quality_service)
        self.assertFalse(hasattr(quality_service, "MAX_INBOX_ROWS"))
        self.assertNotRegex(source.replace("LIMIT fijo", ""), r"(?i)LIMIT|OFFSET")
        created = [(await self.create_bobbin())[1]["bobbin"]["id"] for _ in range(7)]
        pending = self.scalar("SELECT count(*) FROM vinto_txn.quality_release q JOIN vinto_txn.bobbin b ON b.id=q.bobbin_id WHERE q.status='pending' AND b.sequence_number IS NOT NULL")
        ids = [i["bobbin"]["id"] for i in await self.inbox()]
        self.assertEqual(len(ids), pending)  # todas las pendientes, sin recorte
        self.assertTrue(set(created) <= set(ids))
        self.assertEqual(len(quality_service.list_quality_bobbins(self.connection)), pending)


class ServiceTests(InboxCase):
    async def test_service_serializes_decimals_without_float_and_rejects_unknown_status(self):
        _, created = await self.create_bobbin(diametro="1200.10", peso_kg="845.250")
        views = quality_service.list_quality_bobbins(self.connection)
        view = next(v for v in views if str(v.bobbin_id) == created["bobbin"]["id"])
        self.assertEqual((view.diameter_mm, view.weight_kg), ("1200.10", "845.250"))
        self.assertIsInstance(view.grammage_g_m2, str)
        self.assertEqual({v.quality_status for v in views}, {"pending"})
        with self.assertRaises(ValueError):
            quality_service.list_quality_bobbins(self.connection, "foo")

    async def test_service_does_not_depend_on_an_active_assignment(self):
        assignment, created = await self.create_bobbin()
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 0)
        self.assertIn(created["bobbin"]["id"], [str(v.bobbin_id) for v in quality_service.list_quality_bobbins(self.connection)])


if __name__ == "__main__":
    unittest.main()
