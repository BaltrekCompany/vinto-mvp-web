"""MF-08: controles de Calidad POR MÁQUINA, versión 2 de VINTO-P1-18, VINTO-P1-22 y VINTO-P1-26.

  - MD_Ejec 37 (P1-18): sin «punto_de_muestreo».
  - MD_Ejec 38 (P1-18): «porcentaje_consistencia» (decimal DIGITADO, OPCIONAL) justo después de «masa_seca_g».
  - MD_Ejec 39 (P1-18): «hora_del_ensayo» (HH:MM, hora local de planta, OBLIGATORIA): no es la hora de registro.
  - MD_Ejec 31 (P1-22): sin «volumen_desplazado».
  - MD_Ejec 32 (P1-26): «punto_de_muestreo» como lista cerrada de seis opciones, obligatoria.
  - MD_Ejec 40 (P1-26): «porcentaje_cantidad_de_seco» CALCULADO por el backend = masa_seca / masa_humeda × 100 (dos decimales).
  MD_Ejec 33 (absorción de humedad) NO se implementa.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle; la versión 1 (instalada aquí como en producción) sigue legible e intacta."""

import contextlib
import dataclasses
import io
import secrets
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, database_url, drop_database
from app.quality import machine_capture_service as _machine_service
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

P118, P122, P126 = "VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26"
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
FORMS[P126] = {**FORMS[P126], "version_number": 2, "fields": [f for f in FORMS[P126]["fields"] if f["key"] != "absorcion_de_humedad"]}  # MF-11: la v3 añade la absorción; aquí se prueba la v2 de MF-08
STATE = {}
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz -> DIA, fecha operativa 2026-10-06
AFTER_MIDNIGHT = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)  # 02:00 La Paz del 07 -> NOCHE, fecha operativa 2026-10-06
POINTS = ["Caja de formación – Colador", "Tela – Pick up", "Fieltro I", "Fieltro II", "Prensa succión", "Prensa ciega"]


def req(key, value_type, required=True):
    return {"key": key, "label": key, "value_type": value_type, "required": required}


V1 = {  # versión 1 tal como estaba en producción
    P118: [req("producto", "text"), req("numero_de_cuba", "text"), req("punto_de_muestreo", "text"), req("masa_humeda_g", "decimal"), req("masa_seca_g", "decimal"), req("papel_filtro_g", "text"),
           req("papel_muestra_g", "text"), req("peso_muestra_g", "decimal"), req("observaciones", "textarea", False)],
    P122: [req("numero_de_cuba", "text"), req("masa_humeda", "decimal"), req("volumen_desplazado", "decimal"), req("grado_de_refinacion_sr", "decimal"), req("amperaje", "decimal"), req("observacion", "textarea", False)],
    P126: [req("punto_de_muestreo", "text"), req("masa_humeda", "decimal"), req("masa_seca", "decimal"), req("observaciones", "textarea", False)],
}
P118_V2 = {"producto": "papel", "numero_de_cuba": "C-1", "hora_del_ensayo": "07:30", "masa_humeda_g": "12.5", "masa_seca_g": "4.2", "papel_filtro_g": "1.1", "papel_muestra_g": "0.9", "peso_muestra_g": "5.0"}
P122_V2 = {"numero_de_cuba": "C-2", "masa_humeda": "10.5", "grado_de_refinacion_sr": "30.5", "amperaje": "12.5"}
P126_V2 = {"punto_de_muestreo": "Fieltro I", "masa_humeda": "80", "masa_seca": "20"}


def restore_previous(connection, code, number, drop_keys):
    """MF-11: la base efímera trae la versión nueva del bundle; estas pruebas son de un paquete anterior, así que se RETIRA la nueva y se publica la anterior (copia de la nueva sin los campos añadidos)."""
    c = connection
    new_id, form_id, workflow, area, name = c.execute("SELECT v.id, v.form_id, v.workflow_id, v.area, v.name FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()
    c.execute("UPDATE vinto_config.form_version SET status = 'retired' WHERE id = %s", (new_id,))
    old_id = c.execute("INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (form_id, number - 1, name, area, workflow, "b" * 64)).fetchone()[0]
    for fid, key, label, value_type, source, required, order in c.execute("SELECT id, key, label, value_type, source, required, display_order FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY display_order", (new_id,)).fetchall():
        if key in drop_keys:
            continue
        copy = c.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id", (old_id, key, label, value_type, source, required, order)).fetchone()[0]
        for option_key, option_label, option_order in c.execute("SELECT option_key, label, display_order FROM vinto_config.field_option WHERE field_definition_id = %s", (fid,)).fetchall():
            c.execute("INSERT INTO vinto_config.field_option (form_version_id, field_definition_id, option_key, label, display_order) VALUES (%s,%s,%s,%s,%s)", (old_id, copy, option_key, option_label, option_order))
    c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (old_id, new_id))
    c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (old_id,))


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf08_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class Base(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf08")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        # MF-11 publicó P1-26 v3 (con «Absorción de humedad»): estas pruebas son las de MF-08, así que en la base EFÍMERA se vuelve a la v2 (ver restore_previous).
        restore_previous(cls.connection, P126, 3, ("absorcion_de_humedad",))
        cls.current = {code: cls.version(code, 2) for code in V1}
        cls.v1 = {code: cls.install_v1(code) for code in V1}
        password = "pw-" + secrets.token_urlsafe(18)
        cls.user = (create_user(cls.connection, username="mf08.calidad", display_name="Calidad", profile_code="CALIDAD", password=password, sectors=("BOBINAS",)), password)
        cls.cookie_value = None

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def version(cls, code, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()[0]

    @classmethod
    def install_v1(cls, code):
        c = cls.connection
        form_id, workflow, area, name = c.execute("SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (cls.current[code],)).fetchone()
        v1 = c.execute("INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s,1,%s,%s,%s,%s) RETURNING id", (form_id, name, area, workflow, "a" * 64)).fetchone()[0]
        for order, f in enumerate(V1[code], start=1):
            c.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s,%s,%s,%s,'manual',%s,%s)", (v1, f["key"], f["label"], f["value_type"], f["required"], order))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (v1, cls.current[code]))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (v1,))
        return v1

    async def asyncSetUp(self):
        clock = patch.object(_capture_service, "_now", return_value=DAY)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    async def cookie(self):
        if self.__class__.cookie_value is None:
            created, password = self.user
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200)
            self.__class__.cookie_value = reply.set_cookie_value()
        return self.__class__.cookie_value

    def body(self, code, values, capture_id=None):
        return {"capture_id": capture_id or str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": values}

    async def post(self, code, values, machine="MP1", at=DAY, capture_id=None):
        self.clock.return_value = at
        return await call("POST", f"/api/quality/machines/{machine}/captures", json_body=self.body(code, values, capture_id), cookie=await self.cookie())

    async def post_v1(self, code, values, machine="MP1"):
        """Captura HISTÓRICA: solo aquí se fuerza la versión 1, como ocurría antes de publicar la 2."""
        with patch.object(_capture_service, "published_form_version", return_value=self.v1[code]):
            return await self.post(code, values, machine)

    async def get(self, path):
        return await call("GET", path, cookie=await self.cookie())

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def stored(self, capture_id):
        return {k: (t, v) for k, t, v in self.connection.execute(
            """SELECT f.key, d.value_type, coalesce(d.value_decimal::text, d.value_time::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall()}

    def count(self, code):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version v ON v.id = c.form_version_id JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s", (code,))


class DefinitionTests(Base):
    async def test_bundle_versions_and_scope(self):
        self.assertEqual({c: FORMS[c]["version_number"] for c in V1}, {P118: 2, P122: 2, P126: 2})
        self.assertEqual(sorted((f["code"], f["version_number"]) for f in BUNDLE.forms if f["version_number"] != 1),
                         [("VINTO-P1-01", 4), ("VINTO-P1-05", 2), ("VINTO-P1-06", 2), ("VINTO-P1-07", 2), ("VINTO-P1-10", 2), ("VINTO-P1-11", 2), ("VINTO-P1-12", 3), ("VINTO-P1-13", 2), ("VINTO-P1-16", 2), ("VINTO-P1-18", 2), ("VINTO-P1-21", 2), ("VINTO-P1-22", 2), ("VINTO-P1-24", 4), ("VINTO-P1-25", 3), ("VINTO-P1-26", 3), ("VINTO-P1-27", 2), ("VINTO-P1-29", 2), ("VINTO-P1-30", 2), ("VINTO-P1-31", 2)], "respecto de MF-07 solo cambian estas tres (MF-09 añade P1-01 v3 y P1-06 v2; MF-10 y MF-11 las demás de la lista)")
        for code in V1:
            self.assertEqual(FORMS[code]["machines"], ["MP1", "MP3"])
            self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.current[code],)), "published")

    async def test_p1_18_v2_fields(self):
        keys = [f["key"] for f in FORMS[P118]["fields"]]
        self.assertEqual(keys, ["producto", "numero_de_cuba", "hora_del_ensayo", "masa_humeda_g", "masa_seca_g", "porcentaje_consistencia", "papel_filtro_g", "papel_muestra_g", "peso_muestra_g", "observaciones"])
        self.assertEqual(keys.index("porcentaje_consistencia"), keys.index("masa_seca_g") + 1, "% Consistencia inmediatamente después de Masa seca g")
        by = {f["key"]: f for f in FORMS[P118]["fields"]}
        self.assertEqual((by["porcentaje_consistencia"]["value_type"], by["porcentaje_consistencia"]["required"], by["porcentaje_consistencia"]["source"]), ("decimal", False, "manual"), "opcional y digitado")
        self.assertEqual((by["hora_del_ensayo"]["value_type"], by["hora_del_ensayo"]["required"], by["hora_del_ensayo"]["label"]), ("time", True, "Hora"))
        self.assertNotIn("punto_de_muestreo", keys)
        old = {f["key"]: f for f in V1[P118]}
        for key, f in by.items():
            if key in old:
                self.assertEqual((f["value_type"], f["required"]), (old[key]["value_type"], old[key]["required"]), key)

    async def test_p1_22_v2_fields(self):
        keys = [f["key"] for f in FORMS[P122]["fields"]]
        self.assertEqual(keys, ["numero_de_cuba", "masa_humeda", "grado_de_refinacion_sr", "amperaje", "observacion"])
        old = {f["key"]: f for f in V1[P122]}
        for f in FORMS[P122]["fields"]:
            self.assertEqual((f["value_type"], f["required"], f["source"]), (old[f["key"]]["value_type"], old[f["key"]]["required"], "manual"), f["key"])

    async def test_p1_26_v2_fields_options_and_calculated(self):
        fields = FORMS[P126]["fields"]
        self.assertEqual([f["key"] for f in fields], ["punto_de_muestreo", "masa_humeda", "masa_seca", "observaciones", "porcentaje_cantidad_de_seco"])
        point = fields[0]
        self.assertEqual((point["value_type"], point["required"], point["source"]), ("text", True, "manual"))
        self.assertEqual([o["option_key"] for o in point["options"]], POINTS)
        self.assertEqual([o["label"] for o in point["options"]], POINTS, "los textos aprobados, sin cambios")
        self.assertEqual([o["display_order"] for o in point["options"]], list(range(1, 7)))
        calc = fields[-1]
        self.assertEqual((calc["label"], calc["value_type"], calc["source"], calc["required"]), ("% Cantidad de seco", "decimal", "calculated", False))
        self.assertNotIn("absorcion_de_humedad", [f["key"] for f in fields], "MD_Ejec 33 queda fuera")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_option WHERE form_version_id = %s", (self.current[P126],)), 6)


class P118Tests(Base):
    async def test_valid_capture_keeps_the_typed_hour_and_the_optional_percent(self):
        for percent in (None, "12.75"):
            values = {**P118_V2, **({"porcentaje_consistencia": percent} if percent else {})}
            reply = await self.post(P118, values)
            self.assertEqual(reply.status, 201, reply.text)
            capture = reply.json()["capture"]
            self.assertEqual(capture["form"]["version_number"], 2)
            self.assertEqual(capture["values"], {**values, "hora_del_ensayo": "07:30:00"})
            stored = self.stored(capture["id"])
            self.assertEqual(stored["hora_del_ensayo"], ("time", "07:30:00"))
            self.assertEqual("porcentaje_consistencia" in stored, percent is not None)
            if percent:
                self.assertEqual(stored["porcentaje_consistencia"], ("decimal", "12.75"), "se guarda tal como se digitó: no se calcula")
        self.assertNotIn("punto_de_muestreo", capture["values"])

    async def test_hour_is_required_and_strictly_validated(self):
        n = self.count(P118)
        for good in ("00:00", "23:59", "07:05", " 12:30 "):
            self.assertEqual((await self.post(P118, {**P118_V2, "hora_del_ensayo": good})).status, 201, good)
        for bad in ("24:00", "12:60", "25:10", "7:30", "12:5", "abc", "12.30", "1230", "", "   ", None, 730, True):
            self.assertEqual((await self.post(P118, {**P118_V2, "hora_del_ensayo": bad})).status, 422, repr(bad))
        missing = {k: v for k, v in P118_V2.items() if k != "hora_del_ensayo"}
        reply = await self.post(P118, missing)
        self.assertEqual(reply.status, 422)
        self.assertIn("hora_del_ensayo", reply.text)
        self.assertEqual(self.count(P118), n + 4, "los intentos inválidos no dejaron filas")

    async def test_typed_hour_is_not_the_registration_time_and_midnight_adds_no_date(self):
        reply = await self.post(P118, {**P118_V2, "hora_del_ensayo": "07:30"}, at=DAY)  # registro: 12:00 de planta
        capture = reply.json()["capture"]
        self.assertEqual(capture["values"]["hora_del_ensayo"], "07:30:00")
        self.assertTrue(capture["captured_at"].startswith("2026-10-06T16:00"), "la hora de registro sigue siendo la del sistema (UTC)")
        night = await self.post(P118, {**P118_V2, "hora_del_ensayo": "23:50"}, at=AFTER_MIDNIGHT)  # registro: 02:00 del día siguiente, ensayo 23:50
        got = night.json()["capture"]
        self.assertEqual((got["values"]["hora_del_ensayo"], got["operating_date"]), ("23:50:00", "2026-10-06"), "la fecha operativa es la vigente; no se deduce otra por cruzar la medianoche")
        self.assertEqual(self.stored(got["id"])["hora_del_ensayo"], ("time", "23:50:00"), "sin conversión a UTC")

    async def test_removed_field_and_invalid_percent_are_rejected(self):
        for extra in ({"punto_de_muestreo": "salida"}, {"porcentaje_consistencia": "abc"}, {"porcentaje_consistencia": "1,5"}, {"consistencia": "5"}):
            self.assertEqual((await self.post(P118, {**P118_V2, **extra})).status, 422, extra)

    async def test_version_1_stays_readable_with_its_own_fields(self):
        old = await self.post_v1(P118, {k: v for k, v in P118_V2.items() if k != "hora_del_ensayo"} | {"punto_de_muestreo": "salida"})
        self.assertEqual(old.status, 201, old.text)
        old_capture = old.json()["capture"]
        self.assertEqual((old_capture["form"]["version_number"], old_capture["values"]["punto_de_muestreo"]), (1, "salida"))
        self.assertNotIn("hora_del_ensayo", old_capture["values"])
        new = await self.post(P118, P118_V2)
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 2)
        listed = (await self.get(f"/api/quality/machines/MP1/captures?form_code={P118}")).json()
        self.assertEqual({c["form"]["version_number"] for c in listed}, {1, 2})
        self.assertLessEqual({old_capture["id"], new.json()["capture"]["id"]}, {c["id"] for c in listed})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.v1[P118],)), 9)


class P122Tests(Base):
    async def test_volume_is_gone_and_other_rules_hold(self):
        ok = await self.post(P122, P122_V2)
        self.assertEqual(ok.status, 201, ok.text)
        self.assertEqual((ok.json()["capture"]["form"]["version_number"], ok.json()["capture"]["values"]), (2, P122_V2))
        self.assertEqual((await self.post(P122, {**P122_V2, "volumen_desplazado": "5"})).status, 422)
        for key in ("numero_de_cuba", "masa_humeda", "grado_de_refinacion_sr", "amperaje"):  # los demás siguen obligatorios
            self.assertEqual((await self.post(P122, {k: v for k, v in P122_V2.items() if k != key})).status, 422, key)
        self.assertEqual((await self.post(P122, {**P122_V2, "amperaje": "abc"})).status, 422)
        self.assertEqual((await self.post(P122, {**P122_V2, "observacion": "nota"})).status, 201)

    async def test_version_1_with_volume_stays_readable(self):
        old = await self.post_v1(P122, {**P122_V2, "volumen_desplazado": "7.5"})
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["volumen_desplazado"]), (1, "7.5"))
        got = await self.get(f"/api/quality/machines/MP1/captures?form_code={P122}")
        self.assertIn(capture["id"], [c["id"] for c in got.json()])


class P126Tests(Base):
    async def test_the_six_options_are_accepted_exactly_and_nothing_else(self):
        n = self.count(P126)
        for point in POINTS + [" Fieltro II "]:  # el recorte de espacios es la normalización general de texto de toda captura
            reply = await self.post(P126, {**P126_V2, "punto_de_muestreo": point})
            self.assertEqual(reply.status, 201, (point, reply.text))
            self.assertEqual(reply.json()["capture"]["values"]["punto_de_muestreo"], point.strip())
        for bad in ("salida", "fieltro i", "Fieltro  I", "Caja de formacion – Colador", "Caja de formación - Colador", "Tela", "Fieltro III", "", "   ", None, 1, ["Fieltro I"]):
            reply = await self.post(P126, {**P126_V2, "punto_de_muestreo": bad})
            self.assertEqual(reply.status, 422, repr(bad))
        missing = await self.post(P126, {k: v for k, v in P126_V2.items() if k != "punto_de_muestreo"})
        self.assertEqual(missing.status, 422)
        self.assertEqual(self.count(P126), n + 7, "ningún valor inválido dejó filas")

    async def test_percent_is_calculated_by_the_backend_with_two_decimals(self):
        cases = [("80", "20", "25.00"), ("3", "1", "33.33"), ("3", "2", "66.67"), ("16", "1", "6.25"), ("800", "1", "0.13"), ("8", "1", "12.50"), ("1.5", "1.5", "100.00"),
                 ("50", "0", "0.00"), ("7", "7.35", "105.00"), ("3", "-1", "-33.33")]
        for wet, dry, expected in cases:
            reply = await self.post(P126, {**P126_V2, "masa_humeda": wet, "masa_seca": dry})
            self.assertEqual(reply.status, 201, (wet, dry, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual(capture["values"]["porcentaje_cantidad_de_seco"], expected, (wet, dry))
            self.assertEqual(self.stored(capture["id"])["porcentaje_cantidad_de_seco"], ("decimal", expected))
            self.assertEqual((capture["values"]["masa_humeda"], capture["values"]["masa_seca"]), (wet, dry), "las masas se guardan como se digitaron")
        self.assertEqual(_machine_service.percent_two_decimals(Decimal("0.5"), Decimal("1")), Decimal("50.00"))
        self.assertEqual(_machine_service.percent_two_decimals(Decimal("-0.00001"), Decimal("1")), Decimal("0.00"))

    async def test_zero_wet_mass_yields_no_invented_result(self):
        reply = await self.post(P126, {**P126_V2, "masa_humeda": "0", "masa_seca": "5"})
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertNotIn("porcentaje_cantidad_de_seco", capture["values"], "sin resultado, no se guarda ni se inventa un 0")
        self.assertNotIn("porcentaje_cantidad_de_seco", self.stored(capture["id"]))
        self.assertEqual(capture["values"]["masa_humeda"], "0")
        again = await self.post(P126, {**P126_V2, "masa_humeda": "0.0", "masa_seca": "0"})
        self.assertNotIn("porcentaje_cantidad_de_seco", again.json()["capture"]["values"])

    async def test_clients_cannot_send_the_calculated_value(self):
        n = self.count(P126)
        for key in ("porcentaje_cantidad_de_seco", "porcentaje_de_secos"):
            reply = await self.post(P126, {**P126_V2, key: "99.00"})
            self.assertEqual(reply.status, 422, key)
        self.assertIn("calculado", (await self.post(P126, {**P126_V2, "porcentaje_cantidad_de_seco": "25.00"})).text, "el mensaje dice que es un campo calculado por el sistema")
        self.assertEqual((await self.post(P126, {**P126_V2, "absorcion_de_humedad": "3"})).status, 422, "MD_Ejec 33 no existe")
        self.assertEqual(self.count(P126), n)

    async def test_idempotent_retry_with_the_calculated_value(self):
        body = self.body(P126, P126_V2)
        cookie = await self.cookie()
        post = lambda b: call("POST", "/api/quality/machines/MP1/captures", json_body=b, cookie=cookie)  # noqa: E731
        first, again = await post(body), await post(body)
        self.assertEqual((first.status, again.status), (201, 200), (first.text, again.text))
        self.assertEqual(first.json()["capture"], again.json()["capture"])
        self.assertEqual((await post({**body, "values": {**P126_V2, "masa_seca": "21"}})).status, 409)

    async def test_version_1_free_text_stays_readable_and_is_not_recalculated(self):
        old = await self.post_v1(P126, {"punto_de_muestreo": "texto libre antiguo", "masa_humeda": "80", "masa_seca": "20"})
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["punto_de_muestreo"]), (1, "texto libre antiguo"))
        self.assertNotIn("porcentaje_cantidad_de_seco", capture["values"], "no se inventa para registros históricos")
        new = await self.post(P126, P126_V2)
        listed = (await self.get(f"/api/quality/machines/MP1/captures?form_code={P126}")).json()
        self.assertEqual({c["form"]["version_number"] for c in listed}, {1, 2})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.v1[P126],)), 4)
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 2)


def variant(checksum, spec):
    """El bundle vigente con algunas versiones de formulario sustituidas: {código: (versión, campos)}. Reproduce el estado de producción antes de MF-08."""
    forms = []
    for form in BUNDLE.forms:
        if form["code"] in spec:
            number, fields = spec[form["code"]]
            fields = [{"source": "manual", "unit": None, **f, "display_order": n} for n, f in enumerate(fields, start=1)]
            form = {**form, "version_number": number, "fields": fields}
            form["definition_checksum"] = compute_definition_checksum(form)
        forms.append(form)
    return dataclasses.replace(BUNDLE, source_checksum=checksum, forms=tuple(forms))


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción tiene P1-18, P1-22 y P1-26 en v1 (y MF-05 a MF-07 ya importados): el importador debe AÑADIR las tres v2 y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf08_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, variant("1" * 64, {code: (1, fields) for code, fields in V1.items()}))

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

    def test_the_bundle_adds_only_the_three_new_versions_and_is_idempotent(self):
        old_where = f"f.code IN ('{P118}','{P122}','{P126}') AND v.version_number = 1"
        other_where = f"f.code NOT IN ('{P118}','{P122}','{P126}')"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual((len(old[0]), len(old[1])), (3, 9 + 6 + 4))
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 3)
        self.assertEqual(dry.counts["field"]["create"], 10 + 5 + 6)  # P1-26 llega como v3 (MF-11): 6 campos
        self.assertEqual(dry.counts["form_version_machine"]["create"], 6)
        self.assertEqual(dry.counts["option"]["create"], 6)
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "las versiones 1 y sus campos quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        for code in (P118, P122, P126):
            self.assertEqual(self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (code,)).fetchall(),
                             [(1, "published"), (3 if code == P126 else 2, "published")])
        opts = self.connection.execute("""SELECT o.option_key, o.display_order FROM vinto_config.field_option o JOIN vinto_config.form_version v ON v.id = o.form_version_id JOIN vinto_config.form f ON f.id = v.form_id
                                          WHERE f.code = %s ORDER BY o.display_order""", (P126,)).fetchall()
        self.assertEqual(opts, [(p, n) for n, p in enumerate(POINTS, start=1)])
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")


if __name__ == "__main__":
    unittest.main()
