"""M3-B: VINTO-P1-29 «Producción Tubetera» runs through the central production engine with TWO repeatable groups (rodelas, formatos), under an ISOLATED test configuration.

Everything is installed in an ephemeral *_test database: a fictitious Rebobinado context and Tubetera machine plus a CANDIDATE P1-29 definition (tests/m3b_fixtures.py). The
sector and the form are enabled per test with patch.object (sectors._OPERATIONAL, capture_service.CENTRAL_FORM_CODES); the shipped configuration is asserted unchanged. The
M3-A engine guarantees are not re-developed here: these tests prove they are correctly APPLIED to P1-29. This is NOT a homologation: group cardinality, the Tubetera catalog,
the responsible/approval, the espesor unit and the machine naming are pending VINTO decisions. Nothing touches vinto, backend/seed_data or the real policy.
"""

import asyncio
import copy
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
    from m2b2_fixtures import ENABLED_SECTORS, P110_CODE, P110_VALUES, install_p110
    from m3b_fixtures import P129_CODE, P129_GROUPS, P129_SIMPLE_FIELDS, P129_VALUES, TUBETERA_MACHINE, install_p129, install_tubetera
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.m2b2_fixtures import ENABLED_SECTORS, P110_CODE, P110_VALUES, install_p110
    from tests.m3b_fixtures import P129_CODE, P129_GROUPS, P129_SIMPLE_FIELDS, P129_VALUES, TUBETERA_MACHINE, install_p129, install_tubetera
    from tests.test_assignments_api import call

SHIPPED_POLICY = _capture_service.CENTRAL_FORM_CODES
SHIPPED_SECTORS = _sectors.operational_sector_codes()
F6 = "VINTO-P1-06"
F6_VALUES = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}
BUNDLE = load_bundle()
ARTICLE = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")[0]
STATE = {}
RODELAS = "rodelas"
FORMATOS = "formatos"


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m3b_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def order_body(machine, article=ARTICLE):
    return {"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": article, "quantity": 10, "due_date": "2026-11-01"}]}


def values(**changes):
    out = copy.deepcopy(P129_VALUES)
    out.update(changes)
    return out


def with_groups(**groups):
    out = copy.deepcopy(P129_VALUES)
    out["_groups"] = {**out["_groups"], **groups}
    return out


class P129Case(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m3b")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        install_tubetera(cls.connection, [ARTICLE])
        cls.version = install_p129(cls.connection)
        install_p110(cls.connection)
        cls.scope = patch.object(_sectors, "_OPERATIONAL", ENABLED_SECTORS)  # TEST-ONLY: Rebobinado operational in this process
        cls.scope.start()
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", ENABLED_SECTORS), ("SUPERVISION", "SUPERVISION", ENABLED_SECTORS), ("OPERACION", "OPERACION", ENABLED_SECTORS),
                                       ("CALIDAD", "CALIDAD", ENABLED_SECTORS), ("OPERACION_SOLO_BOBINAS", "OPERACION", ("BOBINAS",)), ("OPERACION_SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"m3b.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.scope.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6, P110_CODE, P129_CODE}))  # TEST-ONLY policy
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self, machine=TUBETERA_MACHINE):
        order = await call("POST", "/api/work-orders", json_body=order_body(machine), cookie=await self.cookie("JEFATURA"))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return order, reply.json()["assignment"]

    def body(self, assignment, payload=None, form_code=P129_CODE, **changes):
        out = {"capture_id": str(uuid4()), "form_code": form_code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": copy.deepcopy(P129_VALUES if payload is None else payload)}
        out.update(changes)
        return out

    async def post(self, body, who="OPERACION"):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who))

    async def get(self, path, who="OPERACION"):
        return await call("GET", path, cookie=await self.cookie(who))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def stored_rows(self, capture_id):
        return self.connection.execute(
            """SELECT g.code, r.row_number, (SELECT string_agg(f.key || '=' || coalesce(d.value_text, d.value_decimal::text, d.value_integer::text, d.value_date::text), '|' ORDER BY f.display_order)
                                              FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.group_row_id = r.id)
               FROM vinto_txn.capture_group_row r JOIN vinto_config.field_group g ON g.id = r.field_group_id WHERE r.capture_id = %s ORDER BY g.display_order, r.row_number""", (capture_id,)).fetchall()

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_group_row", "vinto_txn.capture_detail")}


class DefinitionTests(P129Case):
    async def test_the_candidate_definition_keeps_the_legacy_keys_types_and_has_no_simulated_automatic_fields(self):
        rows = self.connection.execute(
            """SELECT f.key, f.value_type, f.required, f.source, g.code FROM vinto_config.field_definition f LEFT JOIN vinto_config.field_group g ON g.id = f.field_group_id
               WHERE f.form_version_id = %s ORDER BY f.display_order""", (self.version,)).fetchall()
        self.assertEqual(len(rows), 6 + 2 + 9)  # 17 manual fields (the 3 legacy automatic ones are not stored)
        self.assertEqual({r[3] for r in rows}, {"manual"})
        by_key = {r[0]: r for r in rows}
        for key in ("operador", "turno", "visto_bueno_responsable"):
            self.assertNotIn(key, by_key)
        for key in ("pegamento_total_kg", "peso_fardo", "numero_mrp_del_sistema", "lote_de_produccion", "cantidad_tubetes_producidos_por_formato", "cantidad_de_hojas_por_formato", "formato_tipo_de_tubete"):
            self.assertEqual(by_key[key][1], "text", key)  # quantities and numbers stay TEXT as declared
        for key in ("rodela_papel_kraft_peso_kg", "merma_kg_por_formato", "diametro_interno_mm_por_formato", "diametro_externo_mm_por_formato", "espesor_mm_por_formato", "peso_kg_por_formato"):
            self.assertEqual(by_key[key][1], "decimal", key)
        self.assertEqual(by_key["fecha_de_produccion"][1], "date")
        self.assertEqual((by_key["observaciones"][1], by_key["observaciones"][2]), ("textarea", False))
        self.assertEqual(by_key["cantidad_tubetes_observados_por_formato"][2], False)
        self.assertEqual({r[4] for r in rows if r[4]}, {RODELAS, FORMATOS})
        groups = self.connection.execute("SELECT code, repeatable, min_rows, max_rows FROM vinto_config.field_group WHERE form_version_id = %s ORDER BY display_order", (self.version,)).fetchall()
        self.assertEqual(groups, [(RODELAS, True, 1, None), (FORMATOS, True, 1, None)])  # TEST-ONLY hypotheses

    async def test_the_shipped_configuration_is_unchanged_and_p129_is_unreachable_without_the_test_configuration(self):
        self.assertEqual(SHIPPED_POLICY, frozenset({F6}))
        self.assertEqual(SHIPPED_SECTORS, ("BOBINAS",))
        _, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            reply = await self.post(self.body(assignment))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertEqual((await self.post(self.body(assignment))).status, 404)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), 0)


class WriteTests(P129Case):
    async def test_201_persists_simple_fields_and_both_groups_in_order_with_exact_values(self):
        order, assignment = await self.assignment()
        body = self.body(assignment)
        reply = await self.post(body)
        self.assertEqual(reply.status, 201, reply.text)
        data = reply.json()
        self.assertEqual((data["created"], data["already_submitted"]), (True, False))
        capture = data["capture"]
        self.assertEqual((capture["form"]["code"], capture["status"], capture["revision"], capture["machine"]["code"]), (P129_CODE, "submitted", 1, TUBETERA_MACHINE))
        self.assertEqual((capture["assignment"]["id"], capture["work_order"]["id"]), (assignment["id"], order["id"]))
        self.assertTrue(capture["shift"]["code"].startswith("FICT_"))
        values = capture["values"]
        self.assertEqual([r["rodela_papel_kraft_identificacion"] for r in values["_groups"][RODELAS]], ["RODELA-FICTICIA-A", "RODELA-FICTICIA-B"])
        self.assertEqual([r["rodela_papel_kraft_peso_kg"] for r in values["_groups"][RODELAS]], ["10.250", "8.100"])  # decimals keep their scale, as text
        self.assertEqual([r["formato_tipo_de_tubete"] for r in values["_groups"][FORMATOS]], ["FORMATO-FICTICIO-1", "FORMATO-FICTICIO-2"])
        first = values["_groups"][FORMATOS][0]
        self.assertEqual((first["merma_kg_por_formato"], first["diametro_interno_mm_por_formato"], first["espesor_mm_por_formato"], first["peso_kg_por_formato"]), ("0.500", "38.10", "1.800", "6.750"))
        self.assertEqual((first["cantidad_tubetes_producidos_por_formato"], first["cantidad_de_hojas_por_formato"]), ("120 (texto)", "4"))  # quantities stay text
        self.assertNotIn("cantidad_tubetes_observados_por_formato", values["_groups"][FORMATOS][1])  # optional, omitted
        self.assertEqual((values["fecha_de_produccion"], values["pegamento_total_kg"], values["peso_fardo"]), ("2026-01-15", "12,5 (texto de ejemplo)", "100,0 (texto de ejemplo)"))
        for forbidden in ("operador", "turno", "visto_bueno_responsable"):
            self.assertNotIn(forbidden, values)
        stored = self.stored_rows(body["capture_id"])
        self.assertEqual([(g, n) for g, n, _ in stored], [(RODELAS, 1), (RODELAS, 2), (FORMATOS, 1), (FORMATOS, 2)])
        self.assertIn("rodela_papel_kraft_peso_kg=10.250", stored[0][2])
        self.assertIn("espesor_mm_por_formato=1.800", stored[2][2])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s AND group_row_id IS NULL", (body["capture_id"],)), 6)
        self.assertEqual(self.scalar("SELECT value_date::text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND f.key = 'fecha_de_produccion'", (body["capture_id"],)), "2026-01-15")
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), self.users["OPERACION"][0].user_id)

    async def test_decimal_precision_is_not_lost_and_the_production_date_is_the_typed_one_not_the_operating_date(self):
        _, assignment = await self.assignment()
        long = "123456789.123456789"
        payload = with_groups(rodelas=[{"rodela_papel_kraft_identificacion": "R", "rodela_papel_kraft_peso_kg": long}])
        payload["fecha_de_produccion"] = "2001-02-03"
        capture = (await self.post(self.body(assignment, payload))).json()["capture"]
        self.assertEqual(capture["values"]["_groups"][RODELAS][0]["rodela_papel_kraft_peso_kg"], long)
        self.assertEqual(capture["values"]["fecha_de_produccion"], "2001-02-03")
        self.assertEqual(capture["operating_date"], assignment["operating_date"])  # two different dates: the manual one is not silently replaced
        self.assertNotEqual(capture["operating_date"], "2001-02-03")

    async def test_200_identical_retry_creates_no_duplicates(self):
        _, assignment = await self.assignment()
        body = self.body(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        before = self.counts()
        again = await self.post(body)
        self.assertEqual((again.status, again.json()["created"], again.json()["already_submitted"]), (200, False, True))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), 4)

    async def test_409_any_change_in_a_simple_field_a_row_the_rows_or_their_order(self):
        _, assignment = await self.assignment()
        body = self.body(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        before = self.counts()
        variants = {}
        changed = copy.deepcopy(body["values"]); changed["_groups"][FORMATOS][1]["merma_kg_por_formato"] = "0.251"; variants["decimal of a format row"] = changed
        changed = copy.deepcopy(body["values"]); changed["_groups"][RODELAS].reverse(); variants["rodela order"] = changed
        changed = copy.deepcopy(body["values"]); changed["_groups"][RODELAS].pop(); variants["fewer rodelas"] = changed
        changed = copy.deepcopy(body["values"]); changed["_groups"][FORMATOS].append(copy.deepcopy(changed["_groups"][FORMATOS][0])); variants["extra format"] = changed
        changed = copy.deepcopy(body["values"]); changed["lote_de_produccion"] = "OTRO"; variants["simple field"] = changed
        changed = copy.deepcopy(body["values"]); changed["fecha_de_produccion"] = "2026-01-16"; variants["production date"] = changed
        for name, payload in variants.items():
            reply = await self.post({**body, "values": payload})
            self.assertEqual((reply.status, reply.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"), name)
        cross = await self.post({**body, "form_code": F6, "values": dict(F6_VALUES)})
        self.assertEqual(cross.status, 409)
        self.assertEqual(self.counts(), before)

    async def test_422_invalid_rows_and_fields_persist_nothing_and_never_echo_values(self):
        _, assignment = await self.assignment()
        before = self.counts()

        def mutate(fn):
            payload = copy.deepcopy(P129_VALUES)
            fn(payload)
            return payload

        cases = {
            "no rodelas (minimum 1)": (mutate(lambda v: v["_groups"].pop(RODELAS)), "_groups.rodelas: se requieren al menos 1 filas"),
            "empty formatos": (with_groups(formatos=[]), "_groups.formatos: se requieren al menos 1 filas"),
            "rodela missing weight": (mutate(lambda v: v["_groups"][RODELAS][1].pop("rodela_papel_kraft_peso_kg")), "_groups.rodelas[2].rodela_papel_kraft_peso_kg: obligatorio"),
            "format missing required": (mutate(lambda v: v["_groups"][FORMATOS][1].pop("diametro_externo_mm_por_formato")), "_groups.formatos[2].diametro_externo_mm_por_formato: obligatorio"),
            "bad decimal": (mutate(lambda v: v["_groups"][FORMATOS][0].update(espesor_mm_por_formato="secreto-1e3")), "espesor_mm_por_formato: debe ser un número decimal"),
            "quantity as JSON number (declared text)": (mutate(lambda v: v["_groups"][FORMATOS][0].update(cantidad_de_hojas_por_formato=4)), "cantidad_de_hojas_por_formato: debe ser texto"),
            "bad date": (mutate(lambda v: v.update(fecha_de_produccion="15/01/2026")), "fecha_de_produccion: debe ser una fecha AAAA-MM-DD"),
            "missing lote": (mutate(lambda v: v.pop("lote_de_produccion")), "lote_de_produccion: obligatorio"),
            "unknown row key": (mutate(lambda v: v["_groups"][RODELAS][0].update(inventada="x")), "_groups.rodelas[1].inventada: campo desconocido"),
            "undeclared group": (with_groups(otros=[{"x": "y"}]), "_groups.otros: grupo no declarado"),
            "grouped field at the top level": (mutate(lambda v: v.update(merma_kg_por_formato="1")), "merma_kg_por_formato: campo del grupo formatos"),
            "pending context sent as values": (mutate(lambda v: v.update(operador="x", turno="DIA", visto_bueno_responsable="ok")), "operador: campo desconocido"),
            "internal references": (mutate(lambda v: v["_groups"][FORMATOS][0].update(id="x", row_number=1, group_row_id="y")), "_groups.formatos[1].id: campo desconocido"),
            "empty row": (with_groups(rodelas=[{"rodela_papel_kraft_identificacion": "R", "rodela_papel_kraft_peso_kg": "1"}, {}]), "_groups.rodelas[2]"),
        }
        for name, (payload, text) in cases.items():
            reply = await self.post(self.body(assignment, payload))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"), name)
            self.assertIn(text, reply.text, name)
            self.assertNotIn("secreto", reply.text)
            self.assertNotIn("SELECT", reply.text)
        self.assertEqual(self.counts(), before)

    async def test_the_technical_row_cap_applies_because_the_candidate_declares_no_maximum(self):
        _, assignment = await self.assignment()
        row = {"rodela_papel_kraft_identificacion": "R", "rodela_papel_kraft_peso_kg": "1"}
        reply = await self.post(self.body(assignment, with_groups(rodelas=[row] * (_capture_service.TECHNICAL_MAX_GROUP_ROWS + 1))))
        self.assertEqual(reply.status, 422)
        self.assertIn(f"máximo {_capture_service.TECHNICAL_MAX_GROUP_ROWS} filas", reply.text)

    async def test_401_403_and_the_sector_scope(self):
        _, assignment = await self.assignment()
        body = self.body(assignment)
        self.assertEqual((await call("POST", "/api/captures", json_body=body)).status, 401)
        for who in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            self.assertEqual((await self.post(body, who)).status, 403, who)
        before = self.counts()
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await self.post(body, who)).status, 404, who)
        self.assertEqual(self.counts(), before)

    async def test_the_form_is_not_available_on_machines_it_is_not_linked_to(self):
        _, mp1 = await self.assignment("MP1")
        reply = await self.post(self.body(mp1))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        _, copasa = await self.assignment("COPASA")
        self.assertEqual((await self.post(self.body(copasa))).json()["code"], "FORM_NOT_AVAILABLE")

    async def test_a_failure_while_writing_rows_rolls_everything_back(self):
        _, assignment = await self.assignment()
        real = _capture_service._insert_groups

        def fail_after_the_rodelas(connection, capture_id, form_version_id, fields, groups, clean_groups):
            real(connection, capture_id, form_version_id, fields, groups, {RODELAS: clean_groups[RODELAS]})  # the first group IS written inside the transaction...
            raise RuntimeError("simulated failure while writing the formats")  # ...and then it fails

        before = self.counts()
        body = self.body(assignment)
        with patch.object(_capture_service, "_insert_groups", fail_after_the_rodelas), self.assertRaises(RuntimeError):
            await self.post(body)
        self.assertEqual(self.counts(), before)
        self.assertEqual((await self.post(body)).status, 201)  # and the very same submission works afterwards
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), 4)

    async def test_concurrency_identical_posts_create_one_capture_with_its_four_rows(self):
        _, assignment = await self.assignment()
        body = self.body(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(5)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (body["capture_id"],)), 4)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (body["capture_id"],)), 6 + 4 + 9 + 8)
        distinct = [self.body(assignment) for _ in range(3)]
        replies = await asyncio.gather(*[self.post(b) for b in distinct])
        self.assertEqual([r.status for r in replies], [201] * 3)
        for b in distinct:
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = %s", (b["capture_id"],)), 4)


class ReadTests(P129Case):
    async def test_get_by_id_and_the_filtered_list_rebuild_every_group(self):
        _, assignment = await self.assignment()
        created = (await self.post(self.body(assignment))).json()["capture"]
        read = await self.get(f"/api/captures/{created['id']}")
        self.assertEqual((read.status, read.json()["values"]), (200, created["values"]))
        listed = (await self.get(f"/api/captures?form_code={P129_CODE}")).json()
        self.assertEqual({c["form"]["code"] for c in listed}, {P129_CODE})
        self.assertEqual([c["values"] for c in listed if c["id"] == created["id"]], [created["values"]])
        self.assertEqual((await self.get(f"/api/captures?form_code={P129_CODE}&machine_code={TUBETERA_MACHINE}")).json()[0]["id"], created["id"])
        self.assertEqual((await self.get(f"/api/captures?form_code={P129_CODE}&machine_code=MP1")).json(), [])

    async def test_the_historic_f6_list_and_the_other_forms_stay_separate(self):
        _, assignment = await self.assignment()
        created = (await self.post(self.body(assignment))).json()["capture"]
        _, mp1 = await self.assignment("MP1")
        f6 = (await self.post(self.body(mp1, F6_VALUES, form_code=F6))).json()["capture"]
        self.assertNotIn("_groups", f6["values"])  # F6 keeps its exact shape
        default = (await self.get("/api/captures")).json()
        self.assertEqual({c["form"]["code"] for c in default}, {F6})
        self.assertNotIn(created["id"], [c["id"] for c in default])
        only = (await self.get(f"/api/captures?form_code={P129_CODE}")).json()
        self.assertNotIn(f6["id"], [c["id"] for c in only])
        self.assertEqual((await self.get(f"/api/captures/{f6['id']}")).json()["form"]["code"], F6)
        _, copasa = await self.assignment("COPASA")
        p110 = await self.post(self.body(copasa, dict(P110_VALUES), form_code=P110_CODE))  # P1-10 keeps working next to P1-29 and never carries _groups
        self.assertEqual(p110.status, 201, p110.text)
        self.assertNotIn("_groups", p110.json()["capture"]["values"])
        rejected = await self.post(self.body(copasa, {**P110_VALUES, "_groups": {}}, form_code=P110_CODE))
        self.assertEqual(rejected.status, 422)

    async def test_404_and_empty_results_outside_the_scope_and_401_403(self):
        _, assignment = await self.assignment()
        created = (await self.post(self.body(assignment))).json()["capture"]
        for who in ("OPERACION_SOLO_BOBINAS", "OPERACION_SIN_SECTOR"):
            self.assertEqual((await self.get(f"/api/captures/{created['id']}", who)).status, 404, who)
            self.assertEqual((await self.get(f"/api/captures?form_code={P129_CODE}", who)).json(), [], who)
        self.assertEqual((await call("GET", f"/api/captures/{created['id']}")).status, 401)
        self.assertEqual((await self.get(f"/api/captures/{created['id']}", "JEFATURA")).status, 403)
        with patch.object(_sectors, "_OPERATIONAL", SHIPPED_SECTORS):
            self.assertEqual((await self.get(f"/api/captures/{created['id']}")).status, 404)
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", SHIPPED_POLICY):
            self.assertEqual((await self.get(f"/api/captures/{created['id']}")).status, 404)
            self.assertEqual((await self.get(f"/api/captures?form_code={P129_CODE}")).status, 422)


if __name__ == "__main__":
    unittest.main()
