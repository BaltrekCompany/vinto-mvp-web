"""RG-MP3-01: pruebas HTTP con PostgreSQL 17 efímero (nunca producción).

Verifica contrato, oferta MP1/MP3, requeridos, idempotencia,
unicidad atómica por fecha operativa+turno y persistencia tipada.
"""
import asyncio
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service
from app.assignments import service as assignment_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

RG = "VINTO-MP3-01"
P101 = "VINTO-P1-01"
DAY = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in ("MP1", "MP3")}
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_rg01_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class RG01Tests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_rg01")
        cls.connection = connect(cls.database)
        cls.patch_db = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patch_db.start()
        cls.users, cls.cookies = {}, {}
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION"):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (
                create_user(cls.connection, username="rg01." + profile.lower(), display_name=profile, profile_code=profile,
                            password=password, sectors=("BOBINAS",)),
                password,
            )

    @classmethod
    def tearDownClass(cls):
        cls.patch_db.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        for target in (capture_service, assignment_service):
            p = patch.object(target, "_now", return_value=DAY)
            p.start()
            self.addCleanup(p.stop)

    async def cookie(self, profile):
        if profile not in self.cookies:
            user, password = self.users[profile]
            r = await call("POST", "/api/auth/login",
                           json_body={"username": user.username, "password": password})
            self.assertEqual(r.status, 200, r.text)
            self.cookies[profile] = r.set_cookie_value()
        return self.cookies[profile]

    async def assignment(self, machine):
        r = await call("POST", "/api/work-orders",
                       json_body={"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE[machine],
                                                                         "quantity": 10, "due_date": "2026-11-30"}]},
                       cookie=await self.cookie("JEFATURA"))
        self.assertEqual(r.status, 201, r.text)
        r = await call("POST", f"/api/work-orders/{r.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))
        self.assertEqual(r.status, 200, r.text)
        order = r.json()
        r = await call("POST", "/api/assignments/activate",
                       json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]},
                       cookie=await self.cookie("SUPERVISION"))
        self.assertEqual(r.status, 201, r.text)
        return r.json()["assignment"]

    def values(self, *, include_optional=False):
        out = {}
        for i, f in enumerate(FORMS[RG]["fields"]):
            if not f["required"] and not include_optional:
                continue
            out[f["key"]] = "07:30" if f["value_type"] == "time" else (
                "test RG01" if f["value_type"] in ("text", "textarea") else f"{i + 1}.25")
        return out

    async def post(self, assignment, *, code=RG, values=None, capture_id=None, device_key=None):
        body = {"capture_id":capture_id or str(uuid4()), "form_code":code,
                "assignment_id":assignment["id"], "device_key":device_key or str(uuid4()),
                "values": self.values() if values is None else values}
        r = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        return r, body

    async def test_01_machine_availability_replaces_mp3_only(self):
        r = await call("GET", "/api/production/machines", cookie=await self.cookie("OPERACION"))
        self.assertEqual(r.status, 200, r.text)
        availability = {m["code"]:{f["code"] for f in m["forms"]} for s in r.json()["sectors"] for m in s["machines"]}
        self.assertIn(P101, availability["MP1"])
        self.assertNotIn(RG, availability["MP1"])
        self.assertIn(RG, availability["MP3"])
        self.assertNotIn(P101, availability["MP3"])

    async def test_02_only_pulper_required_and_optional_absent(self):
        self.assertEqual((len(FORMS[RG]["fields"]), len(self.values())), (133, 7))
        assignment = await self.assignment("MP3")
        bad = dict(self.values())
        bad.pop(next(iter(bad)))
        r, _ = await self.post(assignment, values=bad)
        self.assertEqual((r.status, r.json()["code"]), (422, "CAPTURE_VALIDATION"))
        r, body = await self.post(assignment, values=self.values())
        self.assertEqual(r.status, 201, r.text)
        c = r.json()["capture"]
        self.assertEqual((c["form"]["code"], c["machine"]["code"], c["shift"]["code"]), (RG, "MP3", "DIA"))
        self.assertEqual(c["values"], self.values())
        rows = self.connection.execute(
            "SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id=%s", (body["capture_id"],)).fetchone()[0]
        self.assertEqual(rows, 7)

    async def test_03_reject_wrong_machine_and_legacy_on_mp3(self):
        a1 = await self.assignment("MP1")
        r, _ = await self.post(a1)
        self.assertEqual((r.status, r.json()["code"]), (409, "FORM_NOT_AVAILABLE"))
        # La captura antigua sigue permitida en MP1 si la definición está publicada.
        old_values = {f["key"]: ("07:30" if f["value_type"] == "time" else
                                  "dato" if f["value_type"] in ("text", "textarea") else "1.25")
                      for f in FORMS[P101]["fields"] if f["required"]}
        r, _ = await self.post(a1, code=P101, values=old_values)
        self.assertEqual(r.status, 201, r.text)
        a3 = await self.assignment("MP3")
        r, _ = await self.post(a3, code=P101, values=old_values)
        self.assertEqual((r.status, r.json()["code"]), (409, "FORM_NOT_AVAILABLE"))

    async def test_04_one_per_shift_and_idempotent_retry(self):
        a = await self.assignment("MP3")
        r, body = await self.post(a)
        self.assertEqual(r.status, 201, r.text)
        same = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual((same.status, same.json()["already_submitted"]), (200, True))
        r, _ = await self.post(a)
        self.assertEqual((r.status, r.json()["code"]), (409, "SHIFT_CAPTURE_ALREADY_EXISTS"))

    async def test_05_two_concurrent_submits_differing_id(self):
        a = await self.assignment("MP3")
        async def submit():
            return (await self.post(a))[0]
        r1, r2 = await asyncio.gather(submit(), submit())
        self.assertEqual(sorted([r1.status, r2.status]), [201, 409], (r1.text, r2.text))
        self.assertEqual(
            sum(1 for r in (r1,r2) if r.status==409 and r.json().get("code")=="SHIFT_CAPTURE_ALREADY_EXISTS"), 1
        )


if __name__ == "__main__":
    unittest.main()
