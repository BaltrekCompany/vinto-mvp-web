"""USR-03: HTTP, database and security regression for admin user editing (isolated PostgreSQL 17)."""
import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from pydantic import SecretStr

from app.auth.service import create_user
from app.auth.passwords import verify_password
from app.auth.grants import grant_sector
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

ORIGIN = settings.cors_origins[0]
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("usr03_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class UserEditAPI(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "usr03")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.identity_patch = patch.object(settings, "identity_database_url", None)
        cls.db_patch.start()
        cls.identity_patch.start()
        cls.admin, cls.admin_password = cls.make_user("DATA_BALTREK")
        cls.jefe, cls.jefe_password = cls.make_user("JEFATURA")
        cls.admin_cookie = None
        cls.jefe_cookie = None

    @classmethod
    def tearDownClass(cls):
        cls.identity_patch.stop()
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def make_user(cls, code="OPERACION", *, sectors=()):
        password = "usr03-pw-" + secrets.token_urlsafe(18)
        created = create_user(cls.connection, username="usr03." + uuid4().hex[:15],
                              display_name="Prueba USR03", profile_code=code,
                              password=password, sectors=sectors)
        return created, password

    async def cookie(self, role="admin"):
        if role == "admin" and self.admin_cookie:
            return self.admin_cookie
        if role == "jefe" and self.jefe_cookie:
            return self.jefe_cookie
        created, password = (self.admin, self.admin_password) if role == "admin" else (self.jefe, self.jefe_password)
        response = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual(response.status, 200, response.text)
        cookie = response.set_cookie_value()
        if role == "admin":
            self.admin_cookie = cookie
        else:
            self.jefe_cookie = cookie
        return cookie

    async def send(self, method, uid, action, body, *, role="admin", origin=ORIGIN):
        path = f"/api/admin/users/{uid}" + ("/reset-password" if action == "reset" else "")
        header = [("origin", origin)] if origin is not None else []
        return await call(method, path, json_body=body,
                          cookie=await self.cookie(role) if role else None, extra_headers=header)

    def scalar(self, sql, args=()):
        return self.connection.execute(sql, args).fetchone()[0]

    def sessions(self, uid):
        return self.scalar("SELECT count(*) FROM vinto_auth.session WHERE user_id=%s AND revoked_at IS NULL", (uid,))

    async def login(self, created, password):
        return await call("POST", "/api/auth/login",
                          json_body={"username": created.username, "password": password})

    async def test_01_name_only_preserves_profile_access_grants_and_sessions(self):
        target, password = self.make_user("OPERACION", sectors=("BOBINAS",))
        old_session = (await self.login(target, password)).cookie_value()
        before_grants = self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,))
        reply = await self.send("PATCH", target.user_id, "edit", {"display_name": " Nuevo Nombre "})
        self.assertEqual(reply.status, 200, reply.text)
        body = reply.json()
        self.assertEqual((body["display_name"], body["profile_code"], body["changed"], body["sessions_revoked"]),
                         ("Nuevo Nombre", "OPERACION", True, 0))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,)), before_grants)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=old_session)).status, 200)
        self.assertEqual((await self.login(target, password)).status, 200)
        audit = self.connection.execute(
            "SELECT actor_id::text,request_id FROM vinto_audit.audit_event WHERE entity_table='user' AND entity_key->>'id'=%s ORDER BY id DESC LIMIT 1",
            (str(target.user_id),)).fetchone()
        self.assertEqual(audit[0], str(self.admin.user_id))
        self.assertEqual(audit[1], body["request_id"])

    async def test_02_profile_change_revokes_sessions_preserves_grants_and_audits(self):
        target, password = self.make_user("OPERACION", sectors=("BOBINAS",))
        cookie1 = (await self.login(target, password)).cookie_value()
        cookie2 = (await self.login(target, password)).cookie_value()
        before_grants = self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,))
        reply = await self.send("PATCH", target.user_id, "edit", {"profile_code": "CALIDAD"})
        self.assertEqual(reply.status, 200, reply.text)
        body = reply.json()
        self.assertEqual((body["profile_code"], body["changed"]), ("CALIDAD", True))
        self.assertGreaterEqual(body["sessions_revoked"], 2)
        self.assertEqual(self.sessions(target.user_id), 0)
        for cookie in (cookie1, cookie2):
            self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 401)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,)), before_grants)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_profile WHERE user_id=%s", (target.user_id,)), 1)
        self.assertEqual((await self.login(target, password)).status, 200)
        last = self.connection.execute(
            "SELECT actor_id::text,request_id FROM vinto_audit.audit_event WHERE entity_table='user_profile' AND entity_key->>'user_id'=%s ORDER BY id DESC LIMIT 1",
            (str(target.user_id),)).fetchone()
        self.assertEqual(last[0], str(self.admin.user_id))
        self.assertEqual(last[1], body["request_id"])

    async def test_03_noop_does_not_revoke_sessions_or_audit(self):
        target, password = self.make_user("OPERACION")
        cookie = (await self.login(target, password)).cookie_value()
        prior = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        reply = await self.send("PATCH", target.user_id, "edit",
                                {"display_name": "Prueba USR03", "profile_code": "OPERACION"})
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual(reply.json()["changed"], False)
        self.assertIsNone(reply.json()["request_id"])
        self.assertEqual(reply.json()["sessions_revoked"], 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), prior)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 200)

    async def test_04_cannot_demote_last_administrator(self):
        reply = await self.send("PATCH", self.admin.user_id, "edit", {"profile_code": "OPERACION"})
        self.assertEqual(reply.status, 409, reply.text)
        self.assertEqual(reply.json()["code"], "LAST_ADMINISTRATOR")
        self.assertEqual(self.scalar(
            "SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id=up.profile_id WHERE up.user_id=%s",
            (self.admin.user_id,)), "DATA_BALTREK")
        self.assertEqual((await call("GET", "/api/admin/users", cookie=await self.cookie())).status, 200)

    async def test_05_demote_admin_when_another_admin_exists(self):
        target, _ = self.make_user("DATA_BALTREK")
        response = await self.send("PATCH", target.user_id, "edit", {"profile_code": "SUPERVISION"})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(response.json()["profile_code"], "SUPERVISION")
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id=up.profile_id JOIN vinto_master.\"user\" u ON u.id=up.user_id WHERE p.code='DATA_BALTREK' AND u.active",
            ()), 1)

    async def test_06_reset_password_revokes_sessions_keeps_username_and_no_change_requirement(self):
        target, old_password = self.make_user("OPERACION", sectors=("BOBINAS",))
        cookie = (await self.login(target, old_password)).cookie_value()
        new_password = "new-secure-password-" + secrets.token_urlsafe(16)
        response = await self.send("POST", target.user_id, "reset", {"password": new_password})
        self.assertEqual(response.status, 200, response.text)
        obj = response.json()
        self.assertEqual((obj["changed"], obj["must_change"]), (True, False))
        self.assertGreaterEqual(obj["sessions_revoked"], 1)
        self.assertNotIn(new_password, response.text)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 401)
        self.assertEqual((await self.login(target, old_password)).status, 401)
        self.assertEqual((await self.login(target, new_password)).status, 200)
        username, hash_value, must_change = self.connection.execute(
            "SELECT username,password_hash,must_change FROM vinto_auth.credential WHERE user_id=%s",
            (target.user_id,)).fetchone()
        self.assertEqual(username, target.username)
        self.assertTrue(hash_value.startswith("$argon2id$"))
        self.assertTrue(verify_password(hash_value, new_password))
        self.assertFalse(must_change)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (target.user_id,)), 1)
        audit = self.connection.execute(
            """SELECT actor_id::text,request_id,old_data,new_data::text
               FROM vinto_audit.audit_event
               WHERE entity_schema='vinto_auth' AND entity_table='credential' AND entity_key->>'user_id'=%s
               ORDER BY id DESC LIMIT 1""", (str(target.user_id),)).fetchone()
        self.assertEqual(audit[0], str(self.admin.user_id))
        self.assertEqual(audit[1], obj["request_id"])
        self.assertIsNone(audit[2])
        self.assertNotIn(new_password, audit[3])
        self.assertNotIn(hash_value, audit[3])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id=%s AND event='password_change' AND request_id=%s",
                                     (target.user_id, obj["request_id"])), 1)

    async def test_07_reset_does_not_activate_inactive_user(self):
        target, _ = self.make_user()
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (target.user_id,))
        response = await self.send("POST", target.user_id, "reset",
                                   {"password": "inactive-reset-" + secrets.token_urlsafe(18)})
        self.assertEqual(response.status, 200, response.text)
        self.assertFalse(self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (target.user_id,)))

    async def test_08_unknown_user_and_invalid_profile(self):
        absent = uuid4()
        self.assertEqual((await self.send("PATCH", absent, "edit", {"display_name": "Valid name"})).status, 404)
        self.assertEqual((await self.send("POST", absent, "reset", {"password": "valid-secret-" + secrets.token_urlsafe(17)})).status, 404)
        target, _ = self.make_user()
        for code in ("BAD_CODE", ""):
            reply = await self.send("PATCH", target.user_id, "edit", {"profile_code": code})
            self.assertEqual(reply.status, 422, reply.text)
        self.assertEqual(self.scalar(
            "SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id=up.profile_id WHERE up.user_id=%s",
            (target.user_id,)), "OPERACION")

    async def test_09_unauthorized_actor_and_origin_are_denied(self):
        target, _ = self.make_user()
        for method, action, body in (("PATCH", "edit", {"profile_code": "CALIDAD"}),
                                     ("POST", "reset", {"password": "secured-secret-" + secrets.token_urlsafe(18)})):
            self.assertEqual((await self.send(method, target.user_id, action, body, role=None)).status, 401)
            self.assertEqual((await self.send(method, target.user_id, action, body, role="jefe")).status, 403)
            for origin in (None, "", "null", "http://invalid.example"):
                self.assertEqual((await self.send(method, target.user_id, action, body, origin=origin)).status, 403)
        self.assertEqual(self.scalar(
            "SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id=up.profile_id WHERE up.user_id=%s",
            (target.user_id,)), "OPERACION")

    async def test_10_invalid_and_secret_payloads_are_not_echoed(self):
        target, _ = self.make_user()
        secret = "SENSITIVE_RESET_SECRET_" + secrets.token_urlsafe(18)
        for body in ({"password": "short"}, {"password": secret, "username": "hijack"}):
            reply = await self.send("POST", target.user_id, "reset", body)
            self.assertEqual(reply.status, 422, reply.text)
            self.assertNotIn(secret, reply.text)
            self.assertNotIn('"input"', reply.text)
        for body in ({}, {"display_name": None}, {"username": "changed"}, {"profile_code": None},
                     {"password": secret}, {"display_name": " "}):
            reply = await self.send("PATCH", target.user_id, "edit", body)
            self.assertEqual(reply.status, 422, reply.text)
        self.assertEqual(self.scalar(
            "SELECT username FROM vinto_auth.credential WHERE user_id=%s", (target.user_id,)), target.username)

    async def test_11_username_immutable_even_via_direct_sql(self):
        target, _ = self.make_user()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute(
                "UPDATE vinto_auth.credential SET username=%s WHERE user_id=%s",
                ("changed." + uuid4().hex[:10], target.user_id))
        self.assertEqual(self.scalar("SELECT username FROM vinto_auth.credential WHERE user_id=%s",
                                     (target.user_id,)), target.username)

    async def test_12_self_reset_revokes_the_administrators_own_session(self):
        current_cookie = await self.cookie()
        new_password = "self-reset-" + secrets.token_urlsafe(21)
        response = await self.send("POST", self.admin.user_id, "reset", {"password": new_password})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual((await call("GET", "/api/admin/users", cookie=current_cookie)).status, 401)
        self.admin_password = new_password
        self.admin_cookie = None
        self.assertEqual((await call("GET", "/api/admin/users", cookie=await self.cookie())).status, 200)

    async def test_13_concurrent_demote_and_cli_deactivate_never_remove_both_admins(self):
        """USR-03 and the preexisting CLI deactivation must serialize on the same lock."""
        from app.admin.user_editing import edit_user
        from app.auth.service import deactivate_user
        other, _ = self.make_user("DATA_BALTREK")
        # Set up exactly two active administrators: the fixture and 'other'.
        barrier = threading.Barrier(2)

        def demote_fixture():
            with connect(self.database) as db:
                barrier.wait(timeout=10)
                try:
                    edit_user(db, target_id=self.admin.user_id, actor_id=self.admin.user_id,
                              profile_code="OPERACION")
                    return "changed"
                except Exception as exc:
                    return type(exc).__name__

        def deactivate_other():
            with connect(self.database) as db:
                barrier.wait(timeout=10)
                try:
                    deactivate_user(db, username=other.username, actor_username=other.username,
                                    reason="USR-03 isolated concurrency test")
                    return "changed"
                except Exception as exc:
                    return type(exc).__name__

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(demote_fixture)
            b = pool.submit(deactivate_other)
            results = [a.result(timeout=20), b.result(timeout=20)]
        count = self.scalar(
            """SELECT count(*)
               FROM vinto_master."user" u
               JOIN vinto_master.user_profile up ON up.user_id=u.id
               JOIN vinto_master.profile p ON p.id=up.profile_id
               WHERE u.active AND p.active AND p.code='DATA_BALTREK'""")
        self.assertEqual(count, 1, results)
        self.assertEqual(results.count("changed"), 1, results)
        self.assertTrue(any(x in ("LastActiveAdministrator", "LastAdministratorError",
                                  "UserNotFoundError") for x in results), results)
