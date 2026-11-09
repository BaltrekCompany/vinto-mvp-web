"""Tests aislados de la transicion de decision, permisos de alcance y reintentos.

Estos tests de unidad no sustituyen el gate de integración con PostgreSQL 17.
"""
import unittest
from contextlib import nullcontext
from uuid import uuid4

from fastapi import HTTPException

from app.quality.decision_service import decide_bobbin
from app.quality.decision_schemas import QualityDecisionIn


class Cursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "FOR UPDATE OF q" in sql:
            return Cursor(self.row)
        if "UPDATE vinto_txn.quality_release" in sql:
            return Cursor((uuid4(),))
        return Cursor(None)


class DecisionServiceTests(unittest.TestCase):
    def setUp(self):
        self.actor = uuid4()
        self.bobbin = uuid4()
        self.decision = uuid4()

    def body(self, action="release"):
        if action == "release":
            return QualityDecisionIn(decision_id=self.decision, action=action)
        return QualityDecisionIn(
            decision_id=self.decision, action="reject",
            rejection_type="rechazado", classification="defecto_visible",
            detail="Marca visible", corrective_action="Segregar y revisar")

    def call(self, conn, body=None, sectors=("BOBINAS",)):
        return decide_bobbin(conn, bobbin_id=self.bobbin, actor_id=self.actor, sectors=sectors,
                             request_id="qa-request", body=body or self.body())

    def test_release_pending_writes_audited_decision(self):
        conn = FakeConnection(("pending", None, None, None, None, None))
        result = self.call(conn)
        self.assertEqual(result["status"], "released")
        self.assertFalse(result["already_decided"])
        updates = [params for sql, params in conn.calls if "UPDATE vinto_txn.quality_release" in sql]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][0], "released")
        self.assertEqual(updates[0][1], self.actor)
        self.assertEqual(updates[0][2], self.decision)
        self.assertEqual(sum("vinto.actor_id" in sql for sql, _ in conn.calls), 1)

    def test_reject_persists_four_fields(self):
        conn = FakeConnection(("pending", None, None, None, None, None))
        result = self.call(conn, self.body("reject"))
        self.assertEqual(result["status"], "rejected")
        updates = [params for sql, params in conn.calls if "UPDATE vinto_txn.quality_release" in sql]
        self.assertEqual(updates[0][4:], ("rechazado", "defecto_visible", "Marca visible",
                                        "Segregar y revisar", self.bobbin))

    def test_idempotent_same_request_read_only(self):
        conn = FakeConnection(("released", self.decision, None, None, None, None))
        result = self.call(conn)
        self.assertTrue(result["already_decided"])
        self.assertFalse(any("UPDATE vinto_txn.quality_release" in sql for sql, _ in conn.calls))

    def test_stale_or_different_decision_returns_409(self):
        for row in (("rejected", self.decision, "rechazado", "defecto_visible", "Marca visible", "Segregar y revisar"),
                    ("released", uuid4(), None, None, None, None)):
            with self.subTest(row=row):
                conn = FakeConnection(row)
                with self.assertRaises(HTTPException) as captured:
                    self.call(conn)
                self.assertEqual(captured.exception.status_code, 409)
                self.assertFalse(any("UPDATE vinto_txn.quality_release" in sql for sql, _ in conn.calls))

    def test_no_scope_is_404_without_query(self):
        conn = FakeConnection(("pending", None, None, None, None, None))
        with self.assertRaises(HTTPException) as captured:
            self.call(conn, sectors=("CONVERSION",))
        self.assertEqual(captured.exception.status_code, 404)
        self.assertEqual(conn.calls, [])

    def test_missing_bobbin_is_404_without_mutation(self):
        conn = FakeConnection()
        with self.assertRaises(HTTPException) as captured:
            self.call(conn)
        self.assertEqual(captured.exception.status_code, 404)
        self.assertFalse(any("UPDATE vinto_txn.quality_release" in sql for sql, _ in conn.calls))


if __name__ == "__main__":
    unittest.main()
