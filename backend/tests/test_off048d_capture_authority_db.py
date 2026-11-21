"""OFF-04.8D: disposable PostgreSQL registry and issuance checks.

Only a brand-new *_test database is used. No real users, grants, offline
receipts, deployments or production schema are modified. Authz read-lock logic
is tested by its existing suite; issuance here uses a synthetic decision.
"""
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.offline_capture.contract import CaptureIn, canonical_sha256
from app.offline_scope.signing import SigningKey, encode_b64
from app.quality import offline_capture_authority as authority
from tests.off044_support import make_pg_store, pg_available

DDL = Path(__file__).resolve().parents[1] / "offline_capture_migration" / "proposed_0033_offline_capture_scope_authority.sql"
USER = UUID("11111111-1111-4111-8111-111111111111")
DEVICE = UUID("33333333-3333-4333-8333-333333333333")


def principal():
    return AuthenticatedUser(USER, "synthetic.qa", "Synthetic", ("CALIDAD",),
                             frozenset({QUALITY_CAPTURE}), False, frozenset({"MP1"}))


@pytest.fixture
def db():
    if not pg_available():
        if os.getenv("OFF046_REQUIRE_PG") == "1":
            pytest.fail("OFF-04.8D requires disposable PostgreSQL 17")
        pytest.skip("no disposable PostgreSQL")
    store = make_pg_store()
    with store.transaction() as tx:
        tx.c.execute(DDL.read_text(encoding="utf-8"), prepare=False)
    return store


@pytest.fixture
def signer():
    key = Ed25519PrivateKey.generate()
    pub_bytes = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SigningKey(key, encode_b64(pub_bytes), "ed25519-" + hashlib.sha256(pub_bytes).hexdigest()[:20])


def seed_catalog(store):
    # Synthetic fixture tables only; not the real effective-authz catalog.
    with store.transaction() as tx:
        tx.c.execute("CREATE SCHEMA vinto_master")
        tx.c.execute("CREATE SCHEMA vinto_config")
        tx.c.execute("CREATE TABLE vinto_master.machine (id uuid PRIMARY KEY, code text)")
        tx.c.execute("CREATE TABLE vinto_config.form (id uuid PRIMARY KEY, code text)")
        tx.c.execute("CREATE TABLE vinto_master.user_machine_form_grant (user_id uuid, machine_id uuid, form_id uuid, revoked_at timestamptz)")
        machine_id, form_id = uuid4(), uuid4()
        tx.c.execute("INSERT INTO vinto_master.machine VALUES (%s,'MP1')", (machine_id,))
        tx.c.execute("INSERT INTO vinto_config.form VALUES (%s,'VINTO-P1-22')", (form_id,))
        tx.c.execute("INSERT INTO vinto_master.user_machine_form_grant VALUES (%s,%s,%s,NULL)", (USER, machine_id, form_id))


def capture(snapshot):
    data = {"synthetic": False, "payload": {"numero_de_cuba": "QA-only"}}
    return CaptureIn(capture_id=uuid4(), author_user_id=USER, device_key=DEVICE,
                     form_code="VINTO-P1-22", form_version=2, machine_code="MP1",
                     scope_snapshot_id=snapshot, context_version=str(snapshot),
                     payload_sha256=canonical_sha256(data), payload=data)


def test_issue_verify_revoke_is_one_way_and_immutable(db, signer, monkeypatch):
    seed_catalog(db)
    grant = uuid4()
    def allowed(connection, user, operation, machine, form, *, lock):
        assert lock and operation.value == "quality_machine_capture"
        return SimpleNamespace(allowed=True, grant_id=grant, effective_version=2)
    monkeypatch.setattr(authority, "authorize", allowed)
    with db.transaction() as tx:
        signed = authority.issue_capture_scope(tx.c, principal(), device_key=DEVICE,
                                               machine_codes=["MP1"], signer=signer)
    snapshot = UUID(signed["payload"]["snapshot_id"])
    with db.transaction() as tx:
        assert authority.verify_registered_capture_scope(tx.c, principal=principal(),
            capture=capture(snapshot), trusted_public_key_b64url=signer.public_b64url)
        assert tx.c.execute("SELECT count(*) FROM vinto_offline.capture_scope_authority").fetchone()[0] == 1
    with db.transaction() as tx:
        assert authority.revoke_capture_scope(tx.c, snapshot_id=snapshot, subject_user_id=USER)
    with db.transaction() as tx:
        assert not authority.verify_registered_capture_scope(tx.c, principal=principal(),
            capture=capture(snapshot), trusted_public_key_b64url=signer.public_b64url)
        assert not authority.revoke_capture_scope(tx.c, snapshot_id=snapshot, subject_user_id=USER)
        with pytest.raises(psycopg.Error):
            with tx.c.transaction():
                tx.c.execute("DELETE FROM vinto_offline.capture_scope_authority WHERE snapshot_id=%s", (snapshot,))


def test_registered_envelope_immutable_and_capture_binding_strict(db, signer, monkeypatch):
    seed_catalog(db)
    monkeypatch.setattr(authority, "authorize", lambda *args, **kw:
        SimpleNamespace(allowed=True, grant_id=uuid4(), effective_version=2))
    with db.transaction() as tx:
        signed = authority.issue_capture_scope(tx.c, principal(), device_key=DEVICE,
                                               machine_codes=["MP1"], signer=signer)
    snapshot = UUID(signed["payload"]["snapshot_id"])
    with db.transaction() as tx:
        with pytest.raises(psycopg.Error):
            with tx.c.transaction():
                tx.c.execute("UPDATE vinto_offline.capture_scope_authority SET device_key=%s WHERE snapshot_id=%s",
                             (uuid4(), snapshot))
        false_device = capture(snapshot).model_copy(update={"device_key": uuid4()})
        assert not authority.verify_registered_capture_scope(tx.c, principal=principal(),
            capture=false_device, trusted_public_key_b64url=signer.public_b64url)
        false_version = capture(snapshot).model_copy(update={"form_version": 3})
        assert not authority.verify_registered_capture_scope(tx.c, principal=principal(),
            capture=false_version, trusted_public_key_b64url=signer.public_b64url)
        assert authority.verify_registered_capture_scope(tx.c, principal=principal(),
            capture=capture(snapshot), trusted_public_key_b64url=signer.public_b64url)


def test_schema_is_standalone_and_fails_on_second_application(db):
    with db.transaction() as tx:
        assert tx.c.execute("SELECT count(*) FROM vinto_offline.capture_scope_authority").fetchone()[0] == 0
        with pytest.raises(psycopg.Error):
            with tx.c.transaction():
                tx.c.execute(DDL.read_text(encoding="utf-8"), prepare=False)
        assert tx.c.execute("SELECT count(*) FROM vinto_offline.capture_scope_authority").fetchone()[0] == 0


def test_off048p_binding_uses_registered_postgres_scope_and_honors_revocation(db, signer, monkeypatch):
    """Integrated binding + real registry: no envelope or client flag can bypass revocation."""
    from app.quality.offline_operational_binding import registered_scope_promoter

    seed_catalog(db)
    monkeypatch.setattr(authority, "authorize", lambda *args, **kwargs:
                        SimpleNamespace(allowed=True, grant_id=uuid4(), effective_version=2))
    with db.transaction() as tx:
        signed = authority.issue_capture_scope(
            tx.c, principal(), device_key=DEVICE, machine_codes=["MP1"], signer=signer,
        )
    snapshot = UUID(signed["payload"]["snapshot_id"])
    promoter = registered_scope_promoter(trusted_public_key_b64url=signer.public_b64url)
    incoming = capture(snapshot)
    with db.transaction() as tx:
        assert promoter._verify_capture_scope(principal(), incoming, tx.c) is True
        # Read-only readiness and signatures for other devices are not substitutes.
        assert promoter._verify_capture_scope(
            principal(), incoming.model_copy(update={"device_key": uuid4()}), tx.c
        ) is False
    with db.transaction() as tx:
        assert authority.revoke_capture_scope(
            tx.c, snapshot_id=snapshot, subject_user_id=USER,
        ) is True
    with db.transaction() as tx:
        assert promoter._verify_capture_scope(principal(), incoming, tx.c) is False


def test_off048p_binding_refuses_unregistered_capture_scope(db, signer):
    from app.quality.offline_operational_binding import registered_scope_promoter

    promoter = registered_scope_promoter(trusted_public_key_b64url=signer.public_b64url)
    with db.transaction() as tx:
        assert promoter._verify_capture_scope(principal(), capture(uuid4()), tx.c) is False
