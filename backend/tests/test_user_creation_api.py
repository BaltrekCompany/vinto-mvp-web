"""USR-02: admin-only creation API, exactly one profile, secrets and audit on ephemeral PostgreSQL 17."""
import asyncio
import json
import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from pydantic import SecretStr

from app.auth.service import create_user
from app.auth.passwords import verify_password
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

STATE = {}
ORIGIN = settings.cors_origins[0]
ADMIN = "DATA_BALTREK"


def setUpModule():
    STATE["template"] = build_reference_template("usr02_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class UserCreationAPI(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "usr02")
        cls.connection = connect(cls.database)
        cls.patch_db = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patch_identity = patch.object(settings, "identity_database_url", None)
        cls.patch_db.start()
        cls.patch_identity.start()
        cls.accounts = {}
        for code in ("DATA_BALTREK", "JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"):
            pw = "fixture-" + secrets.token_urlsafe(20)
            created = create_user(cls.connection, username="usr02.actor." + code.lower(),
                                  display_name="USR-02 " + code, profile_code=code, password=pw)
            cls.accounts[code] = (created, pw)
        cls.cookies = {}

    @classmethod
    def tearDownClass(cls):
        cls.patch_identity.stop()
        cls.patch_db.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def cookie(self, code=ADMIN):
        if code not in self.cookies:
            created, password = self.accounts[code]
            reply = await call("POST", "/api/auth/login",
                               json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, reply.text)
            self.cookies[code] = reply.set_cookie_value()
        return self.cookies[code]

    def request_body(self, **overrides):
        body = {
            "username": "new." + uuid4().hex[:12],
            "display_name": "Operador de prueba",
            "profile_code": "OPERACION",
            "password": "admin-defined-" + secrets.token_urlsafe(16),
        }
        body.update(overrides)
        return body

    async def create(self, body, role=ADMIN, origin=ORIGIN):
        headers = [("origin", origin)] if origin is not None else []
        return await call("POST", "/api/admin/users", json_body=body,
                          cookie=await self.cookie(role) if role else None,
                          extra_headers=headers)

    def number(self, table):
        return self.connection.execute("SELECT count(*) FROM " + table).fetchone()[0]

    async def test_active_profile_catalog_from_database_requires_admin(self):
        reply = await call("GET", "/api/admin/profiles", cookie=await self.cookie())
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual([p["code"] for p in reply.json()],
                         ["CALIDAD", "DATA_BALTREK", "JEFATURA", "OPERACION", "SUPERVISION"])
        for role in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"):
            self.assertEqual((await call("GET", "/api/admin/profiles",
                                         cookie=await self.cookie(role))).status, 403)
        self.assertEqual((await call("GET", "/api/admin/profiles")).status, 401)

    async def test_admin_creates_user_without_grants_and_login_without_password_change(self):
        body = self.request_body(username="  NEW.OPERATOR." + uuid4().hex[:6] + "  ",
                                 display_name=" Usuario Operación ")
        response = await self.create(body)
        self.assertEqual(response.status, 201, response.text)
        user = response.json()
        self.assertEqual(user["username"], body["username"].strip().lower())
        self.assertEqual(user["display_name"], "Usuario Operación")
        self.assertEqual((user["active"], user["profiles"], user["sectors"]), (True, ["OPERACION"], []))
        self.assertNotIn("password", response.text.lower())
        self.assertNotIn(body["password"], response.text)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_master.user_profile WHERE user_id=%s",
                                                 (user["id"],)).fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s",
                                                 (user["id"],)).fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id=%s",
                                                 (user["id"],)).fetchone()[0], 0)
        hash_value, must_change = self.connection.execute(
            "SELECT password_hash, must_change FROM vinto_auth.credential WHERE user_id=%s",
            (user["id"],)).fetchone()
        self.assertTrue(hash_value.startswith("$argon2id$"))
        self.assertTrue(verify_password(hash_value, body["password"]))
        self.assertFalse(must_change)
        login = await call("POST", "/api/auth/login",
                           json_body={"username": user["username"], "password": body["password"]})
        self.assertEqual(login.status, 200, login.text)
        self.assertFalse(login.json()["user"]["must_change"])
        listed = await call("GET", "/api/admin/users", cookie=await self.cookie())
        self.assertEqual(listed.status, 200)
        self.assertEqual(len([u for u in listed.json() if u["id"] == user["id"]]), 1)

    async def test_creation_has_actual_administrator_audit_actor(self):
        body = self.request_body(profile_code="CALIDAD")
        user = (await self.create(body)).json()
        audit = self.connection.execute("""
            SELECT actor_id::text, request_id, reason
            FROM vinto_audit.audit_event
            WHERE entity_table='user' AND new_data->>'id'=%s
            ORDER BY id DESC LIMIT 1
        """, (user["id"],)).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual(audit[0], str(self.accounts[ADMIN][0].user_id))
        self.assertTrue(audit[1].startswith("admin-user-create:"))
        self.assertEqual(audit[2], "user creation by create_user")
        text = json.dumps(audit)
        self.assertNotIn(body["password"], text)

    async def test_no_session_and_operational_roles_never_create(self):
        before = self.number('vinto_master."user"')
        body = self.request_body()
        self.assertEqual((await self.create(body, role=None)).status, 401)
        for role in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"):
            self.assertEqual((await self.create(body, role=role)).status, 403, role)
        self.assertEqual(self.number('vinto_master."user"'), before)

    async def test_origin_required_even_with_an_admin_cookie(self):
        before = self.number('vinto_master."user"')
        body = self.request_body()
        for origin in (None, "", "null", "http://evil.example", ORIGIN + ".attacker.example"):
            response = await self.create(body, origin=origin)
            self.assertEqual(response.status, 403, response.text)
        self.assertEqual(self.number('vinto_master."user"'), before)

    async def test_unknown_profile_is_rejected_atomically(self):
        before = self.number('vinto_master."user"')
        response = await self.create(self.request_body(profile_code="NO_EXISTE"))
        self.assertEqual(response.status, 422, response.text)
        self.assertEqual(response.json()["code"], "PROFILE_UNAVAILABLE")
        self.assertEqual(self.number('vinto_master."user"'), before)

    async def test_duplicate_username_returns_conflict_with_no_second_account(self):
        body = self.request_body()
        self.assertEqual((await self.create(body)).status, 201)
        before = self.number('vinto_master."user"')
        duplicate = await self.create({**body, "username": body["username"].upper(), "password": "another-secure-password"})
        self.assertEqual(duplicate.status, 409, duplicate.text)
        self.assertEqual(duplicate.json()["code"], "USERNAME_ALREADY_EXISTS")
        self.assertEqual(self.number('vinto_master."user"'), before)
        self.assertNotIn(body["password"], duplicate.text)

    async def test_invalid_payload_is_redacted_and_does_not_write(self):
        before = self.number('vinto_master."user"')
        secret = "SECRET_MARKER_DO_NOT_REFLECT"
        variants = [
            self.request_body(password="short"),
            self.request_body(username="a b", password=secret),
            self.request_body(extra_role="DATA_BALTREK", password=secret),
            self.request_body(display_name="  ", password=secret),
        ]
        for body in variants:
            response = await self.create(body)
            self.assertEqual(response.status, 422, response.text)
            self.assertNotIn(secret, response.text)
            self.assertNotIn("input", response.text)
        self.assertEqual(self.number('vinto_master."user"'), before)

    async def test_database_rejects_second_profile_with_existing_credential(self):
        body = self.request_body()
        user = (await self.create(body)).json()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.connection.execute(
                "INSERT INTO vinto_master.user_profile (user_id,profile_id) "
                "SELECT %s,id FROM vinto_master.profile WHERE code='CALIDAD'", (user["id"],))
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_master.user_profile WHERE user_id=%s",
            (user["id"],)).fetchone()[0], 1)

    async def test_simultaneous_create_same_username_cannot_duplicate(self):
        body = self.request_body()
        cookie = await self.cookie()
        async def send():
            return await call("POST", "/api/admin/users", json_body=body, cookie=cookie,
                              extra_headers=[("origin", ORIGIN)])
        replies = await asyncio.gather(send(), send())
        self.assertEqual(sorted(r.status for r in replies), [201, 409])
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_auth.credential WHERE lower(username)=%s",
            (body["username"],)).fetchone()[0], 1)
