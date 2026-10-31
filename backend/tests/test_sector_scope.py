"""M1-A · Alcance por sector: solo BOBINAS es operativo; el resto de sectores sigue bloqueado y habilitarlo no concede permisos.

Tres bloques:
1. Configuración (`app/sectors.py`): lista cerrada, validación estricta, valor por defecto.
2. Garantías estáticas: la constante antigua desaparece, ningún módulo repite códigos de sector, los permisos y las migraciones no cambian.
3. Escenario de extremo a extremo en una base EFÍMERA *_test: un sector futuro SINTÉTICO (REBOBINADO + una máquina de prueba, solo en la plantilla de
   test) se opera completo cuando el sector está habilitado (prueba que la operación es válida) y las MISMAS operaciones se rechazan o no se ven cuando
   no lo está (prueba que el rechazo se debe al sector y no a otra causa). Nada toca la base `vinto`, ni existen datos reales de REBOBINADO/CONVERSION.
"""

import re
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app import sectors
from app.auth import permissions
from app.auth.grants import grant_sector
from app.ephemeral_db import build_reference_template, connect, drop_database

try:
    import test_f3_bobbins_api as f3
    from test_assignments_api import call, order_body
    from test_quality_capture_api import P119_VALUES
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    from tests.test_assignments_api import call, order_body
    from tests.test_quality_capture_api import P119_VALUES

APP = Path(__file__).resolve().parent.parent / "app"
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
F6_VALUES = {"cantidad_fardos": 1, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "1"}

# Matriz de permisos vigente al cerrar M1-A. Si un cambio la modifica, esta prueba debe fallar y revisarse a propósito.
PINNED_PROFILE_PERMISSIONS = {
    "JEFATURA": {"work_order.read", "work_order.manage", "assignment.read", "catalog.read"},
    "SUPERVISION": {"work_order.read", "assignment.read", "assignment.manage", "catalog.read"},
    "OPERACION": {"work_order.read", "assignment.read", "production.capture", "catalog.read"},
    "CALIDAD": {"work_order.read", "assignment.read", "quality.capture", "quality.release", "catalog.read"},
    "DATA_BALTREK": {"work_order.read", "assignment.read", "catalog.read", "catalog.manage", "user.manage"},
}
# Checksums SHA-256 de las migraciones aplicadas en DEV (vinto_meta.schema_migration).
PINNED_MIGRATIONS = [
    ("0001_initial_schema.sql", "500b68a0fe3af40d06fda81c12e8945c57b99c669ec84348fa5808e1684d3c0f"),
    ("0002_auth.sql", "311005bf4d3e10c9fcf3ce5a3cd4a8f656116091f3e050a79f21e1d8ed66518a"),
    ("0003_capture_revision_semantics.sql", "b739fb041b3e64401555d07ae86f6bed5b9b4f629075c9ab2331e919f4b652d8"),
    ("0004_bobbin_production.sql", "2346215c46fad1dc6c036f225a43a5a7a9251c21e892f1bfdf7ea7872b77f631"),
    ("0005_quality_capture_bobbin.sql", "abf8b6fb9d678bc44de2260a05e7852b6df34659f2ebbb75a8bb64cabc5b1422"),
    ("0006_user_sector_grants.sql", "98057f5b94236aa843f82ffc9ba4105266ea4f516abe861208a50664eb51ac9a"),  # M1-C1: additive table for sector grants
    ("0007_user_machine_form_grants.sql", "7772dca038902319afb04ab54139a13b0314141b73ae271ad31d3d3017704acc"),  # MF-13-01B.1: additive table for per-machine, per-form grants
]


# ---- 1. configuración -------------------------------------------------------------------------------------------------------

class SectorConfigTests(unittest.TestCase):
    def test_bobinas_rebobinado_and_conversion_are_operational_by_default(self):
        # CLOUD-DEP G.12-C4-COMPLETE sumó REBOBINADO; G.12-C4-FINAL25 sumó CONVERSION (ambos cambios de
        # código revisados, nunca una variable de entorno): los 3 sectores conocidos ya son operativos.
        self.assertEqual(sectors.operational_sector_codes(), ("BOBINAS", "REBOBINADO", "CONVERSION"))
        self.assertEqual(sectors.DEFAULT_OPERATIONAL_SECTORS, ("BOBINAS", "REBOBINADO", "CONVERSION"))
        self.assertTrue(sectors.is_operational_sector("BOBINAS"))
        self.assertTrue(sectors.is_operational_sector("REBOBINADO"))
        self.assertTrue(sectors.is_operational_sector("CONVERSION"))
        for code in ("OTRO", "bobinas", " BOBINAS", "", None, 1):
            self.assertFalse(sectors.is_operational_sector(code), repr(code))

    def test_the_configuration_is_immutable_and_returns_text_codes(self):
        value = sectors.operational_sector_codes()
        self.assertIsInstance(value, tuple)
        with self.assertRaises(TypeError):
            value[0] = "REBOBINADO"  # type: ignore[index]
        self.assertTrue(all(isinstance(code, str) for code in value))

    def test_the_known_sectors_are_a_closed_list(self):
        # CLOUD-DEP G.12-C4-FINAL25: los 3 sectores conocidos ya son operativos (no queda ningún
        # "reconocido pero no habilitado" real); esta prueba solo cubre que la lista es cerrada.
        self.assertEqual(sectors.KNOWN_SECTOR_CODES, frozenset({"BOBINAS", "REBOBINADO", "CONVERSION"}))
        self.assertEqual(set(sectors.operational_sector_codes()), sectors.KNOWN_SECTOR_CODES)

    def test_a_valid_different_configuration_is_accepted_but_not_applied(self):
        self.assertEqual(sectors.validate_operational_sectors(("BOBINAS", "CONVERSION")), ("BOBINAS", "CONVERSION"))
        self.assertEqual(sectors.validate_operational_sectors(["BOBINAS", "REBOBINADO"]), ("BOBINAS", "REBOBINADO"))
        self.assertEqual(sectors.operational_sector_codes(), ("BOBINAS", "REBOBINADO", "CONVERSION"))  # validar no cambia nada

    def test_invalid_configurations_are_rejected(self):
        invalid = {
            "plain text": "BOBINAS", "bytes": b"BOBINAS", "not a collection": 5, "None": None, "empty": (), "duplicate": ("BOBINAS", "BOBINAS"),
            "unknown": ("BOBINAS", "OTRO"), "lowercase": ("bobinas",), "padded": ("BOBINAS ",), "non-text": ("BOBINAS", 3),
            "bobinas removed": ("REBOBINADO",), "only future sectors": ("REBOBINADO", "CONVERSION"),
        }
        for name, value in invalid.items():
            with self.assertRaises(sectors.SectorConfigError, msg=name):
                sectors.validate_operational_sectors(value)
        self.assertTrue(issubclass(sectors.SectorConfigError, ValueError))

    def test_a_bad_default_would_stop_the_module_from_importing(self):
        # La validación se ejecuta al importar: una edición incorrecta de DEFAULT_OPERATIONAL_SECTORS impide arrancar el backend.
        source = (APP / "sectors.py").read_text(encoding="utf-8")
        self.assertRegex(source, r"_OPERATIONAL = validate_operational_sectors\(DEFAULT_OPERATIONAL_SECTORS\)")


# ---- 2. garantías estáticas -------------------------------------------------------------------------------------------------

def app_sources():
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(APP.rglob("*.py")) if "__pycache__" not in p.parts]


class StaticScopeTests(unittest.TestCase):
    def test_the_old_hardcoded_constant_is_gone(self):
        self.assertEqual([p.name for p, text in app_sources() if "ALLOWED_SECTOR_CODES" in text], [])

    def test_no_module_repeats_a_sector_code_literal(self):
        literal = re.compile(r"""["'](BOBINAS|REBOBINADO|CONVERSION)["']""")
        offenders = [str(p.relative_to(APP)) for p, text in app_sources() if p.name != "sectors.py" and "seed" not in p.parts and literal.search(text)]
        self.assertEqual(offenders, [])

    def test_every_sector_filter_in_sql_is_fed_by_the_accessor(self):
        filtered = [(p, text) for p, text in app_sources() if p.name != "sectors.py" and re.search(r"s\.code\s*=\s*ANY\(%s\)", text)]
        self.assertGreaterEqual(len(filtered), 6)  # work_orders, assignments, capture_service, bobbins, quality (x2)
        for path, text in filtered:
            self.assertIn("scoped_sector_codes(", text, str(path.relative_to(APP)))  # M1-C1: the accessor is the user-scoped one
            self.assertRegex(text, r"from app\.sectors import [^\n]*scoped_sector_codes", str(path.relative_to(APP)))
            self.assertNotIn("operational_sector_codes()", text, str(path.relative_to(APP)))  # nobody may bypass the user scope

    def test_sectors_and_permissions_stay_independent(self):
        sectors_source = (APP / "sectors.py").read_text(encoding="utf-8")
        self.assertNotRegex(sectors_source, r"(?m)^\s*(from|import)\s+app")
        self.assertEqual([str(p.relative_to(APP)) for p, text in app_sources() if "auth" in p.parts and "app.sectors" in text], [])

    def test_the_permission_matrix_is_unchanged_and_independent_of_sectors(self):
        self.assertEqual({k: set(v) for k, v in permissions.PROFILE_PERMISSIONS.items()}, PINNED_PROFILE_PERMISSIONS)
        self.assertEqual(permissions.ALL_PERMISSIONS, frozenset().union(*PINNED_PROFILE_PERMISSIONS.values()))
        self.assertEqual(len(permissions.ALL_PERMISSIONS), 10)
        for profile, expected in PINNED_PROFILE_PERMISSIONS.items():
            self.assertEqual(set(permissions.permissions_for_profiles([profile])), expected, profile)
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS", "REBOBINADO")):  # habilitar un sector no cambia ningún permiso
            for profile, expected in PINNED_PROFILE_PERMISSIONS.items():
                self.assertEqual(set(permissions.permissions_for_profiles([profile])), expected, profile)

    def test_existing_migrations_are_intact_and_only_the_known_ones_exist(self):
        from migrate import read_migrations
        self.assertEqual([(m.filename, m.checksum) for m in read_migrations()], PINNED_MIGRATIONS)
        self.assertEqual(sorted(p.name for p in MIGRATIONS.glob("*.sql")), [name for name, _ in PINNED_MIGRATIONS])


# ---- 3. escenario de extremo a extremo con un sector futuro SINTÉTICO (solo en la plantilla efímera) -------------------------

# CLOUD-DEP G.12-C4-FINAL25: los 3 sectores conocidos (BOBINAS/REBOBINADO/CONVERSION) ya son operativos
# por defecto -- ya no queda ningún sector real "reconocido pero no operativo" que usar aquí. FUTURE_SECTOR
# es ahora un código puramente SINTÉTICO (nunca pasa por KNOWN_SECTOR_CODES/validate_operational_sectors:
# este módulo lo inserta a mano en vinto_master.sector y solo lo usa vía patch.object directo sobre
# `_OPERATIONAL`, que no valida contra esa lista cerrada).
FUTURE_SECTOR, FUTURE_MACHINE = "ZZFIX_FUTURE", "TESTREB1"
STATE = {}


def setUpModule():
    template = build_reference_template("vinto_sector_tpl")
    with connect(template) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('vinto.reason', 'M1-A synthetic future sector fixture (tests only)', true)")
            sector = connection.execute("INSERT INTO vinto_master.sector (code,name) VALUES (%s,'Rebobinado (sintético)') RETURNING id", (FUTURE_SECTOR,)).fetchone()[0]
            machine = connection.execute("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,%s,'Máquina sintética de prueba') RETURNING id",
                                         (sector, FUTURE_MACHINE)).fetchone()[0]
            # Turnos: copia de los de BOBINAS SOLO para que la plantilla de prueba pueda resolver un turno. No son horarios reales de REBOBINADO.
            connection.execute("""INSERT INTO vinto_config.shift_schedule (shift_id, sector_id, starts_at, ends_at, timezone, valid_from, valid_to)
                                  SELECT sc.shift_id, %s, sc.starts_at, sc.ends_at, sc.timezone, sc.valid_from, sc.valid_to FROM vinto_config.shift_schedule sc
                                  JOIN vinto_master.sector s ON s.id = sc.sector_id WHERE s.code = 'BOBINAS'""", (sector,))
            connection.execute("""INSERT INTO vinto_master.article_machine (article_id, machine_id)
                                  SELECT am.article_id, %s FROM vinto_master.article_machine am JOIN vinto_master.machine m ON m.id = am.machine_id WHERE m.code = 'MP1'""", (machine,))
            # Los formularios publicados son inmutables: solo en esta plantilla de prueba se desactiva el guard para habilitar la máquina sintética.
            connection.execute("ALTER TABLE vinto_config.form_version_machine DISABLE TRIGGER guard_definition")
            connection.execute("""INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id)
                                  SELECT v.id, %s FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                  WHERE f.code IN ('VINTO-P1-03','VINTO-P1-06','VINTO-P1-19')""", (machine,))
            connection.execute("ALTER TABLE vinto_config.form_version_machine ENABLE TRIGGER guard_definition")
    STATE["previous"] = f3.STATE.get("template")
    f3.STATE["template"] = STATE["template"] = template


def tearDownModule():
    if STATE.get("previous") is None:
        f3.STATE.pop("template", None)
    else:
        f3.STATE["template"] = STATE["previous"]
    if STATE.get("template"):
        drop_database(STATE.pop("template"))


class SectorGateTests(f3.BobbinApiCase):
    async def me_permissions(self, profile):
        reply = await call("GET", "/api/auth/me", cookie=await self.cookie(profile))
        self.assertEqual(reply.status, 200, profile)
        return set(reply.json()["user"]["permissions"])

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.work_order", "vinto_txn.assignment", "vinto_txn.capture",
                                                                         "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_txn.quality_release")}

    async def test_the_future_sector_exists_in_the_data_but_is_not_operational(self):
        # Hay datos (sector, máquina, turnos, relación y formularios) y aun así NO se puede operar: la autoridad es la configuración, no los datos.
        # CLOUD-DEP G.12-C4-FINAL25: CONVERSION (FUTURE_SECTOR) ya es operativo por defecto -- se
        # deshabilita explícitamente dentro de este bloque para simular el escenario "reconocido pero no operativo".
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id=m.sector_id WHERE m.code=%s AND s.code=%s",
                                     (FUTURE_MACHINE, FUTURE_SECTOR)), 1)
        count = lambda: self.scalar("SELECT count(*) FROM vinto_txn.work_order wo JOIN vinto_master.machine m ON m.id=wo.machine_id WHERE m.code=%s", (FUTURE_MACHINE,))
        before = count()  # la base se comparte entre las pruebas de la clase: se compara contra el valor previo, no contra cero
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS", "REBOBINADO")):
            reply = await call("POST", "/api/work-orders", json_body={**order_body("MP1"), "machine_code": FUTURE_MACHINE}, cookie=await self.cookie("JEFATURA"))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        self.assertEqual(count(), before)

    async def test_same_operations_work_when_the_sector_is_enabled_and_are_blocked_when_it_is_not(self):
        jefatura, supervision, operacion, calidad = [await self.cookie(p) for p in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD")]
        future_order = {**order_body("MP1"), "machine_code": FUTURE_MACHINE}
        quality_body = lambda bobbin_id: {"capture_id": str(uuid4()), "form_code": "VINTO-P1-19", "device_key": str(uuid4()), "values": dict(P119_VALUES)}

        # ---------- FASE 1: sector habilitado (solo dentro del bloque). Prueba que las operaciones y los datos son válidos. ----------
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"):  # M1-C1: enabling the sector is not enough, the user also needs an explicit grant
            grant_sector(self.connection, user_id=self.users[profile][0].user_id, sector_code=FUTURE_SECTOR)
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS", FUTURE_SECTOR)):
            order = await call("POST", "/api/work-orders", json_body=future_order, cookie=jefatura)
            self.assertEqual(order.status, 201)
            order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=jefatura)).json()
            activated = await call("POST", "/api/assignments/activate", cookie=supervision,
                                   json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
            self.assertEqual(activated.status, 201)
            assignment = activated.json()["assignment"]
            f6_body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(F6_VALUES)}
            f6 = await call("POST", "/api/captures", json_body=f6_body, cookie=operacion)
            self.assertEqual(f6.status, 201)
            f3_body = self.payload(assignment)
            bobbin = await call("POST", "/api/bobbins", json_body=f3_body, cookie=operacion)
            self.assertEqual(bobbin.status, 201)
            bobbin_id = bobbin.json()["bobbin"]["id"]
            inbox = await call("GET", "/api/quality/bobbins", cookie=calidad)
            self.assertIn(bobbin_id, [i["bobbin"]["id"] for i in inbox.json()])
            q_body = quality_body(bobbin_id)
            quality = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=q_body, cookie=calidad)
            self.assertEqual(quality.status, 201)
            quality_id = quality.json()["capture"]["id"]
            for path, cookie in ((f"/api/work-orders/{order['id']}", jefatura), (f"/api/captures/{f6.json()['capture']['id']}", operacion), (f"/api/bobbins/{bobbin_id}", operacion),
                                 (f"/api/quality/bobbins/{bobbin_id}/captures", calidad), (f"/api/quality/captures/{quality_id}", calidad),
                                 (f"/api/assignments/active?machine_code={FUTURE_MACHINE}", supervision)):
                self.assertEqual((await call("GET", path, cookie=cookie)).status, 200, path)
            # Habilitar el sector NO amplía permisos: los perfiles siguen limitados a lo suyo.
            self.assertEqual((await call("POST", "/api/work-orders", json_body=future_order, cookie=operacion)).status, 403)
            self.assertEqual((await call("POST", "/api/work-orders", json_body=future_order, cookie=supervision)).status, 403)
            self.assertEqual((await call("POST", "/api/assignments/activate", cookie=jefatura, json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})).status, 403)
            self.assertEqual((await call("POST", "/api/captures", json_body={**f6_body, "capture_id": str(uuid4())}, cookie=calidad)).status, 403)
            self.assertEqual((await call("POST", "/api/bobbins", json_body={**f3_body, "capture_id": str(uuid4())}, cookie=calidad)).status, 403)
            self.assertEqual((await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=quality_body(bobbin_id), cookie=operacion)).status, 403)
            for profile, expected in PINNED_PROFILE_PERMISSIONS.items():
                self.assertEqual(await self.me_permissions(profile), expected, profile)

        # ---------- FASE 2: FUTURE_SECTOR (CONVERSION) deshabilitado. Los MISMOS datos y operaciones deben quedar bloqueados o invisibles. ----------
        # CLOUD-DEP G.12-C4-FINAL25: los 3 sectores conocidos (BOBINAS/REBOBINADO/CONVERSION) ya son
        # operativos por defecto, así que ya no hay ningún sector "reconocido pero no operativo" real
        # para ejercitar esta fase -- se simula aquí, deshabilitando explícitamente FUTURE_SECTOR
        # (CONVERSION) dentro de este bloque, sin tocar la configuración real fuera de él.
        self.assertEqual(sectors.operational_sector_codes(), ("BOBINAS", "REBOBINADO", "CONVERSION"))
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS", "REBOBINADO")):
            before = self.counts()
            listed = lambda reply, key=None: [(i[key] if key else i["id"]) for i in reply.json()]
            self.assertNotIn(order["id"], listed(await call("GET", "/api/work-orders", cookie=jefatura)))
            self.assertNotIn(assignment["id"], listed(await call("GET", "/api/assignments", cookie=supervision)))
            self.assertNotIn(f6.json()["capture"]["id"], listed(await call("GET", "/api/captures", cookie=operacion)))
            self.assertNotIn(bobbin_id, [i["bobbin"]["id"] for i in (await call("GET", "/api/quality/bobbins", cookie=calidad)).json()])
            for status in ("released", "rejected"):
                self.assertNotIn(bobbin_id, [i["bobbin"]["id"] for i in (await call("GET", f"/api/quality/bobbins?status={status}", cookie=calidad)).json()])
            missing = {
                "work order": ("GET", f"/api/work-orders/{order['id']}", jefatura, None),
                "F6 capture": ("GET", f"/api/captures/{f6.json()['capture']['id']}", operacion, None),
                "bobbin": ("GET", f"/api/bobbins/{bobbin_id}", operacion, None),
                "quality history": ("GET", f"/api/quality/bobbins/{bobbin_id}/captures", calidad, None),
                "quality capture": ("GET", f"/api/quality/captures/{quality_id}", calidad, None),
                "finish assignment": ("POST", f"/api/assignments/{assignment['id']}/finish", supervision, None),
                "new F6 capture": ("POST", "/api/captures", operacion, {**f6_body, "capture_id": str(uuid4())}),
                "new F3 bobbin": ("POST", "/api/bobbins", operacion, {**f3_body, "capture_id": str(uuid4())}),
                "new quality capture": ("POST", f"/api/quality/bobbins/{bobbin_id}/captures", calidad, quality_body(bobbin_id)),
            }
            for name, (method, path, cookie, body) in missing.items():
                reply = await call(method, path, json_body=body, cookie=cookie)
                self.assertEqual(reply.status, 404, f"{name}: {reply.status} {reply.body[:120]!r}")
            # Reintento EXACTO de una captura que se aceptó cuando el sector estaba habilitado: nunca debe volver a dar éxito (200/201).
            # Hoy F6 y Calidad responden 404 y F3 responde 409 CAPTURE_IDEMPOTENCY_CONFLICT (su comprobación de idempotencia precede al filtro de sector).
            # Esa diferencia es PREEXISTENTE y se conserva en M1-A (contratos intactos); unificarla en 404 queda para M1-B.
            replays = {
                "F6": ("/api/captures", operacion, f6_body, {404}),
                "F3": ("/api/bobbins", operacion, f3_body, {404, 409}),
                "quality": (f"/api/quality/bobbins/{bobbin_id}/captures", calidad, q_body, {404}),
            }
            for name, (path, cookie, body, allowed) in replays.items():
                reply = await call("POST", path, json_body=body, cookie=cookie)
                self.assertIn(reply.status, allowed, f"replay {name}: {reply.status} {reply.body[:120]!r}")
                self.assertNotIn(reply.status, (200, 201), name)
            activate_again = await call("POST", "/api/assignments/activate", cookie=supervision,
                                        json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
            self.assertEqual(activate_again.status, 404, activate_again.body[:120])
            active = await call("GET", f"/api/assignments/active?machine_code={FUTURE_MACHINE}", cookie=supervision)
            self.assertEqual((active.status, active.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
            again = await call("POST", "/api/work-orders", json_body=future_order, cookie=jefatura)
            self.assertEqual((again.status, again.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
            self.assertEqual(self.counts(), before, "las operaciones bloqueadas no escriben nada")
            # Los permisos son los mismos con el sector habilitado y sin habilitar.
            for profile, expected in PINNED_PROFILE_PERMISSIONS.items():
                self.assertEqual(await self.me_permissions(profile), expected, profile)

    async def test_bobinas_keeps_working_with_a_non_operational_sector_present(self):
        # La presencia de datos de otro sector no afecta a Bobinas: flujo completo MP1 → F6 → F3 → Calidad con el sector futuro existiendo pero deshabilitado.
        order, assignment = await self.assignment("MP1")
        f6 = await call("POST", "/api/captures", cookie=await self.cookie("OPERACION"), json_body={
            "capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(F6_VALUES)})
        self.assertEqual(f6.status, 201)
        bobbin = await self.post(self.payload(assignment))
        self.assertEqual(bobbin.status, 201)
        bobbin_id = bobbin.json()["bobbin"]["id"]
        self.assertIn(bobbin_id, [i["bobbin"]["id"] for i in (await call("GET", "/api/quality/bobbins", cookie=await self.cookie("CALIDAD"))).json()])
        quality = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", cookie=await self.cookie("CALIDAD"),
                             json_body={"capture_id": str(uuid4()), "form_code": "VINTO-P1-19", "device_key": str(uuid4()), "values": dict(P119_VALUES)})
        self.assertEqual(quality.status, 201)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id=%s", (bobbin_id,)), "pending")


if __name__ == "__main__":
    unittest.main()
