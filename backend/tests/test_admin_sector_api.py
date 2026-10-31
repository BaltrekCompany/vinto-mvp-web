"""API administrativa de concesiones por sector (M1-C2-b1): /api/admin, permiso user.manage, reutiliza grant_sector / revoke_sector.

Solo bases efímeras *_test (la plantilla trae un sector sintético REBOBINADO, NO operativo salvo dentro de un patch). Nunca toca DEV.
"""

import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from app import sectors
from app.admin import schemas as admin_schemas
from app.admin import service as admin_service
from app.auth import permissions
from app.config import settings
from app.main import app

try:
    import test_sector_authorization as sa
    from test_assignments_api import call as _call, order_body
    from test_sector_authorization import FUTURE_MACHINE, FUTURE_SECTOR, setUpModule, tearDownModule  # noqa: F401
except ModuleNotFoundError:
    import tests.test_sector_authorization as sa
    from tests.test_assignments_api import call as _call, order_body
    from tests.test_sector_authorization import FUTURE_MACHINE, FUTURE_SECTOR, setUpModule, tearDownModule  # noqa: F401

COOKIE = "vinto_session"
PLANT_PROFILES = ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD")
ALLOWED_ORIGIN = settings.cors_origins[0]


async def call(method, path, *, no_origin=False, extra_headers=(), **kwargs):
    """Shared HTTP helper + the Origin a browser (or a well-behaved client) always sends on a POST; pass no_origin=True to test its absence."""
    headers = list(extra_headers)
    if method == "POST" and not no_origin and not any(name.lower() == "origin" for name, _ in headers):
        headers.append(("origin", ALLOWED_ORIGIN))
    return await _call(method, path, extra_headers=headers, **kwargs)


async def raw(method, path, body=b"", headers=(), cookie=None):
    """ASGI call with an arbitrary Content-Type/body (the shared helper always sends application/json)."""
    hdrs = [(b"host", b"127.0.0.1:8000")] + [(k.encode(), v.encode()) for k, v in headers] + ([(b"cookie", f"{COOKIE}={cookie}".encode())] if cookie else [])
    if body:
        hdrs.append((b"content-length", str(len(body)).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": hdrs, "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 1), "root_path": ""}
    sent, delivered = [], False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), json.loads(payload) if payload else None


class AdminCase(sa.SectorAuthorizationCase):
    BUSINESS = ("vinto_txn.work_order", "vinto_txn.assignment", "vinto_txn.capture", "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_txn.quality_release",
                "vinto_master.article", "vinto_master.machine", "vinto_master.sector", "vinto_config.shift_schedule", "vinto_master.user_profile", "vinto_master.profile")

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # CLOUD-DEP G.12-C4-FINAL25: FUTURE_SECTOR (ZZFIX_FUTURE, con fila real en esta base desde
        # setUpModule) y ZZFIX_RECOGNIZED (sin fila, para "reconocido pero ausente") necesitan pasar la
        # validación Pydantic de sector_code y el filtro del catálogo -- ambos importan
        # KNOWN_SECTOR_CODES por nombre (copias congeladas, independientes de app.sectors), así que se
        # parchean aquí, no en app.sectors.
        extra = sectors.KNOWN_SECTOR_CODES | {FUTURE_SECTOR, "ZZFIX_RECOGNIZED"}
        for target in (admin_schemas, admin_service):
            patcher = patch.object(target, "KNOWN_SECTOR_CODES", extra)
            patcher.start()
            self.addCleanup(patcher.stop)

    def business(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in self.BUSINESS}

    def grants_of(self, user_id):
        return sorted(r[0] for r in self.connection.execute("SELECT s.code FROM vinto_master.user_sector us JOIN vinto_master.sector s ON s.id=us.sector_id WHERE us.user_id=%s", (user_id,)))

    def sector_audit(self, user_id):
        return self.connection.execute("""SELECT action, actor_id, request_id, reason, occurred_at, coalesce(new_data, old_data)->>'user_id', database_actor
                                         FROM vinto_audit.audit_event WHERE entity_table='user_sector' AND coalesce(new_data, old_data)->>'user_id' = %s ORDER BY id""", (str(user_id),)).fetchall()

    def sector_audit_total(self):
        return self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='user_sector'")

    async def admin_cookie(self):
        return await self.cookie("DATA_BALTREK")

    async def post(self, user_id, op, code, cookie, **extra):
        return await call("POST", f"/api/admin/users/{user_id}/sectors/{op}", json_body={"sector_code": code}, cookie=cookie, **extra)


class AccessControlTests(AdminCase):
    def routes(self):
        some = uuid4()
        return (("GET", "/api/admin/users", None), ("GET", "/api/admin/sectors", None), ("GET", f"/api/admin/users/{some}/sectors", None),
                ("POST", f"/api/admin/users/{some}/sectors/grant", {"sector_code": "BOBINAS"}), ("POST", f"/api/admin/users/{some}/sectors/revoke", {"sector_code": "BOBINAS"}))

    async def test_no_session_is_401_everywhere_and_writes_nothing(self):
        before = (self.business(), self.sector_audit_total(), self.scalar("SELECT count(*) FROM vinto_master.user_sector"))
        for method, path, body in self.routes():
            reply = await call(method, path, json_body=body)
            self.assertEqual((reply.status, reply.json()), (401, {"detail": "No autenticado"}), path)
            self.assertEqual((await call(method, path, json_body=body, cookie="not-a-session")).status, 401, path)
        self.assertEqual((self.business(), self.sector_audit_total(), self.scalar("SELECT count(*) FROM vinto_master.user_sector")), before)

    async def test_plant_profiles_get_403_and_nothing_changes(self):
        target, _ = await self.new_user("OPERACION")
        before = (self.sector_audit_total(), self.grants_of(target.user_id))
        for profile in PLANT_PROFILES:
            cookie = await self.cookie(profile)
            for method, path, body in self.routes():
                reply = await call(method, path.replace(path.split("/")[4], str(target.user_id)) if len(path.split("/")) > 4 else path, json_body=body, cookie=cookie)
                self.assertEqual((reply.status, reply.json()), (403, {"detail": "Permiso insuficiente"}), f"{profile} {method} {path}")
        reply = await self.post(target.user_id, "grant", "BOBINAS", await self.cookie("JEFATURA"))
        self.assertEqual(reply.status, 403)
        self.assertEqual((self.sector_audit_total(), self.grants_of(target.user_id)), before)

    async def test_catalog_manage_is_not_a_substitute_for_user_manage(self):
        cookie = await self.cookie("OPERACION")
        only_catalog = {**permissions.PROFILE_PERMISSIONS, "OPERACION": frozenset({"catalog.manage", "catalog.read", "work_order.read"})}
        with patch.dict(permissions.PROFILE_PERMISSIONS, only_catalog):
            self.assertEqual((await call("GET", "/api/admin/users", cookie=cookie)).status, 403)
        only_user = {**permissions.PROFILE_PERMISSIONS, "OPERACION": frozenset({"user.manage"})}
        with patch.dict(permissions.PROFILE_PERMISSIONS, only_user):
            self.assertEqual((await call("GET", "/api/admin/users", cookie=cookie)).status, 200)

    async def test_the_routes_are_get_and_post_only_and_the_cors_policy_is_unchanged(self):
        paths = {p: set(m) for p, m in app.openapi()["paths"].items() if p.startswith("/api/admin")}
        self.assertEqual(set(paths), {"/api/admin/users", "/api/admin/sectors", "/api/admin/users/{user_id}/sectors", "/api/admin/users/{user_id}/sectors/grant", "/api/admin/users/{user_id}/sectors/revoke",
                                      # MF-13-01C.1: consulta de catálogo y concesiones máquina-formulario (solo GET; ver test_admin_grants_read_api.py)
                                      "/api/admin/catalog", "/api/admin/catalog/forms", "/api/admin/users/{user_id}", "/api/admin/users/{user_id}/grants", "/api/admin/users/{user_id}/grants/history",
                                      # MF-13-01C.2: alta y baja de concesiones máquina-formulario (solo POST; ver test_admin_grants_write_api.py)
                                      "/api/admin/users/{user_id}/grants/grant", "/api/admin/users/{user_id}/grants/revoke"})
        self.assertEqual(sorted(p for p, methods in paths.items() if methods != {"get"}), ["/api/admin/users/{user_id}/grants/grant", "/api/admin/users/{user_id}/grants/revoke",
                                                                                           "/api/admin/users/{user_id}/sectors/grant", "/api/admin/users/{user_id}/sectors/revoke"], "las únicas escrituras: sectores y concesiones máquina-formulario")
        self.assertTrue(all(methods <= {"get", "post"} for methods in paths.values()))
        cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
        self.assertEqual(sorted(cors.kwargs["allow_methods"]), ["GET", "POST"])
        self.assertEqual(cors.kwargs["allow_headers"], ["Content-Type"])
        self.assertEqual((await call("DELETE", "/api/admin/users", cookie=await self.admin_cookie())).status, 405)

    async def test_every_post_requires_an_allowed_origin_before_anything_is_checked_or_written(self):
        target, _ = await self.new_user("OPERACION")
        cookie = await self.admin_cookie()
        url, body = f"/api/admin/users/{target.user_id}/sectors/grant", json.dumps({"sector_code": "BOBINAS"}).encode()
        before = (self.sector_audit_total(), self.grants_of(target.user_id))
        for op in ("grant", "revoke"):
            path = f"/api/admin/users/{target.user_id}/sectors/{op}"
            cases = {"absent": [], "empty": [("origin", "")], "null": [("origin", "null")], "foreign": [("origin", "http://evil.example")],
                     "look-alike": [("origin", ALLOWED_ORIGIN + ".evil.example")], "scheme": [("origin", ALLOWED_ORIGIN.replace("http://", "https://"))],
                     "trailing slash": [("origin", ALLOWED_ORIGIN + "/")], "upper": [("origin", ALLOWED_ORIGIN.upper())]}
            for name, headers in cases.items():
                for session in (cookie, None, "not-a-session"):  # the origin is checked even before the session: no information about the session leaks to a foreign origin
                    status, _, answer = await raw("POST", path, body, headers=[("content-type", "application/json")] + headers, cookie=session)
                    self.assertEqual((status, answer), (403, {"detail": "Origen no autorizado", "code": "ORIGIN_NOT_ALLOWED"}), f"{op} {name}")
        self.assertEqual((self.sector_audit_total(), self.grants_of(target.user_id)), before, "nothing was written")
        # with the allowed origin the very same request works (and an unauthenticated one is then a plain 401)
        status, _, answer = await raw("POST", url, body, headers=[("content-type", "application/json"), ("origin", ALLOWED_ORIGIN)], cookie=cookie)
        self.assertEqual((status, answer["changed"]), (200, True))
        status, _, _ = await raw("POST", url, body, headers=[("content-type", "application/json"), ("origin", ALLOWED_ORIGIN)])
        self.assertEqual(status, 401)

    async def test_get_requests_do_not_need_an_origin_but_never_widen_cors(self):
        cookie = await self.admin_cookie()
        self.assertEqual((await call("GET", "/api/admin/users", cookie=cookie)).status, 200)
        status, headers, _ = await raw("GET", "/api/admin/users", headers=[("origin", "http://evil.example")], cookie=cookie)
        self.assertNotIn(b"access-control-allow-origin", headers, "a foreign origin never receives CORS permission")

    async def test_the_body_must_be_json_and_is_rejected_before_it_is_read(self):
        target, _ = await self.new_user("OPERACION")
        cookie = await self.admin_cookie()
        path = f"/api/admin/users/{target.user_id}/sectors/grant"
        base = [("origin", ALLOWED_ORIGIN)]
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", "application/jsonx", "application/xml", ""):
            headers = base + ([("content-type", content_type)] if content_type else [])
            status, _, answer = await raw("POST", path, b'{"sector_code":"BOBINAS"}', headers=headers, cookie=cookie)
            self.assertEqual((status, answer["code"]), (415, "UNSUPPORTED_MEDIA_TYPE"), repr(content_type))
        self.assertEqual(self.grants_of(target.user_id), [])
        status, _, answer = await raw("POST", path, b'{"sector_code":"BOBINAS"}', headers=base + [("content-type", "Application/JSON; charset=utf-8")], cookie=cookie)
        self.assertEqual((status, answer["changed"]), (200, True))

    async def test_session_cookie_policy_is_unchanged(self):
        created, password = self.users["DATA_BALTREK"]
        login = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        header = next(v.decode() for k, v in login.headers if k.decode().lower() == "set-cookie")
        self.assertIn("HttpOnly", header)
        self.assertRegex(header, r"(?i)samesite=lax")


class ReadTests(AdminCase):
    async def test_list_users_returns_only_the_needed_fields(self):
        reply = await call("GET", "/api/admin/users", cookie=await self.admin_cookie())
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers and any(k.decode().lower() == "cache-control" and v == b"no-store" for k, v in reply.headers), True)
        users = reply.json()
        self.assertGreaterEqual(len(users), 5)
        for user in users:
            self.assertEqual(set(user), {"id", "username", "display_name", "active", "profiles", "sectors"})
            for sector in user["sectors"]:
                self.assertEqual(set(sector), {"code", "name", "active", "operational"})
        self.assertNotRegex(reply.text.lower(), r"password|hash|token|session|secret|argon")
        by_name = {u["username"]: u for u in users}
        data = by_name[self.users["DATA_BALTREK"][0].username]
        self.assertEqual((data["profiles"], [s["code"] for s in data["sectors"]], data["sectors"][0]["operational"]), (["DATA_BALTREK"], ["BOBINAS"], True))
        self.assertEqual((await call("GET", "/api/admin/users?limit=2", cookie=await self.admin_cookie())).json().__len__(), 2)
        self.assertEqual((await call("GET", "/api/admin/users?limit=0", cookie=await self.admin_cookie())).status, 422)

    async def test_granted_is_distinguished_from_operational(self):
        created, _ = await self.new_user("JEFATURA", "BOBINAS", FUTURE_SECTOR)
        reply = await call("GET", f"/api/admin/users/{created.user_id}/sectors", cookie=await self.admin_cookie())
        self.assertEqual(reply.status, 200)
        body = reply.json()
        self.assertEqual({s["code"]: (s["active"], s["operational"]) for s in body["sectors"]}, {"BOBINAS": (True, True), FUTURE_SECTOR: (True, False)})
        self.assertEqual(set(body), {"user_id", "username", "active", "sectors"})
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS", FUTURE_SECTOR)):
            body = (await call("GET", f"/api/admin/users/{created.user_id}/sectors", cookie=await self.admin_cookie())).json()
            self.assertTrue(all(s["operational"] for s in body["sectors"]))

    async def test_inactive_users_are_listed_as_inactive(self):
        created, _ = await self.new_user("CALIDAD", "BOBINAS")
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (created.user_id,))
        users = (await call("GET", "/api/admin/users", cookie=await self.admin_cookie())).json()
        self.assertFalse(next(u for u in users if u["id"] == str(created.user_id))["active"])

    async def test_missing_user_and_malformed_id(self):
        cookie = await self.admin_cookie()
        reply = await call("GET", f"/api/admin/users/{uuid4()}/sectors", cookie=cookie)
        self.assertEqual((reply.status, reply.json()), (404, {"detail": "Usuario no encontrado", "code": "USER_NOT_FOUND"}))
        self.assertEqual((await call("GET", "/api/admin/users/not-a-uuid/sectors", cookie=cookie)).status, 422)

    async def test_me_contract_and_login_do_not_change_or_create_grants(self):
        created, cookie = await self.new_user("JEFATURA")
        before = self.scalar("SELECT count(*) FROM vinto_master.user_sector")
        me = await call("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(set(me.json()["user"]), {"id", "username", "display_name", "profiles", "permissions", "must_change"})
        await call("GET", "/api/admin/users", cookie=await self.admin_cookie())
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector"), before)
        self.assertEqual(self.grants_of(created.user_id), [])


class SectorCatalogTests(AdminCase):
    """GET /api/admin/sectors: the central catalogue the administration UI offers; read-only, from PostgreSQL, user.manage only."""

    async def catalogue(self):
        reply = await call("GET", "/api/admin/sectors", cookie=await self.admin_cookie())
        self.assertEqual(reply.status, 200)
        return reply.json()

    async def test_catalogue_comes_from_the_database_with_active_and_operational_flags(self):
        # CLOUD-DEP G.12-C4-FINAL25: BOBINAS/REBOBINADO/CONVERSION ya son todos reales, con fila propia
        # y operativos por defecto; FUTURE_SECTOR (ZZFIX_FUTURE, "reconocido" solo en asyncSetUp de esta
        # clase) sigue siendo el sector sintético activo-pero-no-operativo para esta prueba.
        reply = await call("GET", "/api/admin/sectors", cookie=await self.admin_cookie())
        self.assertEqual(reply.status, 200)
        self.assertTrue(any(k.decode().lower() == "cache-control" and v == b"no-store" for k, v in reply.headers))
        body = reply.json()
        self.assertEqual([s["code"] for s in body], ["BOBINAS", "CONVERSION", "REBOBINADO", FUTURE_SECTOR], "sorted by code; only sectors that exist in the database")
        for sector in body:
            self.assertEqual(set(sector), {"code", "name", "active", "operational"})
        self.assertEqual({s["code"]: (s["active"], s["operational"]) for s in body},
                         {"BOBINAS": (True, True), "CONVERSION": (True, True), "REBOBINADO": (True, True), FUTURE_SECTOR: (True, False)})
        self.assertNotRegex(reply.text.lower(), r"password|hash|token|session|secret|argon")
        self.assertEqual(await self.catalogue(), body, "the order is stable")
        for profile in ("DATA_BALTREK",):
            self.assertEqual((await call("GET", "/api/admin/sectors", cookie=await self.cookie(profile))).status, 200)

    async def test_active_inactive_and_non_operational_are_three_different_things(self):
        self.assertEqual({s["code"]: (s["active"], s["operational"]) for s in await self.catalogue()}["BOBINAS"], (True, True))
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS", FUTURE_SECTOR)):
            self.assertEqual({s["code"]: (s["active"], s["operational"]) for s in await self.catalogue()}[FUTURE_SECTOR], (True, True), "active AND enabled in code")
            self.connection.execute("UPDATE vinto_master.sector SET active=false WHERE code=%s", (FUTURE_SECTOR,))
            try:
                listed = {s["code"]: (s["active"], s["operational"]) for s in await self.catalogue()}
                self.assertEqual(listed[FUTURE_SECTOR], (False, False), "an inactive sector is listed, marked inactive and never operational, even if enabled in code")
            finally:
                self.connection.execute("UPDATE vinto_master.sector SET active=true WHERE code=%s", (FUTURE_SECTOR,))
        self.assertEqual({s["code"]: (s["active"], s["operational"]) for s in await self.catalogue()}[FUTURE_SECTOR], (True, False), "active but not enabled in code")

    async def test_unrecognised_codes_in_the_database_are_not_offered(self):
        self.connection.execute("INSERT INTO vinto_master.sector (code, name) VALUES ('EXTRANO', 'No reconocido')")
        try:
            self.assertNotIn("EXTRANO", [s["code"] for s in await self.catalogue()])
        finally:
            self.connection.execute("DELETE FROM vinto_master.sector WHERE code='EXTRANO'")

    async def test_the_catalogue_is_read_only_and_does_not_change_anything(self):
        before = (self.business(), self.sector_audit_total(), self.scalar("SELECT count(*) FROM vinto_master.user_sector"))
        await self.catalogue()
        self.assertEqual((await call("POST", "/api/admin/sectors", json_body={"sector_code": "BOBINAS"}, cookie=await self.admin_cookie())).status, 405)
        self.assertEqual((await call("DELETE", "/api/admin/sectors", cookie=await self.admin_cookie())).status, 405)
        self.assertEqual((self.business(), self.sector_audit_total(), self.scalar("SELECT count(*) FROM vinto_master.user_sector")), before)


class GrantRevokeTests(AdminCase):
    async def test_grant_is_audited_with_the_authenticated_actor_and_is_idempotent(self):
        target, cookie = await self.new_user("JEFATURA")
        admin = await self.admin_cookie()
        admin_id = self.users["DATA_BALTREK"][0].user_id
        reply = await self.post(target.user_id, "grant", "BOBINAS", admin)
        body = reply.json()
        self.assertEqual((reply.status, body["changed"], body["operation"], body["sector_code"]), (200, True, "grant", "BOBINAS"))
        self.assertEqual(body["sector"], {"code": "BOBINAS", "name": body["sector"]["name"], "active": True, "operational": True})
        self.assertEqual([s["code"] for s in body["granted_sectors"]], ["BOBINAS"])
        self.assertTrue(body["request_id"].startswith("admin-sector-grant:"))
        self.assertEqual(self.grants_of(target.user_id), ["BOBINAS"])
        events = self.sector_audit(target.user_id)
        self.assertEqual(len(events), 1)
        action, actor, request_id, reason, occurred_at, subject, _ = events[0]
        self.assertEqual((action, actor, request_id, reason, subject), ("INSERT", admin_id, body["request_id"], "sector grant", str(target.user_id)))
        self.assertIsNotNone(occurred_at)
        # idempotent repetition: no change, no audit event, no touched row
        stamp = self.scalar("SELECT updated_at FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,))
        again = (await self.post(target.user_id, "grant", "BOBINAS", admin)).json()
        self.assertEqual((again["changed"], again["request_id"]), (False, None))
        self.assertEqual(len(self.sector_audit(target.user_id)), 1)
        self.assertEqual(self.scalar("SELECT updated_at FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,)), stamp)
        self.assertEqual(self.grants_of(target.user_id), ["BOBINAS"])

    async def test_revoke_is_audited_idempotent_and_effective_on_the_next_request_with_an_open_session(self):
        order, _ = await self.assignment("MP1")
        target, cookie = await self.new_user("JEFATURA", "BOBINAS")
        admin = await self.admin_cookie()
        self.assertIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=cookie)).json()])
        reply = await self.post(target.user_id, "revoke", "BOBINAS", admin)
        body = reply.json()
        self.assertEqual((reply.status, body["changed"], body["operation"], body["granted_sectors"]), (200, True, "revoke", []))
        # the very next authenticated request of the SAME session sees nothing
        self.assertEqual((await call("GET", "/api/work-orders", cookie=cookie)).json(), [])
        self.assertEqual((await call("GET", f"/api/work-orders/{order['id']}", cookie=cookie)).status, 404)
        self.assertEqual((await call("GET", "/api/captures/count?front=Bobinas", cookie=cookie)).json()["count"], 0)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 200, "the session itself is still valid")
        events = self.sector_audit(target.user_id)
        self.assertEqual([e[0] for e in events], ["INSERT", "DELETE"])  # the INSERT is the test fixture's own grant (create_user)
        self.assertEqual((events[1][1], events[1][2], events[1][3]), (self.users["DATA_BALTREK"][0].user_id, body["request_id"], "sector revoke"))
        again = (await self.post(target.user_id, "revoke", "BOBINAS", admin)).json()
        self.assertEqual((again["changed"], again["request_id"]), (False, None))
        self.assertEqual(len(self.sector_audit(target.user_id)), 2)
        # and re-granting restores access without a new login
        self.assertTrue((await self.post(target.user_id, "grant", "BOBINAS", admin)).json()["changed"])
        self.assertIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=cookie)).json()])

    async def test_unknown_user_unknown_sector_and_invalid_codes(self):
        admin = await self.admin_cookie()
        target, _ = await self.new_user("OPERACION")
        before = (self.sector_audit_total(), self.business())
        reply = await self.post(uuid4(), "grant", "BOBINAS", admin)
        self.assertEqual((reply.status, reply.json()), (404, {"detail": "Usuario no encontrado", "code": "USER_NOT_FOUND"}))
        # CLOUD-DEP G.12-C4-FINAL25: BOBINAS/REBOBINADO/CONVERSION ya son todos reales y tienen fila en
        # esta base; "ZZFIX_RECOGNIZED" (reconocido solo dentro de asyncSetUp de esta clase, ver arriba)
        # sigue sin fila -- cubre "reconocido por el producto pero ausente en esta base".
        reply = await self.post(target.user_id, "grant", "ZZFIX_RECOGNIZED", admin)
        self.assertEqual((reply.status, reply.json()), (404, {"detail": "Sector no encontrado", "code": "SECTOR_NOT_FOUND"}))
        for bad in ("INVENTADO", "bobinas", " BOBINAS", "BOBINAS ", "", "B" * 40, "BOBINAS; DROP TABLE x", None, 5, ["BOBINAS"]):
            reply = await call("POST", f"/api/admin/users/{target.user_id}/sectors/grant", json_body={"sector_code": bad}, cookie=admin)
            self.assertEqual(reply.status, 422, repr(bad))
            self.assertNotRegex(reply.text, r"Traceback|SELECT|psycopg")
        self.assertEqual((await call("POST", f"/api/admin/users/{target.user_id}/sectors/grant", json_body={}, cookie=admin)).status, 422)
        self.assertEqual((await call("POST", f"/api/admin/users/{target.user_id}/sectors/grant", cookie=admin)).status, 415, "no body and no content type")
        status, _, _ = await raw("POST", f"/api/admin/users/{target.user_id}/sectors/grant", b"", headers=[("origin", ALLOWED_ORIGIN), ("content-type", "application/json")], cookie=admin)
        self.assertEqual(status, 422, "an empty JSON body")
        self.assertEqual((await call("POST", "/api/admin/users/not-a-uuid/sectors/grant", json_body={"sector_code": "BOBINAS"}, cookie=admin)).status, 422)
        self.assertEqual((self.sector_audit_total(), self.business()), before)
        self.assertEqual(self.grants_of(target.user_id), [])

    async def test_an_inactive_sector_cannot_be_granted_but_an_old_grant_can_be_revoked(self):
        target, _ = await self.new_user("JEFATURA", FUTURE_SECTOR)
        other, _ = await self.new_user("CALIDAD")
        admin = await self.admin_cookie()
        self.connection.execute("UPDATE vinto_master.sector SET active=false WHERE code=%s", (FUTURE_SECTOR,))
        try:
            reply = await self.post(other.user_id, "grant", FUTURE_SECTOR, admin)
            self.assertEqual((reply.status, reply.json()), (422, {"detail": "El sector está inactivo y no admite nuevas concesiones", "code": "SECTOR_INACTIVE"}))
            self.assertEqual(self.grants_of(other.user_id), [])
            listed = (await call("GET", f"/api/admin/users/{target.user_id}/sectors", cookie=admin)).json()["sectors"]
            self.assertEqual([(s["code"], s["active"], s["operational"]) for s in listed], [(FUTURE_SECTOR, False, False)])
            self.assertTrue((await self.post(target.user_id, "revoke", FUTURE_SECTOR, admin)).json()["changed"])
        finally:
            self.connection.execute("UPDATE vinto_master.sector SET active=true WHERE code=%s", (FUTURE_SECTOR,))
        self.assertEqual(self.grants_of(target.user_id), [])

    async def test_a_grant_on_a_non_operational_sector_is_inert_and_never_enables_it(self):
        target, cookie = await self.new_user("JEFATURA")
        admin = await self.admin_cookie()
        body = (await self.post(target.user_id, "grant", FUTURE_SECTOR, admin)).json()
        self.assertEqual((body["changed"], body["sector"]["active"], body["sector"]["operational"]), (True, True, False))
        self.assertEqual(sectors.operational_sector_codes(), ("BOBINAS", "REBOBINADO", "CONVERSION"))
        before = self.business()
        reply = await call("POST", "/api/work-orders", json_body={**order_body("MP1"), "machine_code": FUTURE_MACHINE}, cookie=cookie)
        self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        self.assertEqual((await call("GET", "/api/work-orders", cookie=cookie)).json(), [])
        self.assertEqual((await call("GET", "/api/captures/count?front=Rebobinado", cookie=cookie)).json()["count"], 0)
        self.assertEqual(self.business(), before)

    async def test_the_actor_and_scope_cannot_be_forged_through_body_query_or_headers(self):
        target, _ = await self.new_user("OPERACION")
        admin = await self.admin_cookie()
        victim = self.users["JEFATURA"][0].user_id
        for extra in ({"actor_id": str(victim)}, {"user_id": str(victim)}, {"sectors": ["BOBINAS", FUTURE_SECTOR]}, {"created_by": str(victim)}, {"request_id": "forged"}, {"all_sectors": True}):
            reply = await call("POST", f"/api/admin/users/{target.user_id}/sectors/grant", json_body={"sector_code": "BOBINAS", **extra}, cookie=admin)
            self.assertEqual(reply.status, 422, extra)
        self.assertEqual(self.grants_of(target.user_id), [])
        reply = await call("POST", f"/api/admin/users/{target.user_id}/sectors/grant?actor_id={victim}&sector_code={FUTURE_SECTOR}", json_body={"sector_code": "BOBINAS"}, cookie=admin,
                           extra_headers=[("x-actor-id", str(victim)), ("x-request-id", "forged")])
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.grants_of(target.user_id), ["BOBINAS"])
        (action, actor, request_id, *_), = self.sector_audit(target.user_id)
        self.assertEqual(actor, self.users["DATA_BALTREK"][0].user_id)
        self.assertNotEqual(actor, victim)
        self.assertTrue(request_id.startswith("admin-sector-grant:") and request_id != "forged")

    async def test_administering_does_not_elevate_permissions_and_data_baltrek_still_cannot_operate(self):
        admin_user, admin = self.users["DATA_BALTREK"][0], await self.admin_cookie()
        target, cookie = await self.new_user("OPERACION")
        await self.post(target.user_id, "grant", "BOBINAS", admin)
        me = await call("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(set(me.json()["user"]["permissions"]), sa.PINNED_PROFILE_PERMISSIONS["OPERACION"])
        # the administrator holds BOBINAS but only its own (read) permissions: no production, no quality, no work-order or assignment management
        order, assignment = await self.assignment("MP1")
        before = self.business()
        denied = (("POST", "/api/work-orders", order_body("MP1")), ("POST", f"/api/work-orders/{order['id']}/publish", None),
                  ("POST", "/api/assignments/activate", {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]}),
                  ("POST", f"/api/assignments/{assignment['id']}/finish", None), ("POST", "/api/captures", {}), ("POST", "/api/bobbins", self.payload(assignment)),
                  ("POST", f"/api/quality/bobbins/{uuid4()}/captures", {}), ("GET", "/api/quality/bobbins", None), ("GET", "/api/captures", None))
        for method, path, body in denied:
            self.assertEqual((await call(method, path, json_body=body, cookie=admin)).status, 403, f"{method} {path}")
        self.assertEqual(self.business(), before)
        self.assertEqual(set((await call("GET", "/api/auth/me", cookie=admin)).json()["user"]["permissions"]), sa.PINNED_PROFILE_PERMISSIONS["DATA_BALTREK"])
        self.assertEqual(admin_user.username, self.users["DATA_BALTREK"][0].username)

    async def test_a_whole_admin_session_changes_no_business_data(self):
        order, _ = await self.assignment("MP1")
        admin = await self.admin_cookie()
        target, _ = await self.new_user("CALIDAD")  # creating the user is test setup, not part of the admin session under test
        before = self.business()
        for op, code in (("grant", "BOBINAS"), ("grant", "BOBINAS"), ("grant", FUTURE_SECTOR), ("revoke", FUTURE_SECTOR), ("revoke", FUTURE_SECTOR), ("revoke", "BOBINAS")):
            self.assertEqual((await self.post(target.user_id, op, code, admin)).status, 200)
        await call("GET", "/api/admin/users", cookie=admin)
        self.assertEqual(self.business(), before)
        self.assertEqual(self.grants_of(target.user_id), [])
        self.assertEqual([e[0] for e in self.sector_audit(target.user_id)], ["INSERT", "INSERT", "DELETE", "DELETE"])
        self.assertTrue(order)


class UnavailableDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_unavailable_is_a_safe_503(self):
        closed = SecretStr(make_conninfo(settings.database_url.get_secret_value(), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed):
            for method, path, body in (("GET", "/api/admin/users", None), ("GET", "/api/admin/sectors", None), ("GET", f"/api/admin/users/{uuid4()}/sectors", None),
                                       ("POST", f"/api/admin/users/{uuid4()}/sectors/grant", {"sector_code": "BOBINAS"})):
                reply = await call(method, path, json_body=body)
                self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}), path)
                self.assertNotRegex(reply.text.lower(), r"password|postgresql://")


if __name__ == "__main__":
    unittest.main()
