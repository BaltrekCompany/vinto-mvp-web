"""MF-10: versión 2 de VINTO-P1-07, P1-10, P1-29, P1-30 (Rebobinado) y P1-12 (Conversión).

  - P1-07 (MD_Ejec 23 y 47): nombre «Registro de producción de bobinas rebobinadas» + «hora_inicio» y «hora_fin» (time, obligatorias).
  - P1-10 (MD_Ejec 24 y 47): sin «codigo_numero_de_producto» ni «numero_de_fardo» (sin correlativo) + horas. Sigue vinculado solo a COPASA.
  - P1-29 (MD_Ejec 30 y 47): sin «peso_fardo» ni «peso_kg_por_formato»; «formato_tipo_de_tubete» = «Formato de tubete»; espesor en MM; diámetros interno y externo de TEXTO; + horas.
  - P1-30 (MD_Ejec 34 y 47): sin gramaje, resistencias ni número MRP; + «lote» (texto, obligatorio) donde estaba la resistencia longitudinal; + horas.
  - P1-12 (MD_Ejec 43): «formato» pasa de decimal a TEXTO libre (4*12, 4X12, 4x12, 4.12).
  Las horas son HH:MM digitadas, hora local de planta: sin duración, sin orden entre inicio y fin, sin conversión a UTC, sin fechas deducidas.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle; la versión 1 de cada formulario (instalada aquí como en producción) sigue publicada, intacta y legible."""

import contextlib
import dataclasses
import io
import secrets
import unittest
from datetime import datetime, timezone
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

P107, P110, P112, P129, P130 = "VINTO-P1-07", "VINTO-P1-10", "VINTO-P1-12", "VINTO-P1-29", "VINTO-P1-30"
CODES = (P107, P110, P112, P129, P130)
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
MACHINE = {P107: "COPASA", P110: "COPASA", P112: "GAMBINI", P129: "TUBETERA", P130: "PERICHUN"}
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in set(MACHINE.values()) | {"OVER", "BELOIT", "SINCRO_II", "SINCRO_III"}}
SECTORS = ("BOBINAS", "REBOBINADO", "CONVERSION")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}
OLD_P107_NAME = "Registro de producción de bobinas refiladas"
NEW_P107_NAME = "Registro de producción de bobinas rebobinadas"
HOURS = {"hora_inicio": "06:30", "hora_fin": "14:45"}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf10_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def req(key, kind, required=True, **extra):
    return {"key": key, "label": key, "value_type": kind, "required": required, **extra}


def v1_fields(code):
    """Definición de la versión 1 de cada formulario, tal como estaba en producción antes de MF-10 (campos de nivel de captura)."""
    current = [{"key": f["key"], "label": f["label"], "value_type": f["value_type"], "required": f["required"], "unit": f["unit"]} for f in FORMS[code]["fields"]]
    if code == P107:
        return [f for f in current if f["key"] not in HOURS]
    if code == P112:
        return [{**f, "value_type": "decimal"} if f["key"] == "formato" else f for f in current]
    if code == P110:
        return [req("codigo_numero_de_producto", "text"), req("numero_de_fardo", "text"), req("peso_fardo", "text"), req("observaciones", "textarea", False)]
    if code == P130:
        return [req("numero_de_bobina", "text"), req("gramaje_g_m2", "decimal"), req("peso_de_bobina", "text"), req("formato_mp1", "decimal"), req("formato_de_salida", "decimal"), req("resistencia_longitudinal", "decimal"),
                req("resistencia_transversal", "decimal"), req("numero_mrp", "text"), req("velocidad", "decimal"), req("observaciones", "textarea", False)]
    if code == P129:
        return [req("fecha_de_produccion", "date"), req("lote_de_produccion", "text"), req("pegamento_total_kg", "text"), req("peso_fardo", "text"), req("numero_mrp_del_sistema", "text"), req("observaciones", "textarea", False)]
    raise KeyError(code)


P129_V1_GROUPS = [
    {"code": "rodelas", "label": "Rodelas de papel kraft", "display_order": 1, "repeatable": True, "min_rows": 1, "max_rows": None, "fields": [
        req("rodela_papel_kraft_identificacion", "text"), req("rodela_papel_kraft_peso_kg", "decimal")]},
    {"code": "formatos", "label": "Formatos de tubete", "display_order": 2, "repeatable": True, "min_rows": 1, "max_rows": None, "fields": [
        req("formato_tipo_de_tubete", "text"), req("cantidad_tubetes_producidos_por_formato", "text"), req("cantidad_tubetes_observados_por_formato", "textarea", False), req("merma_kg_por_formato", "decimal"),
        req("diametro_interno_mm_por_formato", "decimal"), req("diametro_externo_mm_por_formato", "decimal"), req("cantidad_de_hojas_por_formato", "text"), req("espesor_mm_por_formato", "decimal"),
        req("peso_kg_por_formato", "decimal")]},
]


def numbered(fields):
    return [{"source": "manual", "unit": None, **f, "display_order": n} for n, f in enumerate(fields, start=1)]


def variant(checksum, spec):
    """El bundle vigente con algunas formularios sustituidos por una versión anterior: {código: (versión, campos, grupos, nombre)}."""
    forms = []
    for form in BUNDLE.forms:
        if form["code"] in spec:
            number, fields, groups, name = spec[form["code"]]
            built = [{**g, "fields": numbered(g["fields"])} for g in groups]
            form = {**form, "version_number": number, "name": name or form["name"], "fields": numbered(fields), "groups": built}
            form["definition_checksum"] = compute_definition_checksum(form)
        forms.append(form)
    return dataclasses.replace(BUNDLE, source_checksum=checksum, forms=tuple(forms))


def v1_spec():
    return {code: (1, v1_fields(code), P129_V1_GROUPS if code == P129 else [], OLD_P107_NAME if code == P107 else None) for code in CODES}


def values_for(code, version=2):
    """Valores FICTICIOS (nada aquí es un límite ni una regla) para los campos de captura de la versión indicada."""
    fields = FORMS[code]["fields"] if version == 2 else v1_fields(code)
    out = {}
    for n, f in enumerate(fields):
        if f["key"] == "observaciones":
            continue
        kind = f["value_type"]
        out[f["key"]] = f"{n}.25" if kind == "decimal" else ("2026-10-05" if kind == "date" else (HOURS.get(f["key"], "06:30") if kind == "time" else "dato ficticio MF-10"))
    if code == P129:
        out["_groups"] = p129_groups(version)
    return out


def p129_groups(version=2):
    groups = {"rodelas": [{"rodela_papel_kraft_identificacion": "R-1", "rodela_papel_kraft_peso_kg": "1.5"}]}
    row = {"formato_tipo_de_tubete": "F-1", "cantidad_tubetes_producidos_por_formato": "100", "merma_kg_por_formato": "0.5", "diametro_interno_mm_por_formato": "77-78" if version == 2 else "77.5",
           "diametro_externo_mm_por_formato": "80-81" if version == 2 else "80.5", "cantidad_de_hojas_por_formato": "10", "espesor_mm_por_formato": "0.25"}
    if version == 1:
        row["peso_kg_por_formato"] = "2.5"
    groups["formatos"] = [row, {**row, "formato_tipo_de_tubete": "F-2"}]
    return groups


class Base(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf10")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.current = {code: cls.version(code, 2) for code in CODES}
        with contextlib.redirect_stdout(io.StringIO()):
            reference.apply(cls.connection, variant("7" * 64, v1_spec()))  # las versiones 1 históricas, publicadas como en producción (aditivo)
        cls.old = {code: cls.version(code, 1) for code in CODES}
        cls.users, cls.cookies = {}, {}
        for name in ("JEFATURA", "SUPERVISION", "OPERACION"):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"mf10.{name.lower()}", display_name=name.title(), profile_code=name, password=password, sectors=SECTORS), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def version(cls, code, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()[0]

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

    async def post(self, assignment, code, values, old=False, capture_id=None):
        body = {"capture_id": capture_id or str(uuid4()), "form_code": code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": values}
        if not old:
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        with patch.object(_capture_service, "published_form_version", return_value=self.old[code]):  # solo aquí se fuerza la versión 1, como antes de publicar la 2
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))

    async def get(self, capture_id):
        return await call("GET", f"/api/captures/{capture_id}", cookie=await self.cookie("OPERACION"))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def count(self, assignment):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],))

    def stored(self, capture_id):
        return {k: (t, v) for k, t, v in self.connection.execute(
            """SELECT f.key, d.value_type, coalesce(d.value_decimal::text, d.value_time::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND d.group_row_id IS NULL""", (capture_id,)).fetchall()}


class DefinitionTests(Base):
    async def test_versions_names_and_scope(self):
        self.assertEqual({c: FORMS[c]["version_number"] for c in CODES}, {c: 2 for c in CODES})
        self.assertEqual(FORMS[P107]["name"], NEW_P107_NAME)
        self.assertEqual(self.scalar("SELECT name FROM vinto_config.form_version WHERE id = %s", (self.old[P107],)), OLD_P107_NAME, "la versión 1 conserva su nombre")
        self.assertEqual(sorted(FORMS[P107]["machines"]), ["BELOIT", "COPASA", "OVER"], "alcance publicado de P1-07 sin cambios")
        self.assertEqual(FORMS[P110]["machines"], ["COPASA"], "P1-10 sigue habilitado solo para COPASA")
        self.assertEqual(FORMS[P129]["machines"], ["TUBETERA"])
        self.assertEqual(FORMS[P130]["machines"], ["PERICHUN"])
        self.assertEqual(sorted(FORMS[P112]["machines"]), ["GAMBINI", "SINCRO_II", "SINCRO_III"])
        for code in CODES:
            self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.current[code],)), "published")
            self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.old[code],)), "published")

    async def test_hours_are_required_time_fields_in_the_four_rebobinado_forms(self):
        for code in (P107, P110, P129, P130):
            by = {f["key"]: f for f in FORMS[code]["fields"]}
            for key, label in (("hora_inicio", "Hora inicio"), ("hora_fin", "Hora fin")):
                self.assertEqual((by[key]["value_type"], by[key]["required"], by[key]["source"], by[key]["label"]), ("time", True, "manual", label), (code, key))
        self.assertNotIn("hora_inicio", [f["key"] for f in FORMS[P112]["fields"]], "Conversión no recibe horas en MF-10")

    async def test_p1_07_only_adds_the_hours(self):
        keys = [f["key"] for f in FORMS[P107]["fields"]]
        self.assertEqual((len(keys), keys[:2]), (38, ["hora_inicio", "hora_fin"]))
        self.assertEqual(keys[2:], [f["key"] for f in v1_fields(P107)])
        old = {f["key"]: f for f in v1_fields(P107)}
        for f in FORMS[P107]["fields"][2:]:
            self.assertEqual((f["label"], f["value_type"], f["required"]), (old[f["key"]]["label"], old[f["key"]]["value_type"], old[f["key"]]["required"]), f["key"])

    async def test_p1_10_p1_30_and_p1_12_fields(self):
        self.assertEqual([f["key"] for f in FORMS[P110]["fields"]], ["hora_inicio", "hora_fin", "peso_fardo", "observaciones"])
        self.assertEqual([f["key"] for f in FORMS[P130]["fields"]], ["hora_inicio", "hora_fin", "numero_de_bobina", "peso_de_bobina", "formato_mp1", "formato_de_salida", "lote", "velocidad", "observaciones"])
        lote = next(f for f in FORMS[P130]["fields"] if f["key"] == "lote")
        self.assertEqual((lote["value_type"], lote["required"]), ("text", True))
        keys30 = [f["key"] for f in FORMS[P130]["fields"]]
        self.assertEqual(keys30.index("lote"), keys30.index("formato_de_salida") + 1, "Lote en el lugar de la resistencia longitudinal")
        formato = next(f for f in FORMS[P112]["fields"] if f["key"] == "formato")
        self.assertEqual((formato["value_type"], formato["required"]), ("text", True))
        self.assertEqual([f["key"] for f in FORMS[P112]["fields"]], [f["key"] for f in v1_fields(P112)], "P1-12: mismos campos y orden; solo cambia el tipo de Formato")

    async def test_p1_29_definition(self):
        form = FORMS[P129]
        self.assertEqual([f["key"] for f in form["fields"]], ["fecha_de_produccion", "lote_de_produccion", "hora_inicio", "hora_fin", "pegamento_total_kg", "numero_mrp_del_sistema", "observaciones"])
        groups = {g["code"]: g for g in form["groups"]}
        self.assertEqual((groups["rodelas"]["min_rows"], groups["formatos"]["min_rows"], groups["rodelas"]["repeatable"], groups["formatos"]["repeatable"]), (1, 1, True, True), "filas repetibles sin cambios")
        by = {f["key"]: f for f in groups["formatos"]["fields"]}
        self.assertEqual(list(by), ["formato_tipo_de_tubete", "cantidad_tubetes_producidos_por_formato", "cantidad_tubetes_observados_por_formato", "merma_kg_por_formato", "diametro_interno_mm_por_formato",
                                    "diametro_externo_mm_por_formato", "cantidad_de_hojas_por_formato", "espesor_mm_por_formato"])
        self.assertEqual(by["formato_tipo_de_tubete"]["label"], "Formato de tubete")
        self.assertEqual((by["diametro_interno_mm_por_formato"]["value_type"], by["diametro_externo_mm_por_formato"]["value_type"]), ("text", "text"))
        self.assertEqual((by["espesor_mm_por_formato"]["unit"], by["espesor_mm_por_formato"]["value_type"]), ("MM", "decimal"))
        self.assertTrue(all(f["unit"] is None for k, f in by.items() if k != "espesor_mm_por_formato"), "no se añade «m» ni otra unidad")
        self.assertNotIn("peso_kg_por_formato", by)
        self.assertEqual([f["key"] for f in groups["rodelas"]["fields"]], ["rodela_papel_kraft_identificacion", "rodela_papel_kraft_peso_kg"])


class HoursCommon:
    """Reglas de horas comunes a los cuatro formularios de Rebobinado."""

    async def check_hours(self, code):
        assignment = await self.assignment(MACHINE[code])
        good = values_for(code)
        n = self.count(assignment)
        ok = await self.post(assignment, code, good)
        self.assertEqual(ok.status, 201, (code, ok.text))
        capture = ok.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["hora_inicio"], capture["values"]["hora_fin"]), (2, "06:30:00", "14:45:00"))
        self.assertEqual(self.stored(capture["id"])["hora_inicio"], ("time", "06:30:00"), "se guarda tal cual: sin conversión a UTC")
        self.assertTrue(capture["captured_at"].startswith("2026-10-06T16:00"), "la hora de registro sigue siendo la del sistema y no sustituye a las horas digitadas")
        for key in HOURS:  # obligatorias
            reply = await self.post(assignment, code, {k: v for k, v in good.items() if k != key})
            self.assertEqual(reply.status, 422, (code, key))
            self.assertIn(key, reply.text)
        for bad in ("24:00", "12:60", "7:30", "12:5", "abc", "", "   ", None, 730, True):
            self.assertEqual((await self.post(assignment, code, {**good, "hora_inicio": bad})).status, 422, (code, repr(bad)))
        # sin duración, sin orden y sin fechas deducidas: fin anterior a inicio (cruce de medianoche) y horas iguales se guardan tal cual
        for start, end in (("23:30", "00:15"), ("10:00", "09:00"), ("08:00", "08:00"), ("00:00", "23:59")):
            reply = await self.post(assignment, code, {**good, "hora_inicio": start, "hora_fin": end})
            self.assertEqual(reply.status, 201, (code, start, end, reply.text))
            self.assertEqual((reply.json()["capture"]["values"]["hora_inicio"], reply.json()["capture"]["values"]["hora_fin"]), (f"{start}:00", f"{end}:00"))
            self.assertEqual(reply.json()["capture"]["operating_date"], "2026-10-06", "la fecha operativa no se deduce de las horas")
        self.assertEqual(self.count(assignment), n + 5, "los intentos inválidos no dejaron filas")
        return assignment


class P107Tests(Base, HoursCommon):
    async def test_hours_and_name(self):
        assignment = await self.check_hours(P107)
        reply = await self.post(assignment, P107, values_for(P107))
        self.assertEqual(reply.json()["capture"]["form"]["name"], NEW_P107_NAME)

    async def test_version_1_stays_readable_with_its_own_name_and_no_hours(self):
        assignment = await self.assignment("COPASA")
        old = await self.post(assignment, P107, values_for(P107, version=1), old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["form"]["name"]), (1, OLD_P107_NAME))
        self.assertNotIn("hora_inicio", capture["values"], "no se fabrican horas para registros anteriores")
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[P107],)), 36)

    async def test_available_machines_are_unchanged(self):
        for machine in ("COPASA", "BELOIT", "OVER"):
            assignment = await self.assignment(machine)
            reply = await self.post(assignment, P107, values_for(P107))
            self.assertEqual(reply.status, 201, (machine, reply.text))


class P110Tests(Base, HoursCommon):
    async def test_hours_required_and_no_code_or_bale_number(self):
        assignment = await self.check_hours(P110)
        good = values_for(P110)
        self.assertEqual(sorted(good), ["hora_fin", "hora_inicio", "peso_fardo"])
        for key in ("codigo_numero_de_producto", "numero_de_fardo"):
            reply = await self.post(assignment, P110, {**good, key: "X-1"})
            self.assertEqual(reply.status, 422, key)
            self.assertIn(key, reply.text)
        reply = await self.post(assignment, P110, {**good, "observaciones": "nota"})
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual(sorted(capture["values"]), ["hora_fin", "hora_inicio", "observaciones", "peso_fardo"], "no se genera ningún correlativo ni número de fardo")
        self.assertEqual((await self.post(assignment, P110, {k: v for k, v in good.items() if k != "peso_fardo"})).status, 422, "el peso sigue siendo obligatorio")

    async def test_the_product_comes_from_the_authorized_assignment_context(self):
        assignment = await self.assignment("COPASA")
        capture = (await self.post(assignment, P110, values_for(P110))).json()["capture"]
        self.assertEqual((capture["line"]["article"]["code"], capture["work_order"]["number"], capture["machine"]["code"]), (ARTICLE["COPASA"], assignment["work_order"]["number"], "COPASA"))
        self.assertNotIn("codigo_numero_de_producto", capture["values"])

    async def test_only_copasa_can_use_p1_10(self):
        for machine in ("OVER", "BELOIT"):
            assignment = await self.assignment(machine)
            reply = await self.post(assignment, P110, values_for(P110))
            self.assertIn(reply.status, (409, 422), (machine, reply.text))
            self.assertEqual(self.count(assignment), 0, f"{machine}: nada guardado")
        assignment = await self.assignment("COPASA")
        self.assertEqual((await self.post(assignment, P110, values_for(P110))).status, 201)

    async def test_version_1_keeps_its_bale_numbers(self):
        assignment = await self.assignment("COPASA")
        old = await self.post(assignment, P110, {"codigo_numero_de_producto": "P-100", "numero_de_fardo": "F-0007", "peso_fardo": "55,5 kg"}, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["numero_de_fardo"], capture["values"]["codigo_numero_de_producto"]), (1, "F-0007", "P-100"))
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]["numero_de_fardo"]), (200, "F-0007"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[P110],)), 4)


class P129Tests(Base, HoursCommon):
    async def test_hours_required_and_rows_keep_working(self):
        assignment = await self.assignment("TUBETERA")
        good = values_for(P129)
        reply = await self.post(assignment, P129, good)
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], len(capture["values"]["_groups"]["rodelas"]), len(capture["values"]["_groups"]["formatos"])), (2, 1, 2))
        self.assertEqual((capture["values"]["hora_inicio"], capture["values"]["hora_fin"]), ("06:30:00", "14:45:00"))
        for key in HOURS:
            self.assertEqual((await self.post(assignment, P129, {k: v for k, v in good.items() if k != key})).status, 422, key)
        self.assertEqual((await self.post(assignment, P129, {**good, "hora_fin": "24:00"})).status, 422)
        n = self.count(assignment)
        two = {**good, "hora_inicio": "23:30", "hora_fin": "00:15"}
        self.assertEqual((await self.post(assignment, P129, two)).status, 201, "sin validación de orden entre inicio y fin")
        # filas: mínimo una de cada grupo (sin cambios) y varias filas
        no_rows = {**good, "_groups": {"rodelas": good["_groups"]["rodelas"], "formatos": []}}
        self.assertEqual((await self.post(assignment, P129, no_rows)).status, 422)
        self.assertEqual(self.count(assignment), n + 1)

    async def test_removed_fields_are_rejected_and_diameters_accept_text(self):
        assignment = await self.assignment("TUBETERA")
        good = values_for(P129)
        self.assertEqual((await self.post(assignment, P129, {**good, "peso_fardo": "10"})).status, 422, "«Peso fardo» ya no se solicita")
        bad_row = {**good, "_groups": {**good["_groups"], "formatos": [{**good["_groups"]["formatos"][0], "peso_kg_por_formato": "2.5"}]}}
        reply = await self.post(assignment, P129, bad_row)
        self.assertEqual(reply.status, 422, "«Peso» por formato ya no se solicita")
        self.assertIn("peso_kg_por_formato", reply.text)
        for interno, externo in (("77-78", "80-81"), ("76,5 - 77", "abc"), ("77", "80.5"), ("entre 77 y 78", "80-81 mm")):
            rows = [{**good["_groups"]["formatos"][0], "diametro_interno_mm_por_formato": interno, "diametro_externo_mm_por_formato": externo}]
            ok = await self.post(assignment, P129, {**good, "_groups": {**good["_groups"], "formatos": rows}})
            self.assertEqual(ok.status, 201, (interno, externo, ok.text))
            got = ok.json()["capture"]["values"]["_groups"]["formatos"][0]
            self.assertEqual((got["diametro_interno_mm_por_formato"], got["diametro_externo_mm_por_formato"]), (interno.strip(), externo.strip()), "se conserva el texto sin interpretar ni normalizar")
        # el espesor sigue siendo decimal obligatorio
        rows = [{**good["_groups"]["formatos"][0], "espesor_mm_por_formato": "grueso"}]
        self.assertEqual((await self.post(assignment, P129, {**good, "_groups": {**good["_groups"], "formatos": rows}})).status, 422)

    async def test_version_1_keeps_decimal_diameters_weights_and_old_labels(self):
        assignment = await self.assignment("TUBETERA")
        old = await self.post(assignment, P129, {**values_for(P129, version=1), "peso_fardo": "280"}, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        row = capture["values"]["_groups"]["formatos"][0]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["peso_fardo"], row["peso_kg_por_formato"], row["diametro_interno_mm_por_formato"]), (1, "280", "2.5", "77.5"))
        self.assertNotIn("hora_inicio", capture["values"])
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[P129],)), 6 + 2 + 9)
        self.assertEqual(self.scalar("SELECT f.label FROM vinto_config.field_definition f WHERE f.form_version_id = %s AND f.key = 'formato_tipo_de_tubete'", (self.old[P129],)), "formato_tipo_de_tubete")


class P130Tests(Base, HoursCommon):
    async def test_hours_lote_and_removed_fields(self):
        assignment = await self.check_hours(P130)
        good = values_for(P130)
        self.assertEqual(sorted(good), ["formato_de_salida", "formato_mp1", "hora_fin", "hora_inicio", "lote", "numero_de_bobina", "peso_de_bobina", "velocidad"])
        for key in ("gramaje_g_m2", "resistencia_longitudinal", "resistencia_transversal", "numero_mrp"):
            reply = await self.post(assignment, P130, {**good, key: "1.5"})
            self.assertEqual(reply.status, 422, key)
            self.assertIn(key, reply.text)
        for bad in ("", "   ", None):
            self.assertEqual((await self.post(assignment, P130, {**good, "lote": bad})).status, 422, repr(bad))
        self.assertEqual((await self.post(assignment, P130, {k: v for k, v in good.items() if k != "lote"})).status, 422, "Lote es obligatorio")
        ok = await self.post(assignment, P130, {**good, "lote": "L-2026-10 / 7"})
        self.assertEqual(ok.json()["capture"]["values"]["lote"], "L-2026-10 / 7")

    async def test_version_1_keeps_gramaje_resistances_and_mrp_without_inventing_a_lote(self):
        assignment = await self.assignment("PERICHUN")
        old = await self.post(assignment, P130, values_for(P130, version=1), old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        for key in ("gramaje_g_m2", "resistencia_longitudinal", "resistencia_transversal", "numero_mrp"):
            self.assertIn(key, capture["values"], key)
        self.assertEqual(capture["form"]["version_number"], 1)
        self.assertNotIn("lote", capture["values"], "no se inventa un Lote para registros anteriores")
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[P130],)), 10)


class P112Tests(Base):
    async def test_formato_is_free_text_kept_exactly(self):
        assignment = await self.assignment("GAMBINI")
        good = values_for(P112)
        for formato in ("4*12", "4X12", "4x12", "4.12", " 12x4 ", "4 * 12", "(4*12)", "12"):
            reply = await self.post(assignment, P112, {**good, "formato": formato})
            self.assertEqual(reply.status, 201, (formato, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["version_number"], capture["values"]["formato"]), (2, formato.strip()), "se conserva exactamente (solo el recorte general de espacios)")
            self.assertEqual(self.stored(capture["id"])["formato"], ("text", formato.strip()))
        for bad in ("", "   ", None):
            self.assertEqual((await self.post(assignment, P112, {**good, "formato": bad})).status, 422, repr(bad))
        self.assertEqual((await self.post(assignment, P112, {k: v for k, v in good.items() if k != "formato"})).status, 422, "sigue siendo obligatorio")

    async def test_version_1_decimal_values_stay_readable(self):
        assignment = await self.assignment("SINCRO_II")
        old = await self.post(assignment, P112, {**values_for(P112, version=1), "formato": "4.12"}, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["formato"]), (1, "4.12"))
        self.assertEqual(self.stored(capture["id"])["formato"], ("decimal", "4.12"), "el valor histórico sigue siendo decimal")
        # con la definición v1, el texto «4*12» no se acepta (no se reinterpreta nada de lo anterior)
        self.assertEqual((await self.post(assignment, P112, {**values_for(P112, version=1), "formato": "4*12"}, old=True)).status, 422)
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]["formato"]), (200, "4.12"))
        self.assertEqual(self.scalar("SELECT value_type FROM vinto_config.field_definition WHERE form_version_id = %s AND key = 'formato'", (self.old[P112],)), "decimal")


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción tiene los cinco formularios en v1 (y MF-05 a MF-09A ya importados): el importador debe AÑADIR las cinco v2 y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf10_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, variant("1" * 64, v1_spec()))

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def snapshot(self, where):
        c = self.connection
        versions = c.execute(f"""SELECT f.code, v.version_number, v.name, v.status, v.definition_checksum, v.published_at FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                 WHERE {where} ORDER BY 1, 2""").fetchall()
        fields = c.execute(f"""SELECT f.code, v.version_number, d.id, d.key, d.label, d.value_type, d.source, d.required, d.display_order, d.field_group_id IS NOT NULL FROM vinto_config.field_definition d
                               JOIN vinto_config.form_version v ON v.id = d.form_version_id JOIN vinto_config.form f ON f.id = v.form_id WHERE {where} ORDER BY 1, 2, 4""").fetchall()
        return versions, fields

    def test_the_bundle_adds_only_the_five_new_versions_and_is_idempotent(self):
        codes = ",".join(f"'{c}'" for c in CODES)
        old_where = f"f.code IN ({codes}) AND v.version_number = 1"
        other_where = f"f.code NOT IN ({codes})"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual((len(old[0]), len(old[1])), (5, 36 + 4 + 10 + (6 + 2 + 9) + 20))
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 5)
        self.assertEqual(dry.counts["field"]["create"], 38 + 4 + 17 + 9 + 20)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 3 + 1 + 1 + 1 + 3)
        self.assertEqual(dry.counts["field_group"]["create"], 2)
        self.assertEqual(dry.counts["option"]["create"], 0)
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "las versiones 1 y sus campos quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        for code in CODES:
            self.assertEqual(self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (code,)).fetchall(),
                             [(1, "published"), (2, "published")], code)
        names = dict(self.connection.execute("SELECT v.version_number, v.name FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s", (P107,)).fetchall())
        self.assertEqual(names, {1: OLD_P107_NAME, 2: NEW_P107_NAME})
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")


if __name__ == "__main__":
    unittest.main()
