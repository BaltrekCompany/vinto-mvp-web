"""HTTP + PostgreSQL 17 integration tests for GET /api/reports/tubetes-used.

All data is generated in a disposable *_test database. No production/VPS data
is read or modified by this test module.
"""

import secrets
import unittest
from uuid import uuid4

from pydantic import SecretStr

from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from tests.test_assignments_api import PROFILES, call, order_body
except ModuleNotFoundError:
    from test_assignments_api import PROFILES, call, order_body

STATE = {}
VALUES = {
    "hora_inicio": "07:15",
    "hora_fin": "08:40",
    "diametro": "1200.5",
    "peso_kg": "845.25",
    "numero_de_cortes": "3",
    "metraje": "1200",
    "codigo_de_tubete": "47",
    "observaciones": "fixture sintetico TUB-02",
}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_tubetes_api_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE.pop("template"))


class TubetesReportApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_tubetes_api")
        cls.connection = connect(cls.database)
        cls.patcher = __import__("unittest.mock", fromlist=["patch"]).patch.object(
            settings, "database_url", SecretStr(database_url(cls.database))
        )
        cls.patcher.start()
        cls.users, cls.cookies = {}, {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (
                create_user(
                    cls.connection,
                    username=f"tubetes.{profile.lower()}",
                    display_name=f"TUB-02 {profile}",
                    profile_code=profile,
                    password=password,
                    sectors=("BOBINAS",),
                ),
                password,
            )

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        # Tests share only this disposable database; finish any assignment left
        # active by the previous test before constructing the next synthetic OT.
        self.connection.execute(
            "UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'"
        )

    async def cookie(self, profile):
        if profile not in self.cookies:
            created, password = self.users[profile]
            login = await call(
                "POST", "/api/auth/login",
                json_body={"username": created.username, "password": password},
            )
            self.assertEqual(login.status, 200, profile)
            self.cookies[profile] = login.set_cookie_value()
        return self.cookies[profile]

    async def assignment(self, machine="MP1"):
        order_reply = await call(
            "POST", "/api/work-orders", json_body=order_body(machine),
            cookie=await self.cookie("JEFATURA"),
        )
        self.assertEqual(order_reply.status, 201, order_reply.text)
        order = await call(
            "POST", f"/api/work-orders/{order_reply.json()['id']}/publish",
            cookie=await self.cookie("JEFATURA"),
        )
        self.assertEqual(order.status, 200, order.text)
        published = order.json()
        activation = await call(
            "POST", "/api/assignments/activate",
            cookie=await self.cookie("SUPERVISION"),
            json_body={
                "work_order_id": published["id"],
                "baseline_line_id": published["baseline"]["lines"][0]["id"],
            },
        )
        self.assertEqual(activation.status, 201, activation.text)
        return activation.json()["assignment"]

    def payload(self, assignment, code):
        return {
            "capture_id": str(uuid4()),
            "assignment_id": assignment["id"],
            "device_key": str(uuid4()),
            "values": {**VALUES, "codigo_de_tubete": str(code)},
        }

    async def submit_bobbin(self, assignment, code):
        reply = await call(
            "POST", "/api/bobbins", json_body=self.payload(assignment, code),
            cookie=await self.cookie("OPERACION"),
        )
        self.assertEqual(reply.status, 201, reply.text)
        return reply.json()["bobbin"]

    async def decide(self, bobbin_id, action):
        body = {"decision_id": str(uuid4()), "action": action}
        if action == "reject":
            body.update(
                rejection_type="rechazado",
                classification="humedad",
                detail="Fixture sintético de rechazo TUB-02",
                corrective_action="Separar fixture para QA",
            )
        reply = await call(
            "POST", f"/api/quality/bobbins/{bobbin_id}/decision",
            json_body=body, cookie=await self.cookie("CALIDAD"),
        )
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual(reply.json()["status"], "released" if action == "release" else "rejected")

    async def report(self, profile="JEFATURA", query=""):
        return await call(
            "GET", "/api/reports/tubetes-used" + query,
            cookie=await self.cookie(profile),
        )

    def header(self, reply, name):
        key = name.lower().encode()
        return next((value.decode() for current, value in reply.headers if current.lower() == key), None)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    async def test_endpoint_requires_session_and_sets_private_no_store(self):
        reply = await call("GET", "/api/reports/tubetes-used")
        self.assertEqual(reply.status, 401)
        self.assertEqual(self.header(reply, "cache-control"), "private, no-store")

    async def test_only_jefatura_and_supervision_with_bobinas_can_read(self):
        for profile in ("JEFATURA", "SUPERVISION"):
            reply = await self.report(profile)
            self.assertEqual(reply.status, 200, reply.text)
            self.assertEqual(self.header(reply, "cache-control"), "private, no-store")
        for profile in ("OPERACION", "CALIDAD", "DATA_BALTREK"):
            reply = await self.report(profile)
            self.assertEqual(reply.status, 403, profile)
            self.assertEqual(self.header(reply, "cache-control"), "private, no-store")

        no_sector_password = "pw-" + secrets.token_urlsafe(18)
        no_sector = create_user(
            self.connection,
            username=f"tubetes.no-sector.{uuid4().hex[:8]}",
            display_name="TUB-02 Jefatura sin sector",
            profile_code="JEFATURA",
            password=no_sector_password,
            sectors=(),
        )
        login = await call(
            "POST", "/api/auth/login",
            json_body={"username": no_sector.username, "password": no_sector_password},
        )
        self.assertEqual(login.status, 200)
        denied = await call("GET", "/api/reports/tubetes-used", cookie=login.set_cookie_value())
        self.assertEqual(denied.status, 403)
        self.assertEqual(self.header(denied, "cache-control"), "private, no-store")

    async def test_report_includes_mp1_mp3_and_pending_released_rejected_bobbins(self):
        mp1_assignment = await self.assignment("MP1")
        pending = await self.submit_bobbin(mp1_assignment, 901)
        released = await self.submit_bobbin(mp1_assignment, 901)
        await self.decide(released["id"], "release")

        mp3_assignment = await self.assignment("MP3")
        rejected = await self.submit_bobbin(mp3_assignment, 901)
        await self.decide(rejected["id"], "reject")

        statuses = {
            row[0]: row[1]
            for row in self.connection.execute(
                """SELECT b.id, q.status FROM vinto_txn.bobbin b
                   JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
                   WHERE b.id = ANY(%s)""",
                ([pending["id"], released["id"], rejected["id"]],),
            ).fetchall()
        }
        self.assertEqual(statuses, {
            pending["id"]: "pending",
            released["id"]: "released",
            rejected["id"]: "rejected",
        })

        reply = await self.report()
        self.assertEqual(reply.status, 200, reply.text)
        data = reply.json()
        self.assertEqual((data["source_form"], data["date_basis"], data["timezone"]),
                         ("VINTO-P1-03", "operating_date", "America/La_Paz"))
        self.assertEqual([machine["machine"] for machine in data["machines"]], ["MP1", "MP3"])
        mp1, mp3 = data["machines"]
        mp1_code = next(item for item in mp1["tubetes"] if item["code"] == "901")
        mp3_code = next(item for item in mp3["tubetes"] if item["code"] == "901")
        self.assertEqual((mp1_code["usage_count"], len(mp1_code["dates"])), (2, 2))
        self.assertEqual((mp3_code["usage_count"], len(mp3_code["dates"])), (1, 1))
        self.assertEqual((mp1["usage_total"], mp3["usage_total"]), (2, 1))

    async def test_twenty_three_uses_on_the_same_day_are_not_deduplicated_or_limited(self):
        assignment = await self.assignment("MP1")
        for _ in range(23):
            await self.submit_bobbin(assignment, 902)

        reply = await self.report()
        self.assertEqual(reply.status, 200, reply.text)
        mp1 = reply.json()["machines"][0]
        tubete = next(item for item in mp1["tubetes"] if item["code"] == "902")
        self.assertEqual(tubete["usage_count"], 23)
        self.assertEqual(len(tubete["dates"]), 23)
        self.assertEqual(len(set(tubete["dates"])), 1)
        self.assertEqual(mp1["usage_total"], 23)

    async def test_client_query_cannot_change_server_owned_machine_scope(self):
        reply = await self.report(query="?machine=OTHER&sector=CONVERSION")
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual([machine["machine"] for machine in reply.json()["machines"]], ["MP1", "MP3"])

    async def test_report_query_writes_no_business_or_audit_rows(self):
        assignment = await self.assignment("MP1")
        await self.submit_bobbin(assignment, 903)
        # Authenticate before the snapshot so login/session activity is outside the measured window.
        cookie = await self.cookie("JEFATURA")
        tables = (
            "vinto_txn.capture",
            "vinto_txn.capture_detail",
            "vinto_txn.bobbin",
            "vinto_txn.quality_release",
            "vinto_audit.audit_event",
        )
        before = {table: self.scalar(f"SELECT count(*) FROM {table}") for table in tables}
        reply = await call("GET", "/api/reports/tubetes-used", cookie=cookie)
        self.assertEqual(reply.status, 200, reply.text)
        after = {table: self.scalar(f"SELECT count(*) FROM {table}") for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.header(reply, "cache-control"), "private, no-store")


if __name__ == "__main__":
    unittest.main()
