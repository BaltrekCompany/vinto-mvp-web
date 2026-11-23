"""OFF-04.8P: test real MF-13 authority issuance against an ephemeral migrated database.

This deliberately does not assert that operational vinto_txn.capture E2E is complete.
No MF-13 authorization functions are mocked.
"""
import hashlib
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser, create_user
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.authz.capture_gate import gate_for
from app.authz.policies import Operation
from app.authz.errors import AuthorizationDenied, ResourceNotFound
from app.quality.machine_capture_service import submit_machine_capture
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database, database_url
import psycopg
from types import SimpleNamespace
from app.offline_capture.store import PgOfflineCaptureStore
from app.offline_capture.service import AuthzDecision, ContextVerdict, receive_capture
from app.quality.offline_operational_binding import registered_scope_promoter
from app.offline_capture.contract import CaptureIn, canonical_sha256
from app.offline_scope.signing import SigningKey, encode_b64
from app.quality.offline_capture_authority import (
    CaptureScopeDenied, issue_capture_scope, revoke_capture_scope, verify_registered_capture_scope,
)

DDL = Path(__file__).resolve().parents[1] / "offline_capture_migration"
FORM, MACHINE = "VINTO-P1-18", "MP1"


@pytest.fixture(scope="module")
def template():
    name = build_reference_template("off048p_mf13")
    try:
        yield name
    finally:
        drop_database(name)


@pytest.fixture
def db(template):
    name = copy_database(template, "off048p_mf13_case")
    try:
        with connect(name) as connection:
            connection.execute((DDL / "proposed_0032_offline_capture_receipt.sql").read_text(), prepare=False)
            connection.execute((DDL / "proposed_0033_offline_capture_scope_authority.sql").read_text(), prepare=False)
            yield connection
    finally:
        drop_database(name)


def test_real_mf13_grant_and_signed_authority_fail_closed(db):
    admin = create_user(
        db, username=f"offp.admin.{uuid4().hex[:10]}", display_name="OFF QA Admin",
        profile_code="DATA_BALTREK", password="pw-" + uuid4().hex,
        sectors=("BOBINAS",),
    ).user_id
    user = create_user(
        db, username=f"offp.quality.{uuid4().hex[:10]}", display_name="OFF QA Quality",
        profile_code="CALIDAD", password="pw-" + uuid4().hex,
        sectors=("BOBINAS",),
    ).user_id
    who = AuthenticatedUser(
        user_id=user, username="offp.quality", display_name="Quality QA",
        profile_codes=("CALIDAD",), permissions=frozenset({QUALITY_CAPTURE}),
        must_change=False, sectors=frozenset({"BOBINAS"}),
    )
    device = uuid4()
    key = Ed25519PrivateKey.generate()
    public = encode_b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    signer = SigningKey(key, public, "ed25519-" + hashlib.sha256(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()[:20])

    with pytest.raises(CaptureScopeDenied):
        issue_capture_scope(db, who, device_key=device, machine_codes=[MACHINE], signer=signer)

    grant_machine_form(db, user_id=user, machine_code=MACHINE, form_code=FORM, actor_id=admin)
    envelope = issue_capture_scope(db, who, device_key=device, machine_codes=[MACHINE], signer=signer)
    pairs = envelope["payload"]["form_scopes"]
    assert len(pairs) == 1
    assert pairs[0]["machine_code"] == MACHINE and pairs[0]["form_code"] == FORM
    version = pairs[0]["form_version"]
    assert version >= 1
    snapshot = UUID(envelope["payload"]["snapshot_id"])
    payload = {"synthetic": False, "payload": {"numero_de_cuba": "QA"}}
    incoming = CaptureIn(
        capture_id=uuid4(), author_user_id=user, device_key=device,
        form_code=FORM, form_version=version, machine_code=MACHINE,
        scope_snapshot_id=snapshot, context_version=str(snapshot),
        payload_sha256=canonical_sha256(payload), payload=payload,
    )
    with db.transaction():
        assert verify_registered_capture_scope(
            db, principal=who, capture=incoming, trusted_public_key_b64url=public,
        )
        assert not verify_registered_capture_scope(
            db, principal=who, capture=incoming.model_copy(update={"device_key": uuid4()}),
            trusted_public_key_b64url=public,
        )

    # The exact ONLINE service's enforce gate must accept the effective MF-13
    # grant. It may not rely on the previously signed offline snapshot.
    machine_id = db.execute(
        "SELECT id FROM vinto_master.machine WHERE code=%s", (MACHINE,),
    ).fetchone()[0]
    with db.transaction():
        gate_for(who, "enforce", "offline-mf13-positive", Operation.QUALITY_MACHINE_CAPTURE).check_new(
            db, machine_id, MACHINE, FORM,
        )

    revoke_machine_form(db, user_id=user, machine_code=MACHINE, form_code=FORM, actor_id=admin)

    # The offline signature remains stored, but promotion must now be DENIED
    # by the SAME locked MF-13 check that the online capture service invokes.
    # This assertion is about the real gate, not a mock or a second grant table.
    with pytest.raises((AuthorizationDenied, ResourceNotFound)):
        with db.transaction():
            gate_for(who, "enforce", "offline-mf13-revoked", Operation.QUALITY_MACHINE_CAPTURE).check_new(
                db, machine_id, MACHINE, FORM,
            )

    # Exercise the real online machine-capture service (not a stand-in).
    # It MUST deny at the live MF-13 enforce gate before resolving a device,
    # validating fields, or writing operational rows.
    denied_id = uuid4()
    with pytest.raises((AuthorizationDenied, ResourceNotFound)):
        submit_machine_capture(
            db, actor_id=user, machine_code=MACHINE, capture_id=denied_id,
            form_code=FORM, device_key=device, values={},
            sectors=who.sectors,
            gate=gate_for(who, "enforce", "off048p-real-service-revoked", Operation.QUALITY_MACHINE_CAPTURE),
        )
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (denied_id,),
    ).fetchone()[0] == 0

    # End-to-end NEGATIVE: a real receiver and PostgreSQL receipt use the
    # genuine machine service and MF-13 enforce gate after revocation.
    # This is not a successful vinto_txn.capture writing test.
    class Authorizer:
        def authorize(self, principal, capture):
            return AuthzDecision(True)

    class SameContext:
        def evaluate(self, capture):
            return ContextVerdict("same")

    class CentralValidator:
        def validate(self, principal, capture):
            return SimpleNamespace(
                ok=True, errors=[], calculated={}, context_kind="same",
                version_mismatch=False,
            )

    store = PgOfflineCaptureStore(
        lambda: psycopg.connect(database_url(db.info.dbname), autocommit=False)
    )
    actual = receive_capture(
        store, who, incoming, authorizer=Authorizer(),
        context=SameContext(), validator=CentralValidator(),
        promoter=registered_scope_promoter(trusted_public_key_b64url=public),
    )
    assert actual.status == 202
    assert actual.body["operational_registered"] is False
    assert actual.body["reason"] == "operational_not_authorized"
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (incoming.capture_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT count(*) FROM vinto_offline.capture_receipt WHERE capture_id=%s",
        (incoming.capture_id,),
    ).fetchone()[0] == 1
    replay = receive_capture(
        store, who, incoming, authorizer=Authorizer(),
        context=SameContext(), validator=CentralValidator(),
        promoter=registered_scope_promoter(trusted_public_key_b64url=public),
    )
    assert replay.status == 202 and replay.body == actual.body
    assert db.execute(
        "SELECT count(*) FROM vinto_offline.capture_receipt WHERE capture_id=%s",
        (incoming.capture_id,),
    ).fetchone()[0] == 1

    with pytest.raises(CaptureScopeDenied):
        issue_capture_scope(db, who, device_key=device, machine_codes=[MACHINE], signer=signer)

    # Registered scope revocation is independent of MF-13 grant revocation.
    assert revoke_capture_scope(db, snapshot_id=snapshot, subject_user_id=user)
    with db.transaction():
        assert not verify_registered_capture_scope(
            db, principal=who, capture=incoming, trusted_public_key_b64url=public,
        )
