"""OFF-04.5B-06B: QA pilot authentication, synthetic issuer and capture flow over ASGI on DISPOSABLE PostgreSQL databases.

Real sessions (cookie), the repository's own login/me/logout, the dedicated identity connection and the restricted application role. Synthetic users, keys and
grants only; no deployed database, no real key, no industrial data.
"""
import json
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.offline_capture import contract as C
from app.offline_scope.signing import PACKAGE_AUDIENCE, canonical_payload, decode_b64, encode_b64, sign_scope, verify_quality_package, verify_scope
from app.qa_offline_pilot import PilotConfigError, PilotGrant
from app.qa_pilot_auth import (COOKIE_NAME_RE, IssuerDenied, SyntheticIssuer, parse_origins, signer_from_seed, synthetic_definition, verify_identity_database)
from app.qa_pilot_main import create_app_from_env
from tests import off045b06b_support as S
from tests.off044_support import DEVICE, capture

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ORIGIN = "https://qa-pilot.test"
OH = {"Origin": ORIGIN}
COOKIE = "vinto_qa_test_session"
DEVICE_KEY = str(DEVICE)


def _need_pg(exc: Exception):
    if os.environ.get("OFF045B06B_REQUIRE_PG") == "1":
        pytest.fail(f"PostgreSQL is required in CI (OFF045B06B_REQUIRE_PG=1) but is not available: {type(exc).__name__}: {exc}")
    pytest.skip("no disposable PostgreSQL configured (TEST_DATABASE_URL / TEST_ADMIN_DATABASE_URL)")


@pytest.fixture(scope="module")
def template():
    from app.ephemeral_db import drop_database
    try:
        name = S.build_template()
    except Exception as exc:  # noqa: BLE001
        _need_pg(exc)
    yield name
    drop_database(name)
    S.drop_roles()


class Stack:
    """A QA pilot application over a fresh database copy, with both users, a signer and the settings the real process would have."""
    def __init__(self, template, monkeypatch, *, capture_flag=True, auth_flag=True, grants=None, seed=None, origins=ORIGIN, cookie=COOKIE, identity="dedicated"):
        from app.ephemeral_db import copy_database, drop_database
        self.name = copy_database(template, "off06b_run")
        self._drop = drop_database
        self.users = S.create_users(self.name)
        self.seed = seed or S.new_seed()
        monkeypatch.setattr(settings, "auth_cookie_name", cookie)
        monkeypatch.setattr(settings, "database_url", SecretStr(S.app_url(self.name)))
        monkeypatch.setattr(settings, "identity_database_url", SecretStr(S.identity_url(self.name)) if identity == "dedicated" else None)
        self.grants = grants if grants is not None else [S.grant_for(self.users["a"]["id"])]
        self.env = {"OFFLINE_QA_PILOT_ENABLED": "1" if capture_flag else "0", "OFFLINE_QA_PILOT_AUTH_ENABLED": "1" if auth_flag else "0",
                    "OFFLINE_QA_PILOT_GRANTS": json.dumps(self.grants), "OFFLINE_QA_PILOT_ALLOWED_ORIGINS": origins, "OFFLINE_QA_PILOT_SIGNING_SEED_B64URL": self.seed}
        self.signer = signer_from_seed(self.seed)

    def app(self, **over):
        url, iurl = S.app_url(self.name), S.identity_url(self.name)
        return create_app_from_env({**self.env, **over.pop("env", {})}, app_env="qa", connect=lambda: psycopg.connect(url), identity_connect=lambda: psycopg.connect(iurl), **over)

    def client(self, **over) -> TestClient:
        return TestClient(self.app(**over), base_url="https://qa-pilot.test")

    def admin(self):
        from app.ephemeral_db import connect
        return connect(self.name)

    def receipts(self) -> int:
        with self.admin() as c:
            return c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0]

    def close(self):
        self._drop(self.name)


@pytest.fixture
def stack(template, monkeypatch):
    s = Stack(template, monkeypatch)
    yield s
    s.close()


def login(client, user, password=None, **kw):
    return client.post("/api/auth/login", json={"username": user["username"], "password": password or user["password"]}, headers=OH, **kw)


def prepare(client, user):
    """Enrollment as the device does it: login, signed scope, signed package. Returns (scope, package)."""
    assert login(client, user).status_code == 200
    scope = client.post("/api/offline/scope", json={"device_key": DEVICE_KEY, "machine_codes": [S.MACHINE]}, headers=OH)
    assert scope.status_code == 200, scope.text
    package = client.post("/api/offline/quality-package", json={"device_key": DEVICE_KEY, "machine_code": S.MACHINE, "form_code": S.FORM, "signed_scope": scope.json()}, headers=OH)
    assert package.status_code == 200, package.text
    return scope.json(), package.json()


def cap(stack, who="a", **over):
    body = {"form": S.FORM, "author": stack.users[who]["id"], "snapshot": S.SNAPSHOT, "context": S.CONTEXT}
    body.update(over)
    return capture(**body)


# ------------------------------------------------------------------ defaults: everything off
def test_both_flags_off_mounts_nothing_and_opens_no_connection():
    def never():
        raise AssertionError("no connection may be opened")
    app = create_app_from_env({}, app_env="qa", connect=never, identity_connect=never)
    client = TestClient(app, base_url="https://qa-pilot.test")
    assert [p for p in app.openapi()["paths"] if p.startswith("/api")] == []
    assert client.post("/api/auth/login", json={}, headers=OH).status_code == 404   # allowed by the QA guard but no such route exists
    for path in ("/api/auth/me", "/api/offline/scope"):
        assert client.get(path).status_code == 404


@pytest.mark.parametrize("env", ["local", "test", "ci", "prod", "QA", ""])
def test_outside_qa_authentication_is_not_available_even_with_the_flag(env):
    app = create_app_from_env({"OFFLINE_QA_PILOT_AUTH_ENABLED": "1"}, app_env=env, connect=lambda: 1 / 0, identity_connect=lambda: 1 / 0)
    assert not [p for p in app.openapi()["paths"] if p.startswith("/api")]


def test_flag_off_by_default_and_invalid_values_fail_closed(monkeypatch):
    from app.qa_offline_pilot import PilotSettings
    assert PilotSettings.from_env({}, app_env="qa").auth_enabled is False
    for bad in ("yes", "on", "2"):
        with pytest.raises(PilotConfigError):
            PilotSettings.from_env({"OFFLINE_QA_PILOT_AUTH_ENABLED": bad}, app_env="qa")


def test_auth_flag_off_with_capture_flag_on_has_no_login_route(template, monkeypatch):
    s = Stack(template, monkeypatch, auth_flag=False)
    try:
        client = s.client(principal_dependency=lambda: 1 / 0)
        assert client.post("/api/auth/login", json={}, headers=OH).status_code == 404
        assert client.get("/api/auth/me").status_code == 404
    finally:
        s.close()


# ------------------------------------------------------------------ startup: every unsafe configuration refuses to start
def test_startup_refuses_unsafe_authentication_configuration(template, monkeypatch):
    s = Stack(template, monkeypatch)
    try:
        def code(**over):
            with pytest.raises(PilotConfigError) as e:
                s.app(**over)
            return str(e.value)
        for bad_origins in ("", "*", "http://qa.example", "https://qa.example/path", "ftp://x", "https://a, http://b.example", "https://user@qa.example"):
            assert code(env={"OFFLINE_QA_PILOT_ALLOWED_ORIGINS": bad_origins}) in ("origins_required", "origin_invalid", "origins_invalid")
        assert code(env={"OFFLINE_QA_PILOT_SIGNING_SEED_B64URL": ""}) == "signing_seed_invalid"
        assert code(env={"OFFLINE_QA_PILOT_SIGNING_SEED_B64URL": "AAAA"}) == "signing_seed_invalid"
        assert code(env={"OFFLINE_QA_PILOT_GRANTS": "[]"}) == "grants_required"
        for name in ("vinto_session", "other", "vinto_qa_", "vinto_qa_bad name", "VINTO_QA_x"):
            monkeypatch.setattr(settings, "auth_cookie_name", name) if re.fullmatch(r"^[A-Za-z0-9_-]{1,64}$", name) else None
            if re.fullmatch(r"^[A-Za-z0-9_-]{1,64}$", name):
                assert code() == "cookie_name_not_qa_exclusive", name
        monkeypatch.setattr(settings, "auth_cookie_name", COOKIE)
        monkeypatch.setattr(settings, "identity_database_url", None)
        assert code() == "identity_connection_not_dedicated"
        monkeypatch.setattr(settings, "identity_database_url", SecretStr(S.app_url(s.name)))
        monkeypatch.setattr(settings, "database_url", SecretStr(S.app_url(s.name)))
        assert code() == "identity_equals_application_url"
        monkeypatch.setattr(settings, "identity_database_url", SecretStr(S.identity_url(s.name)))
        monkeypatch.setattr(settings, "app_env", "local")
        assert code() == "cookie_would_not_be_secure"
    finally:
        s.close()


def test_identity_connection_must_be_a_separate_minimal_role(template, monkeypatch):
    s = Stack(template, monkeypatch)
    try:
        name = s.name
        def check(connect, role="vinto_app"):
            with connect() as c:
                verify_identity_database(c, receiver_database=name, receiver_role=role)
        check(lambda: psycopg.connect(S.identity_url(name)))                                     # the proper identity role passes
        with pytest.raises(PilotConfigError, match="identity_role_not_separate"):
            check(lambda: psycopg.connect(S.app_url(name)), role="vinto_app")                      # the application role is not an identity connection
        with pytest.raises(PilotConfigError, match="identity_role_too_privileged"):
            check(lambda: s.admin(), role="someone_else")                                          # a superuser is refused
        with pytest.raises(PilotConfigError, match="identity_database_mismatch"):
            with psycopg.connect(S.identity_url(name)) as c:
                verify_identity_database(c, receiver_database="another_qa", receiver_role="vinto_app")
        mutations = {"identity_role_reaches_receiver": f"GRANT USAGE ON SCHEMA vinto_offline TO {S.ID_ROLE}", "identity_role_can_create": f"GRANT CREATE ON DATABASE \"{name}\" TO {S.ID_ROLE}",
                     "identity_role_has_excess_privilege": f"GRANT DELETE ON vinto_auth.session TO {S.ID_ROLE}", "identity_role_lacks_privilege": f"REVOKE UPDATE ON vinto_auth.session FROM {S.ID_ROLE}"}
        for expected, sql in mutations.items():
            with s.admin() as admin:
                admin.execute(sql)
            with pytest.raises(PilotConfigError, match=expected):
                check(lambda: psycopg.connect(S.identity_url(name)))
            with s.admin() as admin:
                admin.execute(sql.replace("GRANT", "REVOKE").replace(" TO ", " FROM ") if sql.startswith("GRANT") else f"GRANT UPDATE ON vinto_auth.session TO {S.ID_ROLE}")
    finally:
        s.close()


def test_the_application_role_has_no_identity_privileges_and_the_flow_works_without_them(stack):
    with psycopg.connect(S.app_url(stack.name), autocommit=True) as c:
        for schema, table in (("vinto_auth", "credential"), ("vinto_auth", "session"), ("vinto_auth", "auth_event"), ("vinto_master", "user")):
            assert not c.execute("SELECT has_table_privilege(c.oid, 'SELECT') OR has_schema_privilege(n.oid, 'USAGE') FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                 "WHERE n.nspname = %s AND c.relname = %s", (schema, table)).fetchone()[0], (schema, table)
    client = stack.client()
    prepare(client, stack.users["a"])
    r = client.post("/api/offline/captures", json=cap(stack), headers=OH)
    assert r.status_code == 201 and stack.receipts() == 1     # sessions resolved through the identity connection, the capture written by the restricted role


# ------------------------------------------------------------------ login / me / logout with the real code
def test_login_cookie_attributes_wrong_credentials_logout_and_session_states(stack):
    client = stack.client()
    a = stack.users["a"]
    bad = login(client, a, "wrong-password-12345")
    unknown = client.post("/api/auth/login", json={"username": "nobody.here", "password": "whatever-123456"}, headers=OH)
    assert bad.status_code == unknown.status_code == 401 and bad.json() == unknown.json()          # the same answer: no account oracle
    assert COOKIE not in client.cookies
    ok = login(client, a)
    assert ok.status_code == 200
    header = ok.headers["set-cookie"].lower()
    assert header.startswith(COOKIE + "=") and "httponly" in header and "secure" in header and "samesite=lax" in header and "domain=" not in header
    assert "vinto_session=" not in header
    assert client.get("/api/auth/me").status_code == 200
    # expired session
    with stack.admin() as admin, admin.transaction():
        admin.execute("SET LOCAL session_replication_role = replica")   # the session-identity trigger is bypassed only here, in the throwaway test database
        admin.execute("UPDATE vinto_auth.session SET created_at = clock_timestamp() - interval '2 hours', expires_at = clock_timestamp() - interval '1 hour'")
    assert client.get("/api/auth/me").status_code == 401
    # revoked session
    login(client, a)
    assert client.get("/api/auth/me").status_code == 200
    with stack.admin() as admin:
        admin.execute("UPDATE vinto_auth.session SET revoked_at = clock_timestamp() WHERE revoked_at IS NULL")
    assert client.get("/api/auth/me").status_code == 401
    # logout really ends the session
    login(client, a)
    assert client.post("/api/auth/logout", headers=OH).status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_a_cookie_of_the_production_name_is_not_a_session(stack):
    client = stack.client()
    assert login(client, stack.users["a"]).status_code == 200
    token = client.cookies.get(COOKIE)
    other = TestClient(stack.app(), base_url="https://qa-pilot.test")
    other.cookies.set("vinto_session", token)           # the production cookie name carrying a valid QA token
    assert other.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------------ Origin / CSRF
def test_every_authenticated_write_needs_an_allowed_origin(stack):
    client = stack.client()
    prepare(client, stack.users["a"])
    body = cap(stack)
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}, {"Origin": ORIGIN + ":444"}, {"Origin": ORIGIN.upper()}):
        for path, payload in (("/api/offline/captures", body), ("/api/auth/login", {"username": "x", "password": "y"}), ("/api/auth/logout", None), ("/api/offline/scope", {"device_key": DEVICE_KEY, "machine_codes": ["MP1"]})):
            r = client.post(path, json=payload, headers=headers) if payload is not None else client.post(path, headers=headers)
            assert r.status_code == 403 and r.json() == {"detail": "Origen no permitido"}, (path, headers)
    assert stack.receipts() == 0 and client.get("/api/auth/me").status_code == 200       # nothing was written and the session survived
    assert "access-control-allow-origin" not in client.options("/api/offline/captures", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}).headers   # no CORS at all
    assert client.post("/api/offline/captures", json=body, headers=OH).status_code == 201


def test_origin_list_parsing_is_strict():
    assert parse_origins("https://a.example, https://b.example:8443, http://127.0.0.1:9000") == ("https://a.example", "https://b.example:8443", "http://127.0.0.1:9000")
    for bad in (None, "", " ", "*", "https://*.example", "http://qa.example", "https://a.example/x", "https://a.example?x=1", "javascript:alert(1)", "https://u:p@a.example"):
        with pytest.raises(PilotConfigError):
            parse_origins(bad)


# ------------------------------------------------------------------ synthetic issuer: scope and package
def test_synthetic_scope_and_package_verify_with_the_synthetic_key_only(stack):
    client = stack.client()
    scope, package = prepare(client, stack.users["a"])
    assert verify_scope(scope, trusted_public_key_b64url=stack.signer.public_b64url)
    assert verify_quality_package(package, trusted_public_key_b64url=stack.signer.public_b64url)
    other = signer_from_seed(S.new_seed())
    assert not verify_scope(scope, trusted_public_key_b64url=other.public_b64url) and not verify_quality_package(package, trusted_public_key_b64url=other.public_b64url)
    p = scope["payload"]
    assert (p["kind"], p["captures_enabled"], p["subject_user_id"], p["device_key"], p["snapshot_id"]) == ("scope_readiness_only", False, str(stack.users["a"]["id"]), DEVICE_KEY, str(S.SNAPSHOT))
    assert p["form_scopes"] == [{"machine_code": "MP1", "form_code": "VINTO-P1-22", "form_version": 1, "grant_id": p["form_scopes"][0]["grant_id"], "operation": "quality_machine_capture"}]
    q = package["payload"]
    assert (q["kind"], q["captures_enabled"], q["form_code"], q["machine_code"], q["scope_snapshot_id"]) == ("quality_definition_readiness_only", False, "VINTO-P1-22", "MP1", str(S.SNAPSHOT))
    d = q["definition"]
    assert d["form_name"].startswith("SINTÉTICO") and d["note"].startswith("Synthetic QA-only") and d["capture_eligible"] is False
    seed = json.loads((BACKEND / "seed_data" / "forms" / "VINTO-P1-22.json").read_text(encoding="utf-8"))
    assert [(f["key"], f["value_type"], f["required"]) for f in d["fields"]] == [(f["key"], f["value_type"], f["required"]) for f in sorted(seed["fields"], key=lambda x: x["display_order"])]
    assert q["content_sha256"] == __import__("hashlib").sha256(canonical_payload(d)).hexdigest()


def test_the_real_issuer_and_the_real_signing_seed_are_never_used(stack, monkeypatch):
    import app.offline_scope.router as real
    import app.offline_scope.signing as signing
    monkeypatch.setattr(signing, "load_signer", lambda: (_ for _ in ()).throw(AssertionError("the real signer must never be used")))
    monkeypatch.setattr(real, "load_signer", signing.load_signer)
    monkeypatch.setattr(settings, "offline_scope_issue_enabled", True)
    monkeypatch.setattr(settings, "offline_quality_package_issue_enabled", True)
    monkeypatch.setattr(settings, "offline_scope_signing_seed_b64url", SecretStr(S.new_seed()))
    client = stack.client()
    scope, package = prepare(client, stack.users["a"])
    real_pub = signer_from_seed(settings.offline_scope_signing_seed_b64url.get_secret_value()).public_b64url
    assert scope["public_key_b64url"] != real_pub and package["public_key_b64url"] != real_pub


def test_issuer_denials(stack):
    client = stack.client()
    b = stack.users["b"]
    assert client.post("/api/offline/scope", json={"device_key": DEVICE_KEY, "machine_codes": ["MP1"]}, headers=OH).status_code == 401      # no session
    assert login(client, b).status_code == 200
    denied = client.post("/api/offline/scope", json={"device_key": DEVICE_KEY, "machine_codes": ["MP1"]}, headers=OH)
    assert (denied.status_code, denied.json()) == (403, {"detail": "Acceso no autorizado"})                                                  # B has no pilot grant (industrial grants do not count)
    client.post("/api/auth/logout", headers=OH)
    assert login(client, stack.users["a"]).status_code == 200
    for body in ({"device_key": DEVICE_KEY, "machine_codes": ["MP3"]}, {"device_key": str(UUID(int=1)), "machine_codes": ["MP1"]}, {"device_key": DEVICE_KEY, "machine_codes": []}):
        assert client.post("/api/offline/scope", json=body, headers=OH).status_code in (403, 422), body
    scope = client.post("/api/offline/scope", json={"device_key": DEVICE_KEY, "machine_codes": ["MP1"]}, headers=OH).json()
    base = {"device_key": DEVICE_KEY, "machine_code": "MP1", "form_code": "VINTO-P1-22", "signed_scope": scope}
    assert client.post("/api/offline/quality-package", json=base, headers=OH).status_code == 200
    # altered signature / payload / foreign key / other device / other machine / other form
    tampered = json.loads(json.dumps(scope)); tampered["signature_b64url"] = encode_b64(bytes(64))
    altered = json.loads(json.dumps(scope)); altered["payload"]["form_scopes"][0]["form_version"] = 9
    foreign = sign_scope(json.loads(json.dumps(scope["payload"])), signer=signer_from_seed(S.new_seed()))
    for name, change in (("signature", {"signed_scope": tampered}), ("payload", {"signed_scope": altered}), ("foreign key", {"signed_scope": foreign}),
                         ("device", {"device_key": str(uuid4())}), ("machine", {"machine_code": "MP3"}), ("form", {"form_code": "VINTO-P1-26"})):
        r = client.post("/api/offline/quality-package", json={**base, **change}, headers=OH)
        assert r.status_code in (403, 422), name
    # a scope issued for A cannot be redeemed by B
    client.post("/api/auth/logout", headers=OH)
    login(client, b)
    assert client.post("/api/offline/quality-package", json=base, headers=OH).status_code == 403


def test_issuer_rejects_stale_future_and_unpinned_scopes_and_removed_grants(stack):
    a = stack.users["a"]
    grant = PilotGrant.model_validate(S.grant_for(a["id"]))
    principal = type("P", (), {"user_id": a["id"], "must_change": False})()
    now = datetime.now(timezone.utc)
    issuer = SyntheticIssuer((grant,), stack.signer, now=lambda: now)
    scope = issuer.scope(principal, UUID(DEVICE_KEY), ["MP1"])
    assert issuer.package(principal, UUID(DEVICE_KEY), "MP1", "VINTO-P1-22", scope)["payload"]["captures_enabled"] is False
    with pytest.raises(IssuerDenied):
        SyntheticIssuer((grant,), stack.signer, now=lambda: now + timedelta(hours=25)).package(principal, UUID(DEVICE_KEY), "MP1", "VINTO-P1-22", scope)   # stale
    with pytest.raises(IssuerDenied):
        SyntheticIssuer((grant,), stack.signer, now=lambda: now - timedelta(hours=1)).package(principal, UUID(DEVICE_KEY), "MP1", "VINTO-P1-22", scope)   # from the future
    with pytest.raises(IssuerDenied):
        SyntheticIssuer((), stack.signer, now=lambda: now).package(principal, UUID(DEVICE_KEY), "MP1", "VINTO-P1-22", scope)                                # grant removed since
    with pytest.raises(IssuerDenied):
        SyntheticIssuer((PilotGrant.model_validate(S.grant_for(a["id"], form_version=2)),), stack.signer, now=lambda: now).package(principal, UUID(DEVICE_KEY), "MP1", "VINTO-P1-22", scope)
    unpinned = PilotGrant.model_validate({k: v for k, v in S.grant_for(a["id"]).items() if k != "scope_snapshot_id"})
    with pytest.raises(IssuerDenied):
        SyntheticIssuer((unpinned,), stack.signer).scope(principal, UUID(DEVICE_KEY), ["MP1"])        # the receiver only accepts a pinned snapshot: no ambiguous scope
    with pytest.raises(IssuerDenied):
        issuer.scope(type("P", (), {"user_id": a["id"], "must_change": True})(), UUID(DEVICE_KEY), ["MP1"])
    assert synthetic_definition(3)["form_version"] == 3


# ------------------------------------------------------------------ capture flow with a real session
def test_full_capture_flow_idempotency_conflict_and_author_checks(stack):
    client = stack.client()
    prepare(client, stack.users["a"])
    body = cap(stack)
    created = client.post("/api/offline/captures", json=body, headers=OH)
    assert (created.status_code, created.json()["outcome"], created.json()["industrial_approval"]) == (201, "created", False)
    assert client.post("/api/offline/captures", json=body, headers=OH).json()["outcome"] == "duplicate" and stack.receipts() == 1
    changed = client.post("/api/offline/captures", json=cap(stack, payload={"numero_de_cuba": "C-9-SINT"}, capture_id=body["capture_id"]), headers=OH)
    assert (changed.status_code, changed.json()["reason"]) == (409, C.R_PAYLOAD_MISMATCH)
    mine = client.get(f"/api/offline/captures/{body['capture_id']}")
    assert mine.status_code == 200 and mine.json()["found"] is True
    # another authenticated user: cannot post A's capture, cannot see it, and without a grant cannot post their own
    other = stack.client()
    login(other, stack.users["b"])
    r = other.post("/api/offline/captures", json=body, headers=OH)
    assert (r.status_code, r.json()["reason"]) == (403, C.R_AUTHOR_MISMATCH)
    assert other.get(f"/api/offline/captures/{body['capture_id']}").json() == {"found": False}
    own = other.post("/api/offline/captures", json=cap(stack, who="b", snapshot=None), headers=OH)
    assert own.status_code == 403
    assert stack.receipts() == 1
    # no session -> 401; ended session -> 401
    anonymous = stack.client()
    assert anonymous.post("/api/offline/captures", json=cap(stack), headers=OH).status_code == 401
    client.post("/api/auth/logout", headers=OH)
    assert client.post("/api/offline/captures", json=cap(stack), headers=OH).status_code == 401


def test_readiness_snapshots_and_foreign_contexts_never_authorise(stack):
    client = stack.client()
    prepare(client, stack.users["a"])
    for snap in (uuid4(), UUID("44444444-4444-4444-8444-444444444444"), None):
        r = client.post("/api/offline/captures", json=cap(stack, snapshot=snap), headers=OH)
        assert r.status_code == 403 and r.json()["reason"] in (C.R_READ_ONLY_SCOPE, C.R_NOT_AUTHORIZED)
    for over in ({"machine": "MP3"}, {"form": "VINTO-P1-26"}, {"form_version": 2}):
        assert client.post("/api/offline/captures", json=cap(stack, **over), headers=OH).status_code == 403
    assert stack.receipts() == 0


def test_flag_combinations_and_the_guard(template, monkeypatch):
    s = Stack(template, monkeypatch, capture_flag=False)          # authentication on, capture flag OFF
    try:
        client = s.client()
        prepare(client, s.users["a"])
        assert client.post("/api/offline/captures", json=cap(s), headers=OH).status_code == 403
        assert client.get(f"/api/offline/captures/{uuid4()}").status_code == 404
        assert s.receipts() == 0
        for method, path in (("POST", "/api/captures"), ("POST", "/api/bobbins"), ("POST", "/api/quality/machines/MP1/captures"), ("POST", "/api/admin/users"),
                             ("PUT", "/api/work-orders/1"), ("PATCH", "/api/assignments/1"), ("DELETE", "/api/offline/captures"), ("POST", "/api/offline/sync")):
            assert client.request(method, path, json={}, headers=OH).status_code == 403, (method, path)
        for path in ("/api/captures", "/api/work-orders", "/api/admin/users", "/api/quality/machines/MP1", "/openapi.json", "/docs", "/health"):
            assert client.get(path).status_code == 404, path
    finally:
        s.close()


def test_industrial_routes_are_not_mounted_with_everything_on(stack):
    app = stack.app()
    paths = sorted(p for p in app.openapi()["paths"] if p.startswith("/api"))
    assert paths == ["/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/offline/captures", "/api/offline/captures/{capture_id}", "/api/offline/quality-package", "/api/offline/scope"]


# ------------------------------------------------------------------ isolation contracts and no leaks
def test_authentication_is_not_part_of_the_operational_app():
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "qa_pilot" not in main and "qa_offline_pilot" not in main and "offline_capture" not in main
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name in ("qa_offline_pilot.py", "qa_pilot_main.py", "qa_pilot_auth.py") or "offline_capture" in path.parts:
            continue
        assert "qa_pilot_auth" not in path.read_text(encoding="utf-8"), path
    source = (BACKEND / "app" / "qa_pilot_auth.py").read_text(encoding="utf-8")
    assert not re.search(r"(admin|work_orders|assignments|bobbins|captures_router|production_access)\.router|app\.admin|app\.work_orders|app\.assignments", source)
    assert "load_signer" not in source and "offline_scope_signing_seed" not in source          # the real issuer's key is never read
    assert COOKIE_NAME_RE.fullmatch("vinto_qa_pilot") and not COOKIE_NAME_RE.fullmatch("vinto_session")


def test_logs_never_contain_credentials_cookies_or_seeds(stack, caplog):
    client = stack.client()
    with caplog.at_level(logging.DEBUG):
        prepare(client, stack.users["a"])
        client.post("/api/offline/captures", json=cap(stack), headers=OH)
        login(client, stack.users["a"], "wrong-password-12345")
    text = caplog.text
    token = client.cookies.get(COOKIE) or ""
    for secret in (stack.users["a"]["password"], "wrong-password-12345", stack.seed, token, S.APP_PASSWORD, S.ID_PASSWORD, stack.users["a"]["username"]):
        assert not secret or secret not in text
