"""RB-CRIA-01: PostgreSQL17 + HTTP reales en base efímera. Nunca producción."""
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service
from app.assignments import service as assignments_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import (
    build_reference_template, connect, copy_database, database_url, drop_database,
)
from app.seed.bundle import load_bundle

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

BUNDLE = load_bundle()
P107 = next(form for form in BUNDLE.forms if form["code"] == "VINTO-P1-07")
ARTICLE = next(x["article_code"] for x in BUNDLE.article_machines if x["machine_code"] == "COPASA")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_rbcria_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class RewindingQualityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_rbcria")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD"):
            password = "rbcria-" + secrets.token_urlsafe(18)
            created = create_user(cls.connection, username="rbcria." + profile.lower(),
                                  display_name="QA " + profile, profile_code=profile,
                                  password=password, sectors=("BOBINAS", "REBOBINADO"))
            cls.users[profile] = (created, password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute(
            "UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'"
        )
        for target in (capture_service, assignments_service):
            mocked = patch.object(target, "_now", return_value=DAY)
            mocked.start()
            self.addCleanup(mocked.stop)

    async def cookie(self, profile):
        if profile not in self.cookies:
            created, password = self.users[profile]
            result = await call("POST", "/api/auth/login",
                                json_body={"username": created.username, "password": password})
            self.assertEqual(result.status, 200, result.text)
            self.cookies[profile] = result.set_cookie_value()
        return self.cookies[profile]

    async def assignment(self):
        order = await call("POST", "/api/work-orders", cookie=await self.cookie("JEFATURA"),
                           json_body={"machine_code": "COPASA", "lines": [
                               {"pv_reference": "PV-RB-CRIA", "article_code": ARTICLE,
                                "quantity": 10, "due_date": "2026-11-01"}]})
        self.assertEqual(order.status, 201, order.text)
        published = await call("POST", f"/api/work-orders/{order.json()['id']}/publish",
                               cookie=await self.cookie("JEFATURA"))
        self.assertEqual(published.status, 200, published.text)
        published = published.json()
        assigned = await call("POST", "/api/assignments/activate",
                              cookie=await self.cookie("SUPERVISION"),
                              json_body={"work_order_id": published["id"],
                                         "baseline_line_id": published["baseline"]["lines"][0]["id"]})
        self.assertEqual(assigned.status, 201, assigned.text)
        return assigned.json()["assignment"]

    def values(self, **weights):
        values = {}
        for f in P107["fields"]:
            if f["required"]:
                values[f["key"]] = ("06:30" if f["value_type"] == "time" else
                                    "1.50" if f["value_type"] == "decimal" else "qa-texto")
        values.update(etiqueta_numero_de_bobina="MADRE-TEXTO-0001",
                      peso_cria_1="12.50", diametro="1200")
        values.update(weights)
        return values

    async def capture(self, assignment, values, *, capture_id=None, device_key=None):
        body = {"capture_id": capture_id or str(uuid4()), "form_code": "VINTO-P1-07",
                "assignment_id": assignment["id"], "device_key": device_key or str(uuid4()),
                "values": values}
        return await call("POST", "/api/captures", json_body=body,
                          cookie=await self.cookie("OPERACION")), body

    def children(self, capture_id):
        return self.connection.execute(
            """SELECT b.id, b.rewind_child_position, b.rewind_mother_label, b.weight_kg,
                      q.status, b.sequence_number, b.management_start_year
               FROM vinto_txn.bobbin b JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
               WHERE b.source_capture_id=%s ORDER BY b.rewind_child_position""",
            (capture_id,),
        ).fetchall()

    async def inbox(self, status="pending"):
        result = await call("GET", f"/api/quality/bobbins?status={status}",
                            cookie=await self.cookie("CALIDAD"))
        self.assertEqual(result.status, 200, result.text)
        return result.json()

    def count(self, table):
        return self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    async def test_one_and_three_children_with_real_independent_pending_states(self):
        self.assertEqual(P107["version_number"], 4)
        self.assertEqual(sum(x["required"] for x in P107["fields"] if x["key"].startswith("peso_cria_")), 1)
        assignment = await self.assignment()
        result, body = await self.capture(assignment, self.values(
            peso_cria_2="11.25", peso_cria_13="9.80"))
        self.assertEqual(result.status, 201, result.text)
        capture_id = body["capture_id"]
        rows = self.children(capture_id)
        self.assertEqual([r[1] for r in rows], [1, 2, 13])
        self.assertEqual([str(r[3]) for r in rows], ["12.50", "11.25", "9.80"])
        self.assertTrue(all(r[2] == "MADRE-TEXTO-0001" and r[4] == "pending"
                            and r[5] is None and r[6] is None for r in rows))
        items = [x for x in await self.inbox()
                 if x["production"]["capture_id"] == capture_id]
        self.assertEqual(len(items), 3)
        self.assertEqual(sorted(x["bobbin"]["rewinding"]["child_position"] for x in items), [1, 2, 13])
        for entry in items:
            self.assertEqual(entry["bobbin"]["rewinding"]["mother_label"], "MADRE-TEXTO-0001")
            self.assertEqual(entry["bobbin"]["machine"]["code"], "COPASA")
            self.assertEqual(entry["production"]["line"]["pv_reference"], "PV-RB-CRIA")
            self.assertIsNone(entry["bobbin"]["sequence_number"])
            self.assertIsNone(entry["bobbin"]["number_of_cuts"])

    async def test_v4_four_optional_fields_omitted_creates_children_and_quality(self):
        optional = {"producto_refilado", "auxiliar", "formato_2", "formato_3"}
        assert all(not f["required"] for f in P107["fields"] if f["key"] in optional)
        assignment = await self.assignment()
        values = self.values(peso_cria_2="11.25", peso_cria_13="9.80")
        self.assertTrue(optional.isdisjoint(values))
        result, body = await self.capture(assignment, values)
        self.assertEqual(result.status, 201, result.text)
        rows = self.children(body["capture_id"])
        self.assertEqual([r[1] for r in rows], [1, 2, 13])
        self.assertTrue(all(r[4] == "pending" for r in rows))

    async def test_all_21_supported_positions_generate_21_distinct_pending_children(self):
        assignment = await self.assignment()
        positions = [*range(1, 12), *range(13, 23)]
        values = self.values(**{f"peso_cria_{n}": str(n) + ".50" for n in positions})
        reply, body = await self.capture(assignment, values)
        self.assertEqual(reply.status, 201, reply.text)
        rows = self.children(body["capture_id"])
        self.assertEqual([r[1] for r in rows], positions)
        self.assertTrue(all(r[4] == "pending" for r in rows))
        self.assertEqual(len({r[0] for r in rows}), 21)
        self.assertEqual(len({r[1] for r in rows}), 21)
        items = [i for i in await self.inbox()
                 if i["production"]["capture_id"] == body["capture_id"]]
        self.assertEqual(len(items), 21)
        self.assertNotIn(12, [i["bobbin"]["rewinding"]["child_position"] for i in items])

    async def test_same_capture_retry_does_not_duplicate_children_or_events(self):
        assignment = await self.assignment()
        capture_id, device_key = str(uuid4()), str(uuid4())
        values = self.values(peso_cria_3="8.40")
        first, _ = await self.capture(assignment, values, capture_id=capture_id, device_key=device_key)
        self.assertEqual(first.status, 201, first.text)
        count = len(self.children(capture_id))
        before = self.count("vinto_txn.bobbin")
        replay, _ = await self.capture(assignment, values, capture_id=capture_id, device_key=device_key)
        self.assertEqual(replay.status, 200, replay.text)
        self.assertEqual((len(self.children(capture_id)), self.count("vinto_txn.bobbin")), (count, before))
        conflict, _ = await self.capture(assignment, {**values, "peso_cria_3": "8.41"},
                                         capture_id=capture_id, device_key=device_key)
        self.assertEqual(conflict.status, 409)
        self.assertEqual(len(self.children(capture_id)), count)

    async def test_invalid_or_missing_weights_roll_back_entire_capture(self):
        assignment = await self.assignment()
        base = self.values()
        baseline = tuple(self.count(t) for t in ("vinto_txn.capture", "vinto_txn.bobbin", "vinto_txn.quality_release"))
        for variant in ({k: v for k, v in base.items() if k != "peso_cria_1"},
                        {**base, "peso_cria_2": "-1"},
                        {**base, "peso_cria_1": "0"},
                        {**base, "peso_cria_2": "0"},
                        {**base, "peso_cria_12": "2"}):
            response, _ = await self.capture(assignment, variant)
            self.assertEqual(response.status, 422, response.text)
            self.assertEqual(tuple(self.count(t) for t in ("vinto_txn.capture", "vinto_txn.bobbin", "vinto_txn.quality_release")), baseline)

    async def test_release_reject_only_selected_child_with_authorized_actor(self):
        assignment = await self.assignment()
        result, body = await self.capture(assignment, self.values(peso_cria_2="9.00", peso_cria_3="7.00"))
        self.assertEqual(result.status, 201, result.text)
        ids = [r[0] for r in self.children(body["capture_id"])]
        release = {"decision_id": str(uuid4()), "action": "release"}
        reject = {"decision_id": str(uuid4()), "action": "reject",
                  "rejection_type": "rechazado", "classification": "defecto_visible",
                  "detail": "No conformidad de QA", "corrective_action": "Segregar cría"}
        endpoint = lambda i: f"/api/quality/bobbins/{i}/decision"
        denied = await call("POST", endpoint(ids[0]), json_body=release,
                            cookie=await self.cookie("OPERACION"))
        self.assertEqual(denied.status, 403)
        for i, data in ((0, release), (1, reject)):
            decided = await call("POST", endpoint(ids[i]), json_body=data,
                                 cookie=await self.cookie("CALIDAD"))
            self.assertEqual((decided.status, decided.json()["status"]),
                             (200, "released" if i == 0 else "rejected"), decided.text)
        self.assertEqual([r[4] for r in self.children(body["capture_id"])],
                         ["released", "rejected", "pending"])
        same = await call("POST", endpoint(ids[1]), json_body=reject,
                          cookie=await self.cookie("CALIDAD"))
        self.assertEqual((same.status, same.json()["already_decided"]), (200, True))
        different = await call("POST", endpoint(ids[1]),
                               json_body={**reject, "decision_id": str(uuid4())},
                               cookie=await self.cookie("CALIDAD"))
        self.assertEqual(different.status, 409)
        pending = await self.inbox()
        self.assertEqual([x["bobbin"]["rewinding"]["child_position"] for x in pending
                          if x["production"]["capture_id"] == body["capture_id"]], [3])
        self.assertEqual(sum(x["bobbin"]["id"] == str(ids[0]) for x in await self.inbox("released")), 1)
        self.assertEqual(sum(x["bobbin"]["id"] == str(ids[1]) for x in await self.inbox("rejected")), 1)

    async def test_unnumbered_legacy_bobbin_still_not_in_quality(self):
        self.connection.execute("INSERT INTO vinto_txn.bobbin (code) VALUES (%s)", ("QA-LEGACY-"+str(uuid4()),))
        found = await self.inbox()
        self.assertFalse(any(x["bobbin"]["code"].startswith("QA-LEGACY") for x in found))
