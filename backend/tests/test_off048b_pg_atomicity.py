"""OFF-04.8B: technical receipt and candidate side effect share a real PostgreSQL transaction.

Uses a NEW disposal-only *_test database created by off044_support. The candidate
side effect intentionally targets a temporary *test-only* table, not the industrial
schema; a later gate must exercise the actual online Quality services on PG17.
"""
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.offline_capture import contract as C
from app.offline_capture.service import PromotionReview, StoreUnavailable, receive_capture, reconcile_capture
from tests.off044_support import (USER_A, SyntheticAuthorizer, ScriptedContext, capture, make_pg_store, pg_available,
                                  principal)


class Accept:
    def validate(self, user, incoming):
        return SimpleNamespace(ok=True, errors=(), calculated={}, version_mismatch=False, context_kind=None)


class ProofPromoter:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = 0

    def promote(self, user, incoming, tx):
        self.calls += 1
        tx.c.execute("INSERT INTO off048_test_proof (capture_id) VALUES (%s)", (incoming.capture_id,))
        if self.mode == "outage":
            raise StoreUnavailable("simulated_crash_after_operational_write")
        if self.mode == "review":
            # The proof row is inside an explicit savepoint, which must be
            # rolled back before the outer transaction can retain a review.
            raise PromotionReview("synthetic_review")
        return SimpleNamespace(capture_id=incoming.capture_id)


@pytest.fixture
def prepared():
    if not pg_available():
        if os.environ.get("OFF046_REQUIRE_PG") == "1":
            pytest.fail("OFF-04.8B requires PostgreSQL 17 in CI")
        pytest.skip("no disposable postgres available")
    store = make_pg_store()
    with store.transaction() as tx:
        tx.c.execute("CREATE TABLE off048_test_proof (capture_id uuid PRIMARY KEY)")
    return store


def receive(store, body, promoter):
    return receive_capture(store, principal(USER_A), C.CaptureIn(**body),
                           authorizer=SyntheticAuthorizer(), context=ScriptedContext(),
                           validator=Accept(), promoter=promoter)


def count_proofs(store):
    with store.transaction() as tx:
        return tx.c.execute("SELECT COUNT(*) FROM off048_test_proof").fetchone()[0]


def count_receipts(store):
    with store.transaction() as tx:
        return tx.c.execute("SELECT COUNT(*) FROM vinto_offline.capture_receipt").fetchone()[0]


def test_postgres_commit_and_replayed_ack_are_exactly_once(prepared):
    body, promoter = capture(), ProofPromoter()
    first = receive(prepared, body, promoter)
    assert first.status == 201 and first.body["operational_registered"] is True
    assert count_proofs(prepared) == 1 and count_receipts(prepared) == 1
    second = receive(prepared, body, promoter)
    assert second.status == 200 and second.body["operational_registered"] is True
    assert promoter.calls == 1 and count_proofs(prepared) == 1
    lookup = reconcile_capture(prepared, principal(USER_A), C.CaptureIn(**body).capture_id)
    assert lookup.status == 200 and lookup.body["operational_registered"] is True


def test_postgres_rollback_both_on_error_after_operational_side_effect(prepared):
    body = capture()
    with pytest.raises(StoreUnavailable):
        receive(prepared, body, ProofPromoter(mode="outage"))
    assert count_proofs(prepared) == 0 and count_receipts(prepared) == 0
    assert receive(prepared, body, ProofPromoter()).status == 201
    assert count_proofs(prepared) == 1 and count_receipts(prepared) == 1


def test_postgres_review_rolls_back_candidate_side_effect_via_savepoint(prepared):
    # The PROMOTER intentionally has no savepoint. The RECEIVER owns it.
    body = capture()
    result = receive(prepared, body, ProofPromoter(mode="review"))
    assert result.status == 202 and result.body["operational_registered"] is False
    assert count_receipts(prepared) == 1 and count_proofs(prepared) == 0


def test_postgres_review_and_valid_capture_are_independent(prepared):
    bad, good = capture(), capture()
    assert receive(prepared, bad, ProofPromoter(mode="review")).status == 202
    assert receive(prepared, good, ProofPromoter()).status == 201
    assert count_receipts(prepared) == 2 and count_proofs(prepared) == 1
