"""Capturas de Calidad ligadas a una Bobina (fundación): POST/GET /api/quality/bobbins/{bobbin_id}/captures y
GET /api/quality/captures/{capture_id}, más la migración 0005 (capture.bobbin_id).

Los formularios de Calidad son SINTÉTICOS y existen solo en la plantilla efímera *_test de este módulo (QA-TEST-*): todavía no hay
formularios reales de Calidad en el bundle. Reutiliza la infraestructura de test_f3_bobbins_api. Nada toca la base `vinto`.
"""

import hashlib
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg

try:
    import test_f3_bobbins_api as f3
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    from tests.test_assignments_api import call

from app import capture_service
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.quality import capture_service as quality_captures

FORM = "QA-TEST-01"
FIELDS = (("humedad_pct", "Humedad", "decimal", True), ("muestras", "Muestras", "integer", False), ("resultado", "Resultado visual", "text", True),
          ("observaciones", "Observaciones", "textarea", False))
VALUES = {"humedad_pct": "6.40", "muestras": 3, "resultado": "conforme", "observaciones": "ensayo sintético"}
F6_VALUES = {"cantidad_fardos": 1, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "1"}


def _create_form(connection, code, number, *, area="quality", machines=("MP1", "MP3"), status="published", fields=FIELDS, source="manual"):
    """Formulario sintético: se inserta como draft (los hijos solo se insertan en draft) y luego se publica/retira."""
    workflow = connection.execute("SELECT id FROM vinto_config.workflow_definition ORDER BY code LIMIT 1").fetchone()[0]
    form_id = connection.execute("INSERT INTO vinto_config.form (legacy_key, code, legacy_number) VALUES (%s,%s,%s) RETURNING id",
                                 (f"test_{code.lower()}", code, number)).fetchone()[0]
    version_id = connection.execute(
        """INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum)
           VALUES (%s, 1, %s, %s, %s, %s) RETURNING id""", (form_id, f"Formulario sintético {code}", area, workflow, hashlib.sha256(code.encode()).hexdigest())).fetchone()[0]
    for machine in machines:
        connection.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, id FROM vinto_master.machine WHERE code=%s", (version_id, machine))
    for order, (key, label, value_type, required) in enumerate(fields, start=1):
        connection.execute("""INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order)
                              VALUES (%s,%s,%s,%s,%s,%s,%s)""", (version_id, key, label, value_type, source if order == 1 else "manual", required, order))
    if status in ("published", "retired"):
        connection.execute("UPDATE vinto_config.form_version SET status='published', published_at=clock_timestamp() WHERE id=%s", (version_id,))
    if status == "retired":
        connection.execute("UPDATE vinto_config.form_version SET status='retired' WHERE id=%s", (version_id,))


def setUpModule():
    template = build_reference_template("vinto_qcap_tpl")
    with connect(template) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('vinto.reason', 'synthetic quality forms for tests', true)")
            _create_form(connection, FORM, 9001)
            _create_form(connection, "QA-TEST-DRAFT", 9002, status="draft")
            _create_form(connection, "QA-TEST-RETIRED", 9003, status="retired")
            _create_form(connection, "QA-TEST-MP3", 9004, machines=("MP3",))
            _create_form(connection, "QA-TEST-AUTO", 9005, source="automatic")  # definición no soportada por esta fundación
            _create_form(connection, "QA-TEST-PROD", 9006, area="production")  # formulario de producción con código propio
    f3.STATE["template"] = template


def tearDownModule():
    if f3.STATE.get("template"):
        drop_database(f3.STATE["template"])
        f3.STATE.pop("template")


class QualityCaptureCase(f3.BobbinApiCase):
    async def bobbin(self, machine="MP1"):
        _, assignment = await self.assignment(machine)
        reply = await self.post(self.payload(assignment))
        self.assertEqual(reply.status, 201)
        return assignment, reply.json()

    def body(self, **changes):
        body = {"capture_id": str(uuid4()), "form_code": FORM, "device_key": str(uuid4()), "values": dict(VALUES)}
        body.update(changes)
        return body

    async def submit(self, bobbin_id, body, profile="CALIDAD"):
        return await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie(profile))

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_master.device",
                                                                       "vinto_txn.quality_release", "vinto_txn.bobbin")}

    def release(self, bobbin_id):
        return self.connection.execute("SELECT status, decided_by, decided_at, decision_reason, updated_at FROM vinto_txn.quality_release WHERE bobbin_id=%s",
                                       (bobbin_id,)).fetchone()


class PermissionTests(QualityCaptureCase):
    async def test_unauthenticated_is_401(self):
        _, created = await self.bobbin()
        bobbin_id = created["bobbin"]["id"]
        self.assertEqual((await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=self.body())).status, 401)
        self.assertEqual((await call("GET", f"/api/quality/bobbins/{bobbin_id}/captures")).status, 401)
        self.assertEqual((await call("GET", f"/api/quality/captures/{uuid4()}")).status, 401)

    async def test_only_calidad_can_capture(self):
        _, created = await self.bobbin()
        bobbin_id = created["bobbin"]["id"]
        before = self.counts()
        for profile in ("OPERACION", "JEFATURA", "SUPERVISION", "DATA_BALTREK"):
            self.assertEqual((await self.submit(bobbin_id, self.body(), profile)).status, 403, profile)
            self.assertEqual((await call("GET", f"/api/quality/bobbins/{bobbin_id}/captures", cookie=await self.cookie(profile))).status, 403, profile)
        self.assertEqual(self.counts(), before)
        self.assertEqual((await self.submit(bobbin_id, self.body())).status, 201)


class ValidationTests(QualityCaptureCase):
    async def test_unknown_bobbin_is_404(self):
        for bobbin_id in (str(uuid4()), "not-a-uuid"):
            reply = await self.submit(bobbin_id, self.body())
            self.assertEqual((reply.status, reply.json()["code"]), (404, "BOBBIN_NOT_FOUND"), bobbin_id)
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES ('LEGACY-QC')")  # Bobina histórica sin numerar: no es evaluable aquí
        legacy = self.scalar("SELECT id FROM vinto_txn.bobbin WHERE code='LEGACY-QC'")
        self.assertEqual((await self.submit(legacy, self.body())).status, 404)

    async def test_forms_that_are_not_published_quality_forms_for_the_machine_are_rejected(self):
        _, created = await self.bobbin("MP1")
        bobbin_id = created["bobbin"]["id"]
        before = self.counts()
        for form_code in ("VINTO-P1-06", "VINTO-P1-03", "QA-TEST-PROD", "QA-TEST-DRAFT", "QA-TEST-RETIRED", "QA-TEST-MP3", "NO-EXISTE"):
            reply = await self.submit(bobbin_id, self.body(form_code=form_code))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"), form_code)
        reply = await self.submit(bobbin_id, self.body(form_code="QA-TEST-AUTO"))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "UNSUPPORTED_FORM_DEFINITION"))
        self.assertEqual(self.counts(), before)

    async def test_the_mp3_only_form_is_accepted_for_an_mp3_bobbin(self):
        _, created = await self.bobbin("MP3")
        self.assertEqual((await self.submit(created["bobbin"]["id"], self.body(form_code="QA-TEST-MP3"))).status, 201)

    async def test_invalid_values_are_422_and_write_nothing(self):
        _, created = await self.bobbin()
        bobbin_id = created["bobbin"]["id"]
        before = self.counts()
        for values in ({**VALUES, "humedad_pct": "abc"}, {**VALUES, "muestras": "tres"}, {k: v for k, v in VALUES.items() if k != "humedad_pct"},
                       {k: v for k, v in VALUES.items() if k != "resultado"}, {**VALUES, "desconocido": 1}, {**VALUES, "humedad_pct": True}, {**VALUES, "resultado": ["x"]}):
            reply = await self.submit(bobbin_id, self.body(values=values))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), values)
        self.assertEqual(self.counts(), before)

    async def test_the_payload_is_closed(self):
        _, created = await self.bobbin()
        bobbin_id = created["bobbin"]["id"]
        for extra in ("assignment_id", "machine", "shift", "operating_date", "work_order", "line", "pv", "article", "bobbin_code", "bobbin_id", "operator", "status", "revision"):
            self.assertEqual((await self.submit(bobbin_id, {**self.body(), extra: "x"})).status, 422, extra)
        for missing in ("capture_id", "form_code", "device_key", "values"):
            body = self.body()
            del body[missing]
            self.assertEqual((await self.submit(bobbin_id, body)).status, 422, missing)
        self.assertEqual((await self.submit(bobbin_id, self.body(capture_id="11111111-1111-1111-8111-111111111111"))).status, 422)  # no es UUIDv4
        self.assertEqual((await self.submit(bobbin_id, self.body(form_code=""))).status, 422)


class CaptureTests(QualityCaptureCase):
    async def test_a_valid_capture_is_created_with_the_bobbin_production_context(self):
        _, created = await self.bobbin("MP1")
        bobbin, f3_capture = created["bobbin"], created["capture"]
        reply = await self.submit(bobbin["id"], self.body())
        self.assertEqual(reply.status, 201)
        data = reply.json()
        self.assertEqual((data["created"], data["already_submitted"]), (True, False))
        c = data["capture"]
        self.assertEqual((c["status"], c["revision"], c["form"]["code"], c["form"]["version_number"]), ("submitted", 1, FORM, 1))
        self.assertEqual(c["bobbin"], {"id": bobbin["id"], "code": bobbin["code"]})
        self.assertEqual((c["machine"], c["shift"], c["operating_date"], c["work_order"], c["line"]),
                         (f3_capture["machine"], f3_capture["shift"], f3_capture["operating_date"], f3_capture["work_order"], f3_capture["line"]))
        self.assertEqual(c["line"]["article"]["code"], bobbin["article"]["code"])
        self.assertEqual(c["values"], {"humedad_pct": "6.40", "muestras": 3, "resultado": "conforme", "observaciones": "ensayo sintético"})
        row = self.connection.execute("SELECT bobbin_id, machine_id, shift_schedule_id, operating_date, assignment_id FROM vinto_txn.capture WHERE id=%s", (c["id"],)).fetchone()
        source = self.connection.execute("""SELECT b.id, b.machine_id, s.shift_schedule_id, s.operating_date, s.assignment_id FROM vinto_txn.bobbin b
                                            JOIN vinto_txn.capture s ON s.id = b.source_capture_id WHERE b.id=%s""", (bobbin["id"],)).fetchone()
        self.assertEqual(row, source)

    async def test_captured_at_is_the_test_instant_while_operating_date_stays_the_production_one(self):
        _, created = await self.bobbin()
        before = self.scalar("SELECT clock_timestamp()")
        c = (await self.submit(created["bobbin"]["id"], self.body())).json()["capture"]
        captured = self.scalar("SELECT captured_at FROM vinto_txn.capture WHERE id=%s", (c["id"],))
        f3_captured = self.scalar("SELECT captured_at FROM vinto_txn.capture WHERE id=%s", (created["capture"]["id"],))
        self.assertGreaterEqual(captured, before)
        self.assertGreater(captured, f3_captured)
        self.assertEqual(c["operating_date"], created["capture"]["operating_date"])

    async def test_a_finished_assignment_does_not_block_the_capture(self):
        assignment, created = await self.bobbin()
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s", (assignment["id"],))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 0)
        reply = await self.submit(created["bobbin"]["id"], self.body())
        self.assertEqual(reply.status, 201)
        self.assertEqual(reply.json()["capture"]["work_order"], created["capture"]["work_order"])

    async def test_a_new_active_assignment_does_not_change_the_old_bobbin_context(self):
        first_assignment, first = await self.bobbin("MP1")
        second_assignment, second = await self.bobbin("MP1")  # activar otra línea en MP1 finaliza la anterior
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (first_assignment["id"],)), "finished")
        c = (await self.submit(first["bobbin"]["id"], self.body())).json()["capture"]
        self.assertEqual((c["work_order"], c["line"]), (first["capture"]["work_order"], first["capture"]["line"]))
        self.assertNotEqual(c["work_order"]["id"], second["capture"]["work_order"]["id"])
        self.assertEqual(self.scalar("SELECT assignment_id FROM vinto_txn.capture WHERE id=%s", (c["id"],)), self.scalar(
            "SELECT s.assignment_id FROM vinto_txn.bobbin b JOIN vinto_txn.capture s ON s.id=b.source_capture_id WHERE b.id=%s", (first["bobbin"]["id"],)))

    async def test_several_captures_of_the_same_bobbin_are_allowed(self):
        _, created = await self.bobbin()
        for _ in range(2):
            self.assertEqual((await self.submit(created["bobbin"]["id"], self.body())).status, 201)
        listed = await call("GET", f"/api/quality/bobbins/{created['bobbin']['id']}/captures", cookie=await self.cookie("CALIDAD"))
        self.assertEqual((listed.status, len(listed.json())), (200, 2))
        self.assertEqual({c["bobbin"]["id"] for c in listed.json()}, {created["bobbin"]["id"]})

    async def test_quality_release_stays_pending_and_untouched(self):
        _, created = await self.bobbin()
        before = self.release(created["bobbin"]["id"])
        self.assertEqual(before[:4], ("pending", None, None, None))
        self.assertEqual((await self.submit(created["bobbin"]["id"], self.body())).status, 201)
        self.assertEqual(self.release(created["bobbin"]["id"]), before)
        inbox = await call("GET", "/api/quality/bobbins", cookie=await self.cookie("CALIDAD"))
        self.assertIn(created["bobbin"]["id"], [i["bobbin"]["id"] for i in inbox.json()])  # sigue en la bandeja pendiente

    async def test_decimals_are_exact_text_and_no_sensitive_data_is_exposed(self):
        _, created = await self.bobbin()
        reply = await self.submit(created["bobbin"]["id"], self.body(values={**VALUES, "humedad_pct": "12.340"}))
        self.assertEqual(reply.json()["capture"]["values"]["humedad_pct"], "12.340")
        raw = reply.body.decode()
        for forbidden in ("created_by", "updated_by", "device", "external_key", "audit", "password", "assignment_id", "decided", "updated_at"):
            self.assertNotIn(forbidden, raw, forbidden)
        self.assertEqual(set(reply.json()["capture"]), {"id", "status", "revision", "captured_at", "submitted_at", "form", "bobbin", "machine", "shift",
                                                         "operating_date", "work_order", "line", "values"})

    async def test_get_detail_and_list(self):
        _, created = await self.bobbin()
        c = (await self.submit(created["bobbin"]["id"], self.body())).json()["capture"]
        got = await call("GET", f"/api/quality/captures/{c['id']}", cookie=await self.cookie("CALIDAD"))
        self.assertEqual((got.status, got.json()), (200, c))
        for missing in (str(uuid4()), "nope", created["capture"]["id"]):  # una captura F3 no es una captura de Calidad
            reply = await call("GET", f"/api/quality/captures/{missing}", cookie=await self.cookie("CALIDAD"))
            self.assertEqual((reply.status, reply.json()["code"]), (404, "CAPTURE_NOT_FOUND"), missing)
        self.assertEqual((await call("GET", f"/api/quality/bobbins/{uuid4()}/captures", cookie=await self.cookie("CALIDAD"))).status, 404)
        self.assertEqual((await call("GET", f"/api/quality/captures/{c['id']}", cookie=await self.cookie("OPERACION"))).status, 403)
        # el endpoint F6 no ve capturas de Calidad
        self.assertEqual((await call("GET", f"/api/captures/{c['id']}", cookie=await self.cookie("OPERACION"))).status, 404)


class IdempotencyTests(QualityCaptureCase):
    async def test_an_identical_retry_returns_the_same_capture(self):
        _, created = await self.bobbin()
        body = self.body()
        first = (await self.submit(created["bobbin"]["id"], body)).json()
        before = self.counts()
        again = await self.submit(created["bobbin"]["id"], body)
        self.assertEqual(again.status, 200)
        self.assertEqual((again.json()["created"], again.json()["already_submitted"], again.json()["capture"]), (False, True, first["capture"]))
        equivalent = await self.submit(created["bobbin"]["id"], {**body, "values": {**VALUES, "muestras": "3"}})  # mismo valor normalizado
        self.assertEqual(equivalent.status, 200)
        self.assertEqual(self.counts(), before)

    async def test_a_reused_capture_id_with_different_content_is_409(self):
        _, created = await self.bobbin("MP1")
        _, other = await self.bobbin("MP1")
        body = self.body()
        self.assertEqual((await self.submit(created["bobbin"]["id"], body)).status, 201)
        before = self.counts()
        for bobbin_id, changed in ((other["bobbin"]["id"], body), (created["bobbin"]["id"], {**body, "values": {**VALUES, "humedad_pct": "7"}}),
                                   (created["bobbin"]["id"], {**body, "device_key": str(uuid4())}), (created["bobbin"]["id"], {**body, "form_code": "QA-TEST-MP3"})):
            reply = await self.submit(bobbin_id, changed)
            self.assertEqual((reply.status, reply.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"), changed)
        self.assertEqual(self.counts(), before)

    async def test_capture_ids_are_unique_across_f3_f6_and_quality(self):
        _, created = await self.bobbin()
        # id de la captura F3 -> conflicto en Calidad
        self.assertEqual((await self.submit(created["bobbin"]["id"], self.body(capture_id=created["capture"]["id"]))).json()["code"], "CAPTURE_IDEMPOTENCY_CONFLICT")
        quality = (await self.submit(created["bobbin"]["id"], self.body())).json()["capture"]
        _, assignment = await self.assignment("MP1")
        f6 = await call("POST", "/api/captures", cookie=await self.cookie("OPERACION"), json_body={
            "capture_id": quality["id"], "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": F6_VALUES})
        self.assertEqual((f6.status, f6.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))


class AtomicityAndRegressionTests(QualityCaptureCase):
    async def test_a_failure_in_the_middle_rolls_everything_back(self):
        _, created = await self.bobbin()
        before = self.counts()
        device_key = str(uuid4())
        calidad = self.users["CALIDAD"][0].user_id
        with patch.object(capture_service, "_insert_details", side_effect=RuntimeError("detail could not be written")):
            with self.assertRaises(RuntimeError):
                quality_captures.submit_quality_capture(self.connection, actor_id=calidad, bobbin_id=created["bobbin"]["id"], capture_id=uuid4(),
                                                        form_code=FORM, device_key=device_key, values=VALUES)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.device WHERE external_key=%s", (device_key,)), 0)
        self.assertEqual(self.release(created["bobbin"]["id"])[0], "pending")

    async def test_f3_and_f6_keep_working_with_bobbin_id_null(self):
        assignment, created = await self.bobbin()
        self.assertIsNone(self.scalar("SELECT bobbin_id FROM vinto_txn.capture WHERE id=%s", (created["capture"]["id"],)))
        f6 = await call("POST", "/api/captures", cookie=await self.cookie("OPERACION"), json_body={
            "capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": F6_VALUES})
        self.assertEqual((f6.status, f6.json()["capture"]["revision"]), (201, 1))
        self.assertIsNone(self.scalar("SELECT bobbin_id FROM vinto_txn.capture WHERE id=%s", (f6.json()["capture"]["id"],)))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id=c.form_version_id "
                                     "WHERE fv.area='production' AND c.bobbin_id IS NOT NULL"), 0)


class SchemaTests(QualityCaptureCase):
    async def test_the_fk_is_on_delete_restrict_and_indexed(self):
        fk = self.connection.execute("""SELECT confdeltype, confrelid::regclass::text FROM pg_constraint
                                        WHERE conname='capture_bobbin_fk' AND conrelid='vinto_txn.capture'::regclass""").fetchone()
        self.assertEqual(fk, ("r", "vinto_txn.bobbin"))
        index = self.scalar("SELECT indexdef FROM pg_indexes WHERE schemaname='vinto_txn' AND indexname='capture_bobbin_fk_idx'")
        self.assertIn("(bobbin_id)", index)
        self.assertNotIn("UNIQUE", index)

    async def test_fk_rejects_unknown_bobbins_and_restricts_deletion(self):
        _, created = await self.bobbin()
        c = (await self.submit(created["bobbin"]["id"], self.body())).json()["capture"]
        with self.assertRaises(psycopg.errors.ForeignKeyViolation) as raised:
            with self.connection.transaction():
                self.connection.execute("DELETE FROM vinto_txn.quality_release WHERE bobbin_id=%s", (created["bobbin"]["id"],))
                self.connection.execute("DELETE FROM vinto_txn.bobbin WHERE id=%s", (created["bobbin"]["id"],))
        self.assertIn("capture_bobbin_fk", str(raised.exception))  # la captura de Calidad impide borrar su Bobina
        with self.assertRaises(psycopg.errors.IntegrityError):  # una Bobina inexistente nunca se acepta (guard de 0005 o FK)
            with self.connection.transaction():
                self.connection.execute("UPDATE vinto_txn.capture SET bobbin_id=%s WHERE id=%s", (uuid4(), c["id"]))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin WHERE id=%s", (created["bobbin"]["id"],)), 1)
        self.assertEqual(self.scalar("SELECT bobbin_id::text FROM vinto_txn.capture WHERE id=%s", (c["id"],)), created["bobbin"]["id"])

    async def test_bobbin_id_is_immutable_and_only_quality_captures_can_carry_it(self):
        _, created = await self.bobbin()
        _, other = await self.bobbin()
        c = (await self.submit(created["bobbin"]["id"], self.body())).json()["capture"]
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute("UPDATE vinto_txn.capture SET bobbin_id=%s WHERE id=%s", (other["bobbin"]["id"], c["id"]))
        with self.assertRaises(psycopg.errors.CheckViolation):  # una captura F3 no puede apuntar a una Bobina después
            self.connection.execute("UPDATE vinto_txn.capture SET bobbin_id=%s WHERE id=%s", (created["bobbin"]["id"], created["capture"]["id"]))

    async def test_the_quality_capture_context_must_match_the_bobbin(self):
        _, mp1 = await self.bobbin("MP1")
        _, mp3 = await self.bobbin("MP3")
        quality_version = self.scalar("SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id=fv.form_id WHERE f.code=%s", (FORM,))
        production_version = self.scalar("SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id=fv.form_id WHERE f.code='VINTO-P1-06'")
        device = self.scalar("INSERT INTO vinto_master.device (external_key) VALUES (%s) RETURNING id", (str(uuid4()),))
        insert = """INSERT INTO vinto_txn.capture (form_version_id, machine_id, shift_schedule_id, device_id, assignment_id, operating_date, captured_at, status, bobbin_id)
                    SELECT %s, s.machine_id, s.shift_schedule_id, %s, s.assignment_id, s.operating_date, clock_timestamp(), 'draft', %s
                    FROM vinto_txn.bobbin b JOIN vinto_txn.capture s ON s.id = b.source_capture_id WHERE b.id = %s"""
        for version, bobbin_ref, context_from in ((production_version, mp1, mp1), (quality_version, mp1, mp3)):
            with self.assertRaises(psycopg.errors.CheckViolation):
                with self.connection.transaction():
                    self.connection.execute(insert, (version, device, bobbin_ref["bobbin"]["id"], context_from["bobbin"]["id"]))

    def test_0005_is_registered_by_the_normal_migration_mechanism(self):
        from migrate import read_migrations
        names = [m.filename for m in read_migrations()]
        self.assertEqual(names[-1], "0005_quality_capture_bobbin.sql")
        applied = self.connection.execute("SELECT version, filename FROM vinto_meta.schema_migration ORDER BY version").fetchall()
        self.assertEqual(applied[-1], (5, "0005_quality_capture_bobbin.sql"))
        self.assertEqual([r[0] for r in applied], list(range(1, len(names) + 1)))


if __name__ == "__main__":
    unittest.main()
