"""HTTP contract of /api/auth/* (cookie session, error mapping, CORS) and the permission dependencies.

The ASGI app is called directly (no network). The application's DATABASE_URL is patched to an ephemeral
*_test database (verified through connect_test_database), so nothing touches vinto. Passwords are generated
per run.
"""

import json
import logging
import secrets
import unittest
from urllib.parse import quote
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI
from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from app.auth.dependencies import current_user, require_permission
from app.auth.service import AuthenticatedUser, create_user
from app.auth.sessions import hash_token
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.main import app

ALLOWED_ORIGIN = "http://127.0.0.1:8787"
COOKIE = settings.auth_cookie_name
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_api_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class Reply:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def header(self, name):
        values = self.all(name)
        return values[0] if values else None

    def all(self, name):
        return [v.decode("latin-1") for k, v in self.headers if k.decode("latin-1").lower() == name.lower()]

    def json(self):
        return json.loads(self.body)

    def set_cookie(self):
        values = [v for v in self.all("set-cookie") if v.startswith(f"{COOKIE}=")]
        return values[0] if values else None

    def cookie_value(self):
        raw = self.set_cookie()
        return None if raw is None else raw.split(";", 1)[0].split("=", 1)[1]

    def attributes(self):
        raw = self.set_cookie() or ""
        return {part.strip().split("=", 1)[0].lower(): (part.strip().split("=", 1) + [""])[1] for part in raw.split(";")[1:]}

    @property
    def text(self):
        return self.body.decode("utf-8", "replace") + " ".join(f"{k.decode()}:{v.decode()}" for k, v in self.headers)


async def call(method, path, *, json_body=None, cookie=None, origin=None, extra_headers=(), asgi_app=None, raw_body=None):
    body = raw_body if raw_body is not None else (b"" if json_body is None else json.dumps(json_body).encode())
    headers = [(b"host", b"127.0.0.1:8000")] + [(k.encode(), v.encode()) for k, v in extra_headers]
    if body:
        headers += [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    if cookie:
        headers.append((b"cookie", f"{COOKIE}={cookie}".encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
             "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 1234), "root_path": ""}
    sent, delivered = [], False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await (asgi_app or app)(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return Reply(start["status"], list(start["headers"]), payload)


class ApiCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_api")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    def make_user(self, profile="OPERACION", **extra):
        password = "pw-" + secrets.token_urlsafe(18)
        created = create_user(self.connection, username=f"api.{uuid4().hex[:12]}", display_name="Api Fixture", profile_code=profile, password=password)
        return created, password

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def events(self, user_id):
        return [r[0] for r in self.connection.execute("SELECT event FROM vinto_auth.auth_event WHERE user_id=%s ORDER BY id", (user_id,)).fetchall()]

    async def login(self, username, password, **kwargs):
        return await call("POST", "/api/auth/login", json_body={"username": username, "password": password}, **kwargs)


class LoginTests(ApiCase):
    async def test_successful_login_returns_the_user_and_a_session_cookie(self):
        created, password = self.make_user("SUPERVISION")
        reply = await self.login(created.username.upper(), password)
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.json(), {"user": {
            "id": str(created.user_id), "username": created.username, "display_name": "Api Fixture",
            "profiles": ["SUPERVISION"], "permissions": ["assignment.manage", "assignment.read", "catalog.read", "work_order.read"],
            "must_change": False}})
        self.assertEqual(reply.header("cache-control"), "no-store")

    async def test_cookie_flags_in_local(self):
        created, password = self.make_user()
        reply = await self.login(created.username, password)
        attributes = reply.attributes()
        self.assertIsNotNone(reply.set_cookie())
        self.assertIn("httponly", attributes)
        self.assertEqual(attributes["samesite"].lower(), "lax")
        self.assertEqual(attributes["path"], "/")
        self.assertNotIn("secure", attributes)  # APP_ENV=local
        self.assertNotIn("domain", attributes)
        self.assertEqual(attributes["max-age"], str(12 * 3600))
        self.assertGreaterEqual(len(reply.cookie_value()), 43)

    async def test_cookie_is_secure_outside_local(self):
        created, password = self.make_user()
        with patch.object(settings, "app_env", "production"):
            reply = await self.login(created.username, password)
        self.assertEqual(reply.status, 200)
        self.assertIn("secure", reply.attributes())
        self.assertIn("httponly", reply.attributes())

    async def test_max_age_follows_the_configured_ttl(self):
        created, password = self.make_user()
        with patch.object(settings, "auth_session_hours", 2):
            reply = await self.login(created.username, password)
        self.assertEqual(reply.attributes()["max-age"], str(2 * 3600))

    async def test_response_never_contains_the_token_or_its_hash(self):
        created, password = self.make_user()
        reply = await self.login(created.username, password)
        token = reply.cookie_value()
        self.assertNotIn(token, reply.body.decode())
        self.assertNotIn(hash_token(token), reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.session WHERE token_hash=%s", (hash_token(token),)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.session WHERE token_hash=%s", (token,)), 0)

    async def test_wrong_unknown_locked_and_inactive_all_give_the_same_401(self):
        wrong_user, wrong_password = self.make_user()
        locked_user, locked_password = self.make_user()
        inactive_user, inactive_password = self.make_user()
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (inactive_user.user_id,))
        for _ in range(5):
            await self.login(locked_user.username, "wrong-" + secrets.token_urlsafe(8))
        replies = {
            "wrong": await self.login(wrong_user.username, "wrong-" + secrets.token_urlsafe(8)),
            "unknown": await self.login("nobody.here", "wrong-" + secrets.token_urlsafe(8)),
            "locked": await self.login(locked_user.username, locked_password),  # correct password, but locked
            "inactive": await self.login(inactive_user.username, inactive_password),  # correct password, inactive
        }
        self.assertEqual(self.scalar("SELECT locked_until IS NOT NULL FROM vinto_auth.credential WHERE user_id=%s", (locked_user.user_id,)), True)
        for name, reply in replies.items():
            with self.subTest(name):
                self.assertEqual(reply.status, 401)
                self.assertEqual(reply.json(), {"detail": "Credenciales inválidas"})
                self.assertIsNone(reply.set_cookie())
                self.assertIsNone(reply.header("retry-after"))
                self.assertEqual(reply.body, replies["wrong"].body)
                self.assertEqual(sorted(k for k, _ in reply.headers), sorted(k for k, _ in replies["wrong"].headers))

    async def test_malformed_bodies_get_a_generic_422_that_does_not_echo_the_input(self):
        secret = "secret-" + secrets.token_urlsafe(12)
        for body in ({"password": secret}, {"username": "x", "password": secret, "extra": 1}, {"username": 5, "password": secret}):
            with self.subTest(body=list(body)):
                reply = await call("POST", "/api/auth/login", json_body=body)
                self.assertEqual((reply.status, reply.json()), (422, {"detail": "Solicitud inválida"}))
                self.assertNotIn(secret, reply.text)
        reply = await call("POST", "/api/auth/login", raw_body=b"{not json")
        self.assertEqual(reply.status, 422)

    async def test_database_down_gives_a_safe_503(self):
        created, password = self.make_user()
        closed = SecretStr(make_conninfo(database_url(self.database), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed):
            reply = await self.login(created.username, password)
        self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))
        self.assertIsNone(reply.set_cookie())
        for forbidden in ("postgresql://", password, "port=1", "127.0.0.1:1", "psycopg"):
            self.assertNotIn(forbidden, reply.text)

    async def test_login_creates_events_with_a_server_generated_request_id(self):
        created, password = self.make_user()
        await self.login(created.username, "wrong-" + secrets.token_urlsafe(8), extra_headers=[("x-request-id", "client-supplied")])
        await self.login(created.username, password, extra_headers=[("x-request-id", "client-supplied")])
        self.assertEqual(self.events(created.user_id), ["login_fail", "login_ok"])
        request_ids = [r[0] for r in self.connection.execute("SELECT request_id FROM vinto_auth.auth_event WHERE user_id=%s ORDER BY id", (created.user_id,)).fetchall()]
        self.assertEqual(len({str(UUID(r)) for r in request_ids}), 2)  # valid and different UUIDs, never the client's value
        self.assertNotIn("client-supplied", request_ids)

    async def test_failed_login_for_unknown_user_records_an_event_without_user(self):
        before = self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id IS NULL AND event='login_fail'")
        await self.login("ghost.account", "wrong-" + secrets.token_urlsafe(8))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_auth.auth_event WHERE user_id IS NULL AND event='login_fail'"), before + 1)

    async def test_several_logins_create_independent_sessions(self):
        created, password = self.make_user()
        first, second = await self.login(created.username, password), await self.login(created.username, password)
        self.assertNotEqual(first.cookie_value(), second.cookie_value())
        for reply in (first, second):
            self.assertEqual((await call("GET", "/api/auth/me", cookie=reply.cookie_value())).status, 200)


class MeTests(ApiCase):
    async def test_valid_cookie_returns_user_with_profiles_and_permissions(self):
        created, password = self.make_user("CALIDAD")
        self.connection.execute("INSERT INTO vinto_master.user_profile (user_id,profile_id) SELECT %s,id FROM vinto_master.profile WHERE code='SUPERVISION'", (created.user_id,))
        cookie = (await self.login(created.username, password)).cookie_value()
        reply = await call("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(reply.status, 200)
        user = reply.json()["user"]
        self.assertEqual(user["profiles"], ["CALIDAD", "SUPERVISION"])
        self.assertEqual(user["permissions"], sorted({"work_order.read", "assignment.read", "assignment.manage", "quality.capture", "quality.release", "catalog.read"}))
        self.assertEqual(user["id"], str(created.user_id))
        self.assertEqual(reply.header("cache-control"), "no-store")

    async def test_missing_random_expired_revoked_and_inactive_all_give_the_same_401(self):
        created, password = self.make_user()
        revoked_cookie = (await self.login(created.username, password)).cookie_value()
        await call("POST", "/api/auth/logout", cookie=revoked_cookie)
        inactive, inactive_password = self.make_user()
        inactive_cookie = (await self.login(inactive.username, inactive_password)).cookie_value()
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (inactive.user_id,))
        expired_token = secrets.token_urlsafe(32)
        self.connection.execute(
            """INSERT INTO vinto_auth.session (user_id,token_hash,created_at,expires_at) VALUES
               (%s,%s,clock_timestamp()-interval '2 hours',clock_timestamp()-interval '1 hour')""", (created.user_id, hash_token(expired_token)))
        for name, cookie in {"missing": None, "random": secrets.token_urlsafe(32), "expired": expired_token, "revoked": revoked_cookie,
                             "inactive user": inactive_cookie, "garbage": "x" * 400}.items():
            with self.subTest(name):
                reply = await call("GET", "/api/auth/me", cookie=cookie)
                self.assertEqual((reply.status, reply.json()), (401, {"detail": "No autenticado"}))

    async def test_me_does_not_extend_the_expiry(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        before = self.scalar("SELECT expires_at FROM vinto_auth.session WHERE token_hash=%s", (hash_token(cookie),))
        await call("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(self.scalar("SELECT expires_at FROM vinto_auth.session WHERE token_hash=%s", (hash_token(cookie),)), before)

    async def test_database_down_gives_a_safe_503_on_me(self):
        closed = SecretStr(make_conninfo(database_url(self.database), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed):
            reply = await call("GET", "/api/auth/me", cookie=secrets.token_urlsafe(32))
        self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))


class LogoutTests(ApiCase):
    async def test_valid_logout_revokes_the_session_and_clears_the_cookie(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        reply = await call("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual((reply.status, reply.body), (204, b""))
        self.assertIsNotNone(self.scalar("SELECT revoked_at FROM vinto_auth.session WHERE token_hash=%s", (hash_token(cookie),)))
        cleared = reply.set_cookie()
        self.assertTrue(cleared.startswith(f'{COOKIE}=""') or cleared.startswith(f"{COOKIE}=;"), cleared)
        self.assertEqual(reply.attributes()["max-age"], "0")
        self.assertIn("httponly", reply.attributes())
        self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 401)
        self.assertEqual(self.events(created.user_id), ["login_ok", "logout"])

    async def test_logout_is_idempotent_and_works_without_a_valid_cookie(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        replies = [await call("POST", "/api/auth/logout", cookie=cookie), await call("POST", "/api/auth/logout", cookie=cookie),
                   await call("POST", "/api/auth/logout"), await call("POST", "/api/auth/logout", cookie=secrets.token_urlsafe(32)),
                   await call("POST", "/api/auth/logout", cookie="x" * 400)]
        self.assertEqual([r.status for r in replies], [204] * 5)
        for reply in replies:
            self.assertIsNotNone(reply.set_cookie())  # the cookie is always cleared
        self.assertEqual(self.events(created.user_id).count("logout"), 1)

    async def test_logout_leaves_other_sessions_of_the_user(self):
        created, password = self.make_user()
        first = (await self.login(created.username, password)).cookie_value()
        second = (await self.login(created.username, password)).cookie_value()
        await call("POST", "/api/auth/logout", cookie=first)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=first)).status, 401)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=second)).status, 200)

    def assert_cookie_cleared(self, reply):
        cleared = reply.set_cookie()
        self.assertIsNotNone(cleared, "logout must always emit a Set-Cookie that deletes the cookie")
        self.assertTrue(cleared.startswith(f'{COOKIE}=""') or cleared.startswith(f"{COOKIE}=;"), cleared)
        self.assertEqual(reply.attributes()["max-age"], "0")
        self.assertEqual(reply.attributes()["path"], "/")
        self.assertIn("httponly", reply.attributes())

    async def test_valid_logout_is_204_revokes_and_clears_the_cookie(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        reply = await call("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual((reply.status, reply.body), (204, b""))
        self.assert_cookie_cleared(reply)
        self.assertIsNotNone(self.scalar("SELECT revoked_at FROM vinto_auth.session WHERE token_hash=%s", (hash_token(cookie),)))

    async def test_logout_without_cookie_is_204_and_clears_the_cookie_even_if_the_database_is_down(self):
        for down in (False, True):
            with self.subTest(database_down=down):
                closed = SecretStr(make_conninfo(database_url(self.database), host="127.0.0.1", port=1))
                with patch.object(settings, "database_url", closed if down else settings.database_url):
                    reply = await call("POST", "/api/auth/logout")
                self.assertEqual((reply.status, reply.body), (204, b""))
                self.assert_cookie_cleared(reply)  # nothing to revoke, so PostgreSQL is not needed

    async def test_logout_with_an_invalid_cookie_is_204_and_clears_the_cookie(self):
        for cookie in (secrets.token_urlsafe(32), "x" * 400, "garbage value"):
            with self.subTest(cookie=cookie[:12]):
                reply = await call("POST", "/api/auth/logout", cookie=cookie)
                self.assertEqual((reply.status, reply.body), (204, b""))
                self.assert_cookie_cleared(reply)

    async def test_logout_with_postgres_down_is_503_but_still_clears_the_cookie(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        closed = SecretStr(make_conninfo(database_url(self.database), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed):
            reply = await call("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))
        self.assert_cookie_cleared(reply)
        for forbidden in (cookie, hash_token(cookie), "postgresql://", "psycopg", "port=1"):
            self.assertNotIn(forbidden, reply.text.replace(f'{COOKIE}=""', ""))
        # The server-side session could not be revoked: it is still alive, and no false logout was recorded.
        self.assertIsNone(self.scalar("SELECT revoked_at FROM vinto_auth.session WHERE token_hash=%s", (hash_token(cookie),)))
        self.assertEqual(self.events(created.user_id), ["login_ok"])
        self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 200)  # documented limitation until expires_at

    async def test_logout_with_a_postgres_error_during_revocation_is_503_clears_the_cookie_and_logs_no_logout(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        with patch("app.auth.router.revoke_session", side_effect=psycopg.OperationalError("connection lost: password=secret-detail")):
            reply = await call("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))
        self.assert_cookie_cleared(reply)
        self.assertNotIn("secret-detail", reply.text)
        self.assertNotIn("connection lost", reply.text)
        self.assertEqual(self.events(created.user_id), ["login_ok"])  # no logout without a real revocation
        self.assertIsNone(self.scalar("SELECT revoked_at FROM vinto_auth.session WHERE token_hash=%s", (hash_token(cookie),)))


class CorsTests(ApiCase):
    async def test_allowed_origin_on_get_and_post_with_credentials(self):
        get_reply = await call("GET", "/health", origin=ALLOWED_ORIGIN)
        self.assertEqual(get_reply.header("access-control-allow-origin"), ALLOWED_ORIGIN)
        self.assertEqual(get_reply.header("access-control-allow-credentials"), "true")
        created, password = self.make_user()
        post_reply = await self.login(created.username, password, origin=ALLOWED_ORIGIN)
        self.assertEqual(post_reply.status, 200)
        self.assertEqual(post_reply.header("access-control-allow-origin"), ALLOWED_ORIGIN)
        self.assertEqual(post_reply.header("access-control-allow-credentials"), "true")

    async def test_preflight_for_post_allows_credentials_and_content_type(self):
        reply = await call("OPTIONS", "/api/auth/login", origin=ALLOWED_ORIGIN, extra_headers=[
            ("access-control-request-method", "POST"), ("access-control-request-headers", "content-type")])
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.header("access-control-allow-origin"), ALLOWED_ORIGIN)
        self.assertEqual(reply.header("access-control-allow-credentials"), "true")
        self.assertIn("POST", reply.header("access-control-allow-methods"))
        self.assertIn("Content-Type", reply.header("access-control-allow-headers"))

    async def test_preflight_rejects_other_headers_and_methods(self):
        header_reply = await call("OPTIONS", "/api/auth/login", origin=ALLOWED_ORIGIN, extra_headers=[
            ("access-control-request-method", "POST"), ("access-control-request-headers", "authorization")])
        self.assertEqual(header_reply.status, 400)
        method_reply = await call("OPTIONS", "/api/auth/login", origin=ALLOWED_ORIGIN, extra_headers=[("access-control-request-method", "DELETE")])
        self.assertEqual(method_reply.status, 400)

    async def test_other_origins_get_no_cors_headers(self):
        for origin in ("http://example.com", "http://127.0.0.1:9999", "null"):
            with self.subTest(origin):
                reply = await call("GET", "/health", origin=origin)
                # Starlette may still emit Allow-Credentials, but without Allow-Origin the browser rejects the response.
                self.assertIsNone(reply.header("access-control-allow-origin"))
                preflight = await call("OPTIONS", "/api/auth/login", origin=origin, extra_headers=[("access-control-request-method", "POST")])
                self.assertIsNone(preflight.header("access-control-allow-origin"))

    async def test_wildcards_never_appear_alongside_credentials(self):
        replies = [await call("GET", "/health", origin=ALLOWED_ORIGIN),
                   await call("OPTIONS", "/api/auth/login", origin=ALLOWED_ORIGIN, extra_headers=[
                       ("access-control-request-method", "POST"), ("access-control-request-headers", "content-type")])]
        for reply in replies:
            for name in ("access-control-allow-origin", "access-control-allow-methods", "access-control-allow-headers"):
                self.assertNotIn("*", reply.header(name) or "", name)
        self.assertNotIn("*", settings.cors_origins)


class SecurityTests(ApiCase):
    async def test_no_response_exposes_passwords_hashes_or_token_hashes(self):
        created, password = self.make_user()
        stored_hash = self.scalar("SELECT password_hash FROM vinto_auth.credential WHERE user_id=%s", (created.user_id,))
        wrong = "wrong-" + secrets.token_urlsafe(8)
        replies = [await self.login(created.username, wrong), await self.login("ghost.user", wrong)]
        login = await self.login(created.username, password)
        cookie = login.cookie_value()
        replies += [login, await call("GET", "/api/auth/me", cookie=cookie), await call("POST", "/api/auth/logout", cookie=cookie),
                    await call("GET", "/api/auth/me", cookie=cookie)]
        token_hash = hash_token(cookie)
        for reply in replies:
            text = reply.text
            for secret in (password, wrong, stored_hash, token_hash, "password_hash", "token_hash", "argon2"):
                self.assertNotIn(secret, text)
            self.assertNotIn(cookie, reply.body.decode())  # the token only ever travels in Set-Cookie

    async def test_logs_never_contain_passwords_or_tokens(self):
        created, password = self.make_user()
        wrong = "wrong-" + secrets.token_urlsafe(8)
        records = []

        class Collector(logging.Handler):
            def emit(self, record):
                records.append(record)

        collector, root = Collector(level=logging.DEBUG), logging.getLogger()
        previous_level = root.level
        root.addHandler(collector)
        root.setLevel(logging.DEBUG)
        try:
            login = await self.login(created.username, password)
            await self.login(created.username, wrong)
            await call("GET", "/api/auth/me", cookie=login.cookie_value())
            await call("POST", "/api/auth/logout", cookie=login.cookie_value())
        finally:
            root.removeHandler(collector)
            root.setLevel(previous_level)
        token = login.cookie_value()
        stored_hash = self.scalar("SELECT password_hash FROM vinto_auth.credential WHERE user_id=%s", (created.user_id,))
        text = " ".join(f"{r.name} {r.getMessage()} {r.args!r}" for r in records)
        for secret in (password, wrong, token, hash_token(token), stored_hash):
            self.assertNotIn(secret, text)

    async def test_events_for_login_failure_and_logout(self):
        created, password = self.make_user()
        await self.login(created.username, "wrong-" + secrets.token_urlsafe(8))
        cookie = (await self.login(created.username, password)).cookie_value()
        await call("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual(self.events(created.user_id), ["login_fail", "login_ok", "logout"])

    async def test_no_audit_event_in_vinto_auth_and_no_secret_in_audit(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        await call("POST", "/api/auth/logout", cookie=cookie)
        audit = " ".join(f"{o} {n}" for o, n in self.connection.execute("SELECT old_data::text,new_data::text FROM vinto_audit.audit_event").fetchall())
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_schema='vinto_auth'"), 0)
        for secret in (password, cookie, hash_token(cookie)):
            self.assertNotIn(secret, audit)

    async def test_existing_routes_keep_their_behaviour(self):
        reply = await call("GET", "/api/captures/count")  # missing front: FastAPI's standard 422 body is preserved
        self.assertEqual(reply.status, 422)
        self.assertIn("detail", reply.json())
        self.assertEqual((await call("GET", "/health")).json(), {"status": "ok"})


class DependencyTests(ApiCase):
    @classmethod
    def build_app(cls):
        probe = FastAPI()

        @probe.get("/whoami")
        def whoami(user: AuthenticatedUser = Depends(current_user)):
            return {"username": user.username}

        @probe.get("/manage-orders")
        def manage(user: AuthenticatedUser = Depends(require_permission("work_order.manage"))):
            return {"ok": user.username}

        @probe.get("/capture")
        def capture(user: AuthenticatedUser = Depends(require_permission("production.capture"))):
            return {"ok": user.username}

        return probe

    async def asserted(self, path, cookie, status):
        reply = await call("GET", path, cookie=cookie, asgi_app=self.build_app())
        self.assertEqual(reply.status, status, (path, reply.body))
        return reply

    async def test_current_user_with_a_valid_session(self):
        created, password = self.make_user()
        cookie = (await self.login(created.username, password)).cookie_value()
        self.assertEqual((await self.asserted("/whoami", cookie, 200)).json(), {"username": created.username})

    async def test_current_user_without_a_valid_session_is_401(self):
        for cookie in (None, secrets.token_urlsafe(32)):
            reply = await self.asserted("/whoami", cookie, 401)
            self.assertEqual(reply.json(), {"detail": "No autenticado"})

    async def test_require_permission_allows_and_forbids(self):
        jefatura, jefatura_password = self.make_user("JEFATURA")
        operator, operator_password = self.make_user("OPERACION")
        admin, admin_password = self.make_user("DATA_BALTREK")
        jefatura_cookie = (await self.login(jefatura.username, jefatura_password)).cookie_value()
        operator_cookie = (await self.login(operator.username, operator_password)).cookie_value()
        admin_cookie = (await self.login(admin.username, admin_password)).cookie_value()
        await self.asserted("/manage-orders", jefatura_cookie, 200)
        forbidden = await self.asserted("/manage-orders", operator_cookie, 403)
        self.assertEqual(forbidden.json(), {"detail": "Permiso insuficiente"})
        await self.asserted("/capture", operator_cookie, 200)
        await self.asserted("/capture", admin_cookie, 403)  # DATA_BALTREK cannot operate the plant
        await self.asserted("/manage-orders", None, 401)  # no session wins over permission

    async def test_unknown_permission_fails_when_the_route_is_defined(self):
        with self.assertRaises(ValueError):
            require_permission("work_order.delete")


if __name__ == "__main__":
    unittest.main()
