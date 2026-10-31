"""MF-13-01B.2: VINTO-P1-10 «Registro de fardos» versión 3, disponible en las cinco rebobinadoras (BELOIT, OVER, COPASA, PERICHUN y TUBETERA).

Decisión funcional: P1-10 deja de estar limitado a COPASA. La v3 es ADITIVA: mismos campos y reglas que la v2 (hora_inicio, hora_fin, peso_fardo, observaciones); solo cambia el vínculo con las máquinas.
La v2, ya publicada e inmutable, sigue vinculada solo a COPASA y conserva sus capturas. Sin numeración automática, sin cambios de peso, sin firmas y sin campos nuevos.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle; la v2 se instala aquí como está en producción (backend/tests/mf13_p110_v2.json)."""

import contextlib
import dataclasses
import io
import json
import secrets
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app.assignments import service as _assignments_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, database_url, drop_database
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

P110 = "VINTO-P1-10"
FIVE = ["BELOIT", "OVER", "COPASA", "PERICHUN", "TUBETERA"]
OTHER_FORMS = {"BELOIT": ["VINTO-P1-07"], "OVER": ["VINTO-P1-07"], "COPASA": ["VINTO-P1-07"], "PERICHUN": ["VINTO-P1-30"], "TUBETERA": ["VINTO-P1-29"]}  # lo que cada máquina ya ofrecía antes
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
V2 = json.loads(Path(__file__).with_name("mf13_p110_v2.json").read_text(encoding="utf-8"))  # P1-10 v2 tal como está publicada en producción (solo COPASA)
V2_PRODUCTION_CHECKSUM = "e35676ab3f9c430ef46f040174330365516d23ecd167b38e7809bae10695ee89"
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in {r["machine_code"] for r in BUNDLE.article_machines}}
SECTORS = ("BOBINAS", "REBOBINADO", "CONVERSION")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}
GOOD = {"hora_inicio": "06:30", "hora_fin": "14:45", "peso_fardo": "55,5 kg"}  # valores FICTICIOS: nada aquí es un límite ni una regla
VERSIONS = {"VINTO-P1-01": 4, "VINTO-P1-02": 1, "VINTO-P1-03": 1, "VINTO-P1-04": 2, "VINTO-P1-05": 2, "VINTO-P1-06": 2, "VINTO-P1-07": 2, "VINTO-P1-10": 3, "VINTO-P1-11": 2, "VINTO-P1-12": 3, "VINTO-P1-13": 2,
            "VINTO-P1-16": 3, "VINTO-P1-18": 2, "VINTO-P1-19": 1, "VINTO-P1-20": 1, "VINTO-P1-21": 2, "VINTO-P1-22": 2, "VINTO-P1-24": 4, "VINTO-P1-25": 3, "VINTO-P1-26": 3, "VINTO-P1-27": 2, "VINTO-P1-28": 1,
            "VINTO-P1-29": 2, "VINTO-P1-30": 2, "VINTO-P1-31": 2}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf13_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def production_before():
    """El bundle vigente con P1-10 como estaba en producción antes de MF-13-01B.2 (v2, solo COPASA)."""
    return dataclasses.replace(BUNDLE, source_checksum="7" * 64, forms=tuple(V2 if f["code"] == P110 else f for f in BUNDLE.forms))


class DefinitionTests(unittest.TestCase):
    def test_v3_changes_only_the_version_and_the_machines(self):
        v3 = FORMS[P110]
        self.assertEqual((V2["version_number"], v3["version_number"]), (2, 3))
        self.assertEqual(V2["machines"], ["COPASA"])
        self.assertEqual(v3["machines"], FIVE)
        ignored = ("version_number", "machines", "definition_checksum")
        self.assertEqual({k: v for k, v in v3.items() if k not in ignored}, {k: v for k, v in V2.items() if k not in ignored}, "mismo nombre, área, flujo, grupos y campos")

    def test_the_fields_and_their_rules_are_the_ones_of_v2_and_nothing_is_added(self):
        keys = [f["key"] for f in FORMS[P110]["fields"]]
        self.assertEqual(keys, ["hora_inicio", "hora_fin", "peso_fardo", "observaciones"])
        self.assertEqual([(f["key"], f["value_type"], f["required"], f["unit"], f["source"]) for f in FORMS[P110]["fields"]],
                         [("hora_inicio", "time", True, None, "manual"), ("hora_fin", "time", True, None, "manual"), ("peso_fardo", "text", True, None, "manual"), ("observaciones", "textarea", False, None, "manual")])
        self.assertEqual(FORMS[P110]["groups"], [])
        for forbidden in ("numero", "correlativo", "firma", "responsable", "codigo"):
            self.assertFalse([k for k in keys if forbidden in k], f"sin campos de {forbidden}: no hay numeración automática ni firmas")

    def test_the_checksums_are_consistent_and_v2_is_the_one_in_production(self):
        self.assertEqual(compute_definition_checksum(FORMS[P110]), FORMS[P110]["definition_checksum"])
        self.assertEqual(compute_definition_checksum(V2), V2["definition_checksum"])
        self.assertEqual(V2["definition_checksum"], V2_PRODUCTION_CHECKSUM)
        self.assertNotEqual(FORMS[P110]["definition_checksum"], V2["definition_checksum"])

    def test_no_other_form_changes_its_version(self):
        self.assertEqual({c: f["version_number"] for c, f in FORMS.items()}, VERSIONS)
        self.assertEqual(FORMS["VINTO-P1-07"]["machines"], ["BELOIT", "OVER", "COPASA"])
        self.assertEqual(FORMS["VINTO-P1-29"]["machines"], ["TUBETERA"])
        self.assertEqual(FORMS["VINTO-P1-30"]["machines"], ["PERICHUN"])
        self.assertEqual(sum(len(f["fields"]) + sum(len(g["fields"]) for g in f["groups"]) for f in BUNDLE.forms), 464, "el total de campos del bundle no cambia")

    def test_only_rebobinado_machines_are_linked(self):
        sectors = {m["code"]: m["sector"] for m in BUNDLE.machines}
        self.assertEqual({sectors[m] for m in FORMS[P110]["machines"]}, {"REBOBINADO"})
        self.assertEqual(sorted(m for m, s in sectors.items() if s == "REBOBINADO"), sorted(FIVE), "P1-10 cubre todas las rebobinadoras del bundle y ninguna otra")


class Base(unittest.IsolatedAsyncioTestCase):
    """Producción central con asignación sobre una base efímera: bundle vigente (P1-10 v3) + la v2 publicada como en producción."""

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf13")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        with contextlib.redirect_stdout(io.StringIO()):
            reference.apply(cls.connection, production_before())  # añade la v2 (solo COPASA) junto a la v3 que ya trae la plantilla (aditivo)
        cls.old, cls.new = cls.version(2), cls.version(3)
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", SECTORS), ("SUPERVISION", "SUPERVISION", SECTORS), ("OPERACION", "OPERACION", SECTORS), ("CALIDAD", "CALIDAD", SECTORS),
                                       ("OPERACION_BOBINAS", "OPERACION", ("BOBINAS",))):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"mf13.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def version(cls, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (P110, number)).fetchone()[0]

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        for target in (_capture_service, _assignments_service):
            p = patch.object(target, "_now", return_value=DAY)
            p.start()
            self.addCleanup(p.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        order = await call("POST", "/api/work-orders", json_body={"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE[machine], "quantity": 10, "due_date": "2026-11-01"}]}, cookie=await self.cookie("JEFATURA"))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return reply.json()["assignment"]

    async def post(self, assignment, values=None, who="OPERACION", old=False, capture_id=None, device_key=None, form=P110):
        body = {"capture_id": capture_id or str(uuid4()), "form_code": form, "assignment_id": assignment["id"], "device_key": device_key or str(uuid4()), "values": GOOD if values is None else values}
        cookie = await self.cookie(who) if who else None
        if not old:
            return await call("POST", "/api/captures", json_body=body, cookie=cookie), body
        with patch.object(_capture_service, "published_form_version", return_value=self.old):  # solo aquí se fuerza la v2, como antes de publicar la v3
            return await call("POST", "/api/captures", json_body=body, cookie=cookie), body

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def count(self, assignment):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],))


class AvailabilityTests(Base):
    async def offer(self, who="OPERACION"):
        reply = await call("GET", "/api/production/machines", cookie=await self.cookie(who))
        self.assertEqual(reply.status, 200, reply.text)
        return {m["code"]: {f["code"]: f["version_number"] for f in m["forms"]} for s in reply.json()["sectors"] for m in s["machines"]}

    async def test_p1_10_v3_is_offered_by_the_backend_for_the_five_rebobinadoras_and_keeps_their_other_forms(self):
        offered = await self.offer()
        for machine in FIVE:
            self.assertEqual(offered[machine][P110], 3, machine)
            self.assertEqual(sorted(offered[machine]), sorted(OTHER_FORMS[machine] + [P110]), f"{machine}: P1-10 se suma a lo que ya ofrecía")
            for code in OTHER_FORMS[machine]:
                self.assertEqual(offered[machine][code], FORMS[code]["version_number"], f"{machine}: {code} no cambia")

    async def test_no_machine_outside_rebobinado_gets_p1_10_and_their_offer_is_the_one_of_the_bundle(self):
        offered = await self.offer()
        for machine, forms in offered.items():
            if machine in FIVE:
                continue
            expected = sorted(f["code"] for f in BUNDLE.forms if machine in f["machines"] and f["code"] in _capture_service.CENTRAL_FORM_CODES and f["area"] == "production")
            self.assertEqual(sorted(forms), expected, machine)
            self.assertNotIn(P110, forms, machine)

    async def test_the_offer_depends_on_the_session_scope(self):
        offered = await self.offer("OPERACION_BOBINAS")
        self.assertEqual(sorted(set(offered) & set(FIVE)), [], "sin concesión de REBOBINADO la sesión no ve ninguna rebobinadora")
        self.assertEqual(sorted(offered), ["MP1", "MP3"])

    async def test_the_old_version_is_not_what_is_offered(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version_machine WHERE form_version_id = %s", (self.old,)), 1, "la v2 sigue solo con COPASA (inmutable)")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version_machine WHERE form_version_id = %s", (self.new,)), 5)
        self.assertEqual(sorted(r[0] for r in self.connection.execute(
            "SELECT m.code FROM vinto_config.form_version_machine l JOIN vinto_master.machine m ON m.id = l.machine_id WHERE l.form_version_id = %s", (self.new,)).fetchall()), sorted(FIVE))
        for version in (self.old, self.new):
            self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (version,)), "published")


class CaptureTests(Base):
    async def test_every_rebobinadora_captures_p1_10_through_its_own_assignment(self):
        for machine in FIVE:
            assignment = await self.assignment(machine)
            reply, _ = await self.post(assignment)
            self.assertEqual(reply.status, 201, (machine, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["code"], capture["form"]["version_number"], capture["machine"]["code"], capture["line"]["article"]["code"]), (P110, 3, machine, ARTICLE[machine]), machine)
            self.assertEqual(capture["values"], {"hora_inicio": "06:30:00", "hora_fin": "14:45:00", "peso_fardo": "55,5 kg"}, "se guarda lo digitado (el backend serializa las horas con segundos), sin cálculos")
            self.assertEqual(self.scalar("SELECT form_version_id FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.new)

    async def test_the_rules_of_the_fields_do_not_change(self):
        assignment = await self.assignment("TUBETERA")
        for key in ("hora_inicio", "hora_fin", "peso_fardo"):
            reply, _ = await self.post(assignment, {k: v for k, v in GOOD.items() if k != key})
            self.assertEqual(reply.status, 422, f"{key} sigue siendo obligatorio")
        for extra in ("numero_de_fardo", "codigo_numero_de_producto", "firma"):
            reply, _ = await self.post(assignment, {**GOOD, extra: "X-1"})
            self.assertEqual(reply.status, 422, f"{extra}: no existe en la v3")
        reply, _ = await self.post(assignment, {**GOOD, "observaciones": "nota"})
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(self.count(assignment), 1, "los rechazos no dejaron filas")
        self.assertNotIn("numero_de_fardo", reply.json()["capture"]["values"], "no se genera ninguna numeración")

    async def test_machines_without_the_link_are_rejected_and_nothing_is_saved(self):
        for machine in ("MP1", "GAMBINI"):
            assignment = await self.assignment(machine)
            reply, _ = await self.post(assignment)
            self.assertEqual(reply.status, 409, (machine, reply.text))
            self.assertIn("FORM_NOT_AVAILABLE", reply.text)
            self.assertEqual(self.count(assignment), 0, f"{machine}: nada guardado")

    async def test_a_retry_is_idempotent_and_a_conflicting_reuse_of_the_id_is_rejected(self):
        assignment = await self.assignment("BELOIT")
        first, body = await self.post(assignment)
        self.assertEqual(first.status, 201, first.text)
        retry = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(retry.status, 200, retry.text)
        self.assertEqual(retry.json()["capture"]["id"], first.json()["capture"]["id"])
        self.assertEqual(self.count(assignment), 1, "el reintento no duplica")
        clash, _ = await self.post(assignment, {**GOOD, "peso_fardo": "99 kg"}, capture_id=body["capture_id"], device_key=body["device_key"])
        self.assertEqual(clash.status, 409, clash.text)
        self.assertEqual(self.count(assignment), 1)
        self.assertEqual(self.scalar("SELECT d.value_text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND f.key = 'peso_fardo'", (body["capture_id"],)), "55,5 kg")

    async def test_authorization_is_the_existing_one(self):
        assignment = await self.assignment("PERICHUN")
        expected = (("anónimo", None, 401), ("JEFATURA", "JEFATURA", 403), ("SUPERVISION", "SUPERVISION", 403), ("CALIDAD", "CALIDAD", 403))
        for label, who, status in expected:
            reply, _ = await self.post(assignment, who=who)
            self.assertEqual(reply.status, status, (label, reply.text))
        scoped, _ = await self.post(assignment, who="OPERACION_BOBINAS")
        self.assertEqual(scoped.status, 404, "un operador sin concesión de REBOBINADO no ve la asignación")
        self.assertEqual(self.count(assignment), 0, "ningún rechazo dejó filas")
        ok, _ = await self.post(assignment)
        self.assertEqual(ok.status, 201, ok.text)


class HistoryTests(Base):
    async def test_v2_captures_of_copasa_stay_readable_listed_and_idempotent(self):
        assignment = await self.assignment("COPASA")
        old, body = await self.post(assignment, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["machine"]["code"]), (2, "COPASA"))
        got = await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))
        self.assertEqual((got.status, got.json()["values"], got.json()["form"]["version_number"]), (200, capture["values"], 2))
        new, _ = await self.post(assignment)
        self.assertEqual((new.status, new.json()["capture"]["form"]["version_number"]), (201, 3), "las capturas nuevas de COPASA usan la v3")
        listed = await call("GET", f"/api/captures?form_code={P110}&machine_code=COPASA", cookie=await self.cookie("OPERACION"))
        self.assertEqual(listed.status, 200, listed.text)
        versions = {c["id"]: c["form"]["version_number"] for c in listed.json()}
        self.assertEqual((versions[capture["id"]], versions[new.json()["capture"]["id"]]), (2, 3), "el historial muestra ambas versiones")
        retry = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual((retry.status, retry.json()["capture"]["id"]), (200, capture["id"]), "el reintento de la v2 no se rechaza")
        self.assertEqual(self.scalar("SELECT form_version_id FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), self.old, "la captura sigue ligada a la v2")

    async def test_the_existing_captures_are_not_rewritten_by_the_new_version(self):
        assignment = await self.assignment("COPASA")
        old, _ = await self.post(assignment, old=True)
        before = self.connection.execute("SELECT id, form_version_id, machine_id, status, revision, captured_at FROM vinto_txn.capture WHERE id = %s", (old.json()["capture"]["id"],)).fetchone()
        details = self.connection.execute("SELECT field_definition_id, value_text, value_time FROM vinto_txn.capture_detail WHERE capture_id = %s ORDER BY 1", (before[0],)).fetchall()
        for machine in FIVE:
            other = await self.assignment(machine)
            self.assertEqual((await self.post(other))[0].status, 201, machine)
        self.assertEqual(self.connection.execute("SELECT id, form_version_id, machine_id, status, revision, captured_at FROM vinto_txn.capture WHERE id = %s", (before[0],)).fetchone(), before)
        self.assertEqual(self.connection.execute("SELECT field_definition_id, value_text, value_time FROM vinto_txn.capture_detail WHERE capture_id = %s ORDER BY 1", (before[0],)).fetchall(), details)


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción tiene P1-10 v2 (solo COPASA) y todo lo demás vigente: el importador debe AÑADIR la v3 y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf13_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, production_before())

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def snapshot(self, where):
        c = self.connection
        versions = c.execute(f"""SELECT f.code, v.version_number, v.name, v.status, v.definition_checksum, v.published_at FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                 WHERE {where} ORDER BY 1, 2""").fetchall()
        fields = c.execute(f"""SELECT f.code, v.version_number, d.id, d.key, d.label, d.value_type, d.source, d.required, d.display_order FROM vinto_config.field_definition d
                               JOIN vinto_config.form_version v ON v.id = d.form_version_id JOIN vinto_config.form f ON f.id = v.form_id WHERE {where} ORDER BY 1, 2, 9""").fetchall()
        links = c.execute(f"""SELECT f.code, v.version_number, m.code FROM vinto_config.form_version_machine l JOIN vinto_config.form_version v ON v.id = l.form_version_id
                              JOIN vinto_config.form f ON f.id = v.form_id JOIN vinto_master.machine m ON m.id = l.machine_id WHERE {where} ORDER BY 1, 2, 3""").fetchall()
        return versions, fields, links

    def test_the_bundle_adds_only_p1_10_v3_and_is_idempotent(self):
        old_where = f"f.code = '{P110}' AND v.version_number = 2"
        other_where = f"f.code <> '{P110}'"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual((len(old[0]), len(old[1]), old[2]), (1, 4, [(P110, 2, "COPASA")]))
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [], "sin conflictos de importación")
        self.assertEqual((dry.counts["form_version"]["create"], dry.counts["field"]["create"], dry.counts["form_version_machine"]["create"]), (1, 4, 5))
        self.assertEqual((dry.counts["field_group"]["create"], dry.counts["option"]["create"]), (0, 0))
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "la v2, sus campos y su vínculo quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        self.assertEqual(self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (P110,)).fetchall(),
                         [(2, "published"), (3, "published")])
        self.assertEqual(self.snapshot(f"f.code = '{P110}' AND v.version_number = 3")[2], [(P110, 3, m) for m in sorted(FIVE)])
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")

    def test_widening_the_machines_of_v2_in_place_would_be_a_conflict_which_is_why_the_version_is_new(self):
        """Contraprueba: mantener la v2 y cambiarle las máquinas NO es importable (el importador nunca actualiza una versión publicada)."""
        in_place = {**V2, "machines": FIVE}
        in_place["definition_checksum"] = compute_definition_checksum(in_place)
        bundle = dataclasses.replace(BUNDLE, source_checksum="5" * 64, forms=tuple(in_place if f["code"] == P110 else f for f in BUNDLE.forms))
        database = f"vinto_mf13_neg_{uuid4().hex[:10]}_test"
        create_database(database)
        try:
            with connect(database) as connection:
                with contextlib.redirect_stdout(io.StringIO()):
                    apply_migrations(connection, read_migrations())
                reference.apply(connection, production_before())
                self.assertNotEqual(reference.dry_run(connection, bundle).conflicts, [])
        finally:
            drop_database(database)


if __name__ == "__main__":
    unittest.main()
