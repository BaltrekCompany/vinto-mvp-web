"""CLOUD-DEP G.12-C4: prueba E2E real (HTTP, PostgreSQL efímero *_test, nunca vinto_piloto) de que los 13
formularios candidatos recién habilitados (CENTRAL_FORM_CODES/MACHINE_QUALITY_FORM_CODES/
ENABLED_BOBBIN_CANDIDATE_FORM_CODES) funcionan de punta a punta con el mecanismo YA EXISTENTE -- sin
simular ninguna política con patch.object (a diferencia de otros módulos de prueba de este repo que SÍ
amplían la política solo para el entorno de prueba): aquí la política real del código YA incluye estos
códigos, así que esta prueba ejercita exactamente lo que el MVP desplegado haría.

Cubre, para representantes de los tres contextos (nunca los 13 por separado -- ya comparten exactamente
el mismo motor de persistencia que F3/F6/P1-19/P1-20, ya regresados en test_import_reference.py/
test_production_access.py/test_quality_capture_api.py/test_f3_bobbins_api.py/test_f6_captures_api.py):
  - "assignment" (Bobinas):  VINTO-P1-05 (Registro de tubetes) vía POST /api/captures
  - "machine" (Calidad):     VINTO-P1-18 (Porcentaje de consistencia) vía POST /api/quality/machines/{m}/captures
  - "bobbin" (Calidad):      VINTO-P1-21 (Perfil de gramaje y humedad) vía POST /api/quality/bobbins/{id}/captures

Para cada uno: envío real, reintento idempotente (mismo capture_id -> misma captura, nunca duplicada),
validación de campo obligatorio ausente (422), denegación de permiso por perfil (403), e historial real.
También confirma que F6 (uno de los 4 formularios originales) sigue funcionando sin cambios -- la
regresión explícita que exige el encargo (B.10).
"""

import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.main import app

try:
    from test_assignments_api import PROFILES, call, order_body
except ModuleNotFoundError:
    from tests.test_assignments_api import PROFILES, call, order_body

STATE = {}


def setUpModule():
    # build_reference_template carga el bundle REAL (backend/seed_data, ya con los 17 formularios) --
    # nunca un bundle sintético aparte: esta prueba corre contra exactamente lo que se desplegaría.
    STATE["template"] = build_reference_template("vinto_candfq_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class CandidateFormsCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_candfq")
        cls.connection = connect(cls.database)
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.users, cls.cookies = {}, {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (create_user(cls.connection, username=f"candfq.{profile.lower()}", display_name=profile.title(),
                                               profile_code=profile, password=password, sectors=("BOBINAS",)), password)
        # Usuario SIN sector BOBINAS: para probar que el aislamiento por sector sigue vigente para los
        # formularios candidatos (nunca solo para los 4 originales).
        password_sin_sector = "pw-" + secrets.token_urlsafe(18)
        created_sin_sector = create_user(cls.connection, username="candfq.sinsector", display_name="Sin Sector",
                                          profile_code="OPERACION", password=password_sin_sector, sectors=())
        cls.users["SIN_SECTOR"] = (created_sin_sector, password_sin_sector)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")

    async def cookie(self, profile):
        if profile not in self.cookies:
            created, password = self.users[profile]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, profile)
            self.cookies[profile] = reply.set_cookie_value()
        return self.cookies[profile]

    async def assignment(self, machine="MP1"):
        order = (await call("POST", "/api/work-orders", json_body=order_body(machine), cookie=await self.cookie("JEFATURA"))).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"),
                           json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201)
        return reply.json()["assignment"]

    async def capture_f3(self, machine="MP1"):
        assignment = await self.assignment(machine)
        reply = await call("POST", "/api/bobbins", cookie=await self.cookie("OPERACION"),
                           json_body={"capture_id": str(uuid4()), "assignment_id": assignment["id"], "device_key": str(uuid4()),
                                      "values": {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5",
                                                  "peso_kg": "845.25", "numero_de_cortes": "3", "observaciones": "ok"}})
        self.assertIn(reply.status, (200, 201), reply.text)
        bobbin = reply.json()["bobbin"]
        return bobbin["id"], bobbin["code"]

    # ---- VINTO-P1-05 (Bobinas, contexto "assignment", vía /api/captures) ------------------------------

    async def test_p1_05_submitted_by_operacion_is_persisted_and_retrievable(self):
        assignment = await self.assignment("MP3")  # MF-12A (MD_Ejec 20): P1-05 (v2) solo está disponible en MP3
        capture_id = str(uuid4())
        values = {"numero_de_bobina": "B-1", "numero_codigo_de_tubete": "TB-7", "tipo_de_tubete": "carton",
                  "cantidad_utilizada": "3", "cantidad_recuperada": "1", "cantidad_devuelta": "0", "estado_del_tubete": "bueno",
                  "procedencia": "almacen", "destino": "produccion"}
        body = {"capture_id": capture_id, "assignment_id": assignment["id"], "device_key": str(uuid4()), "form_code": "VINTO-P1-05", "values": values}
        reply = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 201, reply.text)
        created = reply.json()["capture"]
        self.assertEqual(created["form"]["code"], "VINTO-P1-05")
        self.assertEqual(created["values"], values)

        fetched = await call("GET", f"/api/captures/{capture_id}", cookie=await self.cookie("OPERACION"))
        self.assertEqual(fetched.status, 200)
        self.assertEqual(fetched.json()["values"], values)

    async def test_p1_05_identical_retry_is_idempotent_never_duplicated(self):
        assignment = await self.assignment("MP3")  # MF-12A (MD_Ejec 20): P1-05 (v2) solo está disponible en MP3
        capture_id = str(uuid4())
        values = {"numero_de_bobina": "B-2", "numero_codigo_de_tubete": "TB-8", "tipo_de_tubete": "plastico",
                  "cantidad_utilizada": "2", "cantidad_recuperada": "2", "cantidad_devuelta": "0", "estado_del_tubete": "regular",
                  "procedencia": "proveedor", "destino": "devolucion"}
        body = {"capture_id": capture_id, "assignment_id": assignment["id"], "device_key": str(uuid4()), "form_code": "VINTO-P1-05", "values": values}
        first = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(first.status, 201)
        second = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertIn(second.status, (200, 201), second.text)
        self.assertTrue(second.json()["already_submitted"])
        self.assertEqual(second.json()["capture"]["id"], first.json()["capture"]["id"])
        count = self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (capture_id,)).fetchone()[0]
        self.assertEqual(count, 1, "un reintento idéntico no debe crear una segunda fila")

    async def test_p1_05_missing_required_field_is_rejected(self):
        assignment = await self.assignment("MP3")  # MF-12A (MD_Ejec 20): P1-05 (v2) solo está disponible en MP3
        capture_id = str(uuid4())
        values = {"numero_de_bobina": "B-3", "numero_codigo_de_tubete": "TB-9"}  # faltan 7 obligatorios
        body = {"capture_id": capture_id, "assignment_id": assignment["id"], "device_key": str(uuid4()), "form_code": "VINTO-P1-05", "values": values}
        reply = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 422, reply.text)
        count = self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (capture_id,)).fetchone()[0]
        self.assertEqual(count, 0, "una validación fallida no debe dejar ninguna fila para ESE capture_id")

    async def test_p1_05_denied_to_calidad_profile_without_production_capture_permission(self):
        assignment = await self.assignment("MP1")
        values = {"numero_de_bobina": "B-4", "numero_codigo_de_tubete": "TB-10", "tipo_de_tubete": "carton",
                  "cantidad_utilizada": "1", "cantidad_recuperada": "1", "cantidad_devuelta": "0", "estado_del_tubete": "bueno",
                  "procedencia": "almacen", "destino": "produccion"}
        body = {"capture_id": str(uuid4()), "assignment_id": assignment["id"], "device_key": str(uuid4()), "form_code": "VINTO-P1-05", "values": values}
        reply = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 403, reply.text)

    # ---- VINTO-P1-18 (Calidad, contexto "machine", vía /api/quality/machines/{code}/captures) ---------

    async def test_p1_18_submitted_by_calidad_is_persisted_and_retrievable(self):
        capture_id = str(uuid4())
        values = {"producto": "papel higienico", "numero_de_cuba": "C-1", "hora_del_ensayo": "07:30", "masa_humeda_g": "12.5",
                  "masa_seca_g": "4.2", "papel_filtro_g": "1.1", "papel_muestra_g": "0.9", "peso_muestra_g": "5.0"}
        body = {"capture_id": capture_id, "form_code": "VINTO-P1-18", "device_key": str(uuid4()), "values": values}
        reply = await call("POST", "/api/quality/machines/MP1/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(reply.json()["capture"]["values"], {**values, "hora_del_ensayo": "07:30:00"})  # MF-08: P1-18 v2 (hora del ensayo digitada; sin punto de muestreo)
        fetched = await call("GET", "/api/quality/machines/MP1/captures", cookie=await self.cookie("CALIDAD"))
        self.assertEqual(fetched.status, 200)
        self.assertIn(capture_id, [c["id"] for c in fetched.json()])

    async def test_p1_18_denied_to_operacion_profile_without_quality_capture_permission(self):
        body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-18", "device_key": str(uuid4()),
                "values": {"producto": "x", "numero_de_cuba": "C-2", "hora_del_ensayo": "07:30", "masa_humeda_g": "1",
                            "masa_seca_g": "1", "papel_filtro_g": "1", "papel_muestra_g": "1", "peso_muestra_g": "1"}}
        reply = await call("POST", "/api/quality/machines/MP1/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 403, reply.text)

    async def test_p1_18_denied_without_bobinas_sector_grant(self):
        body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-18", "device_key": str(uuid4()),
                "values": {"producto": "x", "numero_de_cuba": "C-3", "hora_del_ensayo": "07:30", "masa_humeda_g": "1",
                            "masa_seca_g": "1", "papel_filtro_g": "1", "papel_muestra_g": "1", "peso_muestra_g": "1"}}
        reply = await call("POST", "/api/quality/machines/MP1/captures", json_body=body, cookie=await self.cookie("SIN_SECTOR"))
        self.assertEqual(reply.status, 403, reply.text)

    # ---- VINTO-P1-21 (Calidad, contexto "bobbin", vía /api/quality/bobbins/{id}/captures) --------------

    async def test_p1_21_submitted_by_calidad_is_linked_to_the_bobbin_and_in_its_history(self):
        bobbin_id, bobbin_code = await self.capture_f3("MP1")
        capture_id = str(uuid4())
        values = {"gramaje_01": "81.2", "peso_seco_01": "1.9", "humedad_01": "6.5"}  # MF-07: P1-21 versión 2 = tabla de posiciones; la bobina es la de la ruta
        body = {"capture_id": capture_id, "form_code": "VINTO-P1-21", "device_key": str(uuid4()), "values": values}
        reply = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(reply.json()["capture"]["bobbin"]["code"], bobbin_code)
        history = await call("GET", f"/api/quality/bobbins/{bobbin_id}/captures", cookie=await self.cookie("CALIDAD"))
        self.assertEqual(history.status, 200)
        self.assertIn(capture_id, [c["id"] for c in history.json()])
        # P1-21 nunca debe tocar quality_release (confirmado también a nivel de código en capture_service.py).
        status = self.connection.execute("SELECT status, decided_by FROM vinto_txn.quality_release WHERE bobbin_id=%s", (bobbin_id,)).fetchone()
        self.assertEqual(status, ("pending", None))

    async def test_p1_21_no_longer_accepts_a_declared_bobbin_number(self):
        # MF-07: la versión 2 de P1-21 ya no declara «numero_de_bobina» (la bobina es la de la URL): enviarlo es un campo desconocido (el contraste con la bobina sigue vigente para P1-28 y las versiones que lo declaren).
        bobbin_id, bobbin_code = await self.capture_f3("MP3")
        wrong_values = {"numero_de_bobina": str(int(bobbin_code) + 1000), "gramaje_01": "80.0", "peso_seco_01": "1.7", "humedad_01": "5"}
        body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-21", "device_key": str(uuid4()), "values": wrong_values}
        reply = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 422, reply.text)
        self.assertEqual(reply.json()["code"], "CAPTURE_VALIDATION")
        count = self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id=%s", (bobbin_id,)).fetchone()[0]
        self.assertEqual(count, 0, "un numero_de_bobina enviado a P1-21 v2 no debe persistir nada")

    async def test_p1_28_declared_bobbin_number_must_match_the_selected_bobbin(self):
        # app/quality/capture_service.py::BOBBIN_CODE_FIELDS mapea VINTO-P1-28 -> "numero_de_bobina":
        # el valor declarado DEBE coincidir con el código real de la bobina seleccionada en la URL.
        bobbin_id, bobbin_code = await self.capture_f3("MP3")
        wrong_values = {"numero_de_bobina": str(int(bobbin_code) + 1000), "producto": "producto ficticio", "detalle_motivo_de_rechazo": "motivo ficticio",
                         "accion_correctiva": "accion ficticia", "peso_rechazado": "1.0", "estado_disposicion_final": "rechazado"}
        body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-28", "device_key": str(uuid4()), "values": wrong_values}
        reply = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 422, reply.text)
        self.assertEqual(reply.json()["code"], "CAPTURE_VALIDATION")
        count = self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id=%s", (bobbin_id,)).fetchone()[0]
        self.assertEqual(count, 0, "un numero_de_bobina que no coincide no debe persistir nada")

    async def test_p1_24_declared_bobbin_number_must_match_the_selected_bobbin(self):
        # app/quality/capture_service.py::BOBBIN_CODE_FIELDS mapea VINTO-P1-24 -> "numero_de_bobina":
        # el valor declarado DEBE coincidir con el código real de la bobina seleccionada en la URL.
        bobbin_id, bobbin_code = await self.capture_f3("MP3")
        wrong_values = {"numero_de_bobina": str(int(bobbin_code) + 1000), "producto": "producto ficticio", "crepado": "18.5", "gramaje": "21.30",
                        "resistencia_longitudinal_humeda_centro": "120.5", "resistencia_longitudinal_humeda_medio": "118", "resistencia_longitudinal_humeda_extremo": "119.25",
                        "resistencia_transversal_humeda_centro": "60.1", "resistencia_transversal_humeda_medio": "59", "resistencia_transversal_humeda_extremo": "61.75",
                        "tiempo_de_curado_condicion": "30"}
        body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-24", "device_key": str(uuid4()), "values": wrong_values}
        reply = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 422, reply.text)
        self.assertEqual(reply.json()["code"], "CAPTURE_VALIDATION")
        count = self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id=%s", (bobbin_id,)).fetchone()[0]
        self.assertEqual(count, 0, "un numero_de_bobina que no coincide no debe persistir nada")

    async def test_p1_25_declared_bobbin_number_must_match_the_selected_bobbin(self):
        # app/quality/capture_service.py::BOBBIN_CODE_FIELDS mapea VINTO-P1-25 -> "numero_de_bobina":
        # el valor declarado DEBE coincidir con el código real de la bobina seleccionada en la URL.
        bobbin_id, bobbin_code = await self.capture_f3("MP3")
        wrong_values = {"numero_de_bobina": str(int(bobbin_code) + 1000), "producto": "producto ficticio", "crepado": "17", "gramaje_laboratorio_g_m2": "20.5",
                        "curado_min": "30 min", "resistencia_longitudinal_centro_kgf": "1.20", "resistencia_longitudinal_medio_kgf": "1.15", "resistencia_longitudinal_extremo_kgf": "1.18",
                        "elongacion_media_longitudinal": "22.4", "resistencia_longitudinal_humeda_centro_kgf": "0.45", "resistencia_longitudinal_humeda_medio_kgf": "0.41",
                        "resistencia_longitudinal_humeda_extremo_kgf": "0.43", "elongacion_media_transversal": "9.9"}
        body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-25", "device_key": str(uuid4()), "values": wrong_values}
        reply = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(reply.status, 422, reply.text)
        self.assertEqual(reply.json()["code"], "CAPTURE_VALIDATION")
        count = self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id=%s", (bobbin_id,)).fetchone()[0]
        self.assertEqual(count, 0, "un numero_de_bobina que no coincide no debe persistir nada")

    async def test_p1_21_identical_retry_is_idempotent(self):
        bobbin_id, bobbin_code = await self.capture_f3("MP3")
        capture_id = str(uuid4())
        values = {"gramaje_01": "79.8", "peso_seco_01": "1.8", "humedad_01": "5.5"}
        body = {"capture_id": capture_id, "form_code": "VINTO-P1-21", "device_key": str(uuid4()), "values": values}
        first = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertEqual(first.status, 201, first.text)
        second = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=await self.cookie("CALIDAD"))
        self.assertIn(second.status, (200, 201), second.text)
        self.assertEqual(second.json()["capture"]["id"], first.json()["capture"]["id"])
        count = self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (capture_id,)).fetchone()[0]
        self.assertEqual(count, 1)

    # ---- Regresión explícita (encargo B.10): los 4 formularios originales siguen intactos -------------

    async def test_f6_still_works_unaffected_by_the_new_candidate_policy(self):
        assignment = await self.assignment("MP1")
        body = {"capture_id": str(uuid4()), "assignment_id": assignment["id"], "device_key": str(uuid4()), "form_code": "VINTO-P1-06",
                "values": {"cantidad_fardos": 2, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "3.5"}}
        reply = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 201, reply.text)
        self.assertEqual(reply.json()["capture"]["form"]["code"], "VINTO-P1-06")


if __name__ == "__main__":
    unittest.main()
