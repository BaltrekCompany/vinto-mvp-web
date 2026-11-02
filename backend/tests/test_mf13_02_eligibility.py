"""MF-13-02: eligibility flags on the availability endpoints.

`eligible` is the authorization engine's decision (profile permission, sector, machine, form, current published version, active
machine-form grant). It does NOT depend on the gate mode (off/observe/enforce); the mode only governs capture execution.
Checked over HTTP against an ephemeral *_test database with the real bundle.
"""

import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import create_user
from app.authz.errors import AuthorizationUnavailable
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

STATE = {}
MODE_SETTINGS = ("authz_central_captures_mode", "authz_bobbin_production_mode", "authz_quality_bobbin_captures_mode", "authz_quality_machine_captures_mode")


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf1302_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def flags(body, key="forms"):
    """{(sector, machine, form): eligible} for a list key ('forms' or 'bobbin_forms')."""
    out = {}
    for sector in body["sectors"]:
        for machine in sector["machines"]:
            for form in machine.get(key) or []:
                out[(sector["code"], machine["code"], form["code"])] = form.get("eligible")
    return out


class EligibilityCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf1302")
        cls.connection = connect(cls.database)
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.actor = create_user(cls.connection, username="mf1302.admin", display_name="Admin", profile_code="DATA_BALTREK", password="pw-" + secrets.token_urlsafe(18), sectors=()).user_id

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def login(self, profile, sectors):
        password = "pw-" + secrets.token_urlsafe(18)
        created = create_user(self.connection, username=f"mf1302.{uuid4().hex[:12]}", display_name=profile.title(), profile_code=profile, password=password, sectors=sectors)
        reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual(reply.status, 200)
        return created.user_id, reply.set_cookie_value()

    def grant(self, user_id, machine, form):
        self.assertTrue(grant_machine_form(self.connection, user_id=user_id, machine_code=machine, form_code=form, actor_id=self.actor))

    def revoke(self, user_id, machine, form):
        self.assertTrue(revoke_machine_form(self.connection, user_id=user_id, machine_code=machine, form_code=form, actor_id=self.actor))

    async def machines(self, cookie):
        reply = await call("GET", "/api/production/machines", cookie=cookie)
        self.assertEqual(reply.status, 200)
        return reply.json()


class ProductionEligibilityTests(EligibilityCase):
    async def test_without_grants_nothing_is_eligible_and_f3_is_listed(self):
        _, cookie = await self.login("OPERACION", ("BOBINAS",))
        body = await self.machines(cookie)
        central, bobbin = flags(body), flags(body, "bobbin_forms")
        self.assertTrue(central and not any(central.values()))
        self.assertIn(("BOBINAS", "MP1", "VINTO-P1-03"), bobbin)
        self.assertFalse(any(bobbin.values()))

    async def test_a_grant_makes_only_that_pair_eligible_and_a_revocation_removes_it_live(self):
        user_id, cookie = await self.login("OPERACION", ("BOBINAS",))
        self.grant(user_id, "MP1", "VINTO-P1-06")
        self.grant(user_id, "MP1", "VINTO-P1-03")
        body = await self.machines(cookie)
        self.assertEqual([k for k, v in flags(body).items() if v], [("BOBINAS", "MP1", "VINTO-P1-06")])
        self.assertEqual([k for k, v in flags(body, "bobbin_forms").items() if v], [("BOBINAS", "MP1", "VINTO-P1-03")])
        self.revoke(user_id, "MP1", "VINTO-P1-06")
        self.revoke(user_id, "MP1", "VINTO-P1-03")
        body = await self.machines(cookie)
        self.assertFalse(any(flags(body).values()) or any(flags(body, "bobbin_forms").values()))

    async def test_a_grant_on_a_machine_outside_the_users_sectors_is_not_listed(self):
        other_id, other_cookie = await self.login("OPERACION", ("REBOBINADO",))
        self.grant(other_id, "MP1", "VINTO-P1-06")
        body = await self.machines(other_cookie)
        self.assertNotIn("BOBINAS", [s["code"] for s in body["sectors"]])
        self.assertFalse(any(v for k, v in flags(body).items() if k[1] == "MP1"))

    async def test_profiles_without_capture_permission_are_never_eligible(self):
        for profile in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            user_id, cookie = await self.login(profile, ("BOBINAS",))
            self.grant(user_id, "MP1", "VINTO-P1-06")
            body = await self.machines(cookie)
            self.assertFalse(any(flags(body).values()), profile)
            self.assertFalse(any(flags(body, "bobbin_forms").values()), profile)

    async def test_eligibility_does_not_depend_on_the_gate_mode(self):
        user_id, cookie = await self.login("OPERACION", ("BOBINAS",))
        self.grant(user_id, "MP1", "VINTO-P1-06")
        expected = None
        for mode in ("off", "observe", "enforce"):
            with contextlib_patch_modes(mode):
                body = await self.machines(cookie)
            seen = (flags(body), flags(body, "bobbin_forms"))
            expected = expected or seen
            self.assertEqual(seen, expected, mode)
        self.assertTrue(expected[0][("BOBINAS", "MP1", "VINTO-P1-06")])

    async def test_the_response_carries_no_internal_reason(self):
        _, cookie = await self.login("OPERACION", ("BOBINAS",))
        text = (await call("GET", "/api/production/machines", cookie=cookie)).text.lower()
        for word in ("reason", "grant", "denied", "kind", "profile", "permission"):
            self.assertNotIn(word, text)

    async def test_401_without_session_and_an_admin_without_sectors_sees_nothing_eligible(self):
        self.assertEqual((await call("GET", "/api/production/machines")).status, 401)
        _, cookie = await self.login("DATA_BALTREK", ())
        body = await self.machines(cookie)
        self.assertFalse(any(flags(body).values()) or any(flags(body, "bobbin_forms").values()))

    async def test_503_when_the_engine_cannot_decide_and_nothing_is_confirmed(self):
        _, cookie = await self.login("OPERACION", ("BOBINAS",))
        with patch("app.authz.availability.authorize", side_effect=AuthorizationUnavailable(RuntimeError('db down'))):
            reply = await call("GET", "/api/production/machines", cookie=cookie)
        self.assertEqual(reply.status, 503)
        self.assertNotIn("eligible", reply.text)


class QualityEligibilityTests(EligibilityCase):
    async def test_bobbin_forms_expose_the_central_bobbin_forms_with_eligibility(self):
        user_id, cookie = await self.login("CALIDAD", ("BOBINAS",))
        body = (await call("GET", "/api/quality/bobbin-forms", cookie=cookie)).json()
        self.assertTrue(flags(body))
        central = flags(body, "bobbin_forms")
        self.assertEqual({k[2] for k in central}, {"VINTO-P1-19", "VINTO-P1-20"})
        self.assertFalse(any(flags(body).values()) or any(central.values()))
        self.grant(user_id, "MP1", "VINTO-P1-19")
        body = (await call("GET", "/api/quality/bobbin-forms", cookie=cookie)).json()
        self.assertEqual([k for k, v in flags(body, "bobbin_forms").items() if v], [("BOBINAS", "MP1", "VINTO-P1-19")])
        self.revoke(user_id, "MP1", "VINTO-P1-19")
        body = (await call("GET", "/api/quality/bobbin-forms", cookie=cookie)).json()
        self.assertFalse(any(flags(body, "bobbin_forms").values()))

    async def test_machine_forms_follow_the_grants(self):
        user_id, cookie = await self.login("CALIDAD", ("BOBINAS",))
        body = (await call("GET", "/api/quality/machine-forms", cookie=cookie)).json()
        listed = flags(body)
        self.assertTrue(listed and not any(listed.values()))
        machine, form = next((k[1], k[2]) for k in listed)
        self.grant(user_id, machine, form)
        body = (await call("GET", "/api/quality/machine-forms", cookie=cookie)).json()
        self.assertEqual([k for k, v in flags(body).items() if v], [(next(iter(listed))[0], machine, form)])

    async def test_other_profiles_cannot_read_the_quality_lists(self):
        _, cookie = await self.login("OPERACION", ("BOBINAS",))
        for path in ("/api/quality/bobbin-forms", "/api/quality/machine-forms"):
            self.assertEqual((await call("GET", path, cookie=cookie)).status, 403, path)
            self.assertEqual((await call("GET", path)).status, 401, path)


class CompatibilityTests(unittest.TestCase):
    def test_without_a_user_the_output_has_no_new_fields(self):
        from app.production_access import production_machines
        connection = connect(copy_database(STATE["template"], "vinto_mf1302c"))
        try:
            body = production_machines(connection, ("BOBINAS",)).model_dump(exclude_none=True)
        finally:
            name = connection.execute("SELECT current_database()").fetchone()[0]
            connection.close()
            drop_database(name)
        text = str(body)
        self.assertNotIn("eligible", text)
        self.assertNotIn("bobbin_forms", text)


def contextlib_patch_modes(mode):
    import contextlib
    stack = contextlib.ExitStack()
    for name in MODE_SETTINGS:
        stack.enter_context(patch.object(settings, name, mode))
    return stack


if __name__ == "__main__":
    unittest.main()
