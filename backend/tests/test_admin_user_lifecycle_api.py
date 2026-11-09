"""USR-04: isolated PostgreSQL 17 HTTP and database lifecycle regression."""
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from uuid import uuid4
from unittest.mock import patch

from pydantic import SecretStr

from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

ORIGIN = settings.cors_origins[0]
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("usr04_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class AdminUserLifecycleAPI(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "usr04")
        cls.connection = connect(cls.database)
        cls.database_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.identity_patch = patch.object(settings, "identity_database_url", None)
        cls.database_patch.start()
        cls.identity_patch.start()
        cls.admin, cls.admin_password = cls.make_user("DATA_BALTREK")
        cls.nonadmin, cls.nonadmin_password = cls.make_user("JEFATURA")
        cls.admin_cookie = None

    @classmethod
    def tearDownClass(cls):
        cls.identity_patch.stop()
        cls.database_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def make_user(cls, profile="OPERACION"):
        password = "usr04-test-" + secrets.token_urlsafe(20)
        user = create_user(cls.connection, username="usr04." + uuid4().hex[:16],
                           display_name="Usuario prueba", profile_code=profile, password=password,
                           sectors=("BOBINAS",) if profile == "OPERACION" else ())
        return user, password

    async def login(self, user, password):
        return await call("POST", "/api/auth/login", json_body={"username": user.username, "password": password})

    async def admin_session(self):
        if not self.admin_cookie:
            reply = await self.login(self.admin, self.admin_password)
            self.assertEqual(reply.status, 200, reply.text)
            self.admin_cookie = reply.set_cookie_value()
        return self.admin_cookie

    async def change(self, user_id, action, body=None, cookie="admin", origin=ORIGIN):
        token = await self.admin_session() if cookie == "admin" else cookie
        headers = [("origin", origin)] if origin is not None else []
        return await call("POST", f"/api/admin/users/{user_id}/{action}", json_body=body,
                          cookie=token, extra_headers=headers)

    def scalar(self, query, values=()):
        return self.connection.execute(query, values).fetchone()[0]

    async def test_01_deactivate_revokes_sessions_preserves_user_data_and_audits(self):
        user, password = self.make_user()
        login = await self.login(user, password)
        self.assertEqual(login.status, 200)
        cookie = login.set_cookie_value()
        before = self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (user.user_id,))
        reply = await self.change(user.user_id, "deactivate", {"reason": "Baja autorizada"})
        self.assertEqual(reply.status, 200, reply.text)
        body = reply.json()
        self.assertEqual((body["active"], body["changed"]), (False, True))
        self.assertGreaterEqual(body["sessions_revoked"], 1)
        self.assertEqual(self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (user.user_id,)), False)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (user.user_id,)), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_profile WHERE user_id=%s", (user.user_id,)), 1)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 401)
        self.assertEqual((await self.login(user, password)).status, 401)
        audit = self.connection.execute(
            "SELECT actor_id::text,request_id,reason FROM vinto_audit.audit_event WHERE entity_table='user' AND entity_key->>'id'=%s ORDER BY id DESC LIMIT 1",
            (str(user.user_id),)).fetchone()
        self.assertEqual(audit, (str(self.admin.user_id), body["request_id"], "Baja autorizada"))

    async def test_02_reactivate_requires_new_login_not_old_session(self):
        user, password = self.make_user()
        login = await self.login(user, password)
        old_cookie = login.set_cookie_value()
        self.assertEqual((await self.change(user.user_id, "deactivate", {"reason": "Baja temporal"})).status, 200)
        reply = await self.change(user.user_id, "reactivate", {"reason": "Retorno autorizado"})
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual((reply.json()["active"], reply.json()["changed"], reply.json()["sessions_revoked"]), (True, True, 0))
        self.assertEqual((await call("GET", "/api/auth/me", cookie=old_cookie)).status, 401)
        self.assertEqual((await self.login(user, password)).status, 200)

    async def test_03_idempotent_noop_does_not_audit(self):
        user, _ = self.make_user()
        first = await self.change(user.user_id, "deactivate", {"reason": "Baja"})
        self.assertEqual(first.status, 200)
        count = self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='user' AND entity_key->>'id'=%s", (str(user.user_id),))
        repeat = await self.change(user.user_id, "deactivate", {"reason": "Repeticion"})
        self.assertEqual((repeat.json()["changed"], repeat.json()["request_id"], repeat.json()["sessions_revoked"]), (False, None, 0))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='user' AND entity_key->>'id'=%s", (str(user.user_id),)), count)
        self.assertEqual((await self.change(user.user_id, "reactivate", {"reason": "Alta"})).status, 200)
        repeat = await self.change(user.user_id, "reactivate", {"reason": "Repeticion"})
        self.assertEqual((repeat.json()["changed"], repeat.json()["request_id"]), (False, None))

    async def test_04_cannot_deactivate_last_admin(self):
        reply = await self.change(self.admin.user_id, "deactivate", {"reason": "Intento prohibido"})
        self.assertEqual(reply.status, 409, reply.text)
        self.assertEqual(reply.json()["code"], "LAST_ADMINISTRATOR")
        self.assertTrue(self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (self.admin.user_id,)))

    async def test_05_second_admin_can_be_deactivated(self):
        other, _ = self.make_user("DATA_BALTREK")
        reply = await self.change(other.user_id, "deactivate", {"reason": "Baja segundo admin"})
        self.assertEqual(reply.status, 200, reply.text)
        self.assertFalse(self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (other.user_id,)))

    async def test_06_missing_user_requires_reason_and_forbids_untrusted_input(self):
        self.assertEqual((await self.change(uuid4(), "deactivate", {"reason": "Motivo"})).status, 404)
        user, _ = self.make_user()
        for body in ({}, {"reason": ""}, {"reason": "  "}, {"reason": "x", "actor_id": str(self.admin.user_id)},
                     {"reason": "x" * 501}, {"active": False}, {"reason": None}):
            for action in ("deactivate", "reactivate"):
                response = await self.change(user.user_id, action, body)
                self.assertEqual(response.status, 422, response.text)
                self.assertNotIn('"input"', response.text)
        self.assertTrue(self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (user.user_id,)))

    async def test_07_permission_session_origin_rejected(self):
        user, _ = self.make_user()
        nonadmin = (await self.login(self.nonadmin, self.nonadmin_password)).set_cookie_value()
        for action in ("deactivate", "reactivate"):
            self.assertEqual((await self.change(user.user_id, action, {"reason": "x"}, cookie=None)).status, 401)
            self.assertEqual((await self.change(user.user_id, action, {"reason": "x"}, cookie=nonadmin)).status, 403)
            for origin in (None, "", "null", "https://untrusted.invalid"):
                self.assertEqual((await self.change(user.user_id, action, {"reason": "x"}, origin=origin)).status, 403)
        self.assertTrue(self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (user.user_id,)))

    async def test_08_failed_actor_after_loss_of_permission(self):
        user, _ = self.make_user()
        with patch("app.admin.user_lifecycle.require_actor_authorized", side_effect=__import__("app.admin.errors", fromlist=["ActorNotAuthorized"]).ActorNotAuthorized()):
            response = await self.change(user.user_id, "deactivate", {"reason": "Racing actor"})
        self.assertEqual(response.status, 403, response.text)
        self.assertTrue(self.scalar('SELECT active FROM vinto_master."user" WHERE id=%s', (user.user_id,)))


    async def test_09_reactivate_legacy_inactive_account_never_resurrects_old_cookie(self):
        """USR-04 security gate: legacy/manual inactive users may still have unrevoked tokens."""
        user, password = self.make_user()
        old_cookie = (await self.login(user, password)).set_cookie_value()
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (user.user_id,))
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_auth.session WHERE user_id=%s AND revoked_at IS NULL", (user.user_id,)), 1)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=old_cookie)).status, 401)
        reply = await self.change(user.user_id, "reactivate", {"reason": "USR-04 retorno legado"})
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual((reply.json()["changed"], reply.json()["active"], reply.json()["sessions_revoked"]),
                         (True, True, 1))
        self.assertEqual((await call("GET", "/api/auth/me", cookie=old_cookie)).status, 401)
        self.assertEqual((await self.login(user, password)).status, 200)

    async def test_10_concurrent_api_deactivate_and_profile_demotion_keep_an_admin(self):
        """Serialize USR-04 with USR-03 profile edits using separate PostgreSQL connections."""
        from app.admin.user_editing import edit_user
        from app.admin.user_lifecycle import change_user_state
        from app.admin.errors import ActorNotAuthorized, LastActiveAdministrator

        database = copy_database(STATE["template"], "usr04race")
        try:
            with connect(database) as db:
                admin_a = create_user(
                    db, username="race.a." + uuid4().hex[:12],
                    display_name="Administrador A", profile_code="DATA_BALTREK",
                    password="race-pw-" + secrets.token_urlsafe(18))
                admin_b = create_user(
                    db, username="race.b." + uuid4().hex[:12],
                    display_name="Administrador B", profile_code="DATA_BALTREK",
                    password="race-pw-" + secrets.token_urlsafe(18))
            barrier = threading.Barrier(2)

            def deactivate_b():
                with connect(database) as db:
                    barrier.wait(timeout=10)
                    try:
                        change_user_state(
                            db, target_id=admin_b.user_id, actor_id=admin_a.user_id,
                            active=False, reason="USR-04 concurrent safeguard")
                        return "changed"
                    except (ActorNotAuthorized, LastActiveAdministrator):
                        return "blocked"

            def demote_a():
                with connect(database) as db:
                    barrier.wait(timeout=10)
                    try:
                        edit_user(db, target_id=admin_a.user_id,
                                  actor_id=admin_b.user_id, profile_code="OPERACION")
                        return "changed"
                    except (ActorNotAuthorized, LastActiveAdministrator):
                        return "blocked"

            with ThreadPoolExecutor(max_workers=2) as executor:
                task1 = executor.submit(deactivate_b)
                task2 = executor.submit(demote_a)
                results = [task1.result(timeout=20), task2.result(timeout=20)]
            with connect(database) as db:
                admin_count = db.execute(
                    """SELECT count(*) FROM vinto_master."user" u
                       JOIN vinto_master.user_profile up ON up.user_id=u.id
                       JOIN vinto_master.profile p ON p.id=up.profile_id
                       WHERE u.active AND p.active AND p.code='DATA_BALTREK'"""
                ).fetchone()[0]
            self.assertEqual(admin_count, 1, results)
            self.assertEqual(sorted(results), ["blocked", "changed"])
        finally:
            drop_database(database)


if __name__ == "__main__":
    unittest.main()
