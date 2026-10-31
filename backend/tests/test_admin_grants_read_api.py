"""MF-13-01C.1: API administrativa de SOLO LECTURA del catálogo y de las concesiones máquina-formulario (/api/admin/catalog, /catalog/forms, /users/{id}, /users/{id}/grants, /users/{id}/grants/history).

Se verifica contra PostgreSQL REAL (bases efímeras *_test) con los formularios REALES del bundle y a través de la app ASGI: permiso user.manage (401/403), usuarios existentes e inexistentes,
concesiones activas e historial revocado, MP1/MP3 independientes, distinción publicado / ofrecido / habilitado para captura / concedido, ausencia de secretos y de escrituras.
Nada aquí toca endpoints de escritura, capturas, perfiles de usuarios reales ni el catálogo."""

import dataclasses
import json
import secrets
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import sectors
from app.admin.router import router as admin_router
from app.auth import permissions
from app.auth.machine_form_grants import _require_offered, grant_machine_form, machine_form_grants_for_user, revoke_machine_form
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.quality import capture_service as quality_capture_service
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

P101, P102, P103, P105, P106, P110, P118, P119, P121, P131 = ("VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-03", "VINTO-P1-05", "VINTO-P1-06", "VINTO-P1-10", "VINTO-P1-18", "VINTO-P1-19",
                                                              "VINTO-P1-21", "VINTO-P1-31")
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
REBOBINADORAS = ["BELOIT", "OVER", "COPASA", "PERICHUN", "TUBETERA"]
FORBIDDEN_KEYS = ("password", "hash", "token", "secret", "cookie", "session", "credential", "salt")
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_c1_tpl")


def tearDownModule():
    drop_database(STATE["template"])


def old_p105_bundle():
    """Producción tras MF-12A: P1-05 v1 publicada para MP1 y MP3 junto a la v2 vigente (solo MP3)."""
    v1 = {**FORMS[P105], "version_number": 1, "machines": ["MP1", "MP3"]}
    v1["definition_checksum"] = compute_definition_checksum(v1)
    return dataclasses.replace(BUNDLE, source_checksum="7" * 64, forms=tuple(v1 if f["code"] == P105 else f for f in BUNDLE.forms))


def keys_of(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys_of(v)
    elif isinstance(value, list):
        for item in value:
            yield from keys_of(item)


class Base(unittest.IsolatedAsyncioTestCase):
    old_p105 = False

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_c1")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        if cls.old_p105:
            reference.apply(cls.connection, old_p105_bundle())
        cls.users, cls.cookies = {}, {}
        for name, profile in (("ADMIN", "DATA_BALTREK"), ("JEFATURA", "JEFATURA"), ("SUPERVISION", "SUPERVISION"), ("OPERACION", "OPERACION"), ("CALIDAD", "CALIDAD")):
            cls.users[name] = cls.make_user(name, profile)

    @classmethod
    def make_user(cls, name, profile, sectors=("BOBINAS",)):
        password = "pw-" + secrets.token_urlsafe(18)
        created = create_user(cls.connection, username=f"c1.{name.lower()}.{uuid4().hex[:6]}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors)
        return created, password

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

    async def get(self, path, who="ADMIN"):
        return await call("GET", path, cookie=await self.cookie(who) if who else None)

    def admin_id(self):
        return self.users["ADMIN"][0].user_id

    def target(self, profile="OPERACION"):
        return create_user(self.connection, username=f"c1.t.{uuid4().hex[:10]}", display_name=f"Target {uuid4().hex[:4]}", profile_code=profile, password="pw-" + uuid4().hex).user_id

    def grant(self, user, machine="MP1", form=P101):
        return grant_machine_form(self.connection, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin_id())

    def revoke(self, user, machine="MP1", form=P101):
        return revoke_machine_form(self.connection, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin_id())

    def scalar(self, sql, params=()):
        return self.connection.execute(sql, params).fetchone()[0]

    def snapshot(self):
        return tuple(self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_master.user_machine_form_grant", "vinto_master.user_sector", "vinto_master.user_profile", "vinto_audit.audit_event",
                                                                        "vinto_config.form", "vinto_config.form_version", "vinto_config.form_version_machine", 'vinto_master."user"'))


# ---- 1. acceso: user.manage, 401 y 403 ---------------------------------------------------------------------------------------------------------------

class AccessTests(Base):
    def paths(self, uid):
        return ["/api/admin/catalog", "/api/admin/catalog/forms", f"/api/admin/users/{uid}", f"/api/admin/users/{uid}/grants", f"/api/admin/users/{uid}/grants/history"]

    async def test_401_without_a_session_403_without_user_manage_and_200_with_it(self):
        uid = self.target()
        for path in self.paths(uid):
            self.assertEqual((await self.get(path, None)).status, 401, path)
            for who in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"):
                reply = await self.get(path, who)
                self.assertEqual(reply.status, 403, (path, who))
                self.assertNotIn(b"grants", reply.body.lower(), "el 403 no filtra datos")
            reply = await self.get(path)
            self.assertEqual(reply.status, 200, (path, reply.text))
            self.assertEqual({k.decode().lower(): v.decode() for k, v in reply.headers}.get("cache-control"), "no-store", path)

    async def test_the_only_gate_is_the_existing_user_manage_permission(self):
        self.assertEqual([p for p, perms in permissions.PROFILE_PERMISSIONS.items() if permissions.USER_MANAGE in perms], ["DATA_BALTREK"])
        self.users["MIXED"] = self.make_user("mixed", "JEFATURA")  # Jefatura + Data Baltrek: la unión de permisos incluye user.manage
        self.connection.execute("INSERT INTO vinto_master.user_profile (user_id, profile_id) SELECT %s, id FROM vinto_master.profile WHERE code = 'DATA_BALTREK'", (self.users["MIXED"][0].user_id,))
        self.assertEqual((await self.get("/api/admin/catalog", "MIXED")).status, 200)

    async def test_a_revoked_session_and_a_deactivated_admin_lose_access(self):
        self.users["GONE"] = self.make_user("gone", "DATA_BALTREK")
        self.assertEqual((await self.get("/api/admin/catalog", "GONE")).status, 200)
        self.connection.execute("UPDATE vinto_auth.session SET revoked_at = clock_timestamp() WHERE user_id = %s", (self.users["GONE"][0].user_id,))
        self.assertEqual((await self.get("/api/admin/catalog", "GONE")).status, 401)

    async def test_there_is_no_write_route_for_grants_or_the_catalog(self):
        routes = sorted((m, r.path) for r in admin_router.routes for m in r.methods)
        writes = [(m, p) for m, p in routes if m != "GET"]
        # MF-13-01C.2 añade únicamente los dos POST de concesiones máquina-formulario; la lectura (catálogo, detalle, concesiones, historial) sigue sin escrituras
        self.assertEqual(writes, [("POST", "/api/admin/users/{user_id}/grants/grant"), ("POST", "/api/admin/users/{user_id}/grants/revoke"),
                                  ("POST", "/api/admin/users/{user_id}/sectors/grant"), ("POST", "/api/admin/users/{user_id}/sectors/revoke")])
        self.assertFalse([p for _, p in writes if "/catalog" in p or p.endswith("/history") or p.endswith("/grants") or p == "/api/admin/users/{user_id}"], "las rutas de lectura siguen siendo solo GET")
        uid, before = self.target(), self.snapshot()
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            for path in self.paths(uid):
                reply = await call(method, path, json_body={}, cookie=await self.cookie("ADMIN"), extra_headers=[("origin", settings.cors_origins[0])])
                self.assertIn(reply.status, (404, 405), (method, path, reply.status))
        self.assertEqual(self.snapshot(), before, "ningún intento escribió nada")

    async def test_existing_admin_routes_are_unchanged(self):
        routes = sorted((m, r.path) for r in admin_router.routes for m in r.methods if "grants" not in r.path and "catalog" not in r.path and r.path != "/api/admin/users/{user_id}")
        self.assertEqual(routes, [("GET", "/api/admin/sectors"), ("GET", "/api/admin/users"), ("GET", "/api/admin/users/{user_id}/sectors"),
                                  ("POST", "/api/admin/users/{user_id}/sectors/grant"), ("POST", "/api/admin/users/{user_id}/sectors/revoke")])
        self.assertEqual((await self.get("/api/admin/sectors")).status, 200)
        self.assertEqual((await self.get("/api/admin/users")).status, 200)
        self.assertEqual((await self.get(f"/api/admin/users/{self.target()}/sectors")).status, 200)


# ---- 2. usuarios: detalle, existentes e inexistentes ----------------------------------------------------------------------------------------------

class UserTests(Base):
    async def test_unknown_users_are_404_and_malformed_ids_are_422(self):
        for suffix in ("", "/grants", "/grants/history"):
            reply = await self.get(f"/api/admin/users/{uuid4()}{suffix}")
            self.assertEqual((reply.status, reply.json()["code"]), (404, "USER_NOT_FOUND"), suffix)
            self.assertEqual((await self.get(f"/api/admin/users/not-a-uuid{suffix}")).status, 422, suffix)

    async def test_user_detail_shows_profiles_derived_permissions_and_granted_sectors(self):
        created = create_user(self.connection, username=f"c1.d.{uuid4().hex[:8]}", display_name="Operador Detalle", profile_code="OPERACION", password="pw-" + uuid4().hex, sectors=("BOBINAS", "REBOBINADO"))
        body = (await self.get(f"/api/admin/users/{created.user_id}")).json()
        self.assertEqual((body["id"], body["display_name"], body["active"], body["username"]), (str(created.user_id), "Operador Detalle", True, created.username))
        self.assertEqual(body["profiles"], [{"code": "OPERACION", "name": "Operación"}])
        self.assertEqual(body["permissions"], sorted(permissions.PROFILE_PERMISSIONS["OPERACION"]), "se derivan de la matriz existente")
        self.assertEqual([(s["code"], s["operational"]) for s in body["sectors"]], [("BOBINAS", True), ("REBOBINADO", True)])

    async def test_a_user_with_two_profiles_shows_both_and_the_union_of_permissions(self):
        uid = self.target("OPERACION")
        self.connection.execute("INSERT INTO vinto_master.user_profile (user_id, profile_id) SELECT %s, id FROM vinto_master.profile WHERE code = 'CALIDAD'", (uid,))
        body = (await self.get(f"/api/admin/users/{uid}")).json()
        self.assertEqual([p["code"] for p in body["profiles"]], ["CALIDAD", "OPERACION"])
        self.assertEqual(body["permissions"], sorted(permissions.PROFILE_PERMISSIONS["OPERACION"] | permissions.PROFILE_PERMISSIONS["CALIDAD"]))

    async def test_a_granted_but_non_operational_sector_is_reported_as_such(self):
        uid = self.target()
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS",)):
            from app.auth.grants import grant_sector
            grant_sector(self.connection, user_id=uid, sector_code="CONVERSION", actor_id=self.admin_id())
            body = (await self.get(f"/api/admin/users/{uid}")).json()
        self.assertEqual([(s["code"], s["operational"]) for s in body["sectors"]], [("CONVERSION", False)], "concedido no implica operativo")

    async def test_no_secret_ever_leaves_the_api(self):
        uid = self.target()
        self.grant(uid, "MP1", P101)
        self.revoke(uid, "MP1", P101)
        password_hash = self.scalar("SELECT password_hash FROM vinto_auth.credential WHERE user_id = %s", (uid,))
        token_hash = self.scalar("SELECT token_hash FROM vinto_auth.session WHERE user_id = %s LIMIT 1", (self.admin_id(),))
        for path in ("/api/admin/catalog", "/api/admin/catalog/forms", f"/api/admin/users/{uid}", f"/api/admin/users/{uid}/grants", f"/api/admin/users/{uid}/grants/history"):
            reply = await self.get(path)
            self.assertEqual(reply.status, 200, path)
            self.assertFalse([k for k in keys_of(reply.json()) if any(bad in k.lower() for bad in FORBIDDEN_KEYS)], f"{path}: claves sensibles")
            self.assertNotIn(password_hash, reply.text)
            self.assertNotIn(token_hash, reply.text)
            self.assertNotIn(self.cookies["ADMIN"], reply.text)


# ---- 3. concesiones: activas, historial, MP1 / MP3 --------------------------------------------------------------------------------------------------

class GrantsTests(Base):
    async def test_a_user_without_grants_gets_empty_lists(self):
        uid = self.target()
        for suffix in ("/grants", "/grants/history"):
            body = (await self.get(f"/api/admin/users/{uid}{suffix}")).json()
            self.assertEqual((body["user_id"], body["total"], body["truncated"], body["grants"]), (str(uid), 0, False, []))

    async def test_active_grants_and_the_revoked_history_with_mp1_and_mp3_kept_apart(self):
        uid = self.target()
        for machine, form in (("MP1", P101), ("MP3", P101), ("MP3", P102)):
            self.assertTrue(self.grant(uid, machine, form))
        self.assertTrue(self.revoke(uid, "MP1", P101))
        self.assertTrue(self.grant(uid, "MP1", P101))  # fila nueva: la revocada queda en el historial
        active = (await self.get(f"/api/admin/users/{uid}/grants")).json()
        self.assertEqual([(g["machine"]["code"], g["form"]["code"], g["state"]) for g in active["grants"]], [("MP1", P101, "active"), ("MP3", P101, "active"), ("MP3", P102, "active")])
        self.assertEqual((active["total"], active["truncated"]), (3, False))
        self.assertTrue(all(g["revoked_at"] is None and g["revoked_by"] is None for g in active["grants"]))
        history = (await self.get(f"/api/admin/users/{uid}/grants/history")).json()
        self.assertEqual(history["total"], 4)
        self.assertEqual(sorted(g["state"] for g in history["grants"]), ["active", "active", "active", "revoked"])
        (revoked,) = [g for g in history["grants"] if g["state"] == "revoked"]
        self.assertEqual((revoked["machine"]["code"], revoked["form"]["code"]), ("MP1", P101))
        self.assertEqual(revoked["granted_by"]["id"], str(self.admin_id()))
        self.assertEqual(revoked["revoked_by"], {"id": str(self.admin_id()), "display_name": self.users["ADMIN"][0].display_name})
        self.assertIsNotNone(revoked["revoked_at"])
        stamps = [g["granted_at"] for g in history["grants"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True), "el historial va de la más reciente a la más antigua")
        # misma fuente que el servicio: ni una fila más ni una menos
        self.assertEqual({g["id"] for g in history["grants"]}, {str(g.id) for g in machine_form_grants_for_user(self.connection, uid, include_revoked=True)})
        self.assertEqual({g["id"] for g in active["grants"]}, {str(g.id) for g in machine_form_grants_for_user(self.connection, uid)})

    async def test_revoking_one_machine_does_not_show_the_other_as_revoked(self):
        uid = self.target()
        self.grant(uid, "MP1", P101)
        self.grant(uid, "MP3", P101)
        self.revoke(uid, "MP1", P101)
        by = {(g["machine"]["code"], g["form"]["code"]): g["state"] for g in (await self.get(f"/api/admin/users/{uid}/grants/history")).json()["grants"]}
        self.assertEqual(by, {("MP1", P101): "revoked", ("MP3", P101): "active"})
        self.assertEqual([g["machine"]["code"] for g in (await self.get(f"/api/admin/users/{uid}/grants")).json()["grants"]], ["MP3"])

    async def test_the_history_limit_truncates_and_is_validated(self):
        uid = self.target()
        for _ in range(2):
            self.grant(uid, "MP1", P101)
            self.revoke(uid, "MP1", P101)
        self.grant(uid, "MP3", P101)
        body = (await self.get(f"/api/admin/users/{uid}/grants/history?limit=2")).json()
        self.assertEqual((body["total"], len(body["grants"]), body["truncated"]), (3, 2, True))  # 2 ciclos conceder/revocar de la misma terna + 1 alta en MP3
        for bad in ("0", "501", "x"):
            self.assertEqual((await self.get(f"/api/admin/users/{uid}/grants/history?limit={bad}")).status, 422, bad)

    async def test_each_grant_carries_machine_form_and_catalog_status(self):
        uid = self.target()
        self.grant(uid, "MP3", P131)
        (g,) = (await self.get(f"/api/admin/users/{uid}/grants")).json()["grants"]
        self.assertEqual(g["machine"], {"code": "MP3", "name": "MP3", "sector_code": "BOBINAS"})
        self.assertEqual(g["form"], {"code": P131, "name": FORMS[P131]["name"], "area": "production"}, "P1-31 conserva su área funcional actual")
        self.assertEqual(g["catalog"], {"published_version": 2, "offered": True, "enabled_for_capture": True, "capture_policies": ["production_central"]})


# ---- 4. catálogo: máquinas y formularios del bundle vigente --------------------------------------------------------------------------------------

class CatalogTests(Base):
    async def tree(self):
        reply = await self.get("/api/admin/catalog")
        self.assertEqual(reply.status, 200, reply.text)
        return reply.json()

    async def test_the_tree_is_the_database_catalog_sector_machine_form_with_code_name_area_and_effective_version(self):
        tree = await self.tree()
        self.assertEqual([s["code"] for s in tree["sectors"]], ["BOBINAS", "CONVERSION", "REBOBINADO"])
        machines = {m["code"]: m for s in tree["sectors"] for m in s["machines"]}
        self.assertEqual(len(machines), 18)
        for code, machine in machines.items():
            expected = {f["code"]: (f["name"], f["area"], f["version_number"]) for f in BUNDLE.forms if code in f["machines"]}
            self.assertEqual({f["code"]: (f["name"], f["area"], f["effective_version"]) for f in machine["forms"]}, expected, code)
            self.assertTrue(all(f["published"] for f in machine["forms"]), code)

    async def test_p1_01_is_listed_separately_for_mp1_and_mp3_and_p1_10_v3_on_the_five_rebobinadoras(self):
        machines = {m["code"]: {f["code"]: f for f in m["forms"]} for s in (await self.tree())["sectors"] for m in s["machines"]}
        self.assertEqual((machines["MP1"][P101]["effective_version"], machines["MP3"][P101]["effective_version"]), (4, 4))
        self.assertIn(P102, machines["MP1"])
        self.assertIn(P102, machines["MP3"])
        for code in REBOBINADORAS:
            self.assertEqual(machines[code][P110]["effective_version"], 3, code)
        self.assertEqual(sorted(c for c, forms in machines.items() if P110 in forms), sorted(REBOBINADORAS), "P1-10 solo en las cinco rebobinadoras")

    async def test_p1_31_stays_on_mp3_and_keeps_its_area(self):
        machines = {m["code"]: {f["code"]: f for f in m["forms"]} for s in (await self.tree())["sectors"] for m in s["machines"]}
        self.assertEqual(sorted(c for c, forms in machines.items() if P131 in forms), ["MP3"])
        self.assertEqual((machines["MP3"][P131]["area"], machines["MP3"][P131]["effective_version"]), ("production", 2))

    async def test_no_quality_form_is_invented_for_rebobinado_or_conversion(self):
        for sector in (await self.tree())["sectors"]:
            areas = {f["area"] for m in sector["machines"] for f in m["forms"]}
            self.assertEqual(areas, {"quality", "production"} if sector["code"] == "BOBINAS" else {"production"}, sector["code"])
        forms = {f["code"]: f for f in (await self.get("/api/admin/catalog/forms")).json()["forms"]}
        quality_machines = {m["sector_code"] for f in forms.values() if f["area"] == "quality" for m in f["machines"]}
        self.assertEqual(quality_machines, {"BOBINAS"}, "los formularios de Calidad solo están vinculados a MP1 y MP3 en el catálogo")

    async def test_the_form_view_lists_every_form_with_its_effective_version_and_linked_machines(self):
        body = (await self.get("/api/admin/catalog/forms")).json()
        forms = {f["code"]: f for f in body["forms"]}
        self.assertEqual(sorted(forms), sorted(FORMS))
        for code, f in forms.items():
            self.assertEqual((f["name"], f["area"], f["effective_version"], f["published"], f["active"]), (FORMS[code]["name"], FORMS[code]["area"], FORMS[code]["version_number"], True, True), code)
            self.assertEqual(sorted(m["code"] for m in f["machines"]), sorted(FORMS[code]["machines"]), code)

    async def test_published_enabled_and_offered_are_different_things(self):
        machines = {m["code"]: {f["code"]: f for f in m["forms"]} for s in (await self.tree())["sectors"] for m in s["machines"]}
        p103 = machines["MP1"][P103]  # publicado y ofrecido, pero se registra por /api/bobbins: ninguna política de captura central lo acepta
        self.assertEqual((p103["published"], p103["offered"], p103["capture_policies"], p103["enabled_for_capture"]), (True, True, [], False))
        self.assertEqual((machines["MP1"][P106]["capture_policies"], machines["MP1"][P106]["enabled_for_capture"]), (["production_central"], True))
        self.assertEqual(machines["MP1"][P119]["capture_policies"], ["quality_by_bobbin"])
        self.assertEqual(machines["MP1"][P118]["capture_policies"], ["quality_by_machine"])
        self.assertTrue(machines["MP1"][P118]["enabled_for_capture"] and machines["MP1"][P119]["enabled_for_capture"])

    async def test_the_capture_policy_is_read_live_from_the_code_constants(self):
        with patch.object(quality_capture_service, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset()):
            machines = {m["code"]: {f["code"]: f for f in m["forms"]} for s in (await self.tree())["sectors"] for m in s["machines"]}
        self.assertEqual((machines["MP1"][P121]["published"], machines["MP1"][P121]["offered"], machines["MP1"][P121]["capture_policies"], machines["MP1"][P121]["enabled_for_capture"]), (True, True, [], False))

    async def test_a_non_operational_sector_is_offered_but_not_enabled_for_capture(self):
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS",)):
            tree = await self.tree()
        reb = next(s for s in tree["sectors"] if s["code"] == "REBOBINADO")
        self.assertEqual((reb["active"], reb["operational"]), (True, False))
        forms = [f for m in reb["machines"] for f in m["forms"]]
        self.assertTrue(forms and all(f["published"] and f["offered"] and not f["enabled_for_capture"] for f in forms))
        self.assertTrue(all(f["enabled_for_capture"] for m in next(s for s in tree["sectors"] if s["code"] == "BOBINAS")["machines"] for f in m["forms"] if f["capture_policies"]))

    async def test_an_inactive_machine_or_form_is_not_offered_and_not_enabled(self):
        for statement, undo in (("UPDATE vinto_master.machine SET active = false WHERE code = 'MP3'", "UPDATE vinto_master.machine SET active = true WHERE code = 'MP3'"),
                                ("UPDATE vinto_config.form SET active = false WHERE code = 'VINTO-P1-06'", "UPDATE vinto_config.form SET active = true WHERE code = 'VINTO-P1-06'")):
            self.connection.execute(statement)
            self.addCleanup(self.connection.execute, undo)
        machines = {m["code"]: {f["code"]: f for f in m["forms"]} for s in (await self.tree())["sectors"] for m in s["machines"]}
        self.assertTrue(all(not f["offered"] and not f["enabled_for_capture"] for f in machines["MP3"].values()))
        self.assertEqual((machines["MP1"][P106]["active"], machines["MP1"][P106]["offered"], machines["MP1"][P106]["enabled_for_capture"], machines["MP1"][P106]["published"]), (False, False, False, True))
        self.assertTrue(machines["MP1"][P101]["offered"])

    async def test_offered_is_exactly_what_grant_machine_form_accepts(self):
        offered = {(m["code"], f["code"]) for s in (await self.tree())["sectors"] for m in s["machines"] for f in m["forms"] if f["offered"]}
        accepted = set()
        for machine_id, machine in [(r[0], r[1]) for r in self.connection.execute("SELECT id, code FROM vinto_master.machine").fetchall()]:
            for form_id, form in [(r[0], r[1]) for r in self.connection.execute("SELECT id, code FROM vinto_config.form").fetchall()]:
                try:
                    _require_offered(self.connection, form_id, machine_id, machine, form)
                    accepted.add((machine, form))
                except Exception:  # FormNotLinkedToMachineError: el par no se ofrece
                    pass
        self.assertEqual(offered, accepted, "el catálogo y la política de concesión no pueden discrepar")

    async def test_read_only_calls_write_nothing(self):
        uid = self.target()
        self.grant(uid)
        before = self.snapshot()
        for path in ("/api/admin/catalog", "/api/admin/catalog/forms", f"/api/admin/users/{uid}", f"/api/admin/users/{uid}/grants", f"/api/admin/users/{uid}/grants/history"):
            self.assertEqual((await self.get(path)).status, 200, path)
        self.assertEqual(self.snapshot(), before)


class HistoricalLinkTests(Base):
    old_p105 = True

    async def test_a_link_that_only_a_historical_version_has_is_not_offered_nor_listed(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.status = 'published'", (P105,)), 2)
        machines = {m["code"]: {f["code"] for f in m["forms"]} for s in (await self.get("/api/admin/catalog")).json()["sectors"] for m in s["machines"]}
        self.assertNotIn(P105, machines["MP1"])
        self.assertIn(P105, machines["MP3"])
        form = next(f for f in (await self.get("/api/admin/catalog/forms")).json()["forms"] if f["code"] == P105)
        self.assertEqual((form["effective_version"], [m["code"] for m in form["machines"]]), (2, ["MP3"]))

    async def test_a_stored_grant_whose_pair_is_no_longer_offered_is_shown_as_not_offered(self):
        uid = self.target()
        machine_id = self.scalar("SELECT id FROM vinto_master.machine WHERE code = 'MP1'")
        form_id = self.scalar("SELECT id FROM vinto_config.form WHERE code = %s", (P105,))
        self.connection.execute("INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id) VALUES (%s,%s,%s)", (uid, machine_id, form_id))  # alta directa: lo que el servicio ya no permite
        (g,) = (await self.get(f"/api/admin/users/{uid}/grants")).json()["grants"]
        self.assertEqual((g["state"], g["granted_by"]), ("active", None))
        self.assertEqual(g["catalog"], {"published_version": 2, "offered": False, "enabled_for_capture": False, "capture_policies": ["production_central"]})


# ---- 5. coherencia bajo concurrencia -------------------------------------------------------------------------------------------------------------

class ConcurrencyTests(Base):
    async def test_responses_stay_consistent_while_grants_are_toggled_by_another_session(self):
        uid = self.target()
        stop, errors = threading.Event(), []

        def toggler():
            try:
                with connect(self.database) as connection:
                    for _ in range(25):
                        grant_machine_form(connection, user_id=uid, machine_code="MP1", form_code=P101, actor_id=self.admin_id())
                        revoke_machine_form(connection, user_id=uid, machine_code="MP1", form_code=P101, actor_id=self.admin_id())
            except BaseException as error:
                errors.append(repr(error))
            finally:
                stop.set()
        thread = threading.Thread(target=toggler)
        thread.start()
        seen = 0
        while not stop.is_set() or seen < 3:
            body = (await self.get(f"/api/admin/users/{uid}/grants/history")).json()
            active = [g for g in body["grants"] if g["state"] == "active"]
            self.assertLessEqual(len(active), 1, "nunca dos concesiones activas de la misma terna en una respuesta")
            self.assertEqual(body["total"], len(body["grants"]))
            self.assertTrue(all(g["revoked_by"] is not None for g in body["grants"] if g["state"] == "revoked"))
            seen += 1
            if seen > 200:
                break
        thread.join(60)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(seen, 3)


if __name__ == "__main__":
    unittest.main()
