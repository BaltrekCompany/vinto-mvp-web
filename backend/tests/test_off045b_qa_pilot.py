"""OFF-04.5B: ASGI integration tests of the synthetic QA pilot receiver. Synthetic identities, grants and disposable databases only.

Nothing here talks to a deployed API, the VPS or an operational database.
"""
import os
import pathlib
import re
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Header, HTTPException
from fastapi.testclient import TestClient

from app import qa_offline_guard
from app.offline_capture import contract as C
from app.qa_offline_pilot import (ENV_AUTHZ_MODE, ENV_ENABLED, ENV_GRANTS, PILOT_POST_PATH, AuthzEngineProbe, PilotConfigError, PilotGrant, PilotSettings,
                                  QaPilotAuthorizer, create_qa_pilot_app, is_isolated_qa_database_name, parse_grants, pg_store_database_name,
                                  pilot_request_permitted)
from tests.off044_support import SNAPSHOT_CAPTURE, SNAPSHOT_CONSULT, USER_A, USER_B, capture, h, make_pg_store, make_sqlite_store, pg_available, principal

FORM = "VINTO-P1-22"
BACKEND = pathlib.Path(__file__).resolve().parents[1]
GRANT = {"user_id": str(USER_A), "machine_code": "MP1", "form_code": FORM, "form_version": 1, "synthetic": True,
         "scope_snapshot_id": str(SNAPSHOT_CAPTURE), "context_version": "ctx-1"}


def cap(**over):
    return capture(**{"form": FORM, **over})


@pytest.fixture(params=["sqlite", "pg"])
def store(request):
    if request.param == "pg":
        if not pg_available():
            if os.environ.get("OFF044_REQUIRE_PG") == "1":
                pytest.fail("PostgreSQL is required in CI (OFF044_REQUIRE_PG=1) but is not available")
            pytest.skip("no disposable PostgreSQL available")
        return make_pg_store()
    return make_sqlite_store()


def dbname(store) -> str:
    return pg_store_database_name(store) if not hasattr(store, "counts") else "off045b_sqlite_test"


def who(x_synthetic_user: str | None = Header(default=None)):
    if not x_synthetic_user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return principal(UUID(x_synthetic_user))


class Engine:
    def __init__(self, allow=True, boom=False):
        self.allow, self.boom, self.calls = allow, boom, []

    def allowed(self, who_, machine, form):
        self.calls.append((who_.user_id, machine, form))
        if self.boom:
            raise RuntimeError("engine down")
        return self.allow


def make(store, *, env="qa", enabled=True, grants=(GRANT,), mode="off", engine=None, name=None):
    settings = PilotSettings(app_env=env, enabled=enabled, authz_mode=mode, grants=parse_grants(list(grants)))
    return create_qa_pilot_app(settings=settings, store=store, database_name=name or dbname(store), principal_dependency=who, engine=engine)


def receipts(store) -> int:
    if hasattr(store, "counts"):
        return store.counts()["receipts"]
    with store.transaction() as tx:
        return tx.c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0]


def test_flag_off_post_denied_and_nothing_mounted(store):
    app = make(store, enabled=False)
    client = TestClient(app)
    assert client.post(PILOT_POST_PATH, json=cap(), headers=h()).status_code == 403
    assert client.get(f"/api/offline/captures/{uuid4()}", headers=h()).status_code == 404
    assert not [r for r in app.routes if getattr(r, "path", "").startswith("/api/offline")]
    assert receipts(store) == 0


@pytest.mark.parametrize("env", ["local", "test", "ci", "prod", "production", "staging", "QA", ""])
def test_outside_qa_the_pilot_does_not_exist(store, env):
    app = make(store, env=env)
    client = TestClient(app)
    assert client.post(PILOT_POST_PATH, json=cap(), headers=h()).status_code == 404
    assert client.get(f"/api/offline/captures/{uuid4()}", headers=h()).status_code == 404
    assert not [r for r in app.routes if getattr(r, "path", "").startswith("/api/offline")]
    assert receipts(store) == 0


def test_invalid_session_is_401_and_persists_nothing(store):
    client = TestClient(make(store))
    assert client.post(PILOT_POST_PATH, json=cap()).status_code == 401
    assert client.get(f"/api/offline/captures/{uuid4()}").status_code == 401
    assert receipts(store) == 0


def test_wrong_user_is_403(store):
    client = TestClient(make(store, grants=(GRANT, {**GRANT, "user_id": str(USER_B)})))
    # B authenticates but the capture belongs to A: author is immutable and identity comes from the session
    r = client.post(PILOT_POST_PATH, json=cap(author=USER_A), headers=h(USER_B))
    assert (r.status_code, r.json()["reason"]) == (403, C.R_AUTHOR_MISMATCH)
    # B authored it but holds no grant
    client2 = TestClient(make(store))
    r = client2.post(PILOT_POST_PATH, json=cap(author=USER_B, snapshot=None), headers=h(USER_B))
    assert (r.status_code, r.json()["reason"]) == (403, C.R_NOT_AUTHORIZED)
    assert receipts(store) == 0


def test_read_only_snapshot_never_authorises(store):
    client = TestClient(make(store))
    r = client.post(PILOT_POST_PATH, json=cap(snapshot=SNAPSHOT_CONSULT), headers=h())
    assert (r.status_code, r.json()["reason"]) == (403, C.R_READ_ONLY_SCOPE)
    # even a snapshot that is not the one the grant names is refused
    r = client.post(PILOT_POST_PATH, json=cap(snapshot=uuid4()), headers=h())
    assert (r.status_code, r.json()["reason"]) == (403, C.R_READ_ONLY_SCOPE)
    # a grant without a pinned snapshot does not accept a snapshot-bearing capture either
    client_nosnap = TestClient(make(store, grants=({k: v for k, v in GRANT.items() if k != "scope_snapshot_id"},)))
    assert client_nosnap.post(PILOT_POST_PATH, json=cap(snapshot=SNAPSHOT_CONSULT), headers=h()).status_code == 403
    assert receipts(store) == 0


def test_synthetic_grant_allows_technical_receipt_only(store):
    client = TestClient(make(store))
    body = cap()
    r = client.post(PILOT_POST_PATH, json=body, headers=h())
    assert r.status_code == 201 and r.json()["outcome"] == "created"
    assert r.json()["industrial_approval"] is False
    assert receipts(store) == 1
    # a different machine, form or version is not granted
    for over in ({"machine": "MP3"}, {"form": "VINTO-P1-26"}, {"form_version": 2}):
        denied = client.post(PILOT_POST_PATH, json=cap(**over), headers=h())
        assert denied.status_code == 403, over
    assert receipts(store) == 1


def test_unpinned_context_goes_to_review_never_accepted(store):
    client = TestClient(make(store))
    r = client.post(PILOT_POST_PATH, json=cap(context="ctx-other"), headers=h())
    assert r.status_code == 202 and r.json()["reason"] == C.R_CONTEXT_UNVERIFIABLE


def test_duplicate_is_one_receipt_and_changed_content_is_conflict(store):
    client = TestClient(make(store))
    body = cap()
    assert client.post(PILOT_POST_PATH, json=body, headers=h()).status_code == 201
    again = client.post(PILOT_POST_PATH, json=body, headers=h())
    assert (again.status_code, again.json()["outcome"]) == (200, "duplicate")
    assert receipts(store) == 1
    other = cap(payload={"numero_de_cuba": "C-9-SINT"}, capture_id=body["capture_id"])
    r = client.post(PILOT_POST_PATH, json=other, headers=h())
    assert (r.status_code, r.json()["reason"]) == (409, C.R_PAYLOAD_MISMATCH)
    assert receipts(store) == 1


def test_reconciliation_is_only_for_the_original_author(store):
    client = TestClient(make(store, grants=(GRANT, {**GRANT, "user_id": str(USER_B)})))
    body = cap()
    assert client.post(PILOT_POST_PATH, json=body, headers=h()).status_code == 201
    mine = client.get(f"/api/offline/captures/{body['capture_id']}", headers=h(USER_A))
    assert mine.status_code == 200 and mine.json()["found"] is True and mine.json()["industrial_approval"] is False
    theirs = client.get(f"/api/offline/captures/{body['capture_id']}", headers=h(USER_B))
    assert (theirs.status_code, theirs.json()) == (404, {"found": False})
    assert client.get(f"/api/offline/captures/{body['capture_id']}").status_code == 401


def test_every_other_mutating_request_stays_blocked(store):
    app = make(store)
    ops = APIRouter()
    for method, path in (("post", "/api/captures"), ("post", "/api/offline/sync"),
                         ("post", "/api/admin/users"), ("put", "/api/work-orders/1"), ("patch", "/api/assignments/1"), ("delete", "/api/bobbins/1"),
                         ("put", PILOT_POST_PATH), ("patch", PILOT_POST_PATH), ("delete", PILOT_POST_PATH), ("post", PILOT_POST_PATH + "/"),
                         ("post", PILOT_POST_PATH.upper()), ("post", PILOT_POST_PATH + "x")):
        getattr(ops, method)(path)(lambda: {"reached": True})
    app.include_router(ops)
    client = TestClient(app)
    for method, path in (("POST", "/api/captures"), ("POST", "/api/offline/sync"),
                         ("POST", "/api/admin/users"), ("PUT", "/api/work-orders/1"), ("PATCH", "/api/assignments/1"), ("DELETE", "/api/bobbins/1"),
                         ("PUT", PILOT_POST_PATH), ("PATCH", PILOT_POST_PATH), ("DELETE", PILOT_POST_PATH), ("POST", PILOT_POST_PATH + "/"),
                         ("POST", PILOT_POST_PATH.upper()), ("POST", PILOT_POST_PATH + "x"), ("POST", "/api/offline/captures%2F")):
        r = client.request(method, path, headers=h())
        assert r.status_code == 403, (method, path)
        assert r.json() == {"detail": "Operación no disponible en QA offline"}
    assert receipts(store) == 0


def test_observe_is_not_a_grant_and_cannot_restrict(store):
    # no grant: the engine allowing in observe mode does not authorise
    engine = Engine(allow=True)
    client = TestClient(make(store, grants=({**GRANT, "user_id": str(USER_B)},), mode="observe", engine=engine))
    assert client.post(PILOT_POST_PATH, json=cap(), headers=h(USER_A)).status_code == 403
    assert receipts(store) == 0 and engine.calls == []  # never consulted without a grant
    # grant present: engine denial or outage in observe mode changes nothing
    for eng in (Engine(allow=False), Engine(boom=True)):
        c = TestClient(make(store, mode="observe", engine=eng))
        assert c.post(PILOT_POST_PATH, json=cap(), headers=h()).status_code == 201
        assert len(eng.calls) == 1


def test_enforce_needs_both_grant_and_engine(store):
    ok = TestClient(make(store, mode="enforce", engine=Engine(allow=True)))
    assert ok.post(PILOT_POST_PATH, json=cap(), headers=h()).status_code == 201
    for eng in (Engine(allow=False), Engine(boom=True)):
        denied = TestClient(make(store, mode="enforce", engine=eng))
        r = denied.post(PILOT_POST_PATH, json=cap(), headers=h())
        assert (r.status_code, r.json()["reason"]) == (403, C.R_NOT_AUTHORIZED)
    assert receipts(store) == 1
    # engine allow without a grant is still a denial
    no_grant = TestClient(make(store, grants=({**GRANT, "user_id": str(USER_B)},), mode="enforce", engine=Engine(allow=True)))
    assert no_grant.post(PILOT_POST_PATH, json=cap(), headers=h()).status_code == 403


# ---- startup / configuration (fail closed)
def settings_for(**kw):
    base = dict(app_env="qa", enabled=True, authz_mode="off", grants=parse_grants([GRANT]))
    base.update(kw)
    return PilotSettings(**base)


def test_activation_refuses_half_configured_pilot():
    store = make_sqlite_store()
    with pytest.raises(PilotConfigError, match="grants_required"):
        create_qa_pilot_app(settings=settings_for(grants=()), store=store, database_name="x_test", principal_dependency=who)
    with pytest.raises(PilotConfigError, match="store_required"):
        create_qa_pilot_app(settings=settings_for(), store=None, database_name="x_test", principal_dependency=who)
    for name in (None, "", "vinto", "vinto_mvp", "postgres", "vinto_prod", "vinto_pilot", "vintoqa", "qa-x", "vinto_qa;drop"):
        with pytest.raises(PilotConfigError, match="database_not_isolated_qa"):
            create_qa_pilot_app(settings=settings_for(), store=store, database_name=name, principal_dependency=who)
    with pytest.raises(PilotConfigError, match="engine_required"):
        create_qa_pilot_app(settings=settings_for(authz_mode="observe"), store=store, database_name="vinto_qa_offline", principal_dependency=who)
    for ok in ("vinto_qa_offline", "qa", "vinto_qa", "off044_ab12_test"):
        assert is_isolated_qa_database_name(ok)
        create_qa_pilot_app(settings=settings_for(), store=store, database_name=ok, principal_dependency=who)


def test_inactive_pilot_does_not_validate_or_mount_anything():
    # flag off / non-QA never fails: it just provides no receiver
    for s in (settings_for(enabled=False, grants=()), settings_for(app_env="prod", grants=())):
        app = create_qa_pilot_app(settings=s, store=None, database_name=None, principal_dependency=who)
        assert not [r for r in app.routes if getattr(r, "path", "").startswith("/api/offline")]


def test_grants_are_strict_and_synthetic():
    assert parse_grants(None) == () and parse_grants("") == ()
    bad = [{**GRANT, "synthetic": False}, {k: v for k, v in GRANT.items() if k != "synthetic"}, {**GRANT, "extra": 1}, {**GRANT, "user_id": "x"},
           {**GRANT, "form_code": "p1-22"}, {**GRANT, "machine_code": "../x"}, {**GRANT, "form_version": 0}, "notalist", [GRANT] * 21]
    for item in bad:
        with pytest.raises(PilotConfigError):
            parse_grants(item if isinstance(item, str) or isinstance(item, list) and len(item) > 1 else [item])
    with pytest.raises(PilotConfigError):
        parse_grants("{not json")
    assert parse_grants([GRANT]) == (PilotGrant.model_validate(GRANT),)


def test_settings_from_environment():
    import json
    assert PilotSettings.from_env({}, app_env="qa").enabled is False
    s = PilotSettings.from_env({ENV_ENABLED: "true", ENV_AUTHZ_MODE: "observe", ENV_GRANTS: json.dumps([GRANT])}, app_env="qa")
    assert (s.enabled, s.authz_mode, len(s.grants)) == (True, "observe", 1)
    for env in ({ENV_ENABLED: "yes"}, {ENV_ENABLED: "on"}, {ENV_AUTHZ_MODE: "allow"}, {ENV_GRANTS: "[{}]"}):
        with pytest.raises(PilotConfigError):
            PilotSettings.from_env(env, app_env="qa")


def test_error_messages_never_carry_grant_values():
    with pytest.raises(PilotConfigError) as e:
        parse_grants([{**GRANT, "synthetic": False}])
    assert str(USER_A) not in str(e.value) and str(e.value.__cause__) == "None"


# ---- guard
def test_guard_extension_adds_exactly_one_request_only_in_qa_with_flag():
    base = qa_offline_guard.QA_ALLOWED_UNSAFE_REQUESTS
    assert len(base) == 4 and ("POST", PILOT_POST_PATH) not in base  # the reused #219 guard is not widened
    assert not qa_offline_guard.qa_offline_request_permitted(app_env="qa", method="POST", path=PILOT_POST_PATH)
    assert pilot_request_permitted(app_env="qa", method="POST", path=PILOT_POST_PATH, pilot_enabled=True)
    assert not pilot_request_permitted(app_env="qa", method="POST", path=PILOT_POST_PATH, pilot_enabled=False)
    for env in ("QA", "qa ", "prod"):
        # outside the exact QA environment the QA guard is not in force at all, and the pilot adds no permission
        assert pilot_request_permitted(app_env=env, method="POST", path=PILOT_POST_PATH, pilot_enabled=True) == qa_offline_guard.qa_offline_request_permitted(
            app_env=env, method="POST", path=PILOT_POST_PATH)
    for method, path in (("PUT", PILOT_POST_PATH), ("POST", PILOT_POST_PATH + "/"), ("POST", "/API/offline/captures"), ("POST", "/api/captures")):
        assert not pilot_request_permitted(app_env="qa", method=method, path=path, pilot_enabled=True)


# ---- isolation contracts (static)
def test_pilot_is_not_part_of_the_operational_app_or_default_routes():
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "qa_offline_pilot" not in main and "offline_capture" not in main
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name == "qa_offline_pilot.py" or "offline_capture" in path.parts:
            continue
        assert "qa_offline_pilot" not in path.read_text(encoding="utf-8"), path
    source = (BACKEND / "app" / "qa_offline_pilot.py").read_text(encoding="utf-8")
    assert not re.search(r"(DATABASE_URL|IDENTITY_DATABASE_URL|TEST_DATABASE_URL|\.env\b|subprocess|requests\.|httpx|urllib|socket\.)", source)
    assert "capture_eligible" not in source and "captures_enabled" not in source  # readiness-only flags are never reinterpreted


def test_engine_adapter_reads_through_the_central_authz_engine(monkeypatch):
    import app.authz.engine as engine_module
    from app.authz.policies import Operation
    seen = {}

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def transaction(self):
            seen["tx"] = True
            return self
    def fake_authorize(connection, user, operation, machine_code, form_code, *, lock=False):
        seen.update(op=operation, machine=machine_code, form=form_code, lock=lock)
        return type("D", (), {"allowed": True})()
    monkeypatch.setattr(engine_module, "authorize", fake_authorize)
    assert AuthzEngineProbe(lambda: Conn()).allowed(principal(USER_A), "MP1", FORM) is True
    assert seen == {"tx": True, "op": Operation.QUALITY_MACHINE_CAPTURE, "machine": "MP1", "form": FORM, "lock": False}


def test_authorizer_rejects_unknown_mode():
    with pytest.raises(PilotConfigError):
        QaPilotAuthorizer((), engine_mode="allow")
