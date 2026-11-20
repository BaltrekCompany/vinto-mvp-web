"""OFF-04.6 Phase C (server side): the ten Quality forms through the isolated QA pilot application over ASGI on DISPOSABLE PostgreSQL databases.

Real sessions (cookie), the repository's own login, the synthetic signed scope/packages and bobbin contexts, the receiver, and the CENTRAL VALIDATION that runs the same code as the online
Quality routes against the published definitions. Synthetic users, keys, bobbins and content only; nothing industrial, nothing approved."""
import json
import os
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.offline_capture import contract as C
from app.offline_quality import bobbin_context
from app.offline_scope.signing import verify_quality_package, verify_scope
from tests import off045b06b_support as S
from tests import off046_support as T
from tests.test_off045b06b_mobile_auth import DEVICE_KEY, OH, Stack, login

ALL_OPERATIONS = {f: ("quality_machine_capture" if f in T.BY_MACHINE else "quality_bobbin_capture") for f in T.FORMS}


def _need_pg(exc):
    if os.environ.get("OFF046_REQUIRE_PG") == "1":
        pytest.fail(f"PostgreSQL is required in CI (OFF046_REQUIRE_PG=1): {type(exc).__name__}: {exc}")
    pytest.skip("no disposable PostgreSQL configured")


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


@pytest.fixture
def stack(template, monkeypatch):
    s = None

    def make(**kw):
        nonlocal s
        s = Stack(template, monkeypatch, **kw)
        s.grants = T.grants_all(s.users["a"]["id"])
        s.env["OFFLINE_QA_PILOT_GRANTS"] = json.dumps(s.grants)
        s.env["OFFLINE_QA_PILOT_BOBBINS"] = json.dumps(T.BOBBINS)
        return s
    yield make
    if s is not None:
        s.close()


def prepared(stack, who="a"):
    client = stack.client()
    assert login(client, stack.users[who]).status_code == 200
    scope = client.post("/api/offline/scope", json={"device_key": DEVICE_KEY, "machine_codes": [T.MACHINE]}, headers=OH)
    assert scope.status_code == 200, scope.text
    return client, scope.json()


def body_for(stack, form, values, *, bobbin=T.BOBBIN_A, version=None, snapshot=T.SNAPSHOT, capture_id=None, context=None, who="a", machine=T.MACHINE, with_bobbin=True):
    payload = {"synthetic": True, "payload": values}
    if form in T.BY_BOBBIN and with_bobbin and bobbin is not None:
        digest = bobbin_context.context_digest({**bobbin, "is_mother": False})
        payload["bobbin"] = {"bobbin_id": bobbin["bobbin_id"], "context_digest": digest}
        ctx = context or bobbin_context.context_version(str(snapshot), bobbin["bobbin_id"], digest)
    else:
        ctx = context or S.CONTEXT
    return {"capture_id": str(capture_id or uuid4()), "author_user_id": str(stack.users[who]["id"]), "device_key": DEVICE_KEY, "form_code": form,
            "form_version": version if version is not None else T.version(form), "machine_code": machine, "scope_snapshot_id": str(snapshot) if snapshot else None,
            "context_version": ctx, "payload_sha256": C.canonical_sha256(payload), "payload": payload}


def receipts(stack):
    with stack.admin() as c:
        return c.execute("SELECT form_code, outcome, reason, warnings, response_status, industrial_approval FROM vinto_offline.capture_receipt ORDER BY server_seq").fetchall()


def events(stack):
    with stack.admin() as c:
        return c.execute("SELECT kind FROM vinto_offline.capture_event ORDER BY id").fetchall()


# ------------------------------------------------------------------ signed definitions for the ten forms
def test_scope_and_the_ten_packages_are_signed_for_the_right_operations(stack):
    s = stack()
    client, scope = prepared(s)
    assert verify_scope(scope, trusted_public_key_b64url=s.signer.public_b64url)
    pairs = scope["payload"]["form_scopes"]
    assert {p["form_code"]: p["operation"] for p in pairs} == ALL_OPERATIONS and len(pairs) == 10
    assert {p["form_code"]: p["form_version"] for p in pairs} == {f: T.version(f) for f in T.FORMS}
    for form in T.FORMS:
        r = client.post("/api/offline/quality-package", json={"device_key": DEVICE_KEY, "machine_code": T.MACHINE, "form_code": form, "signed_scope": scope}, headers=OH)
        assert r.status_code == 200, (form, r.text)
        package = r.json()
        assert verify_quality_package(package, trusted_public_key_b64url=s.signer.public_b64url)
        d = package["payload"]["definition"]
        assert (package["payload"]["form_code"], package["payload"]["form_version"], package["payload"]["captures_enabled"], d["capture_eligible"]) == (form, T.version(form), False, False)
        assert [f["key"] for f in d["fields"]] == [f["key"] for f in sorted(T.seed(form)["fields"], key=lambda x: x["display_order"])]
        assert set(d["calculated_rules"]) == set(T.calculated_keys(form))
    # a form outside the batch, or a machine outside the grants, is never issued
    for form, machine in (("VINTO-P1-03", T.MACHINE), ("VINTO-P1-22", "MP3")):
        assert client.post("/api/offline/quality-package", json={"device_key": DEVICE_KEY, "machine_code": machine, "form_code": form, "signed_scope": scope}, headers=OH).status_code == 403


def test_bobbin_contexts_are_issued_online_for_authorised_scopes_only(stack):
    s = stack()
    client, scope = prepared(s)
    body = {"device_key": DEVICE_KEY, "machine_code": "MP1", "bobbin_code": T.BOBBIN_A["bobbin_code"], "signed_scope": scope}
    r = client.post("/api/offline/bobbin-context", json=body, headers=OH)
    assert r.status_code == 200, r.text
    out = r.json()
    ctx = out["contexts"][0]
    assert out["snapshot_id"] == str(T.SNAPSHOT) and len(out["contexts"]) == 1 and ctx["bobbin_id"] == T.BOBBIN_A["bobbin_id"]
    assert ctx["context_digest"] == bobbin_context.context_digest({**T.BOBBIN_A, "is_mother": False})
    assert r.headers["cache-control"] == "no-store"
    assert client.post("/api/offline/bobbin-context", json={**body, "bobbin_code": "B-NOPE"}, headers=OH).json()["contexts"] == []
    assert client.post("/api/offline/bobbin-context", json={**body, "bobbin_code": T.BOBBIN_MP3["bobbin_code"]}, headers=OH).json()["contexts"] == []      # another machine's bobbin
    assert client.post("/api/offline/bobbin-context", json={**body, "machine_code": "MP3"}, headers=OH).status_code == 403                                      # no grant there
    forged = json.loads(json.dumps(scope)); forged["payload"]["subject_user_id"] = str(uuid4())
    assert client.post("/api/offline/bobbin-context", json={**body, "signed_scope": forged}, headers=OH).status_code == 403                                      # altered scope
    assert client.post("/api/offline/bobbin-context", json=body).status_code == 403                                                                               # no Origin
    anonymous = stack_client = s.client()
    assert anonymous.post("/api/offline/bobbin-context", json=body, headers=OH).status_code == 401


# ------------------------------------------------------------------ each form: complete capture, idempotency, conflict, reconciliation, server calculations
@pytest.mark.parametrize("form", T.FORMS)
def test_complete_capture_of_each_form_is_received_validated_and_calculated_by_the_server(stack, form):
    s = stack()
    client, _ = prepared(s)
    values, expected = T.valid_values(form)
    body = body_for(s, form, values)
    created = client.post("/api/offline/captures", json=body, headers=OH)
    assert (created.status_code, created.json()["outcome"], created.json()["industrial_approval"], created.json()["technical_acceptance"]) == (201, "created", False, True), created.text
    assert created.json()["server_calculated"] == expected                                              # the SERVER calculated; the device never sent a calculated value
    assert not (set(values) & set(T.calculated_keys(form)))
    assert [(r[0], r[1], r[5]) for r in receipts(s)] == [(form, "accepted", False)] and events(s) == [("received",)]
    dup = client.post("/api/offline/captures", json=body, headers=OH)
    assert (dup.status_code, dup.json()["outcome"]) == (200, "duplicate") and len(receipts(s)) == 1       # idempotent retry
    changed = client.post("/api/offline/captures", json=body_for(s, form, {**values, next(iter(values)): "otro"}, capture_id=body["capture_id"]), headers=OH)
    assert (changed.status_code, changed.json()["reason"]) == (409, C.R_PAYLOAD_MISMATCH) and len(receipts(s)) == 1   # same id, different content: conflict, original kept
    mine = client.get(f"/api/offline/captures/{body['capture_id']}")
    assert mine.status_code == 200 and mine.json()["found"] is True and mine.json()["industrial_approval"] is False
    other = s.client()
    login(other, s.users["b"])
    assert other.get(f"/api/offline/captures/{body['capture_id']}").json() == {"found": False}                # the original author only


# ------------------------------------------------------------------ invalid content is KEPT for central review, never lost, never approved, never echoed
@pytest.mark.parametrize("form", T.FORMS)
def test_content_the_server_refuses_is_kept_for_review_with_field_codes_only(stack, form):
    s = stack()
    client, _ = prepared(s)
    values, _ = T.valid_values(form)
    if form == "VINTO-P1-21":
        values = {"gramaje_01": "SENTINEL-9731"}                      # a half row with a non-numeric value
        expect = {("gramaje_01", "type")}
    else:
        key = T.required_keys(form)[0]
        values = {k: v for k, v in values.items() if k != key}
        expect = {(key, "required")}
    body = body_for(s, form, values)
    r = client.post("/api/offline/captures", json=body, headers=OH)
    assert (r.status_code, r.json()["outcome"], r.json()["reason"], r.json()["technical_acceptance"], r.json()["industrial_approval"]) == (202, "review", C.R_VALIDATION, True, False), r.text
    found = {(e["field"], e["code"]) for e in r.json()["validation_errors"]}
    assert expect <= found and "SENTINEL-9731" not in r.text
    row = receipts(s)
    assert len(row) == 1 and row[0][1] == "review" and row[0][2] == C.R_VALIDATION and any(w.startswith("validation:") for w in row[0][3]) and row[0][5] is False   # kept, with codes
    with s.admin() as c:
        assert "SENTINEL-9731" not in json.dumps(c.execute("SELECT warnings, response_body FROM vinto_offline.capture_receipt").fetchall(), default=str).replace(
            json.dumps(body["payload"]), "")                                                                                                                   # no value echoed in the verdict
    again = client.post("/api/offline/captures", json=body, headers=OH)
    assert (again.status_code, again.json()["outcome"]) == (202, "review") and len(receipts(s)) == 1                                                          # the retry returns the SAME stored verdict


@pytest.mark.parametrize("form", [f for f in T.FORMS if T.calculated_keys(f)])
def test_a_calculated_field_sent_by_the_device_is_refused(stack, form):
    s = stack()
    client, _ = prepared(s)
    values, _ = T.valid_values(form)
    key = T.calculated_keys(form)[0]
    r = client.post("/api/offline/captures", json=body_for(s, form, {**values, key: "99.99"}), headers=OH)
    assert (r.status_code, r.json()["reason"]) == (202, C.R_VALIDATION) and (key, "calculated") in {(e["field"], e["code"]) for e in r.json()["validation_errors"]}


@pytest.mark.parametrize("form", T.FORMS)
def test_unknown_keys_and_wrong_types_are_refused(stack, form):
    s = stack()
    client, _ = prepared(s)
    values, _ = T.valid_values(form)
    typed = next((f["key"] for f in T.seed(form)["fields"] if f["source"] == "manual" and f["value_type"] in ("decimal", "integer", "time") and not f.get("options")), None)
    bad = {**values, "campo_inventado": "x"}
    if typed:
        bad[typed] = "no-es-numero"
    r = client.post("/api/offline/captures", json=body_for(s, form, bad), headers=OH)
    found = {(e["field"], e["code"]) for e in r.json()["validation_errors"]}
    assert r.status_code == 202 and ("campo_inventado", "unknown") in found and (typed is None or (typed, "type") in found)


def test_form_specific_rules_run_with_the_online_code(stack):
    s = stack()
    client, _ = prepared(s)
    v, _ = T.valid_values("VINTO-P1-25")
    r = client.post("/api/offline/captures", json=body_for(s, "VINTO-P1-25", {**v, "n_cortes": "-1"}), headers=OH)
    assert (r.status_code, ("n_cortes", "minimum") in {(e["field"], e["code"]) for e in r.json()["validation_errors"]}) == (202, True)          # minimum integer rule
    v, _ = T.valid_values("VINTO-P1-28", "B-9999-SINT")
    r = client.post("/api/offline/captures", json=body_for(s, "VINTO-P1-28", v), headers=OH)                                                      # declared bobbin number != the bobbin
    assert (r.status_code, ("numero_de_bobina", "bobbin_mismatch") in {(e["field"], e["code"]) for e in r.json()["validation_errors"]}) == (202, True)
    r = client.post("/api/offline/captures", json=body_for(s, "VINTO-P1-21", {k: v for k, v in T.valid_values("VINTO-P1-21")[0].items() if not k.endswith("_02") and not k.endswith("_01")}), headers=OH)
    assert (r.status_code, ("*", "profile_empty") in {(e["field"], e["code"]) for e in r.json()["validation_errors"]}) == (202, True)            # at least one complete position
    r = client.post("/api/offline/captures", json=body_for(s, "VINTO-P1-26", {**T.valid_values("VINTO-P1-26")[0], "punto_de_muestreo": "Punto inventado"}), headers=OH)
    assert (r.status_code, ("punto_de_muestreo", "option") in {(e["field"], e["code"]) for e in r.json()["validation_errors"]}) == (202, True)   # closed option list
    r = client.post("/api/offline/captures", json=body_for(s, "VINTO-P1-26", {**T.valid_values("VINTO-P1-26")[0], "masa_humeda": "0", "masa_seca": "5"}), headers=OH)
    assert r.status_code == 201 and r.json()["server_calculated"] == {}                                                                            # zero denominator: no calculation (as online)


# ------------------------------------------------------------------ permissions and versions
@pytest.mark.parametrize("form", T.FORMS)
def test_wrong_version_other_machine_other_user_and_foreign_snapshot_never_authorise(stack, form):
    s = stack()
    client, _ = prepared(s)
    values, _ = T.valid_values(form)
    for over in ({"version": T.version(form) + 1}, {"version": max(1, T.version(form) - 1) if T.version(form) > 1 else 99}, {"machine": "MP3"}, {"snapshot": uuid4()}, {"snapshot": None}):
        r = client.post("/api/offline/captures", json=body_for(s, form, values, **over), headers=OH)
        assert r.status_code == 403, (form, over, r.text)
    other = s.client()
    login(other, s.users["b"])                                                                           # user B has no registry grant at all
    assert other.post("/api/offline/captures", json=body_for(s, form, values, who="b"), headers=OH).status_code == 403
    assert other.post("/api/offline/captures", json=body_for(s, form, values), headers=OH).json()["reason"] == C.R_AUTHOR_MISMATCH                # A's capture with B's session
    assert receipts(s) == []                                                                              # nothing persisted by a denied request


def test_a_grant_for_one_form_does_not_authorise_another(stack):
    s = stack()
    s.grants = [g for g in T.grants_all(s.users["a"]["id"]) if g["form_code"] == "VINTO-P1-22"]
    s.env["OFFLINE_QA_PILOT_GRANTS"] = json.dumps(s.grants)
    client, scope = prepared(s)
    assert [p["form_code"] for p in scope["payload"]["form_scopes"]] == ["VINTO-P1-22"]
    for form in T.FORMS:
        r = client.post("/api/offline/captures", json=body_for(s, form, T.valid_values(form)[0]), headers=OH)
        assert r.status_code == (201 if form == "VINTO-P1-22" else 403), form


# ------------------------------------------------------------------ bobbin context
@pytest.mark.parametrize("form", T.BY_BOBBIN)
def test_bobbin_context_is_pinned_and_a_change_goes_to_central_review(stack, form):
    s = stack()
    client, _ = prepared(s)
    values, _ = T.valid_values(form)
    ok = client.post("/api/offline/captures", json=body_for(s, form, values), headers=OH)
    assert ok.status_code == 201, ok.text
    # the SAME bobbin, but the device prepared a context that no longer matches (digest changed): incompatible -> review, kept
    stale = body_for(s, form, values, bobbin={**T.BOBBIN_A, "work_order": "OT-OTRA"}, capture_id=uuid4(), context=bobbin_context.context_version(str(T.SNAPSHOT), T.BOBBIN_A["bobbin_id"], "0" * 64))
    r = client.post("/api/offline/captures", json=stale, headers=OH)
    assert (r.status_code, r.json()["outcome"], r.json()["reason"]) == (202, "review", C.R_CONTEXT_INCOMPATIBLE)
    unknown = client.post("/api/offline/captures", json=body_for(s, form, values, bobbin={**T.BOBBIN_A, "bobbin_id": str(uuid4())}), headers=OH)           # a bobbin the registry never prepared
    assert (unknown.status_code, unknown.json()["reason"]) == (202, C.R_CONTEXT_UNVERIFIABLE)
    other_machine = client.post("/api/offline/captures", json=body_for(s, form, values, bobbin=T.BOBBIN_MP3), headers=OH)                             # a bobbin of another machine
    assert (other_machine.status_code, other_machine.json()["reason"]) == (202, C.R_CONTEXT_UNVERIFIABLE)
    missing = client.post("/api/offline/captures", json=body_for(s, form, values, with_bobbin=False), headers=OH)                                      # no bobbin at all
    assert missing.status_code == 202 and missing.json()["outcome"] == "review"
    assert [r[1] for r in receipts(s)] == ["accepted", "review", "review", "review", "review"] and len(events(s)) == 5                                  # every one KEPT


def test_the_two_bobbins_of_a_machine_are_independent_captures_of_the_same_form(stack):
    s = stack()
    client, _ = prepared(s)
    form = "VINTO-P1-20"
    values, _ = T.valid_values(form)
    a = client.post("/api/offline/captures", json=body_for(s, form, values, bobbin=T.BOBBIN_A), headers=OH)
    b = client.post("/api/offline/captures", json=body_for(s, form, values, bobbin=T.BOBBIN_B), headers=OH)
    assert (a.status_code, b.status_code) == (201, 201) and len(receipts(s)) == 2


# ------------------------------------------------------------------ the receiver never approves, releases, rejects or touches an industrial record
def test_no_industrial_table_is_touched_by_any_form(stack):
    s = stack()
    client, _ = prepared(s)
    with s.admin() as c:
        before = {t: c.execute(f"SELECT count(*) FROM vinto_txn.{t}").fetchone()[0] for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='vinto_txn'").fetchall()}
    for form in T.FORMS:
        r = client.post("/api/offline/captures", json=body_for(s, form, T.valid_values(form)[0]), headers=OH)
        assert r.status_code == 201 and r.json()["industrial_approval"] is False
    with s.admin() as c:
        after = {t: c.execute(f"SELECT count(*) FROM vinto_txn.{t}").fetchone()[0] for t in before}
    assert before == after and all(v == 0 for v in after.values()) and len(receipts(s)) == 10
