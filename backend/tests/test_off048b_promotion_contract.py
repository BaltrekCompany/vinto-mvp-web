"""OFF-04.8B: opt-in operational acknowledgement is atomic with receipt.

Synthetic in-memory SQLite test store, injected validator/promoter. These contracts
MUST NOT be confused with PostgreSQL integration: shared transaction with the real
online Quality services will be verified in a disposable PG17 test separately.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.offline_capture import contract as C
from app.offline_capture.service import (ContextVerdict, PromotionReview, StoreUnavailable,
                                         receive_capture, reconcile_capture)
from tests.off044_support import USER_A, USER_B, SyntheticAuthorizer, ScriptedContext, capture, make_sqlite_store, principal


class GoodValidator:
    def __init__(self, *, ok=True):
        self.ok = ok
        self.calls = 0

    def validate(self, user, incoming):
        self.calls += 1
        return SimpleNamespace(ok=self.ok, context_kind=None, version_mismatch=False,
                               errors=[] if self.ok else [("test", "invalid")], calculated={})


class FakePromoter:
    def __init__(self, *, result="ok"):
        self.result = result
        self.calls = 0

    def promote(self, user, incoming, tx):
        self.calls += 1
        if self.result == "review":
            raise PromotionReview("operational_context_changed")
        if self.result == "outage":
            raise StoreUnavailable("operational_unavailable")
        if self.result == "crash":
            raise RuntimeError("unexpected")
        if self.result == "wrong_ack":
            return SimpleNamespace(capture_id=uuid4())
        return SimpleNamespace(capture_id=incoming.capture_id)


def send(store, body, *, validator=None, promoter=None):
    return receive_capture(store, principal(USER_A), C.CaptureIn(**body),
                           authorizer=SyntheticAuthorizer(), context=ScriptedContext(),
                           validator=validator, promoter=promoter)


def test_default_technical_receiver_retains_old_response_shape_and_does_not_promote():
    store, body = make_sqlite_store(), capture()
    reply = send(store, body, validator=GoodValidator())
    assert reply.status == 201
    assert "operational_registered" not in reply.body
    assert "operational_capture_id" not in reply.body
    receipt = store.get(C.CaptureIn(**body).capture_id)
    assert "operational_registered" not in receipt.response_body


def test_opt_in_promotion_ack_persists_and_is_reused_without_second_write():
    store, body, promoter = make_sqlite_store(), capture(), FakePromoter()
    first = send(store, body, validator=GoodValidator(), promoter=promoter)
    assert first.status == 201 and first.body["operational_registered"] is True
    assert first.body["operational_capture_id"] == body["capture_id"]
    second = send(store, body, validator=GoodValidator(), promoter=promoter)
    assert second.status == 200 and second.body["outcome"] == "duplicate"
    assert second.body["operational_registered"] is True and promoter.calls == 1
    lookup = reconcile_capture(store, principal(USER_A), C.CaptureIn(**body).capture_id)
    assert lookup.status == 200 and lookup.body["operational_registered"] is True
    assert lookup.body["operational_capture_id"] == body["capture_id"]
    assert store.counts() == {"receipts": 1, "events": 2}


@pytest.mark.parametrize("failure", ["outage", "crash", "wrong_ack"])
def test_temporary_error_or_wrong_ack_rolls_back_new_technical_receipt(failure):
    store, body = make_sqlite_store(), capture()
    with pytest.raises(StoreUnavailable):
        send(store, body, validator=GoodValidator(), promoter=FakePromoter(result=failure))
    assert store.counts() == {"receipts": 0, "events": 0}


def test_deterministic_operational_exception_records_review_not_registered():
    store, body, promoter = make_sqlite_store(), capture(), FakePromoter(result="review")
    reply = send(store, body, validator=GoodValidator(), promoter=promoter)
    assert reply.status == 202
    assert reply.body["reason"] == "operational_context_changed"
    assert reply.body["operational_registered"] is False
    assert "operational_capture_id" not in reply.body
    receipt = store.get(C.CaptureIn(**body).capture_id)
    assert receipt.outcome == "review"
    assert store.counts() == {"receipts": 1, "events": 1}


def test_review_from_central_validator_never_promotes():
    store, body, promoter = make_sqlite_store(), capture(), FakePromoter()
    reply = send(store, body, validator=GoodValidator(ok=False), promoter=promoter)
    assert reply.status == 202 and reply.body["operational_registered"] is False
    assert promoter.calls == 0


def test_explicit_promotion_requires_the_validator():
    store = make_sqlite_store()
    with pytest.raises(StoreUnavailable, match="operational_requires_validator"):
        send(store, capture(), promoter=FakePromoter())
    assert store.counts() == {"receipts": 0, "events": 0}


def test_conflicted_identity_does_not_invoke_promoter():
    store, body, promoter = make_sqlite_store(), capture(), FakePromoter()
    body["author_user_id"] = str(USER_B)
    reply = send(store, body, validator=GoodValidator(), promoter=promoter)
    assert reply.status == 403 and promoter.calls == 0


def test_unknown_context_does_not_invoke_promoter():
    store, body, promoter = make_sqlite_store(), capture(context="ctx-unknown"), FakePromoter()
    reply = send(store, body, validator=GoodValidator(), promoter=promoter)
    assert reply.status == 202 and reply.body["operational_registered"] is False
    assert promoter.calls == 0
