"""MF-11: versión nueva de VINTO-P1-26 (v3), P1-27 (v2), P1-24 (v4) en Calidad y de P1-11 (v2), P1-12 (v3), P1-13 (v2) y P1-16 (v2) en Conversión.

  - MD_Ejec 33 (P1-26): «absorcion_de_humedad» (decimal DIGITADO, OPCIONAL, sin cálculo ni rango); «% Cantidad de seco» no cambia.
  - MD_Ejec 35 (P1-27): «alcalinidad_total» (decimal DIGITADO, OPCIONAL, sin unidad, sin rango ni fórmula), distinta de la clave calculada de la definición legacy.
  - MD_Ejec 51 (P1-24): «Crepado» pasa a «Crepado (%)» (solo etiqueta; misma clave, tipo y obligatoriedad; sin conversión ni rango).
  - MD_Ejec 46 y 48 (P1-11, P1-12, P1-13, P1-16): «hora_inicio» y «hora_fin» GENERALES (time, obligatorias, HH:MM); un único par en P1-13.
  Las horas son HH:MM digitadas, hora local de planta: sin duración, sin orden entre inicio y fin, sin conversión a UTC, sin fechas deducidas.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle; la versión anterior de cada formulario (instalada aquí como en producción) sigue publicada, intacta y legible."""

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
from app.quality import capture_service as _quality_service
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

try:
    import test_devq2_p118_p121 as q2
    import test_f3_bobbins_api as f3
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_devq2_p118_p121 as q2
    import tests.test_f3_bobbins_api as f3
    from tests.test_assignments_api import call

P111, P112, P113, P116 = "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16"
P124, P126, P127 = "VINTO-P1-24", "VINTO-P1-26", "VINTO-P1-27"
CONVERSION = (P111, P112, P113, P116)
QUALITY = (P124, P126, P127)
NEW_VERSION = {P111: 2, P112: 3, P113: 2, P116: 2, P124: 4, P126: 3, P127: 2}
# MF-12B: el bundle vigente trae P1-16 v3 (una pesada por captura); estas pruebas son las de MF-11, así que reproducen el bundle de ENTONCES (P1-16 v2 con las horas, copia fiel de la definición de producción) con el resto vigente.
_P116_V2 = json.loads((Path(__file__).with_name("mf12b_p116_v2.json")).read_text(encoding="utf-8"))
_REAL = load_bundle()
BUNDLE = dataclasses.replace(_REAL, forms=tuple(_P116_V2 if f["code"] == "VINTO-P1-16" else f for f in _REAL.forms))
FORMS = {f["code"]: f for f in BUNDLE.forms}
MACHINE = {P111: "GAMBINI", P112: "GAMBINI", P113: "OMET_I", P116: "OMET_I"}
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in {r["machine_code"] for r in BUNDLE.article_machines}}
SECTORS = ("BOBINAS", "REBOBINADO", "CONVERSION")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}
HOURS = {"hora_inicio": "06:30", "hora_fin": "14:45"}
POINTS = ["Caja de formación – Colador", "Tela – Pick up", "Fieltro I", "Fieltro II", "Prensa succión", "Prensa ciega"]
VERSIONS = {"VINTO-P1-01": 4, "VINTO-P1-02": 1, "VINTO-P1-03": 1, "VINTO-P1-04": 2, "VINTO-P1-05": 2, "VINTO-P1-06": 2, "VINTO-P1-07": 2, "VINTO-P1-10": 3, P111: 2, P112: 3, P113: 2, P116: 2, "VINTO-P1-18": 2,
            "VINTO-P1-19": 1, "VINTO-P1-20": 1, "VINTO-P1-21": 2, "VINTO-P1-22": 2, P124: 4, "VINTO-P1-25": 3, P126: 3, P127: 2, "VINTO-P1-28": 1, "VINTO-P1-29": 2, "VINTO-P1-30": 2, "VINTO-P1-31": 2}  # MF-12A: P1-01 v4, P1-05 v2 y P1-31 v2
# claves que cada versión NUEVA añade respecto de la anterior
ADDED = {P111: ("hora_inicio", "hora_fin"), P112: ("hora_inicio", "hora_fin"), P113: ("hora_inicio", "hora_fin"), P116: ("hora_inicio", "hora_fin"), P126: ("absorcion_de_humedad",), P127: ("alcalinidad_total",), P124: ()}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf11_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])
        f3.STATE.pop("template", None)


def previous(code):
    """Definición de la versión ANTERIOR (la de producción antes de MF-11): campos y grupos del bundle sin lo añadido (y con la etiqueta antigua de Crepado)."""
    fields = [dict(f) for f in FORMS[code]["fields"] if f["key"] not in ADDED[code]]
    if code == P124:
        fields = [{**f, "label": "Crepado"} if f["key"] == "crepado" else f for f in fields]
    return NEW_VERSION[code] - 1, fields, FORMS[code]["groups"]


def old_spec(codes):
    return {code: previous(code) for code in codes}


def variant(checksum, spec):
    """El bundle vigente con algunos formularios sustituidos por una versión anterior: {código: (versión, campos, grupos)}."""
    forms = []
    for form in BUNDLE.forms:
        if form["code"] in spec:
            number, fields, groups = spec[form["code"]]
            built = [{**g, "fields": [{"source": "manual", "unit": None, **f, "display_order": n} for n, f in enumerate(g["fields"], start=1)]} for g in groups]
            form = {**form, "version_number": number, "fields": [{"source": "manual", "unit": None, **f, "display_order": n} for n, f in enumerate(fields, start=1)], "groups": built}
            form["definition_checksum"] = compute_definition_checksum(form)
        forms.append(form)
    return dataclasses.replace(BUNDLE, source_checksum=checksum, forms=tuple(forms))


def fill(fields, skip=()):
    """Valores FICTICIOS (nada aquí es un límite ni una regla) para los campos manuales de una definición."""
    out = {}
    for n, f in enumerate(fields):
        if f["source"] != "manual" or f["key"] in skip or f["key"] in ("observaciones", "observacion"):
            continue
        kind = f["value_type"]
        out[f["key"]] = f"{n}.25" if kind == "decimal" else (HOURS.get(f["key"], "06:30") if kind == "time" else "dato ficticio MF-11")
    return out


def bobbins_row():
    return {"numero_bobina": "B-1", "posicion": "superior", "saldo_inicial_kg": "10.5", "ingreso_kg": "2.5", "saldo_final_kg": "8"}


def central_values(code, new=True):
    fields = FORMS[code]["fields"] if new else previous(code)[1]
    out = fill(fields)
    if code == P111:
        out["_groups"] = {"bobinas": [bobbins_row()]}
    return out


class DefinitionTests(unittest.TestCase):
    def keys(self, code):
        return [f["key"] for f in FORMS[code]["fields"]]

    def test_the_seven_new_versions_and_no_other_form_changes(self):
        self.assertEqual({c: f["version_number"] for c, f in FORMS.items()}, VERSIONS)
        self.assertEqual({c: sorted(FORMS[c]["machines"]) for c in (P126, P127, P124)}, {c: ["MP1", "MP3"] for c in (P126, P127, P124)}, "P1-26, P1-27 y P1-24 siguen para MP1 y MP3")
        self.assertEqual(sorted(FORMS[P111]["machines"]), ["GAMBINI", "SINCRO_II", "SINCRO_III"])
        self.assertEqual(sorted(FORMS[P112]["machines"]), ["GAMBINI", "SINCRO_II", "SINCRO_III"])
        self.assertEqual(len(FORMS[P113]["machines"]), 8)
        self.assertEqual(len(FORMS[P116]["machines"]), 11)

    def test_p1_26_v3_adds_only_the_optional_typed_absorption(self):
        self.assertEqual(self.keys(P126), ["punto_de_muestreo", "masa_humeda", "masa_seca", "absorcion_de_humedad", "observaciones", "porcentaje_cantidad_de_seco"])
        by = {f["key"]: f for f in FORMS[P126]["fields"]}
        a = by["absorcion_de_humedad"]
        self.assertEqual((a["label"], a["value_type"], a["required"], a["source"], a["unit"]), ("Absorción de humedad", "decimal", False, "manual", None), "digitado, opcional; el % es solo visual")
        self.assertEqual((by["porcentaje_cantidad_de_seco"]["source"], by["porcentaje_cantidad_de_seco"]["label"]), ("calculated", "% Cantidad de seco"), "el cálculo existente no cambia")
        self.assertEqual([o["option_key"] for o in by["punto_de_muestreo"]["options"]], POINTS, "las seis opciones del punto de muestreo se conservan")
        self.assertEqual((by["masa_humeda"]["required"], by["masa_seca"]["required"], by["punto_de_muestreo"]["required"]), (True, True, True))

    def test_p1_27_v2_adds_the_manual_alcalinidad_without_touching_the_rest(self):
        keys = self.keys(P127)
        self.assertEqual(len(keys), 24)
        self.assertEqual(keys.index("alcalinidad_total"), keys.index("purga_caldero_cloruros") + 1, "en la sección Purga de caldero")
        by = {f["key"]: f for f in FORMS[P127]["fields"]}
        a = by["alcalinidad_total"]
        self.assertEqual((a["label"], a["value_type"], a["required"], a["source"], a["unit"]), ("Alcalinidad total", "decimal", False, "manual", None), "sin unidad declarada")
        self.assertNotIn("purga_caldero_alcalinidad_total", keys, "no se reintroduce la clave calculada legacy")
        self.assertTrue(all(f["source"] == "manual" for f in FORMS[P127]["fields"]), "ningún campo calculado")
        self.assertEqual([k for k in keys if k != "alcalinidad_total"][:13], ["ablandador_ph", "ablandador_dureza", "ablandador_solidos_disueltos", "ablandador_conductividad", "agua_alimentacion_caldero_ph",
                         "agua_alimentacion_caldero_dureza", "agua_alimentacion_caldero_solidos_disueltos", "agua_alimentacion_caldero_conductividad", "purga_caldero_ph", "purga_caldero_dureza",
                         "purga_caldero_solidos_disueltos", "purga_caldero_conductividad", "purga_caldero_cloruros"])

    def test_p1_24_v4_only_relabels_crepado(self):
        by = {f["key"]: f for f in FORMS[P124]["fields"]}
        self.assertEqual(list(by), ["crepado", "gramaje", "resistencia_longitudinal_humeda_centro", "resistencia_longitudinal_humeda_medio", "resistencia_longitudinal_humeda_extremo", "promedio_longitudinal_humedo",
                                    "resistencia_transversal_humeda_centro", "resistencia_transversal_humeda_medio", "resistencia_transversal_humeda_extremo", "promedio_transversal_humedo",
                                    "tiempo_de_curado_condicion", "observaciones"])
        c = by["crepado"]
        self.assertEqual((c["label"], c["value_type"], c["required"], c["source"], c["unit"]), ("Crepado (%)", "decimal", True, "manual", None), "misma clave, tipo y obligatoriedad; el % es solo visual")
        self.assertEqual(by["gramaje"]["label"], "Gramaje")

    def test_crepado_is_untouched_in_p1_20_and_p1_25(self):
        for code in ("VINTO-P1-20", "VINTO-P1-25"):
            crepado = next(f for f in FORMS[code]["fields"] if f["key"] == "crepado")
            self.assertEqual((crepado["label"], crepado["value_type"], crepado["required"]), ("Crepado", "decimal", True), code)
            self.assertEqual(FORMS[code]["version_number"], VERSIONS[code])

    def test_hours_are_one_required_manual_time_pair_in_each_conversion_form(self):
        for code in CONVERSION:
            keys = self.keys(code)
            self.assertEqual(keys[:2], ["hora_inicio", "hora_fin"], code)
            self.assertEqual((keys.count("hora_inicio"), keys.count("hora_fin")), (1, 1), f"{code}: un único par de horas (sin duplicados)")
            for f in FORMS[code]["fields"][:2]:
                self.assertEqual((f["value_type"], f["required"], f["source"], f["unit"]), ("time", True, "manual", None), (code, f["key"]))
            self.assertEqual([f["label"] for f in FORMS[code]["fields"][:2]], ["Hora inicio", "Hora fin"])
            self.assertFalse([k for k in keys if "pallet" in k], f"{code}: no hay campos de pallet en la definición")
        self.assertEqual(len(self.keys(P112)), 22)
        self.assertEqual(len(self.keys(P113)), 20)
        self.assertEqual(len(self.keys(P116)), 10)
        self.assertEqual(self.keys(P111), ["hora_inicio", "hora_fin", "observaciones"])
        g = FORMS[P111]["groups"][0]
        self.assertEqual((g["code"], g["min_rows"], g["repeatable"], [f["key"] for f in g["fields"]]), ("bobinas", 1, True, ["numero_bobina", "posicion", "saldo_inicial_kg", "ingreso_kg", "saldo_final_kg"]))

    def test_conversion_forms_keep_their_other_fields_exactly(self):
        for code in (P112, P113, P116):
            self.assertEqual(self.keys(code)[2:], [f["key"] for f in previous(code)[1]], code)
            old = {f["key"]: f for f in previous(code)[1]}
            self.assertEqual(len(old), len(FORMS[code]["fields"]) - 2)
        self.assertEqual(next(f for f in FORMS[P112]["fields"] if f["key"] == "formato")["value_type"], "text", "MF-10 sigue vigente")

    def test_manifest_counts(self):
        self.assertEqual(sum(len(f["fields"]) + sum(len(g["fields"]) for g in f["groups"]) for f in _REAL.forms), 464)  # MF-12A: P1-01 v4 pasa de 73 a 70 campos; MF-12B: P1-04 v2 (9 -> 7) y P1-16 v3 (10 -> 7)


class Base(unittest.IsolatedAsyncioTestCase):
    """Conversión (producción central con asignación) y Calidad por máquina."""

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf11")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.install_p116_v2_as_current()
        cls.current = {code: cls.version(code, NEW_VERSION[code]) for code in NEW_VERSION}
        with contextlib.redirect_stdout(io.StringIO()):
            reference.apply(cls.connection, variant("7" * 64, old_spec(CONVERSION + (P126, P127))))  # las versiones anteriores, publicadas como en producción (aditivo)
        cls.old = {code: cls.version(code, NEW_VERSION[code] - 1) for code in CONVERSION + (P126, P127)}
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", SECTORS), ("SUPERVISION", "SUPERVISION", SECTORS), ("OPERACION", "OPERACION", SECTORS), ("CALIDAD", "CALIDAD", ("BOBINAS",))):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"mf11.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def install_p116_v2_as_current(cls):
        """MF-12B: la plantilla trae P1-16 v3; aquí se publica la v2 de producción (con las horas) y se retira la v3 en la base efímera, de modo que el backend elige la v2 como en MF-11."""
        c = cls.connection
        v3 = cls.version(P116, 3)
        form_id, workflow, area, name = c.execute("SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (v3,)).fetchone()
        v2 = c.execute("INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s,2,%s,%s,%s,%s) RETURNING id", (form_id, name, area, workflow, _P116_V2["definition_checksum"])).fetchone()[0]
        for f in _P116_V2["fields"]:
            c.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s,%s,%s,%s,'manual',%s,%s)", (v2, f["key"], f["label"], f["value_type"], f["required"], f["display_order"]))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (v2, v3))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (v2,))
        c.execute("UPDATE vinto_config.form_version SET status = 'retired' WHERE id = %s", (v3,))

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
        with patch.object(_capture_service, "published_form_version", return_value=self.old[code]):  # solo aquí se fuerza la versión anterior, como antes de publicar la nueva
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))

    async def get(self, capture_id):
        return await call("GET", f"/api/captures/{capture_id}", cookie=await self.cookie("OPERACION"))

    async def post_machine(self, code, values, machine="MP1", old=False, capture_id=None):
        body = {"capture_id": capture_id or str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": values}
        if not old:
            return await call("POST", f"/api/quality/machines/{machine}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        with patch.object(_capture_service, "published_form_version", return_value=self.old[code]):
            return await call("POST", f"/api/quality/machines/{machine}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def count(self, assignment):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],))

    def stored(self, capture_id):
        return {k: (t, v) for k, t, v in self.connection.execute(
            """SELECT f.key, d.value_type, coalesce(d.value_decimal::text, d.value_time::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND d.group_row_id IS NULL""", (capture_id,)).fetchall()}


class HoursTests(Base):
    async def check_hours(self, code):
        assignment = await self.assignment(MACHINE[code])
        good = central_values(code)
        n = self.count(assignment)
        ok = await self.post(assignment, code, good)
        self.assertEqual(ok.status, 201, (code, ok.text))
        capture = ok.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["hora_inicio"], capture["values"]["hora_fin"]), (NEW_VERSION[code], "06:30:00", "14:45:00"))
        self.assertEqual(self.stored(capture["id"])["hora_inicio"], ("time", "06:30:00"), "se guarda tal cual: sin conversión a UTC")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND f.key = 'hora_inicio'", (capture["id"],)), 1, "un único par de horas")
        self.assertTrue(capture["captured_at"].startswith("2026-10-06T16:00"), "la hora de registro sigue siendo la del sistema y no sustituye a las horas digitadas")
        for key in HOURS:  # obligatorias
            reply = await self.post(assignment, code, {k: v for k, v in good.items() if k != key})
            self.assertEqual(reply.status, 422, (code, key))
            self.assertIn(key, reply.text)
        for bad in ("24:00", "12:60", "7:30", "12:5", "abc", "", "   ", None, 730, True):
            self.assertEqual((await self.post(assignment, code, {**good, "hora_inicio": bad})).status, 422, (code, repr(bad)))
        # sin duración, sin orden y sin fechas deducidas: fin anterior a inicio (cruce de medianoche), horas iguales y los extremos del día se guardan tal cual
        for start, end in (("23:30", "00:15"), ("10:00", "09:00"), ("08:00", "08:00"), ("00:00", "23:59")):
            reply = await self.post(assignment, code, {**good, "hora_inicio": start, "hora_fin": end})
            self.assertEqual(reply.status, 201, (code, start, end, reply.text))
            self.assertEqual((reply.json()["capture"]["values"]["hora_inicio"], reply.json()["capture"]["values"]["hora_fin"]), (f"{start}:00", f"{end}:00"))
            self.assertEqual(reply.json()["capture"]["operating_date"], "2026-10-06", "la fecha operativa no se deduce de las horas")
        self.assertEqual(self.count(assignment), n + 5, "los intentos inválidos no dejaron filas")
        return assignment

    async def check_previous_version(self, code, machine):
        assignment = await self.assignment(machine)
        old = await self.post(assignment, code, central_values(code, new=False), old=True)
        self.assertEqual(old.status, 201, (code, old.text))
        capture = old.json()["capture"]
        self.assertEqual(capture["form"]["version_number"], NEW_VERSION[code] - 1)
        self.assertNotIn("hora_inicio", capture["values"], "no se fabrican horas para registros anteriores")
        self.assertNotIn("hora_fin", capture["values"])
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.old[code],)), "published")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[code],)), len(previous(code)[1]) + sum(len(g["fields"]) for g in previous(code)[2]))
        # la versión nueva, publicada a la vez, es la que usan las capturas nuevas
        new = await self.post(assignment, code, central_values(code))
        self.assertEqual(new.json()["capture"]["form"]["version_number"], NEW_VERSION[code])

    async def test_p1_12_hours_required_and_other_fields_unchanged(self):
        assignment = await self.check_hours(P112)
        good = central_values(P112)
        self.assertEqual((await self.post(assignment, P112, {k: v for k, v in good.items() if k != "formato"})).status, 422, "formato sigue obligatorio")
        self.assertEqual((await self.post(assignment, P112, {**good, "formato": "4*12"})).status, 201, "MF-10 sigue vigente")
        await self.check_previous_version(P112, "SINCRO_II")

    async def test_p1_13_has_a_single_pair_of_general_hours(self):
        await self.check_hours(P113)
        await self.check_previous_version(P113, "OMET_II")

    async def test_p1_13_is_available_in_all_its_machines(self):
        for machine in FORMS[P113]["machines"]:
            assignment = await self.assignment(machine)
            reply = await self.post(assignment, P113, central_values(P113))
            self.assertEqual(reply.status, 201, (machine, reply.text))

    async def test_p1_16_hours(self):
        await self.check_hours(P116)
        await self.check_previous_version(P116, "SINCRO_III")

    async def test_p1_11_hours_and_the_bobbin_rows_keep_working(self):
        assignment = await self.check_hours(P111)
        good = central_values(P111)
        reply = await self.post(assignment, P111, {**good, "_groups": {"bobinas": [bobbins_row(), {**bobbins_row(), "numero_bobina": "B-2", "posicion": "inferior"}]}})
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(len(reply.json()["capture"]["values"]["_groups"]["bobinas"]), 2)
        self.assertEqual((await self.post(assignment, P111, {**good, "_groups": {"bobinas": []}})).status, 422, "al menos una fila, sin cambios")
        await self.check_previous_version(P111, "SINCRO_II")

    async def test_conversion_forms_do_not_create_pallet_hours(self):
        for code in CONVERSION:
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition d JOIN vinto_config.form_version v ON v.id = d.form_version_id WHERE v.id = %s AND d.key LIKE '%%pallet%%'", (self.current[code],)), 0)


class QualityMachineTests(Base):
    BASE_126 = {"punto_de_muestreo": "Fieltro I", "masa_humeda": "80", "masa_seca": "20"}

    async def listed(self, code, machine, capture_id):
        reply = await call("GET", f"/api/quality/machines/{machine}/captures?form_code={code}", cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 200, reply.text)
        return next(c for c in reply.json() if c["id"] == capture_id)["values"]

    def base_127(self):
        return fill([f for f in FORMS[P127]["fields"] if f["key"] != "alcalinidad_total"])

    async def test_p1_26_absorption_is_optional_and_typed(self):
        for absorption in (None, "3.5", "0", "150", "12.5"):
            values = {**self.BASE_126, **({"absorcion_de_humedad": absorption} if absorption is not None else {})}
            reply = await self.post_machine(P126, values)
            self.assertEqual(reply.status, 201, (absorption, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual(capture["form"]["version_number"], 3)
            if absorption is None:
                self.assertNotIn("absorcion_de_humedad", capture["values"])
            else:
                self.assertEqual(capture["values"]["absorcion_de_humedad"], absorption, "se guarda tal como se digitó, sin cálculo ni rango")
                self.assertEqual(self.stored(capture["id"])["absorcion_de_humedad"][0], "decimal")
            self.assertEqual(capture["values"]["porcentaje_cantidad_de_seco"], "25.00", "el % de cantidad de seco no cambia")
        for bad in ("abc", "1.2.3"):
            self.assertEqual((await self.post_machine(P126, {**self.BASE_126, "absorcion_de_humedad": bad})).status, 422, bad)

    async def test_optional_new_fields_accept_null_and_empty_and_store_nothing(self):
        for code, values, key in ((P126, self.BASE_126, "absorcion_de_humedad"), (P127, self.base_127(), "alcalinidad_total")):
            for empty in (None, "", "   "):
                reply = await self.post_machine(code, {**values, key: empty})
                self.assertEqual(reply.status, 201, (code, repr(empty), reply.text))
                capture = reply.json()["capture"]
                self.assertNotIn(key, capture["values"], "un valor vacío no se guarda ni se rellena")
                self.assertNotIn(key, self.stored(capture["id"]))

    async def test_p1_26_absorption_is_never_calculated_from_the_other_values(self):
        capture = (await self.post_machine(P126, {**self.BASE_126, "absorcion_de_humedad": "7.5"})).json()["capture"]
        self.assertEqual((capture["values"]["absorcion_de_humedad"], capture["values"]["porcentaje_cantidad_de_seco"]), ("7.5", "25.00"))
        other = (await self.post_machine(P126, {**self.BASE_126, "masa_seca": "40", "absorcion_de_humedad": "7.5"})).json()["capture"]
        self.assertEqual((other["values"]["absorcion_de_humedad"], other["values"]["porcentaje_cantidad_de_seco"]), ("7.5", "50.00"))

    async def test_p1_26_keeps_its_rules_for_mp3_and_required_fields(self):
        self.assertEqual((await self.post_machine(P126, self.BASE_126, machine="MP3")).status, 201)
        for key in self.BASE_126:
            self.assertEqual((await self.post_machine(P126, {k: v for k, v in self.BASE_126.items() if k != key})).status, 422, key)
        self.assertEqual((await self.post_machine(P126, {**self.BASE_126, "punto_de_muestreo": "Otro"})).status, 422, "lista cerrada sin cambios")
        self.assertEqual((await self.post_machine(P126, {**self.BASE_126, "porcentaje_cantidad_de_seco": "25"})).status, 422, "el cliente no envía calculados")

    async def test_p1_26_version_2_stays_readable_without_an_invented_absorption(self):
        old = await self.post_machine(P126, self.BASE_126, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual(capture["form"]["version_number"], 2)
        self.assertNotIn("absorcion_de_humedad", capture["values"])
        self.assertEqual(capture["values"]["porcentaje_cantidad_de_seco"], "25.00")
        self.assertEqual((await self.post_machine(P126, {**self.BASE_126, "absorcion_de_humedad": "1"}, old=True)).status, 422, "la versión 2 no declara el campo")
        self.assertEqual(await self.listed(P126, "MP1", capture["id"]), capture["values"])

    async def test_p1_27_alcalinidad_is_optional_decimal_without_unit(self):
        base = self.base_127()
        for value in (None, "9.5", "0", "250"):
            values = {**base, **({"alcalinidad_total": value} if value is not None else {})}
            reply = await self.post_machine(P127, values, machine="MP3")
            self.assertEqual(reply.status, 201, (value, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual(capture["form"]["version_number"], 2)
            if value is None:
                self.assertNotIn("alcalinidad_total", capture["values"])
            else:
                self.assertEqual(capture["values"]["alcalinidad_total"], value)
                self.assertEqual(self.stored(capture["id"])["alcalinidad_total"][0], "decimal")
        self.assertEqual((await self.post_machine(P127, {**base, "alcalinidad_total": "alta"})).status, 422)
        self.assertIsNone(self.scalar("SELECT unit_id FROM vinto_config.field_definition WHERE form_version_id = %s AND key = 'alcalinidad_total'", (self.current[P127],)))

    async def test_p1_27_does_not_collide_with_the_legacy_calculated_alcalinidad(self):
        base = self.base_127()
        reply = await self.post_machine(P127, {**base, "purga_caldero_alcalinidad_total": "5"})
        self.assertEqual(reply.status, 422, "la clave calculada legacy sigue sin aceptarse")
        self.assertIn("purga_caldero_alcalinidad_total", reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE key = 'purga_caldero_alcalinidad_total'"), 0, "no existe ningún campo calculado de alcalinidad")
        capture = (await self.post_machine(P127, {**base, "alcalinidad_total": "5"})).json()["capture"]
        self.assertEqual(sorted(k for k in capture["values"] if "alcalinidad" in k), ["alcalinidad_total"], "un único valor, sin duplicados")
        for key in base:  # los demás campos siguen siendo obligatorios (excepto observaciones)
            self.assertEqual((await self.post_machine(P127, {k: v for k, v in base.items() if k != key})).status, 422, key)

    async def test_p1_27_version_1_stays_readable(self):
        old = await self.post_machine(P127, self.base_127(), old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual(capture["form"]["version_number"], 1)
        self.assertNotIn("alcalinidad_total", capture["values"])
        self.assertEqual((await self.post_machine(P127, {**self.base_127(), "alcalinidad_total": "1"}, old=True)).status, 422, "la versión 1 no declara el campo")
        self.assertEqual(await self.listed(P127, "MP1", capture["id"]), capture["values"])


def p124_values():
    return fill([f for f in FORMS[P124]["fields"]])


class P124Tests(q2.BobbinBase):
    install = staticmethod(lambda connection: None)  # formularios REALES del bundle (ya publicados por la plantilla de referencia)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        c = cls.connection
        cls.v4 = c.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = 4", (P124,)).fetchone()[0]
        form_id, workflow, area, name = c.execute("SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (cls.v4,)).fetchone()
        cls.v3 = c.execute("INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s,3,%s,%s,%s,%s) RETURNING id", (form_id, name, area, workflow, "a" * 64)).fetchone()[0]
        for order, f in enumerate(previous(P124)[1], start=1):
            c.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s,%s,%s,%s,%s,%s,%s)", (cls.v3, f["key"], f["label"], f["value_type"], f["source"], f["required"], order))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (cls.v3, cls.v4))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (cls.v3,))

    async def asyncSetUp(self):
        await super().asyncSetUp()
        real = frozenset({P124})
        for name in ("BOBBIN_CANDIDATE_FORM_CODES", "ENABLED_BOBBIN_CANDIDATE_FORM_CODES"):
            patcher = patch.object(_quality_service, name, getattr(_quality_service, name) | real)
            patcher.start()
            self.addCleanup(patcher.stop)

    def body_of(self, values, capture_id=None):
        return {"capture_id": capture_id or str(uuid4()), "form_code": P124, "device_key": str(uuid4()), "values": values}

    def manual_values(self, **extra):
        return {**fill([f for f in FORMS[P124]["fields"] if f["source"] == "manual"]), **extra}

    async def test_crepado_keeps_its_key_type_and_requirement_and_accepts_any_decimal(self):
        _, bobbin = await self.bobbin("MP1")
        for crepado in ("12.5", "0", "250", "-3", "99.99"):
            reply = await self.submit(bobbin["id"], self.body_of(self.manual_values(crepado=crepado)))
            self.assertEqual(reply.status, 201, (crepado, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["version_number"], capture["values"]["crepado"]), (4, crepado), "se guarda tal como se digitó: sin rango, conversión ni normalización")
        for bad in ("abc", "", None):
            self.assertEqual((await self.submit(bobbin["id"], self.body_of(self.manual_values(crepado=bad)))).status, 422, repr(bad))
        values = self.manual_values()
        del values["crepado"]
        self.assertEqual((await self.submit(bobbin["id"], self.body_of(values))).status, 422, "sigue obligatorio")

    async def test_version_3_stays_readable_with_the_stored_value(self):
        _, bobbin = await self.bobbin("MP1")
        with patch.object(_capture_service, "published_form_version", return_value=self.v3):
            old = await self.submit(bobbin["id"], self.body_of(self.manual_values(crepado="14.2")))
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["crepado"]), (3, "14.2"), "el dato histórico se conserva sin transformar")
        got = await self.read(f"/api/quality/captures/{capture['id']}")
        self.assertEqual((got.status, got.json()["values"]["crepado"]), (200, "14.2"))
        new = await self.submit(bobbin["id"], self.body_of(self.manual_values(crepado="14.2")))
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 4)
        self.assertEqual(self.scalar("SELECT label FROM vinto_config.field_definition WHERE form_version_id = %s AND key = 'crepado'", (self.v3,)), "Crepado", "la versión 3 conserva su etiqueta")
        self.assertEqual(self.scalar("SELECT label FROM vinto_config.field_definition WHERE form_version_id = %s AND key = 'crepado'", (self.v4,)), "Crepado (%)")


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción tiene los siete formularios en su versión anterior (y MF-05 a MF-10 ya importados): el importador debe AÑADIR las siete versiones nuevas y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf11_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, variant("1" * 64, old_spec(NEW_VERSION)))

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def snapshot(self, where):
        c = self.connection
        versions = c.execute(f"""SELECT f.code, v.version_number, v.status, v.definition_checksum, v.published_at FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                 WHERE {where} ORDER BY 1, 2""").fetchall()
        fields = c.execute(f"""SELECT f.code, v.version_number, d.id, d.key, d.label, d.value_type, d.source, d.required, d.display_order FROM vinto_config.field_definition d
                               JOIN vinto_config.form_version v ON v.id = d.form_version_id JOIN vinto_config.form f ON f.id = v.form_id WHERE {where} ORDER BY 1, 2, 9""").fetchall()
        return versions, fields

    def test_the_bundle_adds_only_the_seven_new_versions_and_is_idempotent(self):
        codes = ", ".join(f"'{c}'" for c in NEW_VERSION)
        old_where = " OR ".join(f"(f.code = '{c}' AND v.version_number = {NEW_VERSION[c] - 1})" for c in NEW_VERSION)
        other_where = f"f.code NOT IN ({codes})"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual(len(old[0]), 7)
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 7)
        self.assertEqual(dry.counts["field"]["create"], 6 + 24 + 12 + 8 + 22 + 20 + 10)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 2 + 2 + 2 + 3 + 3 + 8 + 11)
        self.assertEqual(dry.counts["field_group"]["create"], 1)
        self.assertEqual(dry.counts["option"]["create"], 6 + 2, "seis opciones del punto de muestreo de P1-26 v3 y las dos posiciones del grupo de bobinas de P1-11 v2")
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "las versiones anteriores y sus campos quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        for code, number in NEW_VERSION.items():
            rows = self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (code,)).fetchall()
            self.assertEqual([r for r in rows if r[0] >= number - 1], [(number - 1, "published"), (number, "published")], code)
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")


if __name__ == "__main__":
    unittest.main()
