"""M4-A: GET /api/production/machines — disponibilidad de producción de SOLO LECTURA, verificada por el backend.

Base efímera *_test con un contexto de Rebobinado FICTICIO (tests/m2b2_fixtures.py, tests/m3b_fixtures.py). Con la configuración REAL (solo BOBINAS operativo, política con solo F6) un sector
concedido pero no operativo NO aparece; con la configuración de prueba (parches por prueba) aparecen COPASA (P1-10) y TUBETERA (P1-29) con las asociaciones publicadas. Nada toca vinto.
"""

import secrets
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import SecretStr

from app import capture_service as _capture_service
from app import sectors as _sectors
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.production_access import any_view_permission
from app.seed.bundle import load_bundle

try:
    from m2a_fixtures import install_production_form
    from m2b2_fixtures import ENABLED_SECTORS, P110_CODE, REB_MACHINE, REB_SECTOR, install_p110
    from m3b_fixtures import P129_CODE, install_p129, install_tubetera
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.m2a_fixtures import install_production_form
    from tests.m2b2_fixtures import ENABLED_SECTORS, P110_CODE, REB_MACHINE, REB_SECTOR, install_p110
    from tests.m3b_fixtures import P129_CODE, install_p129, install_tubetera
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
# CLOUD-DEP G.12-C4-COMPLETE: P1-07/10/30 (Rebobinado) también están en SHIPPED_POLICY, pero solo están
# vinculados a BELOIT/OVER/COPASA/PERICHUN -- MP1/MP3 (Bobinas) nunca los ofrecen. SHIPPED_FORMS debe
# quedarse en el subconjunto que SÍ aplica a MP1/MP3, no en la política entera.
SHIPPED_FORMS = sorted(SHIPPED_POLICY & frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-06", "VINTO-P1-31"}))
ARTICLE = sorted(r["article_code"] for r in load_bundle().article_machines if r["machine_code"] == "MP1")[0]
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m4a_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class AvailabilityCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m4a")
        cls.connection = connect(cls.database)
        install_tubetera(cls.connection, [ARTICLE])
        install_p110(cls.connection)
        install_p129(cls.connection)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("OPERACION", "OPERACION", ENABLED_SECTORS), ("JEFATURA", "JEFATURA", ENABLED_SECTORS), ("SOLO_BOBINAS", "OPERACION", ("BOBINAS",)),
                                       ("SOLO_REBOBINADO", "OPERACION", (REB_SECTOR,)), ("SIN_SECTOR", "OPERACION", ()), ("DATA", "DATA_BALTREK", ENABLED_SECTORS)):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"m4a.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def get(self, path="/api/production/machines", who="OPERACION"):
        return await call("GET", path, cookie=await self.cookie(who))

    def enabled(self):
        stack = [patch.object(_sectors, "_OPERATIONAL", ENABLED_SECTORS), patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P110_CODE, P129_CODE}))]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    def codes(self, reply):
        return {s["code"]: {m["code"]: [f["code"] for f in m["forms"]] for m in s["machines"]} for s in reply.json()["sectors"]}


class RealConfigurationTests(AvailabilityCase):
    async def test_a_granted_but_non_operational_sector_is_not_exposed(self):
        # CLOUD-DEP G.12-C4: SHIPPED_POLICY ya no es solo {F6} -- se añadieron 5 candidatos de Bobinas
        # (P1-01/02/04/05/31) para QA interno sobre MP1/MP3.
        # CLOUD-DEP G.12-C4-COMPLETE: SHIPPED_POLICY también suma P1-07/10/30 (Rebobinado), por lo que
        # ya no coincide con lo que se ofrece en MP1/MP3 (esos 3 solo están vinculados a BELOIT/OVER/
        # COPASA/PERICHUN) -- se compara contra el subconjunto real de Bobinas, no contra la política entera.
        self.assertEqual(SHIPPED_POLICY, frozenset({"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-06", "VINTO-P1-31", "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-30"}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS", "REBOBINADO"))
        reply = await self.get(who="OPERACION")  # granted BOBINAS + the fictitious Rebobinado (ZZFIX), never the REAL REBOBINADO
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.codes(reply), {"BOBINAS": {"MP1": SHIPPED_FORMS, "MP3": SHIPPED_FORMS}})
        self.assertNotIn(REB_SECTOR, reply.text)  # the real REBOBINADO is operational, but never granted to this user
        self.assertNotIn('"REBOBINADO"', reply.text)
        self.assertEqual(self.codes(await self.get(who="SOLO_REBOBINADO")), {})  # only the fictitious Rebobinado granted: nothing real is operational for this user

    async def test_401_and_scope(self):
        self.assertEqual((await call("GET", "/api/production/machines")).status, 401)
        self.assertEqual((await self.get(who="SIN_SECTOR")).json(), {"sectors": []})
        self.assertEqual(self.codes(await self.get(who="SOLO_BOBINAS")), {"BOBINAS": {"MP1": SHIPPED_FORMS, "MP3": SHIPPED_FORMS}})

    async def test_the_permission_dependency_requires_at_least_one_view_permission(self):
        class Fake:
            def __init__(self, allowed):
                self.allowed = allowed

            def can(self, permission):
                return permission in self.allowed

        self.assertEqual(any_view_permission(Fake({"production.capture"})).allowed, {"production.capture"})
        self.assertEqual(any_view_permission(Fake({"assignment.read"})).allowed, {"assignment.read"})
        for denied in (set(), {"catalog.read"}, {"user.manage"}, {"quality.capture"}):
            with self.assertRaises(HTTPException) as raised:
                any_view_permission(Fake(denied))
            self.assertEqual(raised.exception.status_code, 403)


class TestConfigurationTests(AvailabilityCase):
    async def test_rebobinado_machines_and_their_published_forms_appear_only_with_the_test_configuration(self):
        self.enabled()
        reply = await self.get()
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.codes(reply), {"BOBINAS": {"MP1": [F6], "MP3": [F6]}, REB_SECTOR: {REB_MACHINE: [P110_CODE], "TUBETERA": [P129_CODE]}})
        reb = next(s for s in reply.json()["sectors"] if s["code"] == REB_SECTOR)
        self.assertEqual({m["code"]: m["name"] for m in reb["machines"]}, {REB_MACHINE: "Copasa (prueba)", "TUBETERA": "Tubetera (prueba)"})
        copasa = next(m for m in reb["machines"] if m["code"] == REB_MACHINE)
        self.assertEqual(copasa["forms"][0]["version_number"], 1)
        self.assertNotIn("articles", copasa)  # only when requested

    async def test_only_granted_users_see_rebobinado_even_when_it_is_operational(self):
        self.enabled()
        self.assertEqual(set(self.codes(await self.get(who="SOLO_BOBINAS"))), {"BOBINAS"})
        self.assertEqual(set(self.codes(await self.get(who="SOLO_REBOBINADO"))), {REB_SECTOR})
        self.assertEqual(self.codes(await self.get(who="SIN_SECTOR")), {})

    async def test_a_form_outside_the_policy_or_not_published_or_inactive_or_not_linked_is_not_listed(self):
        self.enabled()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P110_CODE})):  # P1-29 not enabled by the policy
            self.assertEqual(self.codes(await self.get())[REB_SECTOR], {REB_MACHINE: [P110_CODE], "TUBETERA": []})
        install_production_form(self.connection, "VINTO-TEST-X-DRAFT", machine_codes=(REB_MACHINE,), publish=False)
        install_production_form(self.connection, "VINTO-TEST-X-QUALITY", machine_codes=(REB_MACHINE,), area="quality")
        install_production_form(self.connection, "VINTO-TEST-X-MP1", machine_codes=("MP1",))
        install_production_form(self.connection, "VINTO-TEST-X-OFF", machine_codes=(REB_MACHINE,))
        self.connection.execute("UPDATE vinto_config.form SET active = false WHERE code = 'VINTO-TEST-X-OFF'")
        everything = frozenset({F6, P110_CODE, P129_CODE, "VINTO-TEST-X-DRAFT", "VINTO-TEST-X-QUALITY", "VINTO-TEST-X-MP1", "VINTO-TEST-X-OFF"})
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", everything):
            listed = self.codes(await self.get())
            self.assertEqual(listed[REB_SECTOR][REB_MACHINE], [P110_CODE])  # draft, quality-area and inactive forms are not offered
            self.assertEqual(listed["BOBINAS"]["MP1"], sorted([F6, "VINTO-TEST-X-MP1"]))  # linked to MP1 only there
            self.assertEqual(listed["BOBINAS"]["MP3"], [F6])

    async def test_the_highest_published_version_decides_like_the_capture_engine(self):
        self.enabled()
        version_1 = self.connection.execute("SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = %s", (P110_CODE,)).fetchone()[0]
        v2 = self.connection.execute(
            """INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum)
               SELECT form_id, 2, 'v2 sin máquinas', area, workflow_id, %s FROM vinto_config.form_version WHERE id = %s RETURNING id""", ("9" * 64, version_1)).fetchone()[0]
        self.connection.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s, 'x', 'X', 'text', 'manual', false, 1)", (v2,))
        self.connection.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (v2,))
        # version 2 is the highest published and is NOT linked to COPASA: the engine would answer FORM_NOT_AVAILABLE, so it is not offered
        self.assertEqual(self.codes(await self.get())[REB_SECTOR][REB_MACHINE], [])

    async def test_articles_are_listed_only_on_request_and_only_those_linked_to_the_machine(self):
        self.enabled()
        reply = await self.get("/api/production/machines?articles=true", "JEFATURA")
        self.assertEqual(reply.status, 200)
        machines = {m["code"]: m for s in reply.json()["sectors"] for m in s["machines"]}
        self.assertEqual([a["code"] for a in machines[REB_MACHINE]["articles"]], [ARTICLE])
        self.assertEqual([a["code"] for a in machines["TUBETERA"]["articles"]], [ARTICLE])
        self.assertTrue(all(a["description"] for a in machines[REB_MACHINE]["articles"]))
        self.assertGreater(len(machines["MP1"]["articles"]), 1)
        self.assertEqual(set(machines[REB_MACHINE]), {"code", "name", "forms", "articles"})

    async def test_it_is_read_only(self):
        self.enabled()
        tables = ("vinto_txn.capture", "vinto_txn.assignment", "vinto_txn.work_order", "vinto_config.form_version_machine", "vinto_master.machine", "vinto_audit.audit_event")
        before = {t: self.connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        for who in ("OPERACION", "JEFATURA", "DATA"):
            self.assertEqual((await self.get("/api/production/machines?articles=true", who)).status, 200)
        after = {t: self.connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        self.assertEqual(before, after)
        self.assertEqual((await call("POST", "/api/production/machines", cookie=await self.cookie("OPERACION"))).status, 405)


if __name__ == "__main__":
    unittest.main()
