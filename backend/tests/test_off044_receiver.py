"""OFF-04.4 receiver scenarios (synthetic data, disposable databases only). Runs on SQLite and, when available, PostgreSQL."""
import json
import os
import pathlib
import re
import threading
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.offline_capture import contract as C
from app.offline_capture.router import create_offline_capture_router
from tests.off044_support import (DEVICE, SNAPSHOT_CAPTURE, SNAPSHOT_CONSULT, USER_A, USER_B, FlakyStore, ScriptedContext, SyntheticAuthorizer,
                                  build_app, capture, h, make_pg_store, make_sqlite_store, pg_available)

KINDS = ["sqlite", "pg"]


@pytest.fixture(params=KINDS)
def store(request):
    if request.param == "pg":
        if not pg_available():
            if os.environ.get("OFF044_REQUIRE_PG") == "1":
                pytest.fail("PostgreSQL is required in CI (OFF044_REQUIRE_PG=1) but is not available")
            pytest.skip("no disposable PostgreSQL available")
        return make_pg_store()
    return make_sqlite_store()


def receipts(store) -> int:
    if hasattr(store, "counts"):
        return store.counts()["receipts"]
    with store.transaction() as tx:
        return tx.c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0]


def events(store, kind=None) -> int:
    with store.transaction() as tx:
        if hasattr(store, "counts"):
            q, p = "SELECT count(*) FROM capture_event" + (" WHERE kind=?" if kind else ""), ((kind,) if kind else ())
        else:
            q, p = "SELECT count(*) FROM vinto_offline.capture_event" + (" WHERE kind=%s" if kind else ""), ((kind,) if kind else ())
        return tx.c.execute(q, p).fetchone()[0]


def client(store, **kw) -> TestClient:
    return TestClient(build_app(store, **kw))


# ---------------------------------------------------------------------------------------------- 1-3
def test_first_receipt_is_created_with_technical_acceptance_only(store):
    c, body = client(store), capture()
    r = c.post("/api/offline/captures", json=body, headers=h())
    assert r.status_code == 201
    j = r.json()
    assert j["outcome"] == "created" and j["capture_id"] == body["capture_id"] and j["server_id"].startswith("srv-")
    assert j["technical_acceptance"] is True and j["industrial_approval"] is False and j["payload_sha256"] == body["payload_sha256"]
    assert r.headers["cache-control"] == "no-store"
    assert receipts(store) == 1


def test_identical_duplicate_is_idempotent_and_reuses_the_persisted_response(store):
    c, body = client(store), capture()
    first = c.post("/api/offline/captures", json=body, headers=h()).json()
    r = c.post("/api/offline/captures", json=body, headers=h())
    assert r.status_code == 200 and r.json()["outcome"] == "duplicate" and r.json()["server_id"] == first["server_id"]
    assert {k: v for k, v in r.json().items() if k != "outcome"} == {k: v for k, v in first.items() if k != "outcome"}
    assert receipts(store) == 1 and events(store, "duplicate") == 1


def test_same_id_with_different_content_is_a_conflict_and_nothing_is_overwritten(store):
    c, body = client(store), capture()
    c.post("/api/offline/captures", json=body, headers=h())
    other = capture({"numero_de_cuba": "OTRO"}, capture_id=body["capture_id"])
    r = c.post("/api/offline/captures", json=other, headers=h())
    assert r.status_code == 409 and r.json()["reason"] == C.R_PAYLOAD_MISMATCH and r.json()["outcome"] == "conflict"
    assert receipts(store) == 1 and store.get(UUID(body["capture_id"])).payload_sha256 == body["payload_sha256"] and events(store, "payload_conflict") == 1


# ---------------------------------------------------------------------------------------------- 4
def test_concurrent_posts_register_exactly_one_capture(store):
    app, body, out = build_app(store), capture(), []
    barrier = threading.Barrier(8)

    def go():
        cl = TestClient(app)
        barrier.wait()
        out.append(cl.post("/api/offline/captures", json=body, headers=h()))
    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    codes = sorted(r.status_code for r in out)
    assert codes == [200] * 7 + [201], codes
    assert len({r.json()["server_id"] for r in out}) == 1 and receipts(store) == 1


# ---------------------------------------------------------------------------------------------- 5-6
def test_lost_response_after_persistence_is_reconciled_by_get_and_retry_is_idempotent(store):
    c, body = client(store), capture()
    c.post("/api/offline/captures", json=body, headers=h())            # the client never saw this answer
    g = c.get("/api/offline/captures/" + body["capture_id"], headers=h())
    assert g.status_code == 200 and g.json()["found"] is True and g.json()["outcome"] == "accepted" and g.json()["industrial_approval"] is False
    assert g.json()["payload_sha256"] == body["payload_sha256"]
    assert c.post("/api/offline/captures", json=body, headers=h()).status_code == 200 and receipts(store) == 1


def test_reconciliation_does_not_leak_existence_to_other_users_or_unknown_ids(store):
    c, body = client(store), capture()
    assert c.get("/api/offline/captures/" + str(uuid4()), headers=h()).json() == {"found": False}
    c.post("/api/offline/captures", json=body, headers=h())
    other = c.get("/api/offline/captures/" + body["capture_id"], headers=h(USER_B))
    assert other.status_code == 404 and other.json() == {"found": False}
    assert c.get("/api/offline/captures/" + body["capture_id"]).status_code == 401


# ---------------------------------------------------------------------------------------------- 7-10
def test_authenticated_user_must_be_the_original_author(store):
    c = client(store)
    r = c.post("/api/offline/captures", json=capture(author=USER_A), headers=h(USER_B))
    assert r.status_code == 403 and r.json()["reason"] == C.R_AUTHOR_MISMATCH and receipts(store) == 0


def test_expired_or_missing_session_is_401_and_persists_nothing(store):
    c = client(store)
    r = c.post("/api/offline/captures", json=capture())
    assert r.status_code == 401 and receipts(store) == 0


def test_capture_without_industrial_permission_is_denied_and_audited_not_stored(store):
    c = client(store, authorizer=SyntheticAuthorizer(grants=set()))
    r = c.post("/api/offline/captures", json=capture(), headers=h())
    assert r.status_code == 403 and r.json()["reason"] == C.R_NOT_AUTHORIZED
    assert receipts(store) == 0 and events(store, "denied") == 1


def test_readonly_snapshot_never_authorises_a_capture_even_with_grants(store):
    c = client(store)
    r = c.post("/api/offline/captures", json=capture(snapshot=SNAPSHOT_CONSULT), headers=h())
    assert r.status_code == 403 and r.json()["reason"] == C.R_READ_ONLY_SCOPE and receipts(store) == 0


def test_default_authorizer_denies_everything():
    from app.offline_capture.service import DenyAllAuthorizer
    from app.offline_capture.contract import CaptureIn
    from tests.off044_support import principal
    for snap in (None, SNAPSHOT_CAPTURE, SNAPSHOT_CONSULT):
        assert DenyAllAuthorizer().authorize(principal(USER_A), CaptureIn(**capture(snapshot=snap))).allowed is False


# ---------------------------------------------------------------------------------------------- 11-13
def test_context_changes_compatible_warns_incompatible_goes_to_review(store):
    c = client(store)
    ok = c.post("/api/offline/captures", json=capture(context="ctx-compat"), headers=h())
    assert ok.status_code == 201 and ok.json()["warnings"] == [C.R_CONTEXT_COMPAT]
    assert c.get("/api/offline/captures/" + ok.json()["capture_id"], headers=h()).json()["outcome"] == "accepted_warning"
    rv = c.post("/api/offline/captures", json=capture(context="ctx-incompat"), headers=h())
    assert rv.status_code == 202 and rv.json()["outcome"] == "review" and rv.json()["reason"] == C.R_CONTEXT_INCOMPATIBLE
    ver = c.post("/api/offline/captures", json=capture(context="ctx-oldform"), headers=h())
    assert ver.status_code == 409 and ver.json()["reason"] == C.R_FORM_VERSION and ver.json()["technical_acceptance"] is False


def test_unverifiable_context_requires_review_and_the_result_is_persisted_for_retries(store):
    from app.offline_capture.service import UnverifiableContext
    c, body = client(store, context=UnverifiableContext()), capture(context="ctx-1")
    r = c.post("/api/offline/captures", json=body, headers=h())
    assert r.status_code == 202 and r.json()["outcome"] == "review" and r.json()["reason"] == C.R_CONTEXT_UNVERIFIABLE
    again = c.post("/api/offline/captures", json=body, headers=h())
    assert again.status_code == 202 and again.json()["server_id"] == r.json()["server_id"] and receipts(store) == 1
    assert c.get("/api/offline/captures/" + body["capture_id"], headers=h()).json()["outcome"] == "review"


def test_integrity_mismatch_is_a_conflict_and_nothing_is_stored(store):
    c, body = client(store), capture()
    body["payload_sha256"] = "0" * 64
    r = c.post("/api/offline/captures", json=body, headers=h())
    assert r.status_code == 409 and r.json()["reason"] == C.R_INTEGRITY and receipts(store) == 0 and events(store, "integrity_conflict") == 1
    floaty = capture(); floaty["payload"] = {"x": 1.5}; floaty["payload_sha256"] = "1" * 64
    assert c.post("/api/offline/captures", json=floaty, headers=h()).status_code == 422
    extra = capture(); extra["approved"] = True                       # no field can ask for approval/release
    assert c.post("/api/offline/captures", json=extra, headers=h()).status_code == 422


# ---------------------------------------------------------------------------------------------- 14-15
def test_temporary_storage_error_is_503_leaves_nothing_and_the_retry_succeeds(store):
    flaky = FlakyStore(store)
    c, body = client(flaky), capture()
    flaky.fail = 1
    r = c.post("/api/offline/captures", json=body, headers=h())
    assert r.status_code == 503 and r.json()["reason"] == C.R_UNAVAILABLE and receipts(store) == 0
    assert c.post("/api/offline/captures", json=body, headers=h()).status_code == 201 and receipts(store) == 1
    flaky.fail = 1
    assert c.get("/api/offline/captures/" + body["capture_id"], headers=h()).status_code == 503


def test_state_survives_a_receiver_restart(tmp_path):
    path = str(tmp_path / "restart.sqlite")
    first = make_sqlite_store(path)
    body = capture()
    created = client(first).post("/api/offline/captures", json=body, headers=h()).json()
    restarted = make_sqlite_store(path)                                  # new process, same database
    c = client(restarted)
    assert c.get("/api/offline/captures/" + body["capture_id"], headers=h()).json()["server_id"] == created["server_id"]
    dup = c.post("/api/offline/captures", json=body, headers=h())
    assert dup.status_code == 200 and dup.json()["server_id"] == created["server_id"]


def test_postgres_state_survives_a_new_connection_and_enforces_immutability():
    if not pg_available():
        pytest.skip("no disposable PostgreSQL available")
    store = make_pg_store()
    c, body = client(store), capture()
    created = c.post("/api/offline/captures", json=body, headers=h()).json()
    other = TestClient(build_app(store))                                 # a brand-new application object, new connections
    assert other.get("/api/offline/captures/" + body["capture_id"], headers=h()).json()["server_id"] == created["server_id"]
    from app.offline_capture.store import StoreUnavailable
    for sql in ("UPDATE vinto_offline.capture_receipt SET author_user_id = gen_random_uuid()", "UPDATE vinto_offline.capture_receipt SET outcome = 'review'",
                "DELETE FROM vinto_offline.capture_receipt", "UPDATE vinto_offline.capture_event SET detail = 'x'", "DELETE FROM vinto_offline.capture_event"):
        with pytest.raises(StoreUnavailable):
            with store.transaction() as tx:
                tx.c.execute(sql)
    assert receipts(store) == 1
    with pytest.raises(StoreUnavailable):                                   # approval can never be set
        with store.transaction() as tx:
            tx.c.execute("UPDATE vinto_offline.capture_receipt SET industrial_approval = true")


# ---------------------------------------------------------------------------------------------- author immutability, disabled receiver
def test_a_capture_id_belongs_to_its_first_author(store):
    c, body = client(store), capture()
    c.post("/api/offline/captures", json=body, headers=h())
    hijack = capture(capture_id=body["capture_id"], author=USER_B)
    r = c.post("/api/offline/captures", json=hijack, headers=h(USER_B))
    assert r.status_code == 409 and r.json()["reason"] == C.R_AUTHOR_IMMUTABLE
    assert store.get(UUID(body["capture_id"])).author_user_id == USER_A and receipts(store) == 1


def test_a_disabled_receiver_accepts_no_writes_and_answers_404(store):
    c = client(store, enabled=False)
    assert c.post("/api/offline/captures", json=capture(), headers=h()).status_code == 404
    assert c.get("/api/offline/captures/" + str(uuid4()), headers=h()).status_code == 404
    assert receipts(store) == 0 and events(store) == 0
    # no store at all behaves the same, even when "enabled"
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(create_offline_capture_router(store=None, enabled=True, principal_dependency=lambda: __import__("tests.off044_support", fromlist=["x"]).principal(USER_A)))
    assert TestClient(app).post("/api/offline/captures", json=capture()).status_code == 404


def test_the_operational_application_does_not_register_the_receiver():
    from app.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.startswith("/api/offline/captures") for p in paths), paths
    src = (pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert "offline_capture" not in src


def test_the_receiver_never_touches_operational_tables_or_approves_anything():
    root = pathlib.Path(__file__).resolve().parents[1]
    for f in (root / "app" / "offline_capture").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"vinto_txn|vinto_master|work_order|assignment|\bINSERT INTO (?!vinto_offline|capture_)|\bUPDATE (?!vinto_offline|capture_|seq)", text), f.name
    ddl = (root / "offline_capture_migration" / "proposed_0032_offline_capture_receipt.sql").read_text(encoding="utf-8")
    assert "vinto_txn" not in ddl and "REFERENCES" not in ddl
    assert not (root / "migrations" / "0032_offline_capture_receipt.sql").exists()          # proposal only: never auto-applied by migrate.py


def test_canonical_hash_vectors_are_stable():
    vectors = json.loads((pathlib.Path(__file__).parent / "fixtures" / "off044_hash_vectors.json").read_text(encoding="utf-8"))
    for v in vectors:
        assert C.canonical_sha256(v["value"]) == v["sha256"], v["name"]
