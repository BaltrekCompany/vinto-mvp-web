"""MF-13-01C.2: API administrativa para CONCEDER y REVOCAR el acceso de un usuario a un formulario de una máquina
(POST /api/admin/users/{id}/grants/grant y /grants/revoke).

Se verifica contra PostgreSQL REAL (bases efímeras *_test) con los formularios REALES del bundle y a través de la app ASGI: autenticación y permiso user.manage, actor tomado SOLO de la sesión,
cuerpo estricto (machine_code, form_code), Origin y Content-Type, independencia MP1/MP3 y de las cinco rebobinadoras de P1-10, pares no ofrecidos, idempotencia, historial y auditoría,
concurrencia, y que NADA de esto toca capturas, órdenes, asignaciones, bobinas ni liberaciones de Calidad (las concesiones todavía no se usan para autorizar)."""

import asyncio
import dataclasses
import json
import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import sectors
from app.admin.router import router as admin_router
from app.auth.machine_form_grants import machine_form_grants_for_user
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.main import app
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle

try:
    from test_assignments_api import call as _call
except ModuleNotFoundError:
    from tests.test_assignments_api import call as _call

COOKIE = "vinto_session"
ORIGIN = settings.cors_origins[0]
P101, P102, P105, P110, P131 = "VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-05", "VINTO-P1-10", "VINTO-P1-31"
FIVE = ["BELOIT", "OVER", "COPASA", "PERICHUN", "TUBETERA"]
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
FORBIDDEN_KEYS = ("password", "hash", "token", "secret", "cookie", "session", "credential", "salt")
GRANT, REVOKE = "grants/grant", "grants/revoke"
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_c2_tpl")


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


async def raw(method, path, body=b"", headers=(), cookie=None):
    """ASGI con un Content-Type/Origin arbitrarios (el helper compartido siempre manda application/json)."""
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
    return start["status"], json.loads(payload) if payload else None


class Base(unittest.IsolatedAsyncioTestCase):
    old_p105 = False

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_c2")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        if cls.old_p105:
            reference.apply(cls.connection, old_p105_bundle())
        cls.users, cls.cookies = {}, {}
        for name, profile in (("ADMIN", "DATA_BALTREK"), ("ADMIN2", "DATA_BALTREK"), ("JEFATURA", "JEFATURA"), ("SUPERVISION", "SUPERVISION"), ("OPERACION", "OPERACION"), ("CALIDAD", "CALIDAD")):
            cls.users[name] = cls.make_user(name, profile)

    @classmethod
    def make_user(cls, name, profile, sectors_=("BOBINAS",)):
        password = "pw-" + secrets.token_urlsafe(18)
        created = create_user(cls.connection, username=f"c2.{name.lower()}.{uuid4().hex[:6]}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors_)
        return created, password

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await _call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    def admin_id(self, name="ADMIN"):
        return self.users[name][0].user_id

    def target(self, profile="OPERACION", sectors_=("BOBINAS",)):
        return create_user(self.connection, username=f"c2.t.{uuid4().hex[:10]}", display_name=f"Target {uuid4().hex[:4]}", profile_code=profile, password="pw-" + uuid4().hex, sectors=sectors_).user_id

    async def post(self, uid, action, machine, form, who="ADMIN", *, origin=ORIGIN, extra=None, headers=()):
        hdrs = ([("origin", origin)] if origin else []) + list(headers)
        body = {"machine_code": machine, "form_code": form, **(extra or {})}
        return await _call("POST", f"/api/admin/users/{uid}/{action}", json_body=body, cookie=await self.cookie(who) if who else None, extra_headers=hdrs)

    async def get(self, path, who="ADMIN"):
        return await _call("GET", path, cookie=await self.cookie(who))

    def scalar(self, sql, params=()):
        return self.connection.execute(sql, params).fetchone()[0]

    def rows(self, uid):
        return self.scalar("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (uid,))

    def audit(self, uid):
        return self.connection.execute("SELECT action, actor_id, request_id, reason FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant' AND new_data->>'user_id' = %s ORDER BY id",
                                       (str(uid),)).fetchall()

    def untouched(self):
        return tuple(self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_txn.work_order", "vinto_txn.assignment", "vinto_txn.bobbin",
                                                                        "vinto_txn.quality_release", "vinto_master.user_sector", "vinto_master.user_profile", 'vinto_master."user"',
                                                                        "vinto_config.form", "vinto_config.form_version", "vinto_config.form_version_machine"))


# ---- 1. contrato, autenticación y permiso ---------------------------------------------------------------------------------------------------------

class ContractTests(Base):
    async def test_data_baltrek_grants_and_revokes_with_the_documented_response(self):
        uid = self.target()
        reply = await self.post(uid, GRANT, "MP1", P101)
        self.assertEqual(reply.status, 200, reply.text)
        body = reply.json()
        self.assertEqual({k: body[k] for k in ("user_id", "machine_code", "form_code", "operation", "changed", "active")}, {"user_id": str(uid), "machine_code": "MP1", "form_code": P101, "operation": "grant", "changed": True, "active": True})
        self.assertTrue(body["request_id"].startswith("admin-machine-form-grant:"))
        self.assertEqual((body["grant"]["state"], body["grant"]["granted_by"]["id"], body["grant"]["revoked_at"]), ("active", str(self.admin_id()), None))
        self.assertEqual(body["catalog"], {"published_version": 4, "offered": True, "enabled_for_capture": True, "capture_policies": ["production_central"]})
        self.assertEqual(body["context"], {"user_active": True, "sector_code": "BOBINAS", "sector_granted": True, "sector_operational": True})
        revoked = (await self.post(uid, REVOKE, "MP1", P101)).json()
        self.assertEqual((revoked["operation"], revoked["changed"], revoked["active"], revoked["grant"]["state"], revoked["grant"]["revoked_by"]["id"]), ("revoke", True, False, "revoked", str(self.admin_id())))
        self.assertTrue(revoked["request_id"].startswith("admin-machine-form-revoke:"))
        self.assertEqual(reply.headers and {k.decode().lower(): v.decode() for k, v in reply.headers}.get("cache-control"), "no-store")

    async def test_only_user_manage_may_administer_and_nothing_is_written_otherwise(self):
        uid, before = self.target(), self.untouched()
        for action in (GRANT, REVOKE):
            self.assertEqual((await self.post(uid, action, "MP1", P101, who=None)).status, 401, action)
            for who in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"):
                self.assertEqual((await self.post(uid, action, "MP1", P101, who=who)).status, 403, (action, who))
        self.assertEqual(self.rows(uid), 0)
        self.assertEqual(self.untouched(), before)

    async def test_a_revoked_session_loses_the_right_to_administer(self):
        self.users["GONE"] = self.make_user("gone", "DATA_BALTREK")
        uid = self.target()
        self.assertEqual((await self.post(uid, GRANT, "MP1", P101, who="GONE")).status, 200)
        self.connection.execute("UPDATE vinto_auth.session SET revoked_at = clock_timestamp() WHERE user_id = %s", (self.users["GONE"][0].user_id,))
        self.assertEqual((await self.post(uid, REVOKE, "MP1", P101, who="GONE")).status, 401)
        self.assertEqual(self.rows(uid), 1, "la revocación rechazada no cambió nada")

    async def test_the_actor_is_the_authenticated_session_user_never_the_target_or_the_body(self):
        uid = self.target()
        await self.post(uid, GRANT, "MP1", P101, who="ADMIN2")
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (uid,)), self.admin_id("ADMIN2"))
        await self.post(uid, REVOKE, "MP1", P101, who="ADMIN")
        self.assertEqual(self.connection.execute("SELECT revoked_by, updated_by FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (uid,)).fetchone(), (self.admin_id(), self.admin_id()))
        self.assertEqual([(a[0], a[1]) for a in self.audit(uid)], [("INSERT", self.admin_id("ADMIN2")), ("UPDATE", self.admin_id())])

    async def test_the_request_id_is_generated_by_the_server_and_a_client_header_is_ignored(self):
        uid = self.target()
        body = (await self.post(uid, GRANT, "MP1", P101, headers=[("x-request-id", "client-chosen")])).json()
        self.assertTrue(body["request_id"].startswith("admin-machine-form-grant:") and "client-chosen" not in body["request_id"])
        self.assertEqual(self.audit(uid)[0][2], body["request_id"], "el id de la respuesta es el de la auditoría")

    async def test_no_secret_or_sql_ever_leaves_the_api(self):
        uid = self.target()
        password_hash = self.scalar("SELECT password_hash FROM vinto_auth.credential WHERE user_id = %s", (uid,))
        outputs = [await self.post(uid, GRANT, "MP1", P101), await self.post(uid, REVOKE, "MP1", P101), await self.post(uid, GRANT, "NOPE", P101), await self.post(uid, GRANT, "MP1", "VINTO-P9-99"),
                   await self.post(uid, GRANT, "MP1", P105), await self.post(uuid4(), GRANT, "MP1", P101)]
        for reply in outputs:
            self.assertFalse([k for k in keys_of(reply.json()) if any(bad in k.lower() for bad in FORBIDDEN_KEYS)])
            self.assertNotIn(password_hash, reply.text)
            self.assertNotIn(self.cookies["ADMIN"], reply.text)
            for fragment in ("SELECT ", "INSERT ", "vinto_master", "psycopg", "Traceback"):
                self.assertNotIn(fragment, reply.text)


# ---- 2. solicitud estricta, Origin y Content-Type -------------------------------------------------------------------------------------------------

class RequestHardeningTests(Base):
    async def test_extra_fields_and_forged_authority_are_rejected_before_anything_is_written(self):
        uid, before = self.target(), self.untouched()
        for extra in ({"actor_id": str(self.admin_id("ADMIN2"))}, {"revoked_by": str(self.admin_id())}, {"request_id": "client-chosen"}, {"user_id": str(uuid4())}, {"permissions": ["user.manage"]},
                      {"profiles": ["DATA_BALTREK"]}, {"sector_code": "BOBINAS"}, {"created_by": str(self.admin_id())}, {"anything": 1}):
            for action in (GRANT, REVOKE):
                reply = await self.post(uid, action, "MP1", P101, extra=extra)
                self.assertEqual(reply.status, 422, (action, extra))
        self.assertEqual(self.rows(uid), 0)
        self.assertEqual(self.untouched(), before)
        self.assertEqual(self.audit(uid), [])

    async def test_malformed_bodies_and_codes_are_422(self):
        uid = self.target()
        cookie = await self.cookie("ADMIN")
        for body in ({}, {"machine_code": "MP1"}, {"form_code": P101}, {"machine_code": "", "form_code": P101}, {"machine_code": "mp1", "form_code": P101}, {"machine_code": "MP1", "form_code": "vinto-p1-01"},
                     {"machine_code": "MP1 ", "form_code": P101}, {"machine_code": "MP1", "form_code": P101 + "; DROP"}, {"machine_code": 1, "form_code": P101}, {"machine_code": None, "form_code": P101},
                     {"machine_code": "M" * 65, "form_code": P101}):
            reply = await _call("POST", f"/api/admin/users/{uid}/{GRANT}", json_body=body, cookie=cookie, extra_headers=[("origin", ORIGIN)])
            self.assertEqual(reply.status, 422, body)
        status, _ = await raw("POST", f"/api/admin/users/{uid}/{GRANT}", body=b"[1,2]", headers=[("origin", ORIGIN), ("content-type", "application/json")], cookie=cookie)
        self.assertEqual(status, 422)
        status, _ = await raw("POST", f"/api/admin/users/{uid}/{GRANT}", body=b"{not json", headers=[("origin", ORIGIN), ("content-type", "application/json")], cookie=cookie)
        self.assertEqual(status, 422)
        self.assertEqual((await self.post("not-a-uuid", GRANT, "MP1", P101)).status, 422)
        self.assertEqual(self.rows(uid), 0)

    async def test_the_origin_is_mandatory_and_checked_before_the_session(self):
        uid = self.target()
        for origin in (None, "", "null", "https://evil.example", ORIGIN + ".evil.example", ORIGIN.upper() if ORIGIN.upper() != ORIGIN else "HTTP://X"):
            for who in ("ADMIN", None):
                reply = await self.post(uid, GRANT, "MP1", P101, who=who, origin=origin)
                self.assertEqual((reply.status, reply.json()["code"]), (403, "ORIGIN_NOT_ALLOWED"), (origin, who))
        self.assertEqual(self.rows(uid), 0)

    async def test_the_content_type_must_be_json(self):
        uid, cookie = self.target(), await self.cookie("ADMIN")
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""):
            status, body = await raw("POST", f"/api/admin/users/{uid}/{GRANT}", body=b'{"machine_code":"MP1","form_code":"VINTO-P1-01"}', headers=[("origin", ORIGIN)] + ([("content-type", content_type)] if content_type else []), cookie=cookie)
            self.assertEqual((status, body["code"]), (415, "UNSUPPORTED_MEDIA_TYPE"), content_type)
        status, _ = await raw("POST", f"/api/admin/users/{uid}/{GRANT}", body=b'{"machine_code":"MP1","form_code":"VINTO-P1-01"}', headers=[("origin", ORIGIN), ("content-type", "application/json; charset=utf-8")], cookie=cookie)
        self.assertEqual(status, 200, "application/json con charset es válido")
        self.assertEqual(self.rows(uid), 1)

    async def test_only_post_is_accepted_on_the_new_paths(self):
        uid = self.target()
        for method in ("GET", "PUT", "PATCH", "DELETE"):
            reply = await _call(method, f"/api/admin/users/{uid}/{GRANT}", json_body={"machine_code": "MP1", "form_code": P101}, cookie=await self.cookie("ADMIN"), extra_headers=[("origin", ORIGIN)])
            self.assertEqual(reply.status, 405, method)
        writes = sorted(p for r in admin_router.routes for m in r.methods if m != "GET" for p in [r.path])
        self.assertEqual(writes, ["/api/admin/users/{user_id}/grants/grant", "/api/admin/users/{user_id}/grants/revoke", "/api/admin/users/{user_id}/sectors/grant", "/api/admin/users/{user_id}/sectors/revoke"])
        self.assertEqual(self.rows(uid), 0)


# ---- 3. independencia MP1 / MP3 y P1-10 en las cinco rebobinadoras --------------------------------------------------------------------------------

class IndependenceTests(Base):
    async def active(self, uid):
        return sorted((g["machine"]["code"], g["form"]["code"]) for g in (await self.get(f"/api/admin/users/{uid}/grants")).json()["grants"])

    async def test_p1_01_on_mp1_does_not_grant_it_on_mp3_and_each_is_revoked_separately(self):
        uid = self.target()
        self.assertTrue((await self.post(uid, GRANT, "MP1", P101)).json()["changed"])
        self.assertEqual(await self.active(uid), [("MP1", P101)], "conceder MP1 no concede MP3")
        self.assertTrue((await self.post(uid, GRANT, "MP3", P101)).json()["changed"])
        self.assertEqual(await self.active(uid), [("MP1", P101), ("MP3", P101)])
        self.assertTrue((await self.post(uid, REVOKE, "MP1", P101)).json()["changed"])
        self.assertEqual(await self.active(uid), [("MP3", P101)], "revocar MP1 deja MP3")
        again = (await self.post(uid, GRANT, "MP1", P102)).json()
        self.assertEqual((again["changed"], await self.active(uid)), (True, [("MP1", P102), ("MP3", P101)]), "otro formulario de la misma máquina es otra concesión")

    async def test_p1_10_is_granted_and_revoked_independently_on_each_of_the_five_rebobinadoras(self):
        uid = self.target(sectors_=("BOBINAS", "REBOBINADO"))
        for machine in FIVE:
            body = (await self.post(uid, GRANT, machine, P110)).json()
            self.assertEqual((body["changed"], body["active"], body["catalog"]["published_version"], body["catalog"]["offered"], body["context"]["sector_code"]), (True, True, 3, True, "REBOBINADO"), machine)
        self.assertEqual(await self.active(uid), sorted((m, P110) for m in FIVE))
        self.assertTrue((await self.post(uid, REVOKE, "COPASA", P110)).json()["changed"])
        self.assertEqual(await self.active(uid), sorted((m, P110) for m in FIVE if m != "COPASA"), "revocar COPASA no toca las otras cuatro")
        for machine in ("MP1", "MP3", "GAMBINI"):
            reply = await self.post(uid, GRANT, machine, P110)
            self.assertEqual((reply.status, reply.json()["code"]), (409, "PAIR_NOT_OFFERED"), f"P1-10 no se ofrece en {machine}")

    async def test_granting_never_grants_sectors_profiles_or_other_pairs(self):
        uid = self.target(sectors_=())
        before = self.untouched()
        body = (await self.post(uid, GRANT, "MP3", P131)).json()
        self.assertEqual(body["context"]["sector_granted"], False, "conceder el formulario no concede el sector")
        self.assertEqual(self.untouched(), before, "ni sectores, ni perfiles, ni usuarios, ni catálogo cambian")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id = %s", (uid,)), 0)
        self.assertEqual(await self.active(uid), [("MP3", P131)])


# ---- 4. pares no ofrecidos, inexistentes, usuarios inactivos o sin sector --------------------------------------------------------------------------

class PairPolicyTests(Base):
    async def test_unknown_user_machine_or_form_is_404_and_nothing_is_created(self):
        uid, before = self.target(), self.untouched()
        for action in (GRANT, REVOKE):
            self.assertEqual(((r := await self.post(uuid4(), action, "MP1", P101)).status, r.json()["code"]), (404, "USER_NOT_FOUND"))
            self.assertEqual(((r := await self.post(uid, action, "NOPE", P101)).status, r.json()["code"]), (404, "MACHINE_NOT_FOUND"))
            self.assertEqual(((r := await self.post(uid, action, "MP1", "VINTO-P9-99")).status, r.json()["code"]), (404, "FORM_NOT_FOUND"))
            self.assertEqual(((r := await self.post(uuid4(), action, "NOPE", "VINTO-P9-99")).status, r.json()["code"]), (404, "USER_NOT_FOUND"), "el usuario se comprueba primero")
        self.assertEqual(self.untouched(), before)
        self.assertEqual(self.rows(uid), 0)

    async def test_a_pair_the_catalog_does_not_offer_is_409_on_grant(self):
        uid = self.target()
        reply = await self.post(uid, GRANT, "MP1", P105)  # P1-05 solo se ofrece en MP3
        self.assertEqual((reply.status, reply.json()["code"]), (409, "PAIR_NOT_OFFERED"))
        self.assertEqual(set(reply.json()), {"detail", "code"}, "el error no expone nada más")
        self.assertEqual(self.rows(uid), 0)
        self.assertEqual((await self.post(uid, GRANT, "MP3", P105)).status, 200)

    async def test_an_inactive_machine_or_form_is_not_granted_and_the_state_is_restored(self):
        uid = self.target()
        for statement, undo in (("UPDATE vinto_master.machine SET active = false WHERE code = 'MP3'", "UPDATE vinto_master.machine SET active = true WHERE code = 'MP3'"),
                                ("UPDATE vinto_config.form SET active = false WHERE code = 'VINTO-P1-06'", "UPDATE vinto_config.form SET active = true WHERE code = 'VINTO-P1-06'")):
            self.connection.execute(statement)
            self.addCleanup(self.connection.execute, undo)
        self.assertEqual((await self.post(uid, GRANT, "MP3", P101)).status, 409)
        self.assertEqual((await self.post(uid, GRANT, "MP1", "VINTO-P1-06")).status, 409)
        self.assertEqual((await self.post(uid, GRANT, "MP1", P101)).status, 200, "lo demás sigue concediéndose")
        self.assertEqual(self.rows(uid), 1)

    async def test_offered_and_enabled_for_capture_are_distinct_and_no_capture_policy_is_invented(self):
        uid = self.target()
        p103 = (await self.post(uid, GRANT, "MP1", "VINTO-P1-03")).json()  # publicado y ofrecido, pero se registra por /api/bobbins
        self.assertEqual((p103["changed"], p103["catalog"]["offered"], p103["catalog"]["enabled_for_capture"], p103["catalog"]["capture_policies"]), (True, True, False, []))
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS",)):
            reb = (await self.post(self.target(sectors_=("BOBINAS", "REBOBINADO")), GRANT, "COPASA", P110)).json()
        self.assertEqual((reb["catalog"]["offered"], reb["catalog"]["enabled_for_capture"], reb["context"]["sector_operational"]), (True, False, False), "concedible aunque el sector no sea operativo; solo se informa")

    async def test_inactive_users_and_users_without_the_sector_may_be_granted_and_the_response_says_so(self):
        """Regla EXISTENTE (no se cambia): grant_machine_form no exige usuario activo ni sector concedido; la concesión queda inerte hasta que ambos existan. Se informa en `context`."""
        inactive = self.target()
        self.connection.execute('UPDATE vinto_master."user" SET active = false WHERE id = %s', (inactive,))
        body = (await self.post(inactive, GRANT, "MP1", P101)).json()
        self.assertEqual((body["changed"], body["context"]["user_active"]), (True, False))
        nosector = self.target(sectors_=())
        body = (await self.post(nosector, GRANT, "MP1", P101)).json()
        self.assertEqual((body["changed"], body["context"]["sector_granted"]), (True, False))
        self.assertEqual((await self.post(inactive, REVOKE, "MP1", P101)).json()["active"], False, "y se puede revocar igual")


class InertGrantTests(Base):
    old_p105 = True

    async def test_a_link_that_only_a_historical_version_has_cannot_be_granted_but_an_inert_grant_can_be_revoked(self):
        uid = self.target()
        reply = await self.post(uid, GRANT, "MP1", P105)  # la v1 (publicada) aún la vincula a MP1, la vigente (v2) no
        self.assertEqual((reply.status, reply.json()["code"]), (409, "PAIR_NOT_OFFERED"))
        machine_id = self.scalar("SELECT id FROM vinto_master.machine WHERE code = 'MP1'")
        form_id = self.scalar("SELECT id FROM vinto_config.form WHERE code = %s", (P105,))
        self.connection.execute("INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id) VALUES (%s,%s,%s)", (uid, machine_id, form_id))  # concesión inerte heredada
        revoked = (await self.post(uid, REVOKE, "MP1", P105)).json()
        self.assertEqual((revoked["changed"], revoked["active"], revoked["catalog"]["offered"], revoked["grant"]["state"]), (True, False, False, "revoked"))
        self.assertEqual((await self.post(uid, REVOKE, "MP1", P105)).json()["changed"], False)


# ---- 5. idempotencia, historial y auditoría --------------------------------------------------------------------------------------------------------

class IdempotencyAndHistoryTests(Base):
    async def test_repeating_a_grant_or_a_revoke_changes_nothing_and_audits_nothing(self):
        uid = self.target()
        first = (await self.post(uid, GRANT, "MP1", P101)).json()
        events = len(self.audit(uid))
        again = (await self.post(uid, GRANT, "MP1", P101)).json()
        self.assertEqual((again["changed"], again["request_id"], again["active"], again["grant"]["id"]), (False, None, True, first["grant"]["id"]))
        self.assertEqual((self.rows(uid), len(self.audit(uid))), (1, events), "ni fila ni evento nuevos")
        self.assertTrue((await self.post(uid, REVOKE, "MP1", P101)).json()["changed"])
        events = len(self.audit(uid))
        twice = (await self.post(uid, REVOKE, "MP1", P101)).json()
        self.assertEqual((twice["changed"], twice["request_id"], twice["active"]), (False, None, False))
        self.assertEqual((self.rows(uid), len(self.audit(uid))), (1, events), "revocar dos veces no genera eventos")

    async def test_revoking_something_never_granted_is_a_quiet_no_op(self):
        uid = self.target()
        body = (await self.post(uid, REVOKE, "MP3", P102)).json()
        self.assertEqual((body["changed"], body["active"], body["grant"], body["request_id"]), (False, False, None, None))
        self.assertEqual((self.rows(uid), self.audit(uid)), (0, []))

    async def test_a_revocation_followed_by_a_grant_creates_a_new_row_and_keeps_the_history(self):
        uid = self.target()
        first = (await self.post(uid, GRANT, "MP1", P101)).json()["grant"]["id"]
        await self.post(uid, REVOKE, "MP1", P101)
        second = (await self.post(uid, GRANT, "MP1", P101)).json()["grant"]["id"]
        self.assertNotEqual(first, second)
        history = (await self.get(f"/api/admin/users/{uid}/grants/history")).json()
        self.assertEqual(sorted(g["state"] for g in history["grants"]), ["active", "revoked"])
        self.assertEqual({g["id"] for g in history["grants"]}, {first, second})
        self.assertEqual([a[0] for a in self.audit(uid)], ["INSERT", "UPDATE", "INSERT"], "alta, baja y alta nueva; ningún DELETE")
        self.assertTrue(all(a[1] == self.admin_id() for a in self.audit(uid)))
        self.assertEqual([a[3] for a in self.audit(uid)], ["machine form grant", "machine form revoke", "machine form grant"])

    async def test_the_five_get_endpoints_reflect_the_changes(self):
        uid = self.target()
        await self.post(uid, GRANT, "MP1", P101)
        await self.post(uid, GRANT, "MP3", P101)
        await self.post(uid, REVOKE, "MP1", P101)
        active = (await self.get(f"/api/admin/users/{uid}/grants")).json()
        self.assertEqual([(g["machine"]["code"], g["state"]) for g in active["grants"]], [("MP3", "active")])
        history = (await self.get(f"/api/admin/users/{uid}/grants/history")).json()
        self.assertEqual((history["total"], sorted((g["machine"]["code"], g["state"]) for g in history["grants"])), (2, [("MP1", "revoked"), ("MP3", "active")]))
        detail = (await self.get(f"/api/admin/users/{uid}")).json()
        self.assertEqual(([p["code"] for p in detail["profiles"]], [s["code"] for s in detail["sectors"]]), (["OPERACION"], ["BOBINAS"]), "el detalle no cambia: ni perfiles ni sectores")
        catalog = (await self.get("/api/admin/catalog")).json()
        self.assertEqual(len([m for s in catalog["sectors"] for m in s["machines"]]), 18)
        self.assertEqual((await self.get("/api/admin/catalog/forms")).status, 200)

    async def test_existing_sector_administration_is_unchanged_and_independent(self):
        uid = self.target(sectors_=())
        reply = await _call("POST", f"/api/admin/users/{uid}/sectors/grant", json_body={"sector_code": "BOBINAS"}, cookie=await self.cookie("ADMIN"), extra_headers=[("origin", ORIGIN)])
        self.assertEqual((reply.status, reply.json()["changed"]), (200, True))
        self.assertEqual(self.rows(uid), 0, "conceder un sector no concede ningún formulario")
        await self.post(uid, GRANT, "MP1", P101)
        reply = await _call("POST", f"/api/admin/users/{uid}/sectors/revoke", json_body={"sector_code": "BOBINAS"}, cookie=await self.cookie("ADMIN"), extra_headers=[("origin", ORIGIN)])
        self.assertEqual((reply.status, reply.json()["changed"]), (200, True))
        self.assertEqual(len(machine_form_grants_for_user(self.connection, uid)), 1, "revocar el sector no revoca la concesión del formulario")


# ---- 6. concurrencia -------------------------------------------------------------------------------------------------------------------------------

class ConcurrencyTests(Base):
    async def test_simultaneous_identical_grants_create_exactly_one_row(self):
        uid = self.target()
        replies = await asyncio.gather(*[self.post(uid, GRANT, "MP1", P101) for _ in range(8)])
        self.assertTrue(all(r.status == 200 for r in replies), [r.text for r in replies if r.status != 200])
        self.assertEqual(sorted(r.json()["changed"] for r in replies), [False] * 7 + [True])
        self.assertEqual(self.rows(uid), 1)
        self.assertEqual([a[0] for a in self.audit(uid)], ["INSERT"])
        changed = next(r.json() for r in replies if r.json()["changed"])
        self.assertEqual(self.audit(uid)[0][2], changed["request_id"], "solo la petición que cambió dejó auditoría, con su propio request_id")

    async def test_simultaneous_revocations_by_two_admins_record_the_one_that_won(self):
        uid = self.target()
        await self.post(uid, GRANT, "MP1", P101)
        replies = await asyncio.gather(*[self.post(uid, REVOKE, "MP1", P101, who="ADMIN" if i % 2 == 0 else "ADMIN2") for i in range(8)])
        self.assertEqual(sorted(r.json()["changed"] for r in replies), [False] * 7 + [True])
        winner = "ADMIN" if [r.json()["changed"] for r in replies].index(True) % 2 == 0 else "ADMIN2"
        self.assertEqual(self.scalar("SELECT revoked_by FROM vinto_master.user_machine_form_grant WHERE user_id = %s", (uid,)), self.admin_id(winner), "revoked_by es el administrador cuya petición ganó")
        self.assertEqual([a[0] for a in self.audit(uid)], ["INSERT", "UPDATE"])

    async def test_mp1_and_mp3_grants_racing_each_other_do_not_interfere_and_a_grant_revoke_race_stays_consistent(self):
        uid = self.target()
        replies = await asyncio.gather(*([self.post(uid, GRANT, "MP1", P101) for _ in range(3)] + [self.post(uid, GRANT, "MP3", P101) for _ in range(3)]))
        self.assertEqual(sorted(r.json()["changed"] for r in replies), [False] * 4 + [True] * 2)
        self.assertEqual(sorted(g.machine_code for g in machine_form_grants_for_user(self.connection, uid)), ["MP1", "MP3"])
        other = self.target()
        replies = await asyncio.gather(*([self.post(other, GRANT, "MP1", P101) for _ in range(4)] + [self.post(other, REVOKE, "MP1", P101) for _ in range(4)]))
        self.assertTrue(all(r.status == 200 for r in replies), [r.text for r in replies if r.status != 200])
        rows = machine_form_grants_for_user(self.connection, other, include_revoked=True)
        self.assertLessEqual(sum(g.active for g in rows), 1, "nunca dos concesiones activas de la misma terna")
        self.assertEqual(len(rows), sum(1 for r in replies[:4] if r.json()["changed"]), "cada alta efectiva es exactamente una fila")
        self.assertTrue(all(g.revoked_by == self.admin_id() for g in rows if not g.active))


# ---- 7. disponibilidad de la base de datos y límites -----------------------------------------------------------------------------------------------

class UnavailabilityAndBoundaryTests(Base):
    async def test_postgres_unavailable_is_a_safe_503(self):
        uid, cookie = self.target(), await self.cookie("ADMIN")
        with patch.object(settings, "database_url", SecretStr("postgresql://nobody:nothing@127.0.0.1:1/none")):
            reply = await _call("POST", f"/api/admin/users/{uid}/{GRANT}", json_body={"machine_code": "MP1", "form_code": P101}, cookie=cookie, extra_headers=[("origin", ORIGIN)])
        self.assertEqual(reply.status, 503)
        for fragment in ("nobody", "nothing", "127.0.0.1", "psycopg", "Traceback"):
            self.assertNotIn(fragment, reply.body.decode())  # el cuerpo (las cabeceras CORS sí llevan el origen permitido)
        self.assertEqual(self.rows(uid), 0)

    async def test_nothing_in_captures_work_orders_bobbins_or_quality_is_touched_or_wired_to_the_grants(self):
        from pathlib import Path
        uid, before = self.target(), self.untouched()
        for action, machine, form in ((GRANT, "MP1", P101), (GRANT, "COPASA", P110), (REVOKE, "MP1", P101), (GRANT, "MP3", P131)):
            await self.post(uid, action, machine, form)
        self.assertEqual(self.untouched(), before, "capturas, órdenes, asignaciones, bobinas y liberaciones de Calidad no cambian")
        app_dir = Path(__file__).resolve().parent.parent / "app"
        consumers = sorted(str(p.relative_to(app_dir)).replace("\\", "/") for p in app_dir.rglob("*.py")
                           if "__pycache__" not in p.parts and ("machine_form_grant" in p.read_text(encoding="utf-8") or "user_machine_form_grant" in p.read_text(encoding="utf-8")))
        self.assertEqual(consumers, ["admin/grants_read.py", "admin/grants_write.py", "admin/router.py", "auth/machine_form_grants.py", "authz/engine.py", "authz/readiness.py"],
                         "solo la administración (lectura, escritura y su router), el propio módulo y el motor de solo lectura app/authz (MF-13-01D.1, sin conectar) conocen las concesiones: ni capturas, ni órdenes, ni bobinas, ni Calidad las consultan todavía")

    async def test_only_the_admin_write_module_imports_the_write_functions(self):
        from pathlib import Path
        app_dir = Path(__file__).resolve().parent.parent / "app"
        import re
        imports_a_writer = re.compile(r"from app\.auth\.machine_form_grants import[^\n]*\b(grant|revoke)_machine_form\b")
        writers = sorted(str(p.relative_to(app_dir)).replace("\\", "/") for p in app_dir.rglob("*.py") if "__pycache__" not in p.parts and imports_a_writer.search(p.read_text(encoding="utf-8")))
        self.assertEqual(writers, ["admin/grants_write.py"], "el SQL de escritura vive solo en machine_form_grants.py; la API lo llama desde un único módulo")


if __name__ == "__main__":
    unittest.main()
