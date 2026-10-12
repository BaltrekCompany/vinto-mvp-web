"""GET /api/captures/count (M1-C2-a): session + catalog.read + per-sector scope, with the original response contract.

Runs through the real ASGI app against ephemeral *_test databases. The synthetic REBOBINADO sector of the template is enabled with patch.object ONLY
inside a test. Nothing here touches the DEV database or registers real captures.
"""

import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from app import sectors
from app.auth import permissions
from app.auth.grants import revoke_sector
from app.config import settings

try:
    import test_f3_bobbins_api as f3
    import test_sector_authorization as sa
    from test_assignments_api import call, order_body
    from test_quality_capture_api import P119_VALUES
    from test_sector_authorization import BOTH, FUTURE_MACHINE, FUTURE_SECTOR, F6_VALUES, setUpModule, tearDownModule  # noqa: F401
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    import tests.test_sector_authorization as sa
    from tests.test_assignments_api import call, order_body
    from tests.test_quality_capture_api import P119_VALUES
    from tests.test_sector_authorization import BOTH, FUTURE_MACHINE, FUTURE_SECTOR, F6_VALUES, setUpModule, tearDownModule  # noqa: F401

FRONTS = ("Bobinas", "Rebobinado", "Conversión", "Calidad")
PROFILES = ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK")


class CountCase(sa.SectorAuthorizationCase):
    async def count(self, front, cookie, extra=""):
        return await call("GET", "/api/captures/count?" + urlencode({"front": front}) + extra, cookie=cookie)

    async def counts_of(self, cookie):
        out = {}
        for front in FRONTS:
            reply = await self.count(front, cookie)
            self.assertEqual(reply.status, 200, f"{front}: {reply.status} {reply.body[:120]!r}")
            out[front] = reply.json()["count"]
        return out

    def expected(self, codes, area=None):
        """Independent SQL oracle: captures of machines of those sector codes (optionally only quality-area forms)."""
        extra = " AND f.area = 'quality'" if area else ""
        return self.scalar("""SELECT count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version f ON f.id = c.form_version_id
                              JOIN vinto_master.machine m ON m.id = c.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
                              WHERE s.code = ANY(%s)""" + extra, (list(codes),))

    async def chain(self, jefatura, supervision, operacion, calidad, machine="MP1"):
        """OT -> assignment -> F6 + F3 bobbin -> P1-19 quality capture, as one team. Returns the number of captures it created (3)."""
        body = order_body("MP1") if machine == "MP1" else {**order_body("MP1"), "machine_code": machine}
        order = (await call("POST", "/api/work-orders", json_body=body, cookie=jefatura)).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=jefatura)).json()
        activated = await call("POST", "/api/assignments/activate", cookie=supervision,
                               json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(activated.status, 201)
        assignment = activated.json()["assignment"]
        f6 = await call("POST", "/api/captures", cookie=operacion, json_body={"capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"],
                                                                                 "device_key": str(uuid4()), "values": dict(F6_VALUES)})
        self.assertEqual(f6.status, 201)
        bobbin = await call("POST", "/api/bobbins", cookie=operacion, json_body=self.payload(assignment))
        self.assertEqual(bobbin.status, 201)
        quality = await call("POST", f"/api/quality/bobbins/{bobbin.json()['bobbin']['id']}/captures", cookie=calidad,
                             json_body={"capture_id": str(uuid4()), "form_code": "VINTO-P1-19", "device_key": str(uuid4()), "values": dict(P119_VALUES)})
        self.assertEqual(quality.status, 201)
        return 3


class AuthenticationAndPermissionTests(CountCase):
    async def test_no_session_is_401_for_every_front_and_writes_nothing(self):
        before = self.counts()
        for front in FRONTS:
            reply = await self.count(front, None)
            self.assertEqual((reply.status, reply.json()), (401, {"detail": "No autenticado"}), front)
        self.assertEqual((await self.count("Bobinas", "not-a-real-session")).status, 401)
        self.assertEqual(self.counts(), before)

    async def test_a_valid_session_without_catalog_read_is_403(self):
        cookie = await self.cookie("OPERACION")
        self.assertEqual((await self.count("Bobinas", cookie)).status, 200)
        reduced = {**permissions.PROFILE_PERMISSIONS, "OPERACION": frozenset({"production.capture", "work_order.read", "assignment.read"})}
        with patch.dict(permissions.PROFILE_PERMISSIONS, reduced):
            reply = await self.count("Bobinas", cookie)
            self.assertEqual((reply.status, reply.json()), (403, {"detail": "Permiso insuficiente"}))

    async def test_catalog_read_only_reads_statistics_and_grants_nothing_else(self):
        self.assertTrue(all("catalog.read" in permissions.PROFILE_PERMISSIONS[p] for p in PROFILES))
        for profile in PROFILES:
            cookie = await self.cookie(profile)
            self.assertEqual((await self.count("Bobinas", cookie)).status, 200, profile)
        # the count permission does not unlock any capture/OT operation for a profile that lacks it
        before = self.counts()
        self.assertEqual((await call("POST", "/api/captures", json_body={}, cookie=await self.cookie("JEFATURA"))).status, 403)
        self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=await self.cookie("OPERACION"))).status, 403)
        self.assertEqual(self.counts(), before)

    async def test_the_contract_and_front_validation_are_kept(self):
        cookie = await self.cookie("JEFATURA")
        for front in FRONTS:
            reply = await self.count(front, cookie)
            self.assertEqual(list(reply.json()), ["front", "count", "source"], front)
            self.assertEqual((reply.status, reply.json()["front"], reply.json()["source"], isinstance(reply.json()["count"], int)), (200, front, "database", True))
        for query in ("", "front=Inventado", "front=bobinas", "front=BOBINAS"):
            reply = await call("GET", "/api/captures/count" + ("?" + query if query else ""), cookie=cookie)
            self.assertIn(reply.status, (422,), query)
        self.assertEqual((await call("POST", "/api/captures/count?front=Bobinas", cookie=cookie)).status, 405)


class CountSemanticsTests(CountCase):
    async def test_bobinas_calidad_and_other_fronts_match_an_independent_sql_count(self):
        await self.chain(await self.cookie("JEFATURA"), await self.cookie("SUPERVISION"), await self.cookie("OPERACION"), await self.cookie("CALIDAD"))
        for profile in PROFILES:  # all five profiles hold BOBINAS in this fixture
            counts = await self.counts_of(await self.cookie(profile))
            self.assertEqual(counts["Bobinas"], self.expected(["BOBINAS"]), profile)
            self.assertEqual(counts["Calidad"], self.expected(["BOBINAS"], "quality"), profile)
            self.assertEqual((counts["Rebobinado"], counts["Conversión"]), (0, 0), profile)
        self.assertGreaterEqual(counts["Bobinas"], 3)
        self.assertGreaterEqual(counts["Calidad"], 1)
        self.assertGreater(counts["Bobinas"], counts["Calidad"], "Bobinas keeps counting every capture of its machines (F6, F3 and quality), as before")

    async def test_a_user_without_grants_gets_zero_everywhere(self):
        await self.chain(await self.cookie("JEFATURA"), await self.cookie("SUPERVISION"), await self.cookie("OPERACION"), await self.cookie("CALIDAD"))
        self.assertGreater(self.expected(["BOBINAS"]), 0)
        for profile in ("JEFATURA", "CALIDAD", "DATA_BALTREK"):
            _, cookie = await self.new_user(profile)
            self.assertEqual(await self.counts_of(cookie), {front: 0 for front in FRONTS}, profile)

    async def test_a_grant_to_a_non_operational_sector_reveals_nothing(self):
        await self.chain(await self.cookie("JEFATURA"), await self.cookie("SUPERVISION"), await self.cookie("OPERACION"), await self.cookie("CALIDAD"))
        _, cookie = await self.new_user("JEFATURA", FUTURE_SECTOR)
        self.assertEqual(await self.counts_of(cookie), {front: 0 for front in FRONTS})

    async def test_sectors_are_counted_separately_and_quality_is_filtered_by_sector(self):
        with patch.object(sectors, "_OPERATIONAL", BOTH):
            bob = {p: await self.cookie(p) for p in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD")}
            reb = {p: (await self.new_user(p, FUTURE_SECTOR))[1] for p in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD")}
            await self.chain(bob["JEFATURA"], bob["SUPERVISION"], bob["OPERACION"], bob["CALIDAD"])
            await self.chain(reb["JEFATURA"], reb["SUPERVISION"], reb["OPERACION"], reb["CALIDAD"], machine=FUTURE_MACHINE)
            bob_total, reb_total = self.expected(["BOBINAS"]), self.expected([FUTURE_SECTOR])
            bob_quality, reb_quality = self.expected(["BOBINAS"], "quality"), self.expected([FUTURE_SECTOR], "quality")
            self.assertGreater(reb_total, 0)
            self.assertGreater(reb_quality, 0)
            only_bob = await self.counts_of(bob["CALIDAD"])
            only_reb = await self.counts_of(reb["CALIDAD"])
            self.assertEqual(only_bob, {"Bobinas": bob_total, "Rebobinado": 0, "Conversión": 0, "Calidad": bob_quality})
            self.assertEqual(only_reb, {"Bobinas": 0, "Rebobinado": reb_total, "Conversión": 0, "Calidad": reb_quality})
            both = (await self.new_user("JEFATURA", *BOTH))[1]
            self.assertEqual(await self.counts_of(both), {"Bobinas": bob_total, "Rebobinado": reb_total, "Conversión": 0, "Calidad": bob_quality + reb_quality})
            # once the sector is not operational any more, the very same user sees nothing of it
        self.assertEqual(await self.counts_of(both), {"Bobinas": bob_total, "Rebobinado": 0, "Conversión": 0, "Calidad": bob_quality})

    async def test_the_client_cannot_widen_its_scope(self):
        await self.chain(await self.cookie("JEFATURA"), await self.cookie("SUPERVISION"), await self.cookie("OPERACION"), await self.cookie("CALIDAD"))
        _, nobody = await self.new_user("JEFATURA")
        for extra in ("&sector=BOBINAS", "&sectors=BOBINAS", "&machine=MP1", "&sector_id=1"):
            reply = await self.count("Bobinas", nobody, extra)
            self.assertEqual((reply.status, reply.json()["count"]), (200, 0), extra)
        reply = await call("GET", "/api/captures/count?front=Bobinas", cookie=nobody, extra_headers=[("X-Sectors", "BOBINAS"), ("X-Sector", "BOBINAS")])
        self.assertEqual(reply.json()["count"], 0)
        reply = await call("GET", "/api/captures/count?front=Bobinas", cookie="BOBINAS," + await self.cookie("JEFATURA"))
        self.assertEqual(reply.status, 401)

    async def test_revoking_a_grant_applies_to_the_next_request(self):
        await self.chain(await self.cookie("JEFATURA"), await self.cookie("SUPERVISION"), await self.cookie("OPERACION"), await self.cookie("CALIDAD"))
        created, cookie = await self.new_user("CALIDAD", "BOBINAS")
        self.assertGreater((await self.count("Bobinas", cookie)).json()["count"], 0)
        revoke_sector(self.connection, user_id=created.user_id, sector_code="BOBINAS")
        self.assertEqual((await self.count("Bobinas", cookie)).json()["count"], 0)

    async def test_counting_writes_no_business_data(self):
        await self.chain(await self.cookie("JEFATURA"), await self.cookie("SUPERVISION"), await self.cookie("OPERACION"), await self.cookie("CALIDAD"))
        before = (self.counts(), self.audit_count(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event"))
        for profile in PROFILES:
            await self.counts_of(await self.cookie(profile))
        self.assertEqual((self.counts(), self.audit_count(), self.scalar("SELECT count(*) FROM vinto_audit.audit_event")), before)

    async def test_the_query_is_read_only_and_filters_by_sector_code(self):
        from app.captures import capture_count_query
        for front in FRONTS:
            sql, params = capture_count_query(front, ("BOBINAS",))
            self.assertIn("s.code = ANY(%s)", sql)
            self.assertNotIn("s.name", sql)
            self.assertIn(["BOBINAS"], params)
        self.assertIn("JOIN vinto_master.machine m ON m.id = c.machine_id", capture_count_query("Calidad", ("BOBINAS",))[0])  # Calidad is not global any more
        with self.assertRaises(sectors.SectorConfigError):
            capture_count_query("Bobinas", None)  # no permissive default
        with self.assertRaises(TypeError):
            capture_count_query("Bobinas")  # type: ignore[call-arg]


class TransportTests(unittest.IsolatedAsyncioTestCase):
    """503 and CORS/cookie behaviour that do not need a populated database."""

    async def test_postgres_unavailable_is_a_safe_503_with_cors(self):
        closed = SecretStr(make_conninfo(settings.database_url.get_secret_value(), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed):
            for origin, allowed in (("http://127.0.0.1:8787", True), ("http://example.com", False)):
                reply = await call("GET", "/api/captures/count?front=Bobinas", extra_headers=[("origin", origin)])
                self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))
                self.assertNotIn("password", reply.text.lower())
                self.assertEqual(any(k.decode().lower() == "access-control-allow-origin" for k, _ in reply.headers), allowed, origin)

    async def test_cors_allows_credentials_only_for_explicit_origins(self):
        from app.main import app
        middleware = [m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"][0]
        self.assertIs(middleware.kwargs["allow_credentials"], True)
        self.assertNotIn("*", middleware.kwargs["allow_origins"])
        self.assertEqual(settings.auth_cookie_name, "vinto_session")


class ConnectionTests(CountCase):
    async def test_one_connection_per_request_is_used_for_session_and_count_and_is_always_closed(self):
        import app.database as database
        opened = []
        real_open = database.open_connection

        def tracking_open():
            connection = real_open()
            opened.append(connection)
            return connection

        with patch.object(database, "open_connection", tracking_open):
            cookie = await self.cookie("JEFATURA")
            opened.clear()
            self.assertEqual((await self.count("Bobinas", cookie)).status, 200)  # session (last_seen_at update) + read-only count
            self.assertEqual(len(opened), 1, "the count reuses the request connection; there is no second independent connection")
            self.assertEqual((await self.count("Bobinas", None)).status, 401)
            self.assertEqual((await self.count("Inventado", cookie)).status, 422)
            self.assertEqual(len(opened), 3)
            self.assertTrue(all(c.closed for c in opened), "every request connection is closed, including the 401 and 422 ones")
        # the session is still valid and last_seen_at keeps being updated: the read-only count transaction does not interfere
        before = self.scalar("SELECT max(last_seen_at) FROM vinto_auth.session")
        self.assertEqual((await self.count("Bobinas", cookie)).status, 200)
        self.assertGreater(self.scalar("SELECT max(last_seen_at) FROM vinto_auth.session"), before)


class CookieTests(CountCase):
    async def test_the_session_cookie_is_httponly_and_is_what_authorizes_the_count(self):
        created, password = self.users["JEFATURA"]
        login = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        cookie_header = next(v.decode() for k, v in login.headers if k.decode().lower() == "set-cookie")
        self.assertIn("HttpOnly", cookie_header)
        self.assertEqual((await self.count("Bobinas", login.set_cookie_value())).status, 200)
        self.assertEqual((await self.count("Bobinas", None)).status, 401)


if __name__ == "__main__":
    unittest.main()
