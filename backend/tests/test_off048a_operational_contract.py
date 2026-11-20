"""OFF-04.8A first gate: fail-closed operational bridge (no production database or route).

These are pure contract checks. PostgreSQL atomicity and full Quality service integration
MUST be tested in disposable PG17 before mounting the promoter.
"""
import uuid
from types import SimpleNamespace

import pytest

from app.offline_capture.contract import CaptureIn, canonical_sha256
from app.quality.offline_operational import OperationalReview, QualityOperationalPromoter


OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER = uuid.UUID("22222222-2222-4222-8222-222222222222")
DEVICE = uuid.UUID("33333333-3333-4333-8333-333333333333")
SNAPSHOT = uuid.UUID("55555555-5555-4555-8555-555555555555")


def make_capture(*, synthetic=False, snapshot=SNAPSHOT, form="VINTO-P1-22"):
    body = {"synthetic": synthetic, "payload": {"numero_de_cuba": "E-SINT"}}
    return CaptureIn(capture_id=uuid.uuid4(), author_user_id=OWNER, device_key=DEVICE,
                     form_code=form, form_version=2, machine_code="MP1",
                     scope_snapshot_id=snapshot, context_version="ctx-unchanged",
                     payload_sha256=canonical_sha256(body), payload=body)


def principal(*, owner=OWNER, granted=True, must_change=False):
    return SimpleNamespace(user_id=owner, must_change=must_change,
                           can=lambda permission: granted)


@pytest.mark.parametrize("who", [
    principal(owner=OTHER), principal(granted=False), principal(must_change=True),
])
def test_unauthorized_never_reaches_operational_connection(who):
    with pytest.raises(OperationalReview, match="operational_not_authorized"):
        QualityOperationalPromoter(lambda p, c: True).promote(who, make_capture(), tx=SimpleNamespace())


@pytest.mark.parametrize("capture", [
    make_capture(synthetic=True),
    make_capture(snapshot=None),
])
def test_synthetic_and_unsigned_scope_fail_closed(capture):
    with pytest.raises(OperationalReview, match="operational_scope_required"):
        QualityOperationalPromoter(lambda p, c: True).promote(principal(), capture, tx=SimpleNamespace())



def test_machine_form_wire_context_is_the_signed_snapshot_id():
    capture = make_capture()
    assert capture.scope_snapshot_id == SNAPSHOT
    # OFF-04.6 browser lab uses snapshot ID itself as machine context version.
    # The server adapter must validate this wire contract, not a draft context UUID.
    assert capture.context_version != str(capture.scope_snapshot_id)


def test_trusted_scope_verifier_is_mandatory_and_fail_closed():
    with pytest.raises(TypeError, match="capture scope verifier"):
        QualityOperationalPromoter(None)
    with pytest.raises(OperationalReview, match="operational_scope_required"):
        QualityOperationalPromoter(lambda principal, capture: False).promote(
            principal(), make_capture(), tx=SimpleNamespace())
