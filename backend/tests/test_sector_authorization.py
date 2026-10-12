"""Sector authorization (M1-C1): users only reach the sectors they were explicitly granted, on top of their profile permissions.

Pure tests cover the scope function and the structure of the routers. The database tests run through the real ASGI app against ephemeral
*_test databases: the template has a synthetic REBOBINADO sector (tests only) that is enabled with patch.object ONLY inside a test.
Nothing here touches the DEV database, enables a sector in code, or changes the permission matrix.
"""

import ast
import inspect
import re
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import sectors
from app.auth import permissions
from app.auth.errors import SectorNotFoundError, UserNotFoundError
from app.auth.grants import grant_sector, revoke_sector, sector_codes_for_user
from app.auth.service import create_user
from app.ephemeral_db import copy_database, drop_database

try:
    import test_f3_bobbins_api as f3
    import test_sector_scope as scope
    from test_assignments_api import call, order_body
    from test_quality_capture_api import P119_VALUES
    from test_sector_scope import F6_VALUES, FUTURE_MACHINE, FUTURE_SECTOR, PINNED_PROFILE_PERMISSIONS, setUpModule, tearDownModule  # noqa: F401
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    import tests.test_sector_scope as scope
    from tests.test_assignments_api import call, order_body
    from tests.test_quality_capture_api import P119_VALUES
    from tests.test_sector_scope import F6_VALUES, FUTURE_MACHINE, FUTURE_SECTOR, PINNED_PROFILE_PERMISSIONS, setUpModule, tearDownModule  # noqa: F401

APP = Path(__file__).resolve().parent.parent / "app"
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
BOTH = ("BOBINAS", FUTURE_SECTOR)


# ---- 1. scope function (pure) ---------------------------------------------------------------------------------------------------

class ScopeFunctionTests(unittest.TestCase):
    def test_the_scope_is_mandatory_none_is_an_error_and_empty_is_nothing(self):
        with self.assertRaises(TypeError):
            sectors.scoped_sector_codes()  # type: ignore[call-arg]
        with self.assertRaises(sectors.SectorConfigError):
            sectors.scoped_sector_codes(None)  # None never means "all sectors"
        with self.assertRaises(sectors.SectorConfigError):
            sectors.in_scope("BOBINAS", None)
        with self.assertRaises(TypeError):
            sectors.in_scope("BOBINAS")  # type: ignore[call-arg]
        self.assertEqual(sectors.scoped_sector_codes(sectors.operational_sector_codes()), ("BOBINAS",))  # broad access must be asked for explicitly
        self.assertEqual(sectors.scoped_sector_codes(()), ())
        self.assertEqual(sectors.scoped_sector_codes(frozenset()), ())
        self.assertFalse(sectors.in_scope("BOBINAS", frozenset()))  # no grant never means access

    def test_a_grant_to_a_non_operational_sector_is_inert(self):
        self.assertEqual(sectors.scoped_sector_codes({"REBOBINADO"}), ())
        self.assertEqual(sectors.scoped_sector_codes({"REBOBINADO", "CONVERSION"}), ())
        self.assertEqual(sectors.scoped_sector_codes({"BOBINAS", "REBOBINADO"}), ("BOBINAS",))
        self.assertFalse(sectors.in_scope("REBOBINADO", {"REBOBINADO"}))

    def test_the_scope_is_the_intersection_of_grants_and_operational_sectors(self):
        with patch.object(sectors, "_OPERATIONAL", ("BOBINAS", "REBOBINADO")):
            self.assertEqual(sectors.scoped_sector_codes({"REBOBINADO"}), ("REBOBINADO",))
            self.assertEqual(sectors.scoped_sector_codes({"BOBINAS"}), ("BOBINAS",))
            self.assertEqual(sectors.scoped_sector_codes({"BOBINAS", "REBOBINADO", "CONVERSION"}), ("BOBINAS", "REBOBINADO"))
            self.assertEqual(sectors.scoped_sector_codes(set()), ())
            self.assertTrue(sectors.in_scope("REBOBINADO", ["REBOBINADO"]))
            self.assertFalse(sectors.in_scope("BOBINAS", ["REBOBINADO"]))

    def test_unknown_or_malformed_values_never_widen_the_scope(self):
        self.assertEqual(sectors.scoped_sector_codes({"OTRO", "bobinas", " BOBINAS", ""}), ())
        for code in (None, 1, "", "bobinas"):
            self.assertFalse(sectors.in_scope(code, {"BOBINAS"}), repr(code))
        for text in ("BOBINAS", b"BOBINAS"):
            with self.assertRaises(sectors.SectorConfigError):
                sectors.scoped_sector_codes(text)  # a bare string would be iterated character by character

    def test_the_principal_has_no_sectors_by_default(self):
        from app.auth.service import AuthenticatedUser
        user = AuthenticatedUser(uuid4(), "x", "X", ("JEFATURA",), permissions.permissions_for_profiles(["JEFATURA"]), False)
        self.assertEqual(user.sectors, frozenset())


# ---- 2. structure (pure): the routers cannot forget the user scope -------------------------------------------------------------

def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


class RouterStructureTests(unittest.TestCase):
    SERVICES = ("work_orders/service.py", "assignments/service.py", "capture_service.py", "bobbins/service.py", "quality/service.py", "quality/capture_service.py")
    ROUTERS = ("work_orders/router.py", "assignments/router.py", "captures.py", "bobbins/router.py", "quality/router.py")

    def scoped_functions(self):
        names = set()
        for rel in self.SERVICES:
            for node in ast.walk(_parse(APP / rel)):
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_") and "sectors" in {a.arg for a in node.args.args + node.args.kwonlyargs}:
                    names.add(node.name)
        return names

    def test_every_service_entry_point_used_by_a_router_receives_the_user_sectors(self):
        scoped = self.scoped_functions()
        self.assertGreaterEqual(len(scoped), 14)
        checked = 0
        for rel in self.ROUTERS:
            for node in ast.walk(_parse(APP / rel)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in scoped and isinstance(node.func.value, ast.Name):
                    keywords = {k.arg: k.value for k in node.keywords}
                    self.assertIn("sectors", keywords, f"{rel}: {node.func.attr}() is called without sectors=")
                    self.assertEqual(ast.unparse(keywords["sectors"]), "user.sectors", f"{rel}: {node.func.attr}()")
                    checked += 1
        self.assertGreaterEqual(checked, 17)

    def test_every_router_function_that_reads_the_user_names_it_user_not_underscore(self):
        for rel in self.ROUTERS:
            for node in ast.walk(_parse(APP / rel)):
                if isinstance(node, ast.FunctionDef) and any("user.sectors" in ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.Call)):
                    self.assertIn("user", {a.arg for a in node.args.args}, f"{rel}: {node.name}")

    def test_no_service_filters_by_the_global_operational_list_anymore(self):
        offenders = [p.name for p in APP.rglob("*.py") if p.name != "sectors.py" and "seed" not in p.parts and "operational_sector_codes" in p.read_text(encoding="utf-8").replace("`operational_sector_codes()`", "")]
        self.assertEqual(offenders, [])

    def test_there_is_no_administrator_bypass(self):
        text = "".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py") if "seed" not in p.parts)
        for forbidden in ("is_admin", "is_superuser", "ALL_SECTORS", "bypass_scope", "sectors=None if"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_the_permission_matrix_is_still_the_pinned_one(self):
        self.assertEqual({k: set(v) for k, v in permissions.PROFILE_PERMISSIONS.items()}, PINNED_PROFILE_PERMISSIONS)

    def test_the_migration_is_additive(self):
        sql = (MIGRATIONS / "0006_user_sector_grants.sql").read_text(encoding="utf-8")
        statements = " ".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
        for forbidden in (r"\bDROP\b", r"\bTRUNCATE\b", r"\bDELETE\s+FROM\b", r"\bUPDATE\s+vinto_", r'\bALTER\s+TABLE\s+(?!vinto_master\."user_sector")'):
            self.assertIsNone(re.search(forbidden, statements, re.IGNORECASE), forbidden)
        self.assertEqual(statements.upper().count("CREATE TABLE"), 1)
        self.assertNotIn("'REBOBINADO'", sql.split("INSERT INTO")[-1])  # the backfill only ever grants BOBINAS
        self.assertNotIn("'CONVERSION'", sql.split("INSERT INTO")[-1])


# ---- 3. database behaviour --------------------------------------------------------------------------------------------------------

class SectorAuthorizationCase(f3.BobbinApiCase):
    """f3.BobbinApiCase users (one per profile) hold an explicit BOBINAS grant, exactly like today's users after the migration backfill."""

    async def new_user(self, profile, *sector_codes):
        name = f"sa.{uuid4().hex[:10]}"
        password = "pw-" + uuid4().hex
        created = create_user(self.connection, username=name, display_name=f"{profile} sa", profile_code=profile, password=password, sectors=sector_codes)
        reply = await call("POST", "/api/auth/login", json_body={"username": name, "password": password})
        self.assertEqual(reply.status, 200)
        return created, reply.set_cookie_value()

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.work_order", "vinto_txn.assignment", "vinto_txn.capture",
                                                                         "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_txn.quality_release",
                                                                         "vinto_master.user_sector")}

    def audit_count(self):
        return self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table <> 'user_sector' AND entity_schema IN ('vinto_txn')")


class GrantServiceTests(SectorAuthorizationCase):
    async def test_the_principal_carries_exactly_the_explicit_grants(self):
        _, none = await self.new_user("JEFATURA")
        created, cookie = await self.new_user("OPERACION", "BOBINAS")
        self.assertEqual(sector_codes_for_user(self.connection, created.user_id), frozenset({"BOBINAS"}))
        none_user = self.connection.execute("SELECT id FROM vinto_master.\"user\" WHERE display_name='JEFATURA sa' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        self.assertEqual(sector_codes_for_user(self.connection, none_user), frozenset())
        self.assertTrue(none and cookie)

    async def test_duplicate_grants_are_idempotent_and_the_database_forbids_them(self):
        created, _ = await self.new_user("OPERACION", "BOBINAS", "BOBINAS")  # repeated in the request
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (created.user_id,)), 1)
        self.assertFalse(grant_sector(self.connection, user_id=created.user_id, sector_code="BOBINAS"))
        self.assertTrue(grant_sector(self.connection, user_id=created.user_id, sector_code=FUTURE_SECTOR))
        self.assertFalse(grant_sector(self.connection, user_id=created.user_id, sector_code=FUTURE_SECTOR))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (created.user_id,)), 2)
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.connection.execute("INSERT INTO vinto_master.user_sector (user_id, sector_id) SELECT %s, id FROM vinto_master.sector WHERE code='BOBINAS'", (created.user_id,))

    async def test_unknown_user_or_sector_is_rejected_without_writing(self):
        created, _ = await self.new_user("OPERACION", "BOBINAS")
        before = self.counts()
        with self.assertRaises(SectorNotFoundError):
            grant_sector(self.connection, user_id=created.user_id, sector_code="NO_EXISTE")
        with self.assertRaises(SectorNotFoundError):
            grant_sector(self.connection, user_id=created.user_id, sector_code=None)
        with self.assertRaises(UserNotFoundError):
            grant_sector(self.connection, user_id=uuid4(), sector_code="BOBINAS")
        users = self.scalar('SELECT count(*) FROM vinto_master."user"')
        with self.assertRaises(SectorNotFoundError):
            create_user(self.connection, username=f"sa.{uuid4().hex[:10]}", display_name="X", profile_code="OPERACION", password="pw-" + uuid4().hex, sectors=("BOBINAS", "NO_EXISTE"))
        self.assertEqual(self.scalar('SELECT count(*) FROM vinto_master."user"'), users, "creating the user is all-or-nothing")
        self.assertEqual(self.counts(), before)

    async def test_revoking_is_idempotent(self):
        created, _ = await self.new_user("OPERACION", "BOBINAS")
        self.assertTrue(revoke_sector(self.connection, user_id=created.user_id, sector_code="BOBINAS"))
        self.assertFalse(revoke_sector(self.connection, user_id=created.user_id, sector_code="BOBINAS"))
        self.assertEqual(sector_codes_for_user(self.connection, created.user_id), frozenset())

    async def test_grants_are_audited(self):
        created, _ = await self.new_user("OPERACION")
        grant_sector(self.connection, user_id=created.user_id, sector_code="BOBINAS", actor_id=self.users["DATA_BALTREK"][0].user_id, request_id="test-grant")
        row = self.connection.execute("""SELECT action, actor_id, request_id, reason FROM vinto_audit.audit_event
                                         WHERE entity_table='user_sector' AND new_data->>'user_id'=%s ORDER BY id DESC LIMIT 1""", (str(created.user_id),)).fetchone()
        self.assertEqual((row[0], row[1], row[2], row[3]), ("INSERT", self.users["DATA_BALTREK"][0].user_id, "test-grant", "sector grant"))


class UsersWithoutGrantsTests(SectorAuthorizationCase):
    """Rule: the absence of a grant never means access. Every profile with its functional permission, but no sector, sees and changes nothing."""

    async def test_every_plant_profile_without_a_grant_sees_nothing_and_writes_nothing(self):
        order, assignment = await self.assignment("MP1")
        bobbin = (await self.post(self.payload(assignment))).json()
        bobbin_id, capture_id = bobbin["bobbin"]["id"], bobbin["capture"]["id"]
        f6_id = (await call("POST", "/api/captures", cookie=await self.cookie("OPERACION"), json_body={
            "capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(F6_VALUES)})).json()["capture"]["id"]
        quality = (await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", cookie=await self.cookie("CALIDAD"), json_body={
            "capture_id": str(uuid4()), "form_code": "VINTO-P1-19", "device_key": str(uuid4()), "values": dict(P119_VALUES)})).json()["capture"]["id"]
        _, jefatura = await self.new_user("JEFATURA")
        _, supervision = await self.new_user("SUPERVISION")
        _, operacion = await self.new_user("OPERACION")
        _, calidad = await self.new_user("CALIDAD")
        before = self.counts()

        # reads: empty lists and 404, indistinguishable from "does not exist"
        self.assertEqual((await call("GET", "/api/work-orders", cookie=jefatura)).json(), [])
        self.assertEqual((await call("GET", "/api/assignments", cookie=supervision)).json(), [])
        self.assertEqual((await call("GET", "/api/captures", cookie=operacion)).json(), [])
        self.assertEqual((await call("GET", "/api/quality/bobbins", cookie=calidad)).json(), [])
        for status in ("released", "rejected"):
            self.assertEqual((await call("GET", f"/api/quality/bobbins?status={status}", cookie=calidad)).json(), [])
        gone = (("GET", f"/api/work-orders/{order['id']}", jefatura), ("GET", f"/api/captures/{f6_id}", operacion), ("GET", f"/api/bobbins/{bobbin_id}", operacion),
                ("GET", f"/api/quality/bobbins/{bobbin_id}/captures", calidad), ("GET", f"/api/quality/captures/{quality}", calidad))
        for method, path, cookie in gone:
            self.assertEqual((await call(method, path, cookie=cookie)).status, 404, path)
        missing = await call("GET", f"/api/work-orders/{uuid4()}", cookie=jefatura)
        existing = await call("GET", f"/api/work-orders/{order['id']}", cookie=jefatura)
        self.assertEqual((existing.status, existing.json()), (missing.status, missing.json()), "out of scope is indistinguishable from nonexistent")

        # writes: refused and nothing is written
        line = order["baseline"]["lines"][0]["id"]
        self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=jefatura)).json()["code"], "MACHINE_OUTSIDE_SCOPE")
        self.assertEqual((await call("POST", f"/api/work-orders/{order['id']}/lines", json_body={"pv_reference": "PV-9", "article_code": "X", "quantity": 1, "due_date": "2026-12-01"}, cookie=jefatura)).status, 404)
        self.assertEqual((await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=jefatura)).status, 404)
        self.assertEqual((await call("POST", "/api/assignments/activate", cookie=supervision, json_body={"work_order_id": order["id"], "baseline_line_id": line})).status, 404)
        self.assertEqual((await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=supervision)).status, 404)
        self.assertEqual((await call("GET", "/api/assignments/active?machine_code=MP1", cookie=supervision)).json()["code"], "MACHINE_OUTSIDE_SCOPE")
        self.assertEqual((await call("POST", "/api/captures", cookie=operacion, json_body={
            "capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(F6_VALUES)})).status, 404)
        self.assertEqual((await call("POST", "/api/bobbins", cookie=operacion, json_body=self.payload(assignment))).status, 404)
        self.assertEqual((await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", cookie=calidad, json_body={
            "capture_id": str(uuid4()), "form_code": "VINTO-P1-19", "device_key": str(uuid4()), "values": dict(P119_VALUES)})).status, 404)
        # an exact retry of an accepted capture must not succeed for a user who lost (or never had) the sector
        retry = await call("POST", "/api/bobbins", cookie=operacion, json_body={"capture_id": capture_id, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": self.payload(assignment)["values"]})
        self.assertNotIn(retry.status, (200, 201))
        self.assertEqual(self.counts(), before, "blocked operations write nothing")
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (assignment["id"],)), "active")

    async def test_data_baltrek_never_receives_operational_scope_implicitly(self):
        order, _ = await self.assignment("MP1")
        _, anonymous = await self.new_user("DATA_BALTREK")
        self.assertEqual((await call("GET", "/api/work-orders", cookie=anonymous)).json(), [])
        self.assertEqual((await call("GET", f"/api/work-orders/{order['id']}", cookie=anonymous)).status, 404)
        self.assertEqual((await call("GET", "/api/assignments", cookie=anonymous)).json(), [])
        # an explicit grant gives it read access (its profile already has the read permissions) but never manage/capture
        _, granted = await self.new_user("DATA_BALTREK", "BOBINAS")
        self.assertIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=granted)).json()])
        self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=granted)).status, 403)
        self.assertEqual((await call("POST", "/api/captures", json_body={}, cookie=granted)).status, 403)

    async def test_a_grant_never_adds_permissions(self):
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            _, cookie = await self.new_user(profile, "BOBINAS", FUTURE_SECTOR)
            reply = await call("GET", "/api/auth/me", cookie=cookie)
            self.assertEqual(set(reply.json()["user"]["permissions"]), PINNED_PROFILE_PERMISSIONS[profile], profile)
            self.assertNotIn("sectors", reply.json()["user"], "the /me contract is unchanged")
        _, operacion = await self.new_user("OPERACION", "BOBINAS")
        self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=operacion)).status, 403)
        _, jefatura = await self.new_user("JEFATURA", "BOBINAS")
        self.assertEqual((await call("POST", "/api/captures", json_body={}, cookie=jefatura)).status, 403)

    async def test_unauthenticated_requests_are_still_401_and_never_reach_the_database_state(self):
        before = self.counts()
        for method, path in (("GET", "/api/work-orders"), ("POST", "/api/work-orders"), ("GET", "/api/assignments"), ("GET", "/api/captures"), ("POST", "/api/bobbins"),
                             ("GET", "/api/quality/bobbins"), ("GET", f"/api/bobbins/{uuid4()}")):
            self.assertEqual((await call(method, path)).status, 401, path)
        self.assertEqual(self.counts(), before)


class GrantLifecycleTests(SectorAuthorizationCase):
    async def test_revoking_applies_to_existing_sessions_immediately_and_regranting_restores_access(self):
        order, _ = await self.assignment("MP1")
        created, cookie = await self.new_user("JEFATURA", "BOBINAS")
        self.assertIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=cookie)).json()])
        revoke_sector(self.connection, user_id=created.user_id, sector_code="BOBINAS")
        self.assertEqual((await call("GET", "/api/work-orders", cookie=cookie)).json(), [])  # same cookie, no re-login
        self.assertEqual((await call("GET", f"/api/work-orders/{order['id']}", cookie=cookie)).status, 404)
        self.assertEqual((await call("GET", "/api/auth/me", cookie=cookie)).status, 200, "the session itself is still valid")
        grant_sector(self.connection, user_id=created.user_id, sector_code="BOBINAS")
        self.assertIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=cookie)).json()])

    async def test_users_that_predate_the_grants_keep_working_after_the_backfill(self):
        # The migration backfill: every active user holding one of the five profiles gets BOBINAS (DATA_BALTREK included, for its existing reads); inactive users and other sectors get nothing.
        database = copy_database(f3.STATE["template"], "vinto_backfill")
        try:
            with scope.connect(database) as connection:
                users = {}
                for profile in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"):
                    users[profile] = create_user(connection, username=f"bf.{profile.lower()}", display_name=profile, profile_code=profile, password="pw-" + uuid4().hex).user_id
                inactive = create_user(connection, username="bf.inactive", display_name="inactive", profile_code="OPERACION", password="pw-" + uuid4().hex).user_id
                connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (inactive,))
                connection.execute("ALTER TABLE vinto_master.user_sector DISABLE TRIGGER USER")
                connection.execute("DELETE FROM vinto_master.user_sector")  # simulate the state before 0006
                connection.execute("ALTER TABLE vinto_master.user_sector ENABLE TRIGGER USER")
                connection.execute("DROP TABLE vinto_master.user_sector")
                connection.execute((MIGRATIONS / "0006_user_sector_grants.sql").read_text(encoding="utf-8"))
                grants = {user: sector_codes_for_user(connection, user) for user in (*users.values(), inactive)}
                self.assertEqual({p: grants[u] for p, u in users.items()},
                                 {"JEFATURA": {"BOBINAS"}, "SUPERVISION": {"BOBINAS"}, "OPERACION": {"BOBINAS"}, "CALIDAD": {"BOBINAS"}, "DATA_BALTREK": {"BOBINAS"}})
                self.assertEqual(grants[inactive], frozenset())
                self.assertEqual(connection.execute("SELECT count(*) FROM vinto_master.user_sector us JOIN vinto_master.sector s ON s.id=us.sector_id WHERE s.code <> 'BOBINAS'").fetchone()[0], 0)
                self.assertGreaterEqual(connection.execute("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='user_sector' AND request_id='migration:0006_user_sector_grants'").fetchone()[0], 4)
        finally:
            drop_database(database)


class CrossSectorIsolationTests(SectorAuthorizationCase):
    """With the synthetic sector ENABLED (inside the test only) users stay inside the sectors they were granted."""

    async def test_users_of_one_sector_cannot_see_or_change_the_other(self):
        with patch.object(sectors, "_OPERATIONAL", BOTH):
            ref_jef = (await self.new_user("JEFATURA", FUTURE_SECTOR))[1]
            ref_sup = (await self.new_user("SUPERVISION", FUTURE_SECTOR))[1]
            ref_ope = (await self.new_user("OPERACION", FUTURE_SECTOR))[1]
            ref_cal = (await self.new_user("CALIDAD", FUTURE_SECTOR))[1]
            future_order = {**order_body("MP1"), "machine_code": FUTURE_MACHINE}

            # a REBOBINADO-only team runs the whole chain in its own sector
            order = await call("POST", "/api/work-orders", json_body=future_order, cookie=ref_jef)
            self.assertEqual(order.status, 201)
            order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=ref_jef)).json()
            line = order["baseline"]["lines"][0]["id"]
            activated = await call("POST", "/api/assignments/activate", cookie=ref_sup, json_body={"work_order_id": order["id"], "baseline_line_id": line})
            self.assertEqual(activated.status, 201)
            assignment = activated.json()["assignment"]
            f6_body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(F6_VALUES)}
            f6 = await call("POST", "/api/captures", json_body=f6_body, cookie=ref_ope)
            self.assertEqual(f6.status, 201)
            bobbin = await call("POST", "/api/bobbins", json_body=self.payload(assignment), cookie=ref_ope)
            self.assertEqual(bobbin.status, 201)
            bobbin_id = bobbin.json()["bobbin"]["id"]
            q_body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-19", "device_key": str(uuid4()), "values": dict(P119_VALUES)}
            quality = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=q_body, cookie=ref_cal)
            self.assertEqual(quality.status, 201)
            quality_id = quality.json()["capture"]["id"]
            self.assertIn(bobbin_id, [i["bobbin"]["id"] for i in (await call("GET", "/api/quality/bobbins", cookie=ref_cal)).json()])

            # the BOBINAS team (the regular fixtures) sees none of it and cannot touch it
            bob = {p: await self.cookie(p) for p in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD")}
            before = self.counts()
            self.assertNotIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=bob["JEFATURA"])).json()])
            self.assertNotIn(assignment["id"], [a["id"] for a in (await call("GET", "/api/assignments", cookie=bob["SUPERVISION"])).json()])
            self.assertNotIn(f6.json()["capture"]["id"], [c["id"] for c in (await call("GET", "/api/captures", cookie=bob["OPERACION"])).json()])
            inbox = await call("GET", "/api/quality/bobbins", cookie=bob["CALIDAD"])
            self.assertEqual(inbox.status, 200, inbox.body[:200])
            self.assertNotIn(bobbin_id, [i["bobbin"]["id"] for i in inbox.json()])
            for method, path, who in (("GET", f"/api/work-orders/{order['id']}", "JEFATURA"), ("GET", f"/api/captures/{f6.json()['capture']['id']}", "OPERACION"),
                                      ("GET", f"/api/bobbins/{bobbin_id}", "OPERACION"), ("GET", f"/api/quality/bobbins/{bobbin_id}/captures", "CALIDAD"),
                                      ("GET", f"/api/quality/captures/{quality_id}", "CALIDAD"), ("POST", f"/api/work-orders/{order['id']}/publish", "JEFATURA"),
                                      ("POST", f"/api/assignments/{assignment['id']}/finish", "SUPERVISION")):
                self.assertEqual((await call(method, path, cookie=bob[who])).status, 404, path)
            self.assertEqual((await call("POST", "/api/work-orders", json_body=future_order, cookie=bob["JEFATURA"])).json()["code"], "MACHINE_OUTSIDE_SCOPE")
            self.assertEqual((await call("GET", f"/api/assignments/active?machine_code={FUTURE_MACHINE}", cookie=bob["SUPERVISION"])).json()["code"], "MACHINE_OUTSIDE_SCOPE")
            self.assertEqual((await call("POST", "/api/assignments/activate", cookie=bob["SUPERVISION"], json_body={"work_order_id": order["id"], "baseline_line_id": line})).status, 404)
            self.assertEqual((await call("POST", "/api/captures", json_body={**f6_body, "capture_id": str(uuid4())}, cookie=bob["OPERACION"])).status, 404)
            self.assertEqual((await call("POST", "/api/bobbins", json_body=self.payload(assignment), cookie=bob["OPERACION"])).status, 404)
            self.assertEqual((await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body={**q_body, "capture_id": str(uuid4())}, cookie=bob["CALIDAD"])).status, 404)
            self.assertEqual(self.counts(), before, "cross-sector attempts write nothing")

            # and the other way around: the REBOBINADO team cannot reach BOBINAS
            mp1_order, mp1_assignment = await self.assignment("MP1")
            self.assertNotIn(mp1_order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=ref_jef)).json()])
            self.assertEqual((await call("GET", f"/api/work-orders/{mp1_order['id']}", cookie=ref_jef)).status, 404)
            self.assertEqual((await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=ref_jef)).json()["code"], "MACHINE_OUTSIDE_SCOPE")
            self.assertEqual((await call("POST", "/api/bobbins", json_body=self.payload(mp1_assignment), cookie=ref_ope)).status, 404)
            self.assertEqual((await call("POST", f"/api/assignments/{mp1_assignment['id']}/finish", cookie=ref_sup)).status, 404)
            self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (mp1_assignment["id"],)), "active")

            # a user granted both sectors sees both
            both = (await self.new_user("JEFATURA", *BOTH))[1]
            ids = [o["id"] for o in (await call("GET", "/api/work-orders", cookie=both)).json()]
            self.assertIn(order["id"], ids)
            self.assertIn(mp1_order["id"], ids)

    async def test_a_grant_to_a_sector_that_is_not_enabled_does_nothing(self):
        # default configuration: only BOBINAS is operational, so a REBOBINADO grant is inert even though the data exists
        _, cookie = await self.new_user("JEFATURA", FUTURE_SECTOR)
        before = self.counts()
        self.assertEqual((await call("GET", "/api/work-orders", cookie=cookie)).json(), [])
        reply = await call("POST", "/api/work-orders", json_body={**order_body("MP1"), "machine_code": FUTURE_MACHINE}, cookie=cookie)
        self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        self.assertEqual(self.counts(), before)
        self.assertEqual(sectors.operational_sector_codes(), ("BOBINAS",))

    async def test_existing_bobinas_behaviour_is_unchanged_for_granted_users(self):
        order, assignment = await self.assignment("MP1")
        bobbin = await self.post(self.payload(assignment))
        self.assertEqual(bobbin.status, 201)
        self.assertIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=await self.cookie("JEFATURA"))).json()])
        quality = await call("POST", f"/api/quality/bobbins/{bobbin.json()['bobbin']['id']}/captures", cookie=await self.cookie("CALIDAD"),
                             json_body={"capture_id": str(uuid4()), "form_code": "VINTO-P1-19", "device_key": str(uuid4()), "values": dict(P119_VALUES)})
        self.assertEqual(quality.status, 201)
        _, own = await self.new_user("CALIDAD", "BOBINAS")  # a private session: logging out the shared fixture cookie would break the other tests
        self.assertEqual((await call("POST", "/api/auth/logout", cookie=own)).status, 204)
        self.assertEqual((await call("GET", "/api/work-orders", cookie=own)).status, 401)


class ServiceScopeTests(SectorAuthorizationCase):
    """The services have NO permissive default: the scope must be passed, and an empty or partial scope is honoured by reads and writes."""

    SERVICE_MODULES = ("app.work_orders.service", "app.assignments.service", "app.capture_service", "app.bobbins.service", "app.quality.service", "app.quality.capture_service")

    def scoped_functions(self):
        import importlib
        found = []
        for name in self.SERVICE_MODULES:
            module = importlib.import_module(name)
            for attribute, function in vars(module).items():
                if inspect.isfunction(function) and function.__module__ == name and "sectors" in inspect.signature(function).parameters:
                    found.append((name, attribute, function))
        return found

    def test_no_service_function_has_a_default_for_the_scope(self):
        found = self.scoped_functions()
        self.assertGreaterEqual(len(found), 26)
        for module, name, function in found:
            parameter = inspect.signature(function).parameters["sectors"]
            self.assertIs(parameter.default, inspect.Parameter.empty, f"{module}.{name}: sectors must be required")

    def test_omitting_the_scope_is_a_type_error_and_none_is_rejected_without_touching_the_database(self):
        from app import capture_service
        from app.assignments import service as assignments
        from app.bobbins import service as bobbins
        from app.quality import capture_service as quality_captures
        from app.quality import service as quality
        from app.work_orders import service as work_orders
        some = str(uuid4())
        calls = [(work_orders.list_work_orders, {}), (work_orders.get_work_order, {"work_order_id": some}), (assignments.list_assignments, {}),
                 (assignments.get_assignment, {"assignment_id": some}), (assignments.get_active, {"machine_code": "MP1"}), (capture_service.list_captures, {}),
                 (capture_service.get_capture, {"capture_id": some}), (bobbins.get_bobbin, {"bobbin_id": some}), (quality.list_quality_bobbins, {}),
                 (quality_captures.get_quality_capture, {"capture_id": some}), (quality_captures.list_bobbin_quality_captures, {"bobbin_id": some})]
        before = self.counts()
        for function, kwargs in calls:
            with self.assertRaises(TypeError, msg=function.__name__):
                function(self.connection, **kwargs)
            with self.assertRaises(sectors.SectorConfigError, msg=function.__name__):
                function(self.connection, sectors=None, **kwargs)
            with self.assertRaises(sectors.SectorConfigError, msg=function.__name__):
                function(self.connection, sectors="BOBINAS", **kwargs)  # a bare string is not a collection of codes
        with self.assertRaises(TypeError):
            work_orders.create_work_order(self.connection, actor_id=self.users["JEFATURA"][0].user_id, machine_code="MP1", lines=[])
        with self.assertRaises(sectors.SectorConfigError):
            work_orders.publish_work_order(self.connection, actor_id=self.users["JEFATURA"][0].user_id, work_order_id=some, sectors=None)
        self.assertEqual(self.counts(), before)

    async def test_an_empty_scope_denies_every_read_and_write_of_the_services(self):
        from app import capture_service
        from app.assignments import errors as assignment_errors
        from app.assignments import service as assignments
        from app.bobbins import errors as bobbin_errors
        from app.bobbins import service as bobbins
        from app.quality import capture_service as quality_captures
        from app.quality import service as quality
        from app.work_orders import errors as wo_errors
        from app.work_orders import service as work_orders
        order, assignment = await self.assignment("MP1")
        bobbin = (await self.post(self.payload(assignment))).json()
        bobbin_id = bobbin["bobbin"]["id"]
        actor = self.users["JEFATURA"][0].user_id
        before = self.counts()
        none = ()
        self.assertEqual(work_orders.list_work_orders(self.connection, sectors=none), [])
        self.assertEqual(assignments.list_assignments(self.connection, sectors=none), [])
        self.assertEqual(capture_service.list_captures(self.connection, sectors=none), [])
        self.assertEqual(quality.list_quality_bobbins(self.connection, sectors=none), [])
        with self.assertRaises(wo_errors.WorkOrderNotFoundError):
            work_orders.get_work_order(self.connection, order["id"], sectors=none)
        with self.assertRaises(assignment_errors.AssignmentNotFoundError):
            assignments.get_assignment(self.connection, assignment["id"], sectors=none)
        with self.assertRaises(bobbin_errors.BobbinNotFoundError):
            bobbins.get_bobbin(self.connection, bobbin_id, sectors=none)
        with self.assertRaises(wo_errors.MachineOutsideScopeError):
            assignments.get_active(self.connection, machine_code="MP1", sectors=none)
        with self.assertRaises(wo_errors.MachineOutsideScopeError):
            work_orders.create_work_order(self.connection, actor_id=actor, machine_code="MP1", lines=[work_orders.LineInput("PV-1", "X", 1, None)], sectors=none)
        with self.assertRaises(wo_errors.WorkOrderNotFoundError):
            work_orders.publish_work_order(self.connection, actor_id=actor, work_order_id=order["id"], sectors=none)
        with self.assertRaises(assignment_errors.AssignmentNotFoundError):
            assignments.finish(self.connection, actor_id=actor, assignment_id=assignment["id"], sectors=none)
        with self.assertRaises(assignment_errors.AssignmentNotFoundError):
            capture_service.lock_active_assignment(self.connection, assignment["id"], none)
        with self.assertRaises(bobbin_errors.BobbinNotFoundError):
            quality_captures.list_bobbin_quality_captures(self.connection, bobbin_id, sectors=none)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (assignment["id"],)), "active")

    async def test_the_scope_is_always_intersected_with_the_operational_sectors(self):
        from app.work_orders import service as work_orders
        order, _ = await self.assignment("MP1")
        ids = lambda scope: [o.id.__str__() for o in work_orders.list_work_orders(self.connection, sectors=scope)]
        self.assertIn(order["id"], ids(("BOBINAS",)))
        self.assertEqual(ids((FUTURE_SECTOR,)), [])  # granted but not operational: nothing
        self.assertIn(order["id"], ids(("BOBINAS", FUTURE_SECTOR, "CONVERSION", "INVENTADO")))
        self.assertEqual(ids(("INVENTADO", "bobinas", "")), [])
        with patch.object(sectors, "_OPERATIONAL", BOTH):
            self.assertIn(order["id"], ids(("BOBINAS",)))
            self.assertNotIn(order["id"], ids((FUTURE_SECTOR,)), "REBOBINADO without BOBINAS must not reach Bobinas even when both are operational")
            self.assertIn(order["id"], ids(BOTH))
            self.assertEqual(ids(()), [])
        from app.work_orders import errors as wo_errors
        with patch.object(sectors, "_OPERATIONAL", BOTH):
            with self.assertRaises(wo_errors.MachineOutsideScopeError):
                work_orders.create_work_order(self.connection, actor_id=self.users["JEFATURA"][0].user_id, machine_code="MP1",
                                              lines=[work_orders.LineInput("PV-1", "X", 1, None)], sectors=(FUTURE_SECTOR,))


class AuthenticationConsistencyTests(SectorAuthorizationCase):
    """Identity and grants come from the database on every request; the cookie only carries an opaque token."""

    async def test_login_and_every_later_request_read_the_current_grants(self):
        from app.auth.sessions import login_with_session, resolve_session
        password = "pw-" + uuid4().hex
        user = create_user(self.connection, username=f"sa.{uuid4().hex[:10]}", display_name="consistency2", profile_code="OPERACION", password=password, sectors=("BOBINAS",))
        principal, session = login_with_session(self.connection, user.username, password)
        self.assertEqual(principal.sectors, frozenset({"BOBINAS"}))
        self.assertEqual(resolve_session(self.connection, session.raw_token).sectors, frozenset({"BOBINAS"}))
        revoke_sector(self.connection, user_id=user.user_id, sector_code="BOBINAS")
        self.assertEqual(resolve_session(self.connection, session.raw_token).sectors, frozenset(), "the next resolution sees the revocation")
        grant_sector(self.connection, user_id=user.user_id, sector_code=FUTURE_SECTOR)
        self.assertEqual(resolve_session(self.connection, session.raw_token).sectors, frozenset({FUTURE_SECTOR}))
        relogin, _ = login_with_session(self.connection, user.username, password)
        self.assertEqual(relogin.sectors, frozenset({FUTURE_SECTOR}))
        self.assertEqual(relogin.permissions, permissions.permissions_for_profiles(["OPERACION"]))

    async def test_grants_of_an_inactive_sector_are_ignored(self):
        created, cookie = await self.new_user("JEFATURA", "BOBINAS", FUTURE_SECTOR)
        self.assertEqual(sector_codes_for_user(self.connection, created.user_id), frozenset({"BOBINAS", FUTURE_SECTOR}))
        self.connection.execute("UPDATE vinto_master.sector SET active=false WHERE code=%s", (FUTURE_SECTOR,))
        try:
            self.assertEqual(sector_codes_for_user(self.connection, created.user_id), frozenset({"BOBINAS"}))
        finally:
            self.connection.execute("UPDATE vinto_master.sector SET active=true WHERE code=%s", (FUTURE_SECTOR,))
        self.assertTrue(cookie)

    async def test_an_inactive_user_loses_the_session_and_the_cookie_cannot_carry_scope(self):
        created, cookie = await self.new_user("JEFATURA", "BOBINAS")
        self.assertEqual((await call("GET", "/api/work-orders", cookie=cookie)).status, 200)
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (created.user_id,))
        self.assertEqual((await call("GET", "/api/work-orders", cookie=cookie)).status, 401)
        forged = await call("GET", "/api/work-orders", cookie="BOBINAS,REBOBINADO," + cookie)
        self.assertEqual(forged.status, 401)
        for header in ("X-Sectors", "X-Sector", "X-Machine"):
            reply = await call("GET", "/api/work-orders", cookie=await self.new_user_cookie("JEFATURA"), extra_headers=[(header, "BOBINAS")])
            self.assertEqual(reply.json(), [], f"{header} from the client must be ignored")

    async def new_user_cookie(self, profile, *sector_codes):
        return (await self.new_user(profile, *sector_codes))[1]

    async def test_a_client_cannot_name_its_own_sector_or_machine_scope(self):
        order, _ = await self.assignment("MP1")
        cookie = await self.new_user_cookie("JEFATURA")  # no grant
        for query in ("?sector=BOBINAS", "?sectors=BOBINAS", "?machine_code=MP1&sector=BOBINAS"):
            reply = await call("GET", f"/api/work-orders{query}", cookie=cookie)
            self.assertEqual((reply.status, reply.json()), (200, []), query)
        body = {**order_body("MP1"), "sector": "BOBINAS", "sectors": ["BOBINAS"]}
        self.assertEqual((await call("POST", "/api/work-orders", json_body=body, cookie=cookie)).status, 422)
        self.assertEqual((await call("GET", f"/api/work-orders/{order['id']}", cookie=cookie)).status, 404)


class DataBaltrekCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    """Users that exist BEFORE 0006 (all five profiles) keep exactly what they could do, after the backfill, with no new permission."""

    PROFILE_NAMES = ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK")

    @classmethod
    def setUpClass(cls):
        from pydantic import SecretStr
        from app.config import settings
        from app.ephemeral_db import connect, database_url
        cls.database = copy_database(f3.STATE["template"], "vinto_bfcompat")
        cls.connection = connect(cls.database)
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.passwords, cls.users, cls.cookies = {}, {}, {}
        connection = cls.connection
        connection.execute("DROP TABLE vinto_master.user_sector")  # the state before 0006
        for profile in cls.PROFILE_NAMES:
            password = "pw-" + uuid4().hex
            cls.passwords[profile] = password
            cls.users[profile] = create_user(connection, username=f"bfc.{profile.lower()}", display_name=profile, profile_code=profile, password=password)
        connection.execute((MIGRATIONS / "0006_user_sector_grants.sql").read_text(encoding="utf-8"))  # applies the real migration, backfill included

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def cookie(self, profile):
        if profile not in self.cookies:
            reply = await call("POST", "/api/auth/login", json_body={"username": self.users[profile].username, "password": self.passwords[profile]})
            self.assertEqual(reply.status, 200, profile)
            self.cookies[profile] = reply.set_cookie_value()
        return self.cookies[profile]

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def counts(self):
        return {t: self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.work_order", "vinto_txn.assignment", "vinto_txn.capture", "vinto_txn.bobbin", "vinto_txn.quality_release")}

    async def test_each_of_the_five_existing_users_holds_only_bobinas_and_the_same_permissions(self):
        for profile in self.PROFILE_NAMES:
            self.assertEqual(sector_codes_for_user(self.connection, self.users[profile].user_id), frozenset({"BOBINAS"}), profile)
            me = await call("GET", "/api/auth/me", cookie=await self.cookie(profile))
            self.assertEqual(set(me.json()["user"]["permissions"]), PINNED_PROFILE_PERMISSIONS[profile], profile)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector"), 5)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_master.user_sector us JOIN vinto_master.sector s ON s.id=us.sector_id WHERE s.code <> 'BOBINAS'"), 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='user_sector' AND request_id='migration:0006_user_sector_grants'"), 5)
        data = PINNED_PROFILE_PERMISSIONS["DATA_BALTREK"]
        self.assertTrue({"work_order.read", "assignment.read"} <= data)
        self.assertFalse(data & {"work_order.manage", "assignment.manage", "production.capture", "quality.capture", "quality.release"})

    async def test_the_whole_bobinas_flow_still_works_and_data_baltrek_keeps_read_only_access(self):
        jefatura, supervision, operacion, calidad, data = [await self.cookie(p) for p in self.PROFILE_NAMES[:4] + ("DATA_BALTREK",)]
        order = (await call("POST", "/api/work-orders", json_body=order_body("MP1"), cookie=jefatura)).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=jefatura)).json()
        line = order["baseline"]["lines"][0]["id"]
        activated = await call("POST", "/api/assignments/activate", cookie=supervision, json_body={"work_order_id": order["id"], "baseline_line_id": line})
        self.assertEqual(activated.status, 201)
        assignment = activated.json()["assignment"]
        f6 = await call("POST", "/api/captures", cookie=operacion, json_body={"capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"],
                                                                                "device_key": str(uuid4()), "values": dict(F6_VALUES)})
        self.assertEqual(f6.status, 201)
        f3_body = {"capture_id": str(uuid4()), "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(f3.VALUES)}
        bobbin = await call("POST", "/api/bobbins", cookie=operacion, json_body=f3_body)
        self.assertEqual(bobbin.status, 201)
        bobbin_id = bobbin.json()["bobbin"]["id"]
        retry = await call("POST", "/api/bobbins", cookie=operacion, json_body=f3_body)
        self.assertEqual((retry.status, retry.json()["already_submitted"]), (200, True), "idempotent retries still work for a granted user")
        for form, values in (("VINTO-P1-19", P119_VALUES), ):
            quality = await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", cookie=calidad, json_body={"capture_id": str(uuid4()), "form_code": form, "device_key": str(uuid4()), "values": dict(values)})
            self.assertEqual(quality.status, 201, form)

        # DATA_BALTREK: the reads it had before 0006 (work_order.read, assignment.read) …
        self.assertIn(order["id"], [o["id"] for o in (await call("GET", "/api/work-orders", cookie=data)).json()])
        self.assertEqual((await call("GET", f"/api/work-orders/{order['id']}", cookie=data)).status, 200)
        self.assertIn(assignment["id"], [a["id"] for a in (await call("GET", "/api/assignments", cookie=data)).json()])
        self.assertEqual((await call("GET", "/api/assignments/active?machine_code=MP1", cookie=data)).status, 200)
        # … and nothing else: every write stays 403 and writes nothing
        before = self.counts()
        writes = (("POST", "/api/work-orders", order_body("MP1")), ("POST", f"/api/work-orders/{order['id']}/publish", None), ("POST", "/api/assignments/activate", {"work_order_id": order["id"], "baseline_line_id": line}),
                  ("POST", f"/api/assignments/{assignment['id']}/finish", None), ("POST", "/api/captures", {}), ("POST", "/api/bobbins", f3_body),
                  ("POST", f"/api/quality/bobbins/{bobbin_id}/captures", {}), ("GET", "/api/captures", None), ("GET", f"/api/bobbins/{bobbin_id}", None), ("GET", "/api/quality/bobbins", None))
        for method, path, body in writes:
            self.assertEqual((await call(method, path, json_body=body, cookie=data)).status, 403, f"{method} {path}")
        self.assertEqual(self.counts(), before)
        # a user created AFTER 0006 starts with no scope, whatever the profile
        late = create_user(self.connection, username="bfc.late", display_name="late", profile_code="DATA_BALTREK", password="pw-late-" + uuid4().hex)
        self.assertEqual(sector_codes_for_user(self.connection, late.user_id), frozenset())

    async def test_a_user_with_several_profiles_gets_exactly_one_grant_and_inactive_profiles_or_users_none(self):
        database = copy_database(f3.STATE["template"], "vinto_bfmulti")
        try:
            with scope.connect(database) as connection:
                connection.execute("DROP TABLE vinto_master.user_sector")
                multi = create_user(connection, username="bfm.multi", display_name="multi", profile_code="JEFATURA", password="pw-" + uuid4().hex).user_id
                connection.execute("INSERT INTO vinto_master.user_profile (user_id, profile_id) SELECT %s, id FROM vinto_master.profile WHERE code IN ('CALIDAD','DATA_BALTREK')", (multi,))
                only_inactive_profile = create_user(connection, username="bfm.inactiveprofile", display_name="ip", profile_code="SUPERVISION", password="pw-" + uuid4().hex).user_id
                connection.execute("UPDATE vinto_master.profile SET active=false WHERE code='SUPERVISION'")
                gone = create_user(connection, username="bfm.gone", display_name="gone", profile_code="OPERACION", password="pw-" + uuid4().hex).user_id
                connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s', (gone,))
                connection.execute((MIGRATIONS / "0006_user_sector_grants.sql").read_text(encoding="utf-8"))
                rows = lambda user: connection.execute("SELECT count(*) FROM vinto_master.user_sector WHERE user_id=%s", (user,)).fetchone()[0]
                self.assertEqual((rows(multi), rows(only_inactive_profile), rows(gone)), (1, 0, 0))
                self.assertEqual(connection.execute("SELECT count(*) FROM vinto_master.user_sector").fetchone()[0], 1)
        finally:
            drop_database(database)

    async def test_the_backfill_never_grants_missing_or_future_sectors(self):
        database = copy_database(f3.STATE["template"], "vinto_bfempty")
        try:
            with scope.connect(database) as connection:
                connection.execute("DROP TABLE vinto_master.user_sector")
                create_user(connection, username="bfe.a", display_name="a", profile_code="DATA_BALTREK", password="pw-" + uuid4().hex)
                connection.execute("UPDATE vinto_master.sector SET code = 'RENOMBRADO' WHERE code = 'BOBINAS'")  # BOBINAS does not exist in this database
                connection.execute((MIGRATIONS / "0006_user_sector_grants.sql").read_text(encoding="utf-8"))
                self.assertEqual(connection.execute("SELECT count(*) FROM vinto_master.user_sector").fetchone()[0], 0)
        finally:
            drop_database(database)


if __name__ == "__main__":
    unittest.main()
